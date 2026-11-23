"""The transport: one socket, token matching, pings, streams, counters."""

from __future__ import annotations

import asyncio
import os
import socket
from typing import TYPE_CHECKING, Any

import pytest
from airlink.coap import CONTENT, EMPTY, GET, POST, Message, MType, build_request
from airlink.errors import TransportError
from airlink.transport import Transport

if TYPE_CHECKING:
    from conftest import Bench


def info_request(transport: Transport, *, mtype: MType = MType.NON) -> Message:
    return build_request(mtype, GET, transport.next_mid(), transport.new_token(), "/sys/dev/info")


def register(transport: Transport, token: bytes) -> None:
    transport.send(build_request(MType.NON, GET, transport.next_mid(), token, "/sys/dev/status", observe=0))


def test_request_is_matched_by_token(bench: Bench) -> None:
    async def body() -> None:
        transport = bench.transport()
        await transport.open()
        first, second = info_request(transport), info_request(transport)
        one, two = await asyncio.gather(transport.request(first, 1.0), transport.request(second, 1.0))
        assert one is not None and two is not None
        assert (one.token, two.token) == (first.token, second.token)
        assert all(reply.code == CONTENT and b"AC3220/10" in reply.payload for reply in (one, two))
        assert transport.counters.sent == 2 and transport.counters.received == 2

    bench.run(body)


def test_confirmable_request_takes_the_piggybacked_answer(bench: Bench) -> None:
    async def body() -> None:
        transport = bench.transport()
        await transport.open()
        reply = await transport.request(info_request(transport, mtype=MType.CON), 1.0)
        assert reply is not None and reply.mtype is MType.ACK and reply.code == CONTENT

    bench.run(body)


def test_request_without_answer_returns_none_at_the_deadline(bench: Bench) -> None:
    async def body() -> None:
        transport = bench.transport()
        await transport.open()
        assert await transport.request(info_request(transport), 0.1) is None
        assert not transport._pending and not transport._pending_mids

    bench.run(body, silent=True)


def test_ping_is_answered_with_a_reset(bench: Bench) -> None:
    async def body() -> None:
        transport = bench.transport()
        await transport.open()
        assert await transport.ping(1.0) is True
        assert bench.fake.pings_received == 1
        bench.fake.ping_enabled = False
        assert await transport.ping(0.1) is False

    bench.run(body)


def test_stream_delivers_every_message_for_its_token(bench: Bench) -> None:
    async def body() -> None:
        transport = bench.transport()
        await transport.open()
        seen: list[Message] = []
        token = transport.new_token()
        transport.add_stream(token, seen.append)
        register(transport, token)
        # The device answers a new registration with its status...
        await bench.until(lambda: len(seen) == 1)
        # ...and then reports every change.
        bench.fake.change("D03221", 9)
        bench.fake.change("D03221", 10)
        await bench.until(lambda: len(seen) == 3)
        assert all(msg.token == token and msg.max_age == 60 for msg in seen)
        assert transport.counters.resets_sent == 0 and transport.counters.acks_sent == 0

    bench.run(body)


def test_confirmable_notification_is_acknowledged(bench: Bench) -> None:
    async def body() -> None:
        transport = bench.transport()
        await transport.open()
        seen: list[Message] = []
        token = transport.new_token()
        transport.add_stream(token, seen.append)
        register(transport, token)
        await bench.until(lambda: bench.fake.acks_received == 1)
        assert seen[0].mtype is MType.CON and transport.counters.acks_sent == 1

    bench.run(body, notify_con=True)


@pytest.mark.parametrize("confirmable", [False, True])
def test_unknown_token_is_answered_with_a_reset(bench: Bench, confirmable: bool) -> None:
    async def body() -> None:
        bench.fake.notify_con = confirmable
        transport = bench.transport()
        await transport.open()
        token = transport.new_token()
        transport.add_stream(token, lambda msg: None)
        register(transport, token)
        await bench.until(lambda: bool(bench.fake.observers))
        transport.remove_stream(token)
        bench.fake.change("D03221", 9)
        await bench.until(lambda: bench.fake.resets_received == 1)
        assert transport.counters.unknown_token == 1 and transport.counters.resets_sent == 1
        # A firmware that listens stops serving that observer. The AC3220/10
        # was measured to carry on, which the default of the simulation copies.
        assert not bench.fake.observers

    bench.run(body, answer_registration="on_change", honour_rst=True)


def test_ping_from_the_device_is_answered_with_a_reset(bench: Bench) -> None:
    async def body() -> None:
        transport = bench.transport()
        await transport.open()
        await transport.ping(1.0)
        bench.fake.send_raw(("127.0.0.1", transport.local_port), Message(MType.CON, EMPTY, 4711).encode())
        await bench.until(lambda: bench.fake.resets_received == 1)

    bench.run(body)


