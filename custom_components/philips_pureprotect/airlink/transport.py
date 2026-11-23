"""One UDP socket that speaks the small CoAP subset the purifier needs.

Every datagram is sent exactly once. Retries, the deadlines of an exchange
and everything about the device's behaviour belong to the session; this
module matches answers to requests, acknowledges what must be acknowledged
and keeps the counters.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import random
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .coap import EMPTY, CoapError, Message, MType, code_class
from .errors import TransportError

_LOGGER = logging.getLogger(__package__)  # see session.py

Addr = tuple[str, int]
StreamCallback = Callable[[Message], None]
# Called with a direction ("tx", "rx", "rx_foreign" or "rx_malformed"), the
# other side's address and the raw datagram.
TraceCallback = Callable[[str, Addr, bytes], None]

_TOKEN_LENGTH = 4


@dataclass(slots=True)
class TransportCounters:
    """What went through the socket since the transport was created."""

    sent: int = 0
    received: int = 0  # well-formed datagrams from the device address
    foreign: int = 0  # datagrams from any other address, ignored
    malformed: int = 0  # not CoAP, from the device address
    unknown_token: int = 0  # responses nobody waits for, answered with a Reset
    resets_sent: int = 0
    acks_sent: int = 0


class _Protocol(asyncio.DatagramProtocol):
    """Forwards the callbacks of one socket; a replaced socket is ignored."""

    def __init__(self, owner: Transport) -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: tuple[Any, ...]) -> None:
        self._owner._datagram_received(self, data, (str(addr[0]), int(addr[1])))

    def error_received(self, exc: Exception) -> None:
        self._owner._socket_failed(self, exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc is not None:
            self._owner._socket_failed(self, exc)


class Transport:
    """A CoAP endpoint that talks to exactly one device address."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        bind_host: str = "0.0.0.0",  # noqa: S104 - an unbound source survives address changes
        on_contact: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        trace: TraceCallback | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.counters = TransportCounters()
        self.trace = trace
        self._bind_host = bind_host
        self._on_contact = on_contact
        self._on_error = on_error
        self._peer: Addr = (host, port)
        self._udp: asyncio.DatagramTransport | None = None
        self._protocol: _Protocol | None = None
        self._mid = random.randrange(0x10000)
        self._pending: dict[bytes, asyncio.Future[Message | None]] = {}
        self._pending_mids: dict[int, bytes] = {}
        self._pings: dict[int, asyncio.Future[bool]] = {}
        self._streams: dict[bytes, StreamCallback] = {}

    # -- lifecycle ---------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Return True while there is a usable socket."""
        return self._udp is not None and not self._udp.is_closing()

    @property
    def local_port(self) -> int:
        """Return the local UDP port, or 0 while there is no socket."""
        udp = self._udp
        return 0 if udp is None else int(udp.get_extra_info("sockname")[1])

    async def open(self) -> None:
        """Resolve the host and bind a socket; raises OSError on failure.

        Every open takes a new local port on purpose. The AC3220/10 serves
        one observer per source address and the newest registration wins
        (docs/metingen.md, measurement 9), so nothing is left behind on the
        device, and a registration from a new port is the kind it answers
        with a status frame (measurement 8). The caller supplies the deadline.
        """
        if self.is_open:
            return
        loop = asyncio.get_running_loop()
        self._peer = await self._resolve(loop)
        protocol = _Protocol(self)
        udp, _ = await loop.create_datagram_endpoint(
            lambda: protocol, local_addr=(self._bind_host, 0), family=socket.AF_INET
        )
        self._udp = udp
        self._protocol = protocol

    async def resolve_again(self) -> bool:
        """Look the host name up again; True when it now leads to another address.

        The socket is kept: it is bound to no address of its own, so it
        reaches the new address as it is. Whatever still arrives from the old
        address is ignored from then on. Raises OSError when the name cannot
        be resolved; the caller supplies the deadline.
        """
        peer = await self._resolve(asyncio.get_running_loop())
        if peer == self._peer:
            return False
        self._peer = peer
        return True

    async def _resolve(self, loop: asyncio.AbstractEventLoop) -> Addr:
        try:
            return str(ipaddress.IPv4Address(self.host)), self.port
        except ValueError:
            pass
        try:
            infos = await loop.getaddrinfo(self.host, self.port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
        except UnicodeError as err:
            # A name with an empty or an over-long label never reaches the
            # resolver: encoding it fails, and that is not an OSError.
            raise OSError(f"not a host name: {self.host!r}") from err
        if not infos:
            raise OSError(f"cannot resolve {self.host}")
        return str(infos[0][4][0]), self.port

    def close(self) -> None:
        """Close the socket; whoever waits for an answer gets "no answer"."""
        udp, self._udp, self._protocol = self._udp, None, None
        if udp is not None:
            udp.close()
        for waiting in self._pending.values():
            if not waiting.done():
                waiting.set_result(None)
        for ping in self._pings.values():
            if not ping.done():
                ping.set_result(False)

    # -- identifiers -------------------------------------------------------

    def next_mid(self) -> int:
        """Return a fresh message id."""
        self._mid = (self._mid + 1) & 0xFFFF
        return self._mid

    def new_token(self) -> bytes:
        """Return a random token that is not in use."""
        while True:
            token = os.urandom(_TOKEN_LENGTH)
            if token not in self._pending and token not in self._streams:
                return token

    # -- sending -----------------------------------------------------------

    def send(self, msg: Message) -> None:
        """Send one message; raises TransportError when there is no socket."""
        udp = self._udp
        if udp is None or udp.is_closing():
            raise TransportError("the socket is closed")
        data = msg.encode()
        self.counters.sent += 1
        self._emit_trace("tx", self._peer, data)
        udp.sendto(data, self._peer)

    async def request(self, msg: Message, timeout: float) -> Message | None:
        """Send a request and wait for the response that carries its token.

        Returns None when nothing arrived in time or the socket was closed.
        A Reset that answers the request is returned as that Reset message.
        """
        waiting: asyncio.Future[Message | None] = asyncio.get_running_loop().create_future()
        self._pending[msg.token] = waiting
        self._pending_mids[msg.mid] = msg.token
        try:
            self.send(msg)
            async with asyncio.timeout(timeout):
                return await waiting
        except TimeoutError:
            return None
        finally:
            self._pending.pop(msg.token, None)
            self._pending_mids.pop(msg.mid, None)

    async def ping(self, timeout: float) -> bool:
        """Send an empty confirmable message; True when the peer answered.

        The AC3220/10 answers with a Reset within 5-120 ms, running and in
        standby (docs/metingen.md, measurements 1 and 2).
        """
        mid = self.next_mid()
        answered: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pings[mid] = answered
        try:
            self.send(Message(MType.CON, EMPTY, mid))
            async with asyncio.timeout(timeout):
                return await answered
        except TimeoutError:
            return False
        finally:
            self._pings.pop(mid, None)

    # -- streams -----------------------------------------------------------

    def add_stream(self, token: bytes, callback: StreamCallback) -> None:
        """Deliver every response that carries this token to the callback."""
        self._streams[token] = callback

    def remove_stream(self, token: bytes) -> None:
        """Forget a token; later messages for it are answered with a Reset."""
        self._streams.pop(token, None)

    # -- receiving ---------------------------------------------------------

    def _datagram_received(self, protocol: _Protocol, data: bytes, sender: Addr) -> None:
        if protocol is not self._protocol:
            return
        if sender != self._peer:
            self.counters.foreign += 1
            self._emit_trace("rx_foreign", sender, data)
            return
        try:
            msg = Message.decode(data)
        except CoapError:
            self.counters.malformed += 1
            self._emit_trace("rx_malformed", sender, data)
            return
        self.counters.received += 1
        self._emit_trace("rx", sender, data)
        try:
            if self._on_contact is not None:
                self._on_contact()
            self._dispatch(msg)
        except Exception:
            _LOGGER.exception("%s: handling a datagram failed", self.host)

    def _dispatch(self, msg: Message) -> None:
        if msg.code == EMPTY:
            self._dispatch_empty(msg)
            return
        if code_class(msg.code) not in (2, 4, 5):
            # A request from the device. Nothing here serves requests.
            if msg.mtype is MType.CON:
                self._reply(MType.RST, msg.mid)
            return
        stream = self._streams.get(msg.token)
        waiting = self._pending.get(msg.token)
        if waiting is not None and not waiting.done():
            waiting.set_result(msg)
        known = stream is not None or waiting is not None
        if known:
            if msg.mtype is MType.CON:
                self._reply(MType.ACK, msg.mid)
        elif msg.mtype in (MType.CON, MType.NON):
            # Tells a device to stop serving an observer that no longer
            # exists (report 6.3; RFC 7641 section 3.6). The AC3220/10 was
            # measured to ignore it (metingen.md, measurement 10); it stays
            # as the correct and harmless answer for firmware that listens.
            self.counters.unknown_token += 1
            self._reply(MType.RST, msg.mid)
        if stream is not None:
            stream(msg)

    def _dispatch_empty(self, msg: Message) -> None:
        if msg.mtype is MType.CON:
            # A ping from the device.
            self._reply(MType.RST, msg.mid)
            return
        ping = self._pings.get(msg.mid)
        if ping is not None:
            if not ping.done():
                ping.set_result(True)
            return
        if msg.mtype is MType.RST:
            token = self._pending_mids.get(msg.mid)
            waiting = self._pending.get(token) if token is not None else None
            if waiting is not None and not waiting.done():
                waiting.set_result(msg)
        # An empty ACK only says that the response follows separately.

    def _reply(self, mtype: MType, mid: int) -> None:
        try:
            self.send(Message(mtype, EMPTY, mid))
        except TransportError:
            return
        if mtype is MType.RST:
            self.counters.resets_sent += 1
        else:
            self.counters.acks_sent += 1

    def _socket_failed(self, protocol: _Protocol, exc: Exception) -> None:
        if protocol is not self._protocol:
            return
        if self._on_error is not None:
            try:
                self._on_error(exc)
            except Exception:
                _LOGGER.exception("%s: the socket error handler failed", self.host)

    def _emit_trace(self, direction: str, addr: Addr, data: bytes) -> None:
        if self.trace is None:
            return
        try:
            self.trace(direction, addr, data)
        except Exception:
            _LOGGER.exception("%s: the trace callback failed", self.host)
