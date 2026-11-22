"""The purifier's four resources, built on the logging endpoint.

Every call is a single attempt with a deadline. Nothing is retried here:
the scenarios decide what to repeat, so that losses stay visible.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import crypto
from .coap import DEFAULT_PORT, GET, POST, Message, MType, build_request, code_text
from .endpoint import Addr, Endpoint, Received
from .eventlog import redact

INFO_PATH = "/sys/dev/info"
SYNC_PATH = "/sys/dev/sync"
STATUS_PATH = "/sys/dev/status"
CONTROL_PATH = "/sys/dev/control"

# Keys that change in (nearly) every frame and say nothing about the state.
NOISE_KEYS = frozenset({"Runtime", "rssi", "free_memory", "StatusType"})


@dataclass(slots=True)
class Reply:
    """Outcome of one request."""

    ok: bool
    latency: float | None = None
    kind: str = "timeout"  # "response", "reset" or "timeout"
    mtype: str | None = None
    code: str | None = None
    data: Any = None
    note: str = ""


@dataclass(slots=True)
class Frame:
    """One message received on a status observation."""

    index: int
    t: float
    endpoint: str
    token: bytes
    mtype: MType
    mid: int
    code: int
    observe: int | None
    max_age: int | None
    size: int
    decode: str  # "ok", "ok_stripped" or "err:<reason>"
    counter: str | None = None
    reported: dict[str, Any] | None = None
    changed: dict[str, Any] = field(default_factory=dict)
    identical: bool = False


def decode_status(payload: bytes) -> tuple[str, str | None, dict[str, Any] | None]:
    """Decode a status payload. Returns (result tag, counter, reported dict)."""
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        text = payload.decode("latin-1")
    reason = "unknown"
    for tag, candidate in (("ok", text), ("ok_stripped", text.replace("\x00", "").strip())):
        if tag == "ok_stripped" and candidate == text:
            break
        try:
            counter, plain = crypto.decrypt(candidate)
            reported = json.loads(plain)["state"]["reported"]
            if not isinstance(reported, dict):
                raise TypeError
        except crypto.EnvelopeError as err:
            # Keep the reason of the strict attempt; it describes the wire data.
            reason = err.reason if tag == "ok" else reason
            continue
        except (ValueError, KeyError, TypeError):
            reason = "bad_json" if tag == "ok" else reason
            continue
        return tag, counter, reported
    return f"err:{reason}", text[:8] if crypto.is_valid_counter(text[:8]) else None, None


class Purifier:
    """Talks to one purifier through one endpoint."""

    def __init__(self, endpoint: Endpoint, host: str, port: int = DEFAULT_PORT, *, redact_ids: bool = True) -> None:
        self.ep = endpoint
        self.addr: Addr = (host, port)
        self.redact_ids = redact_ids
        self.counter: str | None = None
        self.frames: list[Frame] = []
        self.latest: dict[str, Any] | None = None
        self.device_id: str | None = None
        self._frame_event = asyncio.Event()
        self._exchange = asyncio.Lock()
        self._on_frame: list[Callable[[Frame], None]] = []

    @property
    def log(self):  # noqa: ANN201 - EventLog, avoids an import cycle in type hints
        """Return the event log of the endpoint."""
        return self.ep.log

    # -- plain requests ----------------------------------------------------

    async def _request(self, code: int, path: str, *, con: bool, timeout: float, payload: bytes = b"") -> tuple[Reply, Received | None]:
        mtype = MType.CON if con else MType.NON
        msg = build_request(mtype, code, self.ep.next_mid(), self.ep.new_token(), path, payload=payload)
        sent = self.log.now()
        received = await self.ep.request(msg, self.addr, timeout, what=path)
        if received is None:
            return Reply(ok=False), None
        latency = round(received.t - sent, 4)
        if received.msg.mtype == MType.RST:
            return Reply(ok=False, latency=latency, kind="reset", mtype="RST", code="0.00"), received
        reply = Reply(
            ok=received.msg.code >> 5 == 2,
            latency=latency,
            kind="response",
            mtype=received.msg.mtype.name,
            code=code_text(received.msg.code),
        )
        return reply, received

    async def info(self, *, con: bool = False, timeout: float = 3.0) -> Reply:
        """Read the plaintext info resource."""
        reply, received = await self._request(GET, INFO_PATH, con=con, timeout=timeout)
        if received is not None and reply.kind == "response":
            try:
                reply.data = json.loads(received.msg.payload.decode("utf-8", "replace"))
            except ValueError:
                reply.ok = False
                reply.note = "geen geldige JSON"
                reply.data = None
        self.log.write(
            "info",
            endpoint=self.ep.name,
            ok=reply.ok,
            kind=reply.kind,
            latency=reply.latency,
            con=con,
            data=redact(reply.data, self.redact_ids) if isinstance(reply.data, dict) else None,
            note=reply.note or None,
        )
        return reply

    async def sync(self, *, con: bool = False, timeout: float = 3.0) -> Reply:
        """Run the sync handshake and remember the returned counter."""
        async with self._exchange:
            return await self._sync(con=con, timeout=timeout)

    async def _sync(self, *, con: bool, timeout: float) -> Reply:
        nonce = os.urandom(4).hex().upper().encode()
        reply, received = await self._request(POST, SYNC_PATH, con=con, timeout=timeout, payload=nonce)
        raw = None
        if received is not None and reply.kind == "response":
            raw = received.msg.payload
            text = raw.decode("latin-1")
            if crypto.is_valid_counter(text):
                self.counter = text.upper()
                reply.data = self.counter
            else:
                reply.ok = False
                reply.note = "misvormd sync-antwoord"
        self.log.write(
            "sync",
            endpoint=self.ep.name,
            ok=reply.ok,
            kind=reply.kind,
            latency=reply.latency,
            con=con,
            counter=reply.data,
            raw_hex=raw.hex() if raw is not None and not reply.ok else None,
            note=reply.note or None,
        )
        return reply

    async def ping(self, *, timeout: float = 3.0) -> Reply:
        """Send an empty confirmable message and expect a Reset."""
        sent = self.log.now()
        received = await self.ep.ping(self.addr, timeout)
        if received is None:
            reply = Reply(ok=False)
        else:
            reply = Reply(
                ok=True,
                latency=round(received.t - sent, 4),
                kind="reset" if received.msg.mtype == MType.RST else "response",
                mtype=received.msg.mtype.name,
                code=code_text(received.msg.code),
            )
        self.log.write("ping", endpoint=self.ep.name, ok=reply.ok, kind=reply.kind, latency=reply.latency)
        return reply

    async def control(
        self,
        values: dict[str, Any],
        *,
        sync_first: bool = True,
        con: bool = False,
        timeout: float = 3.0,
    ) -> Reply:
        """Write values. By default a sync is done right before, under one lock."""
        async with self._exchange:
            if sync_first or self.counter is None:
                synced = await self._sync(con=con, timeout=timeout)
                if not synced.ok:
                    reply = Reply(ok=False, kind=synced.kind, note="sync mislukt vóór schrijven")
                    self.log.write("control", endpoint=self.ep.name, ok=False, values=values, note=reply.note)
                    return reply
            assert self.counter is not None
            counter = crypto.next_counter(self.counter)
            self.counter = counter
            document = {"state": {"desired": {"CommandType": "app", "DeviceId": "", "EnduserId": "", **values}}}
            envelope = crypto.encrypt(counter, json.dumps(document))
            reply, received = await self._request(POST, CONTROL_PATH, con=con, timeout=timeout, payload=envelope.encode())
        if received is not None and reply.kind == "response":
            text = received.msg.payload.decode("utf-8", "replace")
            try:
                reply.data = json.loads(text).get("status")
            except (ValueError, AttributeError):
                reply.data = None
                reply.note = f"onverwacht antwoord: {text[:60]!r}"
            reply.ok = reply.data == "success"
        self.log.write(
            "control",
            endpoint=self.ep.name,
            ok=reply.ok,
            kind=reply.kind,
            latency=reply.latency,
            values=values,
            counter=counter,
            status=reply.data,
            sync_first=sync_first,
            note=reply.note or None,
        )
        return reply

    # -- observation -------------------------------------------------------

    def register(self, token: bytes, *, con: bool = False, what: str = "register") -> None:
        """Send an Observe registration. The answer, if any, arrives as a frame."""
        self.ep.add_stream(token, self._frame_received)
        mtype = MType.CON if con else MType.NON
        msg = build_request(mtype, GET, self.ep.next_mid(), token, STATUS_PATH, observe=0)
        self.ep.send(msg, self.addr, what=what)

    def deregister(self, token: bytes, *, con: bool = False) -> None:
        """Send an Observe deregistration (Observe: 1) for a token."""
        mtype = MType.CON if con else MType.NON
        msg = build_request(mtype, GET, self.ep.next_mid(), token, STATUS_PATH, observe=1)
        self.ep.send(msg, self.addr, what="deregister")

    def plain_status_get(self, token: bytes) -> None:
        """Send a status GET without the Observe option."""
        self.ep.add_stream(token, self._frame_received)
        msg = build_request(MType.NON, GET, self.ep.next_mid(), token, STATUS_PATH)
        self.ep.send(msg, self.addr, what="plain-get")

    def on_frame(self, callback: Callable[[Frame], None]) -> None:
        """Call back for every frame."""
        self._on_frame.append(callback)

    def _frame_received(self, received: Received) -> None:
        msg = received.msg
        frame = Frame(
            index=len(self.frames),
            t=received.t,
            endpoint=self.ep.name,
            token=msg.token,
            mtype=msg.mtype,
            mid=msg.mid,
            code=msg.code,
            observe=msg.observe,
            max_age=msg.max_age,
            size=received.size,
            decode="err:no_payload",
        )
        if msg.code >> 5 == 2 and msg.payload:
            frame.decode, frame.counter, frame.reported = decode_status(msg.payload)
        elif msg.code >> 5 != 2:
            frame.decode = f"err:code_{code_text(msg.code)}"
        first = self.latest is None
        if frame.reported is not None:
            if "DeviceId" in frame.reported:
                self.device_id = str(frame.reported["DeviceId"])
            previous = self.latest or {}
            frame.changed = {
                key: value
                for key, value in frame.reported.items()
                if previous.get(key) != value and key not in NOISE_KEYS
            }
            frame.identical = not first and not frame.changed
            self.latest = frame.reported
        self.frames.append(frame)
        self.log.write(
            "frame",
            index=frame.index,
            endpoint=frame.endpoint,
            token=frame.token.hex(),
            type=frame.mtype.name,
            mid=frame.mid,
            observe=frame.observe,
            max_age=frame.max_age,
            size=frame.size,
            decode=frame.decode,
            counter=frame.counter,
            status_type=(frame.reported or {}).get("StatusType"),
            runtime=(frame.reported or {}).get("Runtime"),
            identical=frame.identical,
            reported=redact(frame.reported, self.redact_ids) if first and frame.reported else None,
            changed=redact(frame.changed, self.redact_ids) if not first and frame.changed else None,
        )
        self._frame_event.set()
        for callback in self._on_frame:
            callback(frame)

    async def wait_frame(
        self,
        *,
        since: int | None = None,
        timeout: float,
        predicate: Callable[[Frame], bool] | None = None,
    ) -> Frame | None:
        """Wait for a frame with index >= since that satisfies the predicate."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        index = len(self.frames) if since is None else since
        while True:
            while index < len(self.frames):
                frame = self.frames[index]
                index += 1
                if predicate is None or predicate(frame):
                    return frame
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            self._frame_event.clear()
            try:
                await asyncio.wait_for(self._frame_event.wait(), remaining)
            except TimeoutError:
                return None
