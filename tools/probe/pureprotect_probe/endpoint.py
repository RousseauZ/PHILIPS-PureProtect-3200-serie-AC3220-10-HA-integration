"""One UDP socket that speaks CoAP and logs every datagram.

The endpoint never retransmits and never hides anything: a lost datagram
shows up as a missing answer, which is what a measurement needs.
"""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .coap import (
    EMPTY,
    CoapError,
    Message,
    MType,
    code_class,
    code_text,
)
from .eventlog import EventLog

Addr = tuple[str, int]


@dataclass(slots=True)
class Received:
    """A decoded datagram with its arrival time and sender."""

    t: float
    addr: Addr
    msg: Message
    size: int


class Endpoint(asyncio.DatagramProtocol):
    """A CoAP endpoint bound to one local UDP port."""

    def __init__(self, log: EventLog, name: str = "A") -> None:
        self.log = log
        self.name = name
        self.peer_ip: str | None = None
        # What to do with a response whose token nobody is waiting for:
        # "rst" answers a confirmable one with a Reset (RFC 7252 section 4.2),
        # "rst-all" also resets non-confirmable ones, "ignore" stays silent.
        self.unknown_policy = "rst"
        self._transport: asyncio.DatagramTransport | None = None
        self._mid = random.randrange(0x10000)
        self._pending: dict[bytes, asyncio.Future[Received]] = {}
        self._pending_mid: dict[int, asyncio.Future[Received]] = {}
        self._mid_to_token: dict[int, bytes] = {}
        self._streams: dict[bytes, Callable[[Received], None]] = {}
        self._reject_next: set[bytes] = set()
        self._listeners: list[Callable[[Received], None]] = []

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    async def open(
        cls,
        log: EventLog,
        name: str = "A",
        *,
        local_port: int = 0,
        peer_ip: str | None = None,
        bind_host: str = "0.0.0.0",  # noqa: S104 - replies to broadcasts need it
    ) -> Endpoint:
        """Create the socket. ``peer_ip`` limits accepted senders to one host."""
        loop = asyncio.get_running_loop()
        endpoint = cls(log, name)
        endpoint.peer_ip = peer_ip
        await loop.create_datagram_endpoint(
            lambda: endpoint, local_addr=(bind_host, local_port), allow_broadcast=True
        )
        return endpoint

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store the transport and log the local address."""
        self._transport = transport  # type: ignore[assignment]
        sockname = transport.get_extra_info("sockname")
        self.log.write("socket", endpoint=self.name, local=list(sockname[:2]))

    @property
    def local_port(self) -> int:
        """Return the local UDP port."""
        if self._transport is None:
            return 0
        return int(self._transport.get_extra_info("sockname")[1])

    def close(self) -> None:
        """Close the socket and fail everything that is still waiting."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        for future in list(self._pending.values()) + list(self._pending_mid.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._pending_mid.clear()

    def error_received(self, exc: Exception) -> None:
        """Log socket errors such as ICMP port unreachable."""
        self.log.write("socket_error", endpoint=self.name, error=repr(exc))

    # -- identifiers -------------------------------------------------------

    def next_mid(self) -> int:
        """Return a fresh message id."""
        self._mid = (self._mid + 1) & 0xFFFF
        return self._mid

    @staticmethod
    def new_token(length: int = 4) -> bytes:
        """Return a random token."""
        return os.urandom(length)

    # -- sending -----------------------------------------------------------

    def send(self, msg: Message, addr: Addr, *, what: str = "") -> None:
        """Send one message and log it."""
        if self._transport is None:
            raise RuntimeError("endpoint is closed")
        data = msg.encode()
        self.log.write("tx", endpoint=self.name, to=list(addr), what=what, **_describe(msg, len(data)))
        self._transport.sendto(data, addr)

    async def request(self, msg: Message, addr: Addr, timeout: float, *, what: str = "") -> Received | None:
        """Send a request and wait for the response with the same token.

        Returns None on timeout. A Reset answering the request is returned as
        the Received object, so the caller can tell it from silence.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Received] = loop.create_future()
        self._pending[msg.token] = future
        self._mid_to_token[msg.mid] = msg.token
        try:
            self.send(msg, addr, what=what)
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            return None
        finally:
            self._pending.pop(msg.token, None)
            self._mid_to_token.pop(msg.mid, None)

    async def ping(self, addr: Addr, timeout: float) -> Received | None:
        """Send an empty confirmable message; a live CoAP stack answers with a Reset."""
        loop = asyncio.get_running_loop()
        mid = self.next_mid()
        future: asyncio.Future[Received] = loop.create_future()
        self._pending_mid[mid] = future
        try:
            self.send(Message(MType.CON, EMPTY, mid), addr, what="ping")
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            return None
        finally:
            self._pending_mid.pop(mid, None)

    # -- streams (observations) and listeners ------------------------------

    def add_stream(self, token: bytes, callback: Callable[[Received], None]) -> None:
        """Deliver every response carrying this token to the callback."""
        self._streams[token] = callback

    def remove_stream(self, token: bytes) -> None:
        """Forget a token; later messages for it count as unknown."""
        self._streams.pop(token, None)
        self._reject_next.discard(token)

    def reject_next(self, token: bytes) -> None:
        """Answer the next message for this token with a Reset (once)."""
        self._reject_next.add(token)

    def add_listener(self, callback: Callable[[Received], None]) -> None:
        """Call back for every response, known token or not (used by discovery)."""
        self._listeners.append(callback)

    # -- receiving ---------------------------------------------------------

    def datagram_received(self, data: bytes, addr: Any) -> None:
        """Decode, log and dispatch one datagram."""
        sender: Addr = (addr[0], addr[1])
        try:
            msg = Message.decode(data)
        except CoapError as err:
            self.log.write(
                "rx_invalid", endpoint=self.name, sender=list(sender), size=len(data), error=str(err), head=data[:16].hex()
            )
            return
        received = Received(self.log.now(), sender, msg, len(data))
        foreign = self.peer_ip is not None and sender[0] != self.peer_ip
        self.log.write(
            "rx", endpoint=self.name, sender=list(sender), foreign=foreign or None, **_describe(msg, len(data))
        )
        if foreign:
            return
        if msg.code == EMPTY:
            self._handle_empty(received)
        elif code_class(msg.code) in (2, 4, 5):
            self._handle_response(received)
        else:
            self.log.write("rx_unexpected_request", endpoint=self.name, sender=list(sender))

    def _handle_empty(self, received: Received) -> None:
        msg = received.msg
        if msg.mtype == MType.CON:
            # A ping from the other side: answer with a Reset.
            self.send(Message(MType.RST, EMPTY, msg.mid), received.addr, what="pong")
            return
        future = self._pending_mid.get(msg.mid)
        if future is not None and not future.done():
            future.set_result(received)
            return
        if msg.mtype == MType.RST:
            token = self._mid_to_token.get(msg.mid)
            waiting = self._pending.get(token) if token is not None else None
            if waiting is not None and not waiting.done():
                waiting.set_result(received)
        # An empty ACK only says "request received, response follows".

    def _handle_response(self, received: Received) -> None:
        msg = received.msg
        known = False
        rejected = False
        stream = self._streams.get(msg.token)
        if stream is not None:
            known = True
            if msg.token in self._reject_next:
                self._reject_next.discard(msg.token)
                rejected = True
        future = self._pending.get(msg.token)
        if future is not None and not future.done():
            known = True
            future.set_result(received)
        if rejected:
            self.send(Message(MType.RST, EMPTY, msg.mid), received.addr, what="reject")
        elif msg.mtype == MType.CON:
            if known:
                self.send(Message(MType.ACK, EMPTY, msg.mid), received.addr, what="ack")
            elif self.unknown_policy in ("rst", "rst-all"):
                self.send(Message(MType.RST, EMPTY, msg.mid), received.addr, what="rst-unknown")
        elif msg.mtype == MType.NON and not known and self.unknown_policy == "rst-all":
            self.send(Message(MType.RST, EMPTY, msg.mid), received.addr, what="rst-unknown")
        if stream is not None:
            stream(received)
        for listener in self._listeners:
            listener(received)


def _describe(msg: Message, size: int) -> dict[str, Any]:
    """Return the loggable header fields of a message."""
    fields: dict[str, Any] = {
        "type": msg.mtype.name,
        "code": code_text(msg.code),
        "mid": msg.mid,
        "token": msg.token.hex(),
        "size": size,
        "payload_len": len(msg.payload),
    }
    path = msg.option_values(11)
    if path:
        fields["path"] = msg.uri_path
    if msg.observe is not None:
        fields["observe"] = msg.observe
    if msg.max_age is not None:
        fields["max_age"] = msg.max_age
    if msg.block2 is not None:
        fields["block2"] = list(msg.block2)
    return fields
