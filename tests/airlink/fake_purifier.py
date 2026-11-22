"""A simulated purifier on a local UDP port, for tests.

The defaults follow what was measured on a real AC3220/10 with firmware
0.2.3 and Wi-Fi ``AWS_Philips_AIR_Combo@86`` (docs/metingen.md). Every quirk
of other firmware that the research found is a switch, so that each one can
be exercised without hardware.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any

from airlink import crypto
from airlink.coap import (
    CONTENT,
    EMPTY,
    GET,
    OPT_MAX_AGE,
    OPT_OBSERVE,
    POST,
    CoapError,
    Message,
    MType,
    uint_bytes,
)

Addr = tuple[str, int]
Observer = tuple[Addr, bytes]

POWER = "D03102"
MODE = "D0310C"
MODE_WHILE_OFF = -16

# Shaped like the status of the measured AC3220/10 (identifiers are made up).
DEFAULT_STATE: dict[str, Any] = {
    "D01S03": "Testkamer",
    "D01S04": "Unicorn",
    "D01S05": "AC3220/10",
    "D01S12": "0.2.3",
    "ProductId": "00000000000011ee88c206d016384e4a",
    "DeviceId": "11111111222211ef93334444555566aa",
    "Runtime": 0,
    "rssi": -50,
    "WifiVersion": "AWS_Philips_AIR_Combo@86",
    "StatusType": "status",
    "ConnectType": "Online",
    "D03102": 1,
    "D03103": 0,
    "D03105": 101,
    "D0310C": 0,
    "D0310D": 1,
    "D03110": 0,
    "D03211": 0,
    "D03115": 0,
    "D03120": 1,
    "D03221": 3,
    "D03224": 212,
    "D03125": 47,
    "D0312A": 1,
    "D0312C": 4,
    "D03130": 100,
    "D03134": 0,
    "D03135": 2,
    "D03137": 4,
    "D03180": 0,
    "D03240": 0,
    "D05408": 9600,
    "D0540E": 9600,
    "D05207": 720,
    "D0520D": 720,
}

_SPEED_OF_MODE = {1: 1, 2: 2, 3: 3, 4: 4, 5: 18, 18: 18, 19: 3}


class _AltSource(asyncio.DatagramProtocol):
    """A second socket, used to send from an address the client does not know."""


class FakePurifier(asyncio.DatagramProtocol):
    """Simulated device. Set the quirk attributes before or during a test."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = dict(DEFAULT_STATE)

        # -- measured on the AC3220/10; switch off to simulate other firmware --
        # "on_change": a registration is answered only by the next change.
        # "immediate": it is answered at once (older firmware).
        self.answer_registration = "on_change"
        self.standby_silent = True  # no frames while off, except for the power key
        self.standby_discards_settings = True  # acknowledged, not applied
        self.push_on_same_value = True  # a write of the current value still notifies

        # -- quirks found by the research ---------------------------------
        self.lapse_after: float | None = None  # observer expires unless re-registered
        self.single_observer_per_ip = False  # newest registration wins
        self.honour_deregister = True
        self.deregister_ignores_token = False  # Observe: 1 drops every observer of the address
        self.honour_rst = True
        self.notify_con = False
        self.info_enabled = True
        self.sync_enabled = True
        self.ping_enabled = True
        self.control_enabled = True
        self.silent = False  # drop everything, as if powered off
        self.strict_counter = True
        self.refuse_control = False  # answer "failed" to every write
        self.fail_next_controls = 0  # answer "failed" to the next writes only
        self.readonly_keys: set[str] = {"D03105", "D03137"}  # acknowledged, then discarded
        self.corrupt_next_frames = 0  # NUL bytes with a valid digest
        self.drop_next_notifications = 0  # change notifications that get lost
        self.malformed_next_syncs = 0
        self.drop_next_infos = 0
        self.blocked_tokens: set[bytes] = set()  # registrations with these are ignored
        self.observe_requires_fresh_sync = False  # only honoured right after a sync
        self.stale_frame_before_echo = False  # a frame with the old values precedes the echo
        self.echo_delay = 0.0  # seconds between the control answer and the echo
        self.reply_from_other_port = False  # everything leaves from a second socket

        # -- what arrived at the device, also while it is silent -----------
        self.observers: dict[Observer, dict[str, Any]] = {}
        self.requests: list[tuple[str, str]] = []
        self.registrations: list[Observer] = []
        self.deregistrations: list[Observer] = []
        self.controls: list[dict[str, Any]] = []
        self.control_envelopes: list[str] = []
        self.datagrams_received = 0
        self.pings_received = 0
        self.syncs_received = 0
        self.resets_received = 0
        self.acks_received = 0
        self.frames_sent = 0

        self._transport: asyncio.DatagramTransport | None = None
        self._alt_transport: asyncio.DatagramTransport | None = None
        self._counter: str | None = None
        self._last_path: dict[Addr, str] = {}
        self._mode_before_standby = 0
        self._mid = 100
        self._frame_counter = 0x10000000
        self._observe_seq = 40
        # An hour of uptime, so that a reboot is a clear fall of Runtime.
        self._boot = time.monotonic() - 3600.0
        self._sent_notifications: dict[int, Observer] = {}
        self._timers: list[asyncio.TimerHandle] = []

    @classmethod
    async def start(cls, host: str = "127.0.0.1") -> FakePurifier:
        """Bind to a free port and return the running device."""
        loop = asyncio.get_running_loop()
        device = cls()
        await loop.create_datagram_endpoint(lambda: device, local_addr=(host, 0))
        alt, _ = await loop.create_datagram_endpoint(_AltSource, local_addr=(host, 0))
        device._alt_transport = alt
        return device

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self._transport = transport

    @property
    def port(self) -> int:
        assert self._transport is not None
        return int(self._transport.get_extra_info("sockname")[1])

    def close(self) -> None:
        for timer in self._timers:
            timer.cancel()
        for transport in (self._transport, self._alt_transport):
            if transport is not None:
                transport.close()

    # -- test controls -----------------------------------------------------

    @property
    def is_on(self) -> bool:
        return bool(self.state[POWER] == 1)

    def change(self, key: str, value: Any, *, status_type: str = "status") -> None:
        """Change a value as a button or a sensor would, and notify if the device would."""
        if key == POWER:
            if self._set_power(1 if value else 0):
                self._notify(status_type)
            return
        self.state[key] = value
        if self.is_on or not self.standby_silent:
            self._notify(status_type)

    def power_off(self, *, notify: bool = True) -> None:
        """Go to standby; with ``notify=False`` nobody is told (a test's starting point)."""
        if self._set_power(0) and notify:
            self._notify("status")

    def power_on(self, *, notify: bool = True) -> None:
        if self._set_power(1) and notify:
            self._notify("status")

    def reboot(self) -> None:
        """Forget observers and the counter, as after a power cycle."""
        self.observers.clear()
        self._counter = None
        self._last_path.clear()
        self._boot = time.monotonic()
        self._observe_seq = 1

    def push(self, *, status_type: str = "status", runtime_shift_ms: int = 0, state: dict[str, Any] | None = None) -> None:
        """Send a frame to every observer now, whatever the standby rule says."""
        for observer in list(self.observers):
            self._send_frame(observer, status_type, state=state, runtime_shift_ms=runtime_shift_ms)

    def send_stray_notification(self, addr: Addr, token: bytes | None = None) -> None:
        """Send a status frame for a token the client never registered."""
        self._send_frame((addr, token if token is not None else os.urandom(4)), "status")

    def send_raw(self, addr: Addr, data: bytes) -> None:
        """Send arbitrary bytes from the device address."""
        assert self._transport is not None
        self._transport.sendto(data, addr)

    # -- wire --------------------------------------------------------------

    def _next_mid(self) -> int:
        self._mid = (self._mid + 1) & 0xFFFF
        return self._mid

    def _send(self, msg: Message, addr: Addr) -> None:
        transport = self._alt_transport if self.reply_from_other_port else self._transport
        assert transport is not None
        if not transport.is_closing():
            transport.sendto(msg.encode(), addr)

    def _respond(
        self, request: Message, addr: Addr, payload: bytes, options: list[tuple[int, bytes]] | None = None
    ) -> None:
        """Answer a request: piggybacked on the ACK for CON, NON otherwise."""
        if request.mtype == MType.CON:
            msg = Message(MType.ACK, CONTENT, request.mid, request.token, options or [], payload)
        else:
            msg = Message(MType.NON, CONTENT, self._next_mid(), request.token, options or [], payload)
        self._send(msg, addr)

    def datagram_received(self, data: bytes, addr: Any) -> None:
        sender: Addr = (addr[0], addr[1])
        self.datagrams_received += 1
        try:
            msg = Message.decode(data)
        except CoapError:
            return
        # The counters say what arrived, also while the device plays dead.
        self._record(msg, sender)
        if self.silent:
            return
        if msg.code == EMPTY:
            if msg.mtype == MType.CON:
                if self.ping_enabled:
                    self._send(Message(MType.RST, EMPTY, msg.mid), sender)
            elif msg.mtype == MType.RST:
                target = self._sent_notifications.pop(msg.mid, None)
                if target is not None and self.honour_rst:
                    self.observers.pop(target, None)
            return
        path = msg.uri_path
        previous_path = self._last_path.get(sender)
        self._last_path[sender] = path
        if msg.code == GET and path == "/sys/dev/info":
            if self.info_enabled:
                self._handle_info(msg, sender)
        elif msg.code == POST and path == "/sys/dev/sync":
            if self.sync_enabled:
                self._handle_sync(msg, sender)
        elif msg.code == GET and path == "/sys/dev/status":
            self._handle_status(msg, sender, previous_path)
        elif msg.code == POST and path == "/sys/dev/control":
            if self.control_enabled:
                self._handle_control(msg, sender)
        else:
            reply_type = MType.ACK if msg.mtype == MType.CON else MType.NON
            mid = msg.mid if msg.mtype == MType.CON else self._next_mid()
            self._send(Message(reply_type, 0x84, mid, msg.token), sender)  # 4.04

    def _record(self, msg: Message, sender: Addr) -> None:
        if msg.code == EMPTY:
            if msg.mtype == MType.CON:
                self.pings_received += 1
            elif msg.mtype == MType.RST:
                self.resets_received += 1
            elif msg.mtype == MType.ACK:
                self.acks_received += 1
            return
        path = msg.uri_path
        self.requests.append((msg.mtype.name, path))
        if msg.code == POST and path == "/sys/dev/sync":
            self.syncs_received += 1
        elif msg.code == GET and path == "/sys/dev/status" and msg.observe is not None:
            (self.deregistrations if msg.observe == 1 else self.registrations).append((sender, msg.token))

    def _handle_info(self, msg: Message, sender: Addr) -> None:
        if self.drop_next_infos > 0:
            self.drop_next_infos -= 1
            return
        info = {
            "product_id": self.state["ProductId"],
            "device_id": self.state["DeviceId"],
            "name": self.state["D01S03"],
            "type": self.state["D01S04"],
            "modelid": self.state["D01S05"],
            "swversion": "0.0.0",
            "option": "119",
        }
        self._respond(msg, sender, json.dumps(info, separators=(",", ":")).encode())

    def _handle_sync(self, msg: Message, sender: Addr) -> None:
        # Measured: every sync returns a fresh, non-sequential counter.
        counter = os.urandom(4).hex().upper()
        self._counter = counter
        payload = counter.encode()
        if self.malformed_next_syncs > 0:
            self.malformed_next_syncs -= 1
            payload = counter[:6].encode() + b"\x00\x00"
        self._respond(msg, sender, payload)

    def _handle_status(self, msg: Message, sender: Addr, previous_path: str | None) -> None:
        observe = msg.observe
        if observe is None:
            return  # measured: a GET without Observe is never answered
        key: Observer = (sender, msg.token)
        if observe == 1:
            if self.honour_deregister:
                if self.deregister_ignores_token:
                    for other in [k for k in self.observers if k[0] == sender]:
                        del self.observers[other]
                else:
                    self.observers.pop(key, None)
            return
        if msg.token in self.blocked_tokens:
            return
        if self.observe_requires_fresh_sync and previous_path != "/sys/dev/sync":
            return
        if self.single_observer_per_ip:
            for other in [k for k in self.observers if k[0][0] == sender[0] and k != key]:
                del self.observers[other]
        self.observers[key] = {"registered": time.monotonic()}
        if self.answer_registration == "immediate":
            self._send_frame(key, "status")

    def _handle_control(self, msg: Message, sender: Addr) -> None:
        def answer(status: str) -> None:
            self._respond(msg, sender, json.dumps({"status": status}).encode())

        try:
            envelope = msg.payload.decode("ascii")
            counter, plain = crypto.decrypt(envelope)
            desired = json.loads(plain)["state"]["desired"]
        except (crypto.EnvelopeError, ValueError, KeyError, UnicodeDecodeError):
            answer("failed")
            return
        self.control_envelopes.append(envelope)
        self.controls.append({k: v for k, v in desired.items() if k not in ("CommandType", "DeviceId", "EnduserId")})
        if self.strict_counter:
            # Accepted only with the counter of the latest sync plus one.
            if self._counter is None or counter != crypto.next_counter(self._counter):
                answer("failed")
                return
            self._counter = counter
        if self.refuse_control or self.fail_next_controls > 0:
            self.fail_next_controls = max(0, self.fail_next_controls - 1)
            answer("failed")
            return
        before = dict(self.state)
        power_changed = False
        changed = False
        if POWER in desired and isinstance(desired[POWER], int):
            power_changed = self._set_power(1 if desired[POWER] else 0)
        for key, value in desired.items():
            if key in ("CommandType", "DeviceId", "EnduserId", POWER) or key in self.readonly_keys:
                continue
            if not self.is_on and self.standby_discards_settings:
                continue  # measured for the child lock: "success", not applied
            if isinstance(value, str):
                # Real firmware ignores string values, except "0".
                if value != "0":
                    continue
                value = 0
            if key == "D03130":
                value = 100 if value else 0
            if key not in self.state:
                continue
            if self.state[key] != value:
                self.state[key] = value
                changed = True
                if key == MODE:
                    self.state["D0310D"] = _SPEED_OF_MODE.get(value, 1)
        answer("success")
        if power_changed:
            notify = True
        elif self.is_on or not self.standby_silent:
            notify = changed or self.push_on_same_value
        else:
            notify = False
        if not notify:
            return
        if self.stale_frame_before_echo:
            # Generated before the main processor applied the write.
            for observer in list(self.observers):
                self._send_frame(observer, "status", state=before)
        if self.echo_delay > 0:
            loop = asyncio.get_running_loop()
            self._timers.append(loop.call_later(self.echo_delay, self._notify, "control"))
        else:
            self._notify("control")

    def _set_power(self, value: int) -> bool:
        """Switch on or off; returns True when the power state changed."""
        if self.state[POWER] == value:
            return False
        self.state[POWER] = value
        if value:
            self.state[MODE] = self._mode_before_standby
            self.state["D0310D"] = _SPEED_OF_MODE.get(self._mode_before_standby, 1)
        else:
            # Measured: the mode reads -16 while the device is off.
            self._mode_before_standby = self.state[MODE]
            self.state[MODE] = MODE_WHILE_OFF
            self.state["D0310D"] = 0
        return True

    # -- notifications -----------------------------------------------------

    def _notify(self, status_type: str) -> None:
        if self.drop_next_notifications > 0:
            self.drop_next_notifications -= 1
            return
        now = time.monotonic()
        for key, meta in list(self.observers.items()):
            if self.lapse_after is not None and now - meta["registered"] > self.lapse_after:
                continue
            self._send_frame(key, status_type)

    def _send_frame(
        self,
        observer: Observer,
        status_type: str,
        *,
        state: dict[str, Any] | None = None,
        runtime_shift_ms: int = 0,
    ) -> None:
        sender, token = observer
        reported = dict(self.state if state is None else state)
        reported["StatusType"] = status_type
        reported["Runtime"] = int((time.monotonic() - self._boot) * 1000) + runtime_shift_ms
        self._frame_counter += 1
        counter = f"{self._frame_counter:08X}"
        plain = json.dumps({"state": {"reported": reported, "desired": None}}, separators=(",", ":"))
        envelope = crypto.encrypt(counter, plain)
        if self.corrupt_next_frames > 0:
            self.corrupt_next_frames -= 1
            body = envelope[8:-64]
            body = body[:40] + "\x00\x00" + body[42:]
            digest = hashlib.sha256((counter + body).encode("latin-1")).hexdigest().upper()
            envelope = counter + body + digest
        self._observe_seq += 1
        options = [(OPT_OBSERVE, uint_bytes(self._observe_seq)), (OPT_MAX_AGE, uint_bytes(60))]
        mtype = MType.CON if self.notify_con else MType.NON
        mid = self._next_mid()
        self._sent_notifications[mid] = observer
        self.frames_sent += 1
        self._send(Message(mtype, CONTENT, mid, token, options, envelope.encode("latin-1")), sender)
