"""Finding purifiers with the plaintext info resource."""

from __future__ import annotations

import asyncio
from typing import Any

from airlink import discover, parse_info
from airlink.coap import Message
from conftest import Bench

TELEVISION = b'{"name":"[LG] webOS TV","swversion":"1.0"}'


class _Television(asyncio.DatagramProtocol):
    """Answers every request on the CoAP port, without ids (measured: an LG television, measurement 11)."""

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport: Any = transport

    def datagram_received(self, data: bytes, addr: Any) -> None:
        request = Message.decode(data)
        answer = Message(request.mtype, 0x45, request.mid, request.token, [], TELEVISION)
        self.transport.sendto(answer.encode(), addr)


def test_finds_the_purifier_and_its_identity(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        found = await discover(["127.0.0.1"], port=fake.port, rounds=2, round_wait=0.1)
        assert list(found) == ["127.0.0.1"]
        identity = found["127.0.0.1"]
        assert identity.device_id == fake.state["DeviceId"] and identity.model_id == "AC3220/10"
        # A search registers nothing and leaves the counter alone.
        assert not fake.registrations and fake.syncs_received == 0 and not fake.controls

    bench.run(body)


def test_a_lost_answer_is_made_up_for_by_the_next_round(bench: Bench) -> None:
    async def body() -> None:
        bench.fake.drop_next_infos = 1
        found = await discover(["127.0.0.1"], port=bench.fake.port, rounds=2, round_wait=0.1)
        assert "127.0.0.1" in found

    bench.run(body)


def test_nothing_answers(bench: Bench) -> None:
    async def body() -> None:
        bench.fake.silent = True
        assert await discover(["127.0.0.1"], port=bench.fake.port, rounds=2, round_wait=0.05) == {}
        assert await discover([], port=bench.fake.port) == {}

    bench.run(body)


def test_a_television_on_the_same_port_is_not_a_purifier(bench: Bench) -> None:
    async def body() -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(_Television, local_addr=("127.0.0.1", 0))
        try:
            port = transport.get_extra_info("sockname")[1]
            assert await discover(["127.0.0.1"], port=port, rounds=1, round_wait=0.1) == {}
        finally:
            transport.close()

    bench.run(body)


def test_an_address_that_cannot_be_sent_to_is_skipped(bench: Bench) -> None:
    async def body() -> None:
        found = await discover(["999.1.1.1", "127.0.0.1"], port=bench.fake.port, rounds=1, round_wait=0.1)
        assert list(found) == ["127.0.0.1"]

    bench.run(body)


def test_parse_info_wants_both_ids() -> None:
    assert parse_info(TELEVISION) is None
    assert parse_info(b"\x00 not json") is None
    assert parse_info(b"[1, 2]") is None
    assert parse_info(b'{"device_id": "a", "product_id": ""}') is None
    identity = parse_info(b'{"device_id": "a", "product_id": "b", "modelid": "AC3220/10", "name": "Woonkamer"}')
    assert identity is not None and (identity.device_id, identity.model_id, identity.name) == (
        "a",
        "AC3220/10",
        "Woonkamer",
    )