def test_foreign_and_malformed_datagrams_are_counted_and_ignored(bench: Bench) -> None:
    async def body() -> None:
        contacts: list[int] = []
        transport = bench.transport(on_contact=lambda: contacts.append(1))
        await transport.open()
        seen: list[Message] = []
        token = transport.new_token()
        transport.add_stream(token, seen.append)
        client = ("127.0.0.1", transport.local_port)

        # A well-formed frame for a known token, but from another address.
        stranger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            stranger.bind(("127.0.0.1", 0))
            stranger.sendto(Message(MType.NON, CONTENT, 1, token, [], b"x").encode(), client)
            await bench.until(lambda: transport.counters.foreign == 1)
        finally:
            stranger.close()
        assert not seen and not contacts and transport.counters.sent == 0

        # Not CoAP at all, from the device address.
        bench.fake.send_raw(client, b"\x00")
        await bench.until(lambda: transport.counters.malformed == 1)
        assert not contacts and transport.counters.received == 0

    bench.run(body)


def test_trace_sees_both_directions_and_may_fail(bench: Bench) -> None:
    async def body() -> None:
        events: list[tuple[str, tuple[str, int], bytes]] = []

        def trace(direction: str, addr: tuple[str, int], data: bytes) -> None:
            events.append((direction, addr, data))
            raise RuntimeError("a broken trace callback")

        transport = bench.transport(trace=trace)
        await transport.open()
        request = info_request(transport)
        reply = await transport.request(request, 1.0)
        assert reply is not None
        assert [event[0] for event in events] == ["tx", "rx"]
        assert events[0][1] == ("127.0.0.1", bench.fake.port) and events[0][2] == request.encode()
        assert Message.decode(events[1][2]).token == request.token

    bench.run(body)


def test_reset_answering_a_request_is_returned(bench: Bench) -> None:
    async def body() -> None:
        transport = bench.transport()
        await transport.open()
        client = ("127.0.0.1", transport.local_port)
        request = build_request(MType.NON, POST, transport.next_mid(), os.urandom(4), "/sys/dev/sync", payload=b"00")
        bench.fake.sync_enabled = False
        waiting = asyncio.ensure_future(transport.request(request, 1.0))
        await asyncio.sleep(0.01)
        bench.fake.send_raw(client, Message(MType.RST, EMPTY, request.mid).encode())
        reply = await waiting
        assert reply is not None and reply.mtype is MType.RST

    bench.run(body)


def test_close_ends_waiting_requests_and_reopen_takes_a_new_port(bench: Bench) -> None:
    async def body() -> None:
        bench.fake.silent = True
        transport = bench.transport()
        assert transport.local_port == 0
        await transport.open()
        port = transport.local_port
        seen: list[Message] = []
        token = transport.new_token()
        transport.add_stream(token, seen.append)

        waiting = asyncio.ensure_future(transport.request(info_request(transport), 5.0))
        pinging = asyncio.ensure_future(transport.ping(5.0))
        await asyncio.sleep(0.01)
        transport.close()
        assert await waiting is None and await pinging is False
        assert not transport.is_open and transport.local_port == 0
        with pytest.raises(TransportError):
            transport.send(Message(MType.CON, EMPTY, 1))
        with pytest.raises(TransportError):
            await transport.request(info_request(transport), 1.0)

        # A new endpoint for the device; the streams are still there.
        await transport.open()
        assert transport.is_open and transport.local_port not in (0, port)
        bench.fake.silent = False
        register(transport, token)
        await bench.until(lambda: len(seen) == 1)

    bench.run(body)


def test_host_name_is_resolved_at_open_and_again_on_request(bench: Bench) -> None:
    async def body() -> None:
        loop = asyncio.get_running_loop()
        address = {"purifier.test": "127.0.0.1"}

        async def getaddrinfo(host: str, port: int, **_: Any) -> list[Any]:
            if host not in address:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
            return [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", (address[host], port))]

        loop.getaddrinfo = getaddrinfo  # type: ignore[method-assign]
        transport = Transport("purifier.test", bench.fake.port)
        try:
            await transport.open()
            assert await transport.ping(1.0) is True
            assert await transport.resolve_again() is False, "the same address: nothing changes"

            # The name leads elsewhere now. The socket stays and reaches the
            # new address; the old one has become a stranger.
            port = transport.local_port
            address["purifier.test"] = "127.0.0.2"
            assert await transport.resolve_again() is True
            assert transport.local_port == port
            assert await transport.ping(0.1) is False, "nothing listens at the new address"
            assert bench.fake.pings_received == 1
            bench.fake.send_raw(("127.0.0.1", port), Message(MType.CON, EMPTY, 4711).encode())
            await bench.until(lambda: transport.counters.foreign == 1)

            # A name that is gone leaves the transport where it was.
            del address["purifier.test"]
            with pytest.raises(OSError, match="not known"):
                await transport.resolve_again()
        finally:
            transport.close()

        # An address is never looked up.
        literal = bench.transport()
        await literal.open()
        assert await literal.resolve_again() is False

    bench.run(body)


@pytest.mark.parametrize("host", ["purifier..lan", "p" * 64 + ".lan"])
def test_name_that_cannot_be_encoded_fails_like_one_that_does_not_resolve(bench: Bench, host: str) -> None:
    async def body() -> None:
        # The resolver refuses such a name with a UnicodeError; open()
        # promises an OSError for every way of not getting a socket.
        transport = Transport(host, bench.fake.port)
        with pytest.raises(OSError, match="not a host name"):
            await transport.open()
        assert not transport.is_open

    bench.run(body)
