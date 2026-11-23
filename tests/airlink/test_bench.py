"""The test bench itself: the simulated purifier and the way the tests wait.

A simulator that is kinder than the device, or a test that only passes when
it looks at the right millisecond, hides defects in the session.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest
from airlink import SessionState
from airlink.coap import GET, MType, build_request

if TYPE_CHECKING:
    from airlink.transport import Transport
    from conftest import Bench

LIVE = SessionState.LIVE


def test_simulator_does_not_answer_a_registration_made_in_standby(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.registration_answer_delay = 0.2  # the lower end of what was measured
        fake.power_off(notify=False)
        session = await bench.started(options=bench.quiet)
        await bench.until(lambda: bool(fake.observers))
        # Measured: a registration made in standby is not answered, also not
        # when the device is switched on a moment later. One change, one frame.
        fake.power_on()
        await bench.until(lambda: session.state is LIVE)
        await asyncio.sleep(0.3)
        assert fake.frames_sent == 1, "the registration made in standby was answered after all"
        assert session.diagnostics().frames_received == 1

    bench.run(body)


def test_simulator_can_leave_a_new_token_from_the_same_port_unanswered(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        first = bench.transport()
        await first.open()
        frames: list[bytes] = []

        def register(transport: Transport, token: bytes) -> None:
            transport.add_stream(token, lambda msg: frames.append(msg.token))
            transport.send(build_request(MType.NON, GET, transport.next_mid(), token, "/sys/dev/status", observe=0))

        # Measured: a registration from a new port is answered while the device is on...
        one = first.new_token()
        register(first, one)
        await bench.until(lambda: frames == [one])
        # ...and a new token from that port takes the stream over. Whether it
        # is answered is not measured; the switch simulates that it is not.
        two = first.new_token()
        register(first, two)
        await bench.until(lambda: [token for _, token in fake.observers] == [two])
        await asyncio.sleep(0.1)
        assert frames == [one]
        fake.change("D03221", 9)
        await bench.until(lambda: frames == [one, two])
        # Another port is a new port again.
        second = bench.transport()
        await second.open()
        three = second.new_token()
        register(second, three)
        await bench.until(lambda: frames == [one, two, three])

    bench.run(body, answer_new_token_on_same_port=False)


@pytest.mark.parametrize(
    ("module", "name", "poll"),
    [
        # Used to wait for the 25 ms in which the other client holds the stream.
        ("test_session_frames", "test_refresh_takes_the_stream_back_from_another_client", 0.03),
        # Used to wait for the 20 ms of OFFLINE before the new socket's registration is answered.
        ("test_session_liveness", "test_frames_keep_the_session_live_while_probes_fail", 0.1),
    ],
)
def test_waiting_does_not_depend_on_a_fast_poll(
    bench: Bench, monkeypatch: pytest.MonkeyPatch, module: str, name: str, poll: float
) -> None:
    """``Bench.until`` means "wait for this to hold", not "catch this while it lasts".

    These two tests once passed only at the 5 ms poll of an idle machine.
    They run here once more, unchanged, with a poll that is far slower than
    anything they may rely on.
    """

    async def slow_until(predicate: Callable[[], bool], what: str = "condition not met", timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(what)
            await asyncio.sleep(poll)

    monkeypatch.setattr(type(bench), "until", staticmethod(slow_until))
    getattr(importlib.import_module(module), name)(bench)
