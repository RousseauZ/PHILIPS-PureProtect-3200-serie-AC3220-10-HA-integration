"""A simulated purifier on a local UDP port, for tests.

It implements the four resources and can show each firmware quirk that the
research found, so that every quirk can be exercised without hardware.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from pureprotect_probe import crypto
from pureprotect_probe.coap import (
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

# Shaped like the published AC3220/10 status (identifiers are made up).
DEFAULT_STATE: dict[str, Any] = {
    "D01S03": "Testkamer",
    "D01S04": "Unicorn",
    "D01S05": "AC3220/10",
    "D01S12": "0.2.3",
    "ProductId": "00000000000011ee88c206d016384e4a",
    "DeviceId": "11111111222211ef93334444555566aa",
    "Runtime": 1000,
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
    "D03134": 1,
    "D03135": 1,
    "D03137": 1,
    "D03180": 0,
    "D03240": 0,
    "D05408": 9600,
    "D0540E": 9501,
    "D05207": 720,
    "D0520D": 621,
}


class FakePurifier(asyncio.DatagramProtocol):
    """Simulated device. Set the quirk attributes before or during a test."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = dict(DEFAULT_STATE)
        # "immediate": a registration is answered at once.
        # "on_change": it is answered only by the next change (push-on-change).
        self.answer_registration = "immediate"
        self.lapse_after: float | None = None  # observer expires unless re-registered
        self.single_observer_per_ip = False
        self.honour_deregister = True
        self.honour_rst = True
        self.notify_con = False
        self.info_enabled = True
        self.sync_enabled = True
        self.ping_enabled = True
        self.silent = False  # drop everything, as if powered off
        self.strict_counter = True
        self.global_counter = True  # one counter for all clients
        self.readonly_keys: set[str] = {"D03105", "D03137"}  # acked, then discarded
        self.push_on_same_value = False
        self.corrupt_next_frames = 0  # NUL bytes with a valid digest
        self.drop_next_notifications = 0  # change notifications that get lost
        self.malformed_next_syncs = 0
        self.observers: dict[tuple[tuple[str, int], bytes], dict[str, Any]] = {}
        self.counters: dict[Any, str] = {}
        self.requests: list[tuple[str, str]] = []
        self.resets_received = 0
        self.acks_received = 0
        self._transport: asyncio.DatagramTransport | None = None
        self._mid = 100
        self._frame_counter = 0x10000000
        self._observe_seq = 40
        self._boot = time.monotonic()
        self._sent_notifications: dict[int, tuple[tuple[str, int], bytes]] = {}

    @classmethod
    async def start(cls, host: str = "127.0.0.1") -> FakePurifier:
        """Bind to a free port and return the running device."""
        loop = asyncio.get_running_loop()
        device = cls()
        await loop.create_datagram_endpoint(lambda: device, local_addr=(host, 0))
        return device

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    @property
    def port(self) -> int:
        assert self._transport is not None
        return int(self._transport.get_extra_info("sockname")[1])

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()

    # -- test controls -----------------------------------------------------

    def change(self, key: str, value: Any, *, status_type: str = "status") -> None:
        """Change a value as if a button was pressed, and notify observers."""
        self.state[key] = value
        self._notify(status_type)

    def reboot(self) -> None:
        """Forget observers and counters, as after a power cycle."""
        self.observers.clear()
        self.counters.clear()
        self._boot = time.monotonic()
        self._observe_seq = 1

    # -- wire --------------------------------------------------------------

    def _next_mid(self) -> int:
        self._mid = (self._mid + 1) & 0xFFFF
        return self._mid

    def _send(self, msg: Message, addr: tuple[str, int]) -> None:
        assert self._transport is not None
        self._transport.sendto(msg.encode(), addr)

    def _respond(self, request: Message, addr: tuple[str, int], payload: bytes, options: list[tuple[int, bytes]] | None = None) -> None:
        """Answer a request: piggybacked on the ACK for CON, NON otherwise."""
        if request.mtype == MType.CON:
            msg = Message(MType.ACK, CONTENT, request.mid, request.token, options or [], payload)
        else:
            msg = Message(MType.NON, CONTENT, self._next_mid(), request.token, options or [], payload)
        self._send(msg, addr)

    def datagram_received(self, data: bytes, addr: Any) -> None:
        sender = (addr[0], addr[1])
        try:
            msg = Message.decode(data)
        except CoapError:
            return
        if self.silent:
            return
        if msg.code == EMPTY:
            if msg.mtype == MType.CON and self.ping_enabled:
                self._send(Message(MType.RST, EMPTY, msg.mid), sender)
            elif msg.mtype == MType.RST:
                self.resets_received += 1
                target = self._sent_notifications.pop(msg.mid, None)
                if target is not None and self.honour_rst:
                    self.observers.pop(target, None)
            elif msg.mtype == MType.ACK:
                self.acks_received += 1
            return
        path = msg.uri_path
        self.requests.append((msg.mtype.name, path))
        if msg.code == GET and path == "/sys/dev/info":
            if self.info_enabled:
                self._handle_info(msg, sender)
        elif msg.code == POST and path == "/sys/dev/sync":
            if self.sync_enabled:
                self._handle_sync(msg, sender)
        elif msg.code == GET and path == "/sys/dev/status":
            self._handle_status(msg, sender)
        elif msg.code == POST and path == "/sys/dev/control":
            self._handle_control(msg, sender)
        else:
            reply_type = MType.ACK if msg.mtype == MType.CON else MType.NON
            mid = msg.mid if msg.mtype == MType.CON else self._next_mid()
            self._send(Message(reply_type, 0x84, mid, msg.token), sender)  # 4.04

    def _handle_info(self, msg: Message, sender: tuple[str, int]) -> None:
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

    def _counter_key(self, sender: tuple[str, int]) -> Any:
        return "global" if self.global_counter else sender

    def _handle_sync(self, msg: Message, sender: tuple[str, int]) -> None:
        counter = os.urandom(4).hex().upper()
        self.counters[self._counter_key(sender)] = counter
        payload = counter.encode()
        if self.malformed_next_syncs > 0:
            self.malformed_next_syncs -= 1
            payload = counter[:6].encode() + b"\x00\x00"
        self._respond(msg, sender, payload)

    def _handle_status(self, msg: Message, sender: tuple[str, int]) -> None:
        observe = msg.observe
        if observe is None:
            return  # a plain GET is never answered
        key = (sender, msg.token)
        if observe == 1:
            if self.honour_deregister:
                self.observers.pop(key, None)
            return
        if self.single_observer_per_ip:
            for other in [k for k in self.observers if k[0][0] == sender[0] and k != key]:
                del self.observers[other]
        self.observers[key] = {"registered": time.monotonic()}
        if self.answer_registration == "immediate":
            self._send_frame(key, "status")

    def _handle_control(self, msg: Message, sender: tuple[str, int]) -> None:
        def answer(status: str) -> None:
            self._respond(msg, sender, json.dumps({"status": status}).encode())

        try:
            counter, plain = crypto.decrypt(msg.payload.decode("ascii"))
            desired = json.loads(plain)["state"]["desired"]
        except (crypto.EnvelopeError, ValueError, KeyError, UnicodeDecodeError):
            answer("failed")
            return
        if self.strict_counter:
            last = self.counters.get(self._counter_key(sender))
            if last is None or counter != crypto.next_counter(last):
                answer("failed")
                return
            self.counters[self._counter_key(sender)] = counter
        changed = False
        for key, value in desired.items():
            if key in ("CommandType", "DeviceId", "EnduserId") or key in self.readonly_keys:
                continue
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
                if key == "D0310C":
                    self.state["D0310D"] = {1: 1, 2: 2, 3: 3, 4: 4, 5: 18, 18: 18, 19: 3}.get(value, 1)
        answer("success")
        if changed or self.push_on_same_value:
            self._notify("control")

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

    def _send_frame(self, key: tuple[tuple[str, int], bytes], status_type: str) -> None:
        sender, token = key
        state = dict(self.state)
        state["StatusType"] = status_type
        state["Runtime"] = int((time.monotonic() - self._boot) * 1000) + 1000
        self._frame_counter += 1
        counter = f"{self._frame_counter:08X}"
        plain = json.dumps({"state": {"reported": state, "desired": None}}, separators=(",", ":"))
        envelope = crypto.encrypt(counter, plain)
        if self.corrupt_next_frames > 0:
            self.corrupt_next_frames -= 1
            import hashlib

            body = envelope[8:-64]
            body = body[:40] + "\x00\x00" + body[42:]
            digest = hashlib.sha256((counter + body).encode("latin-1")).hexdigest().upper()
            envelope = counter + body + digest
        self._observe_seq += 1
        options = [(OPT_OBSERVE, uint_bytes(self._observe_seq)), (OPT_MAX_AGE, uint_bytes(60))]
        mtype = MType.CON if self.notify_con else MType.NON
        mid = self._next_mid()
        self._sent_notifications[mid] = key
        self._send(Message(mtype, CONTENT, mid, token, options, envelope.encode("latin-1")), sender)
