"""Presumed standby: what the session concludes from a registration that stays unanswered.

A device in standby cannot say that it is off: it answers every probe and
sends no status frame (docs/metingen.md, measurements 2 and 5). Measured as
well: a device that is on answers a registration from a newly opened socket
with a status frame after 0.2 to 1.9 s, six times out of six. So a reachable
device that leaves such a registration without any frame is taken to be in
standby, until a frame says otherwise.
"""

from __future__ import annotations

import asyncio
import socket
import time
from typing import TYPE_CHECKING, Any

import pytest
from airlink import DeviceOffError, RestoredState, Session, SessionState
from fake_purifier import FakePurifier

if TYPE_CHECKING:
    from conftest import Bench

OFFLINE, REACHABLE, LIVE, SUSPECT = (
    SessionState.OFFLINE,
    SessionState.REACHABLE,
    SessionState.LIVE,
    SessionState.SUSPECT,
)
POWER = "D03102"
# The time a reachable device gets to send a frame, in these tests.
PRESUME = 0.3


def stored_on(bench: Bench) -> RestoredState:
    """Return what was stored while the device was on."""
    return RestoredState(status={**bench.fake.state, POWER: 1, "D0310C": 0}, received_at=1_700_000_000.0)


def test_a_reachable_device_that_sends_no_frame_is_presumed_to_be_in_standby(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)  # switched off while nobody was listening
        session = bench.session(
            options=bench.options(bench.quiet, standby_presume_after=PRESUME), restored=stored_on(bench)
        )
        told: list[tuple[bool, int]] = []
        session.add_listener(lambda: told.append((session.presumed_standby, (session.status or {})[POWER])))
        await session.start()
        await bench.until(lambda: session.available)
        reachable_at = time.monotonic()
        assert not session.presumed_standby and session.status is not None and session.status[POWER] == 1

        await bench.until(lambda: session.presumed_standby, "standby was never presumed")
        assert time.monotonic() - reachable_at >= PRESUME * 0.9, "presumed before the time for a frame was up"
        # The power key reads 0; everything else is what the device last sent.
        assert session.status == {**stored_on(bench).status, POWER: 0}  # type: ignore[dict-item]
        assert not session.status_is_live and session.state is REACHABLE
        assert session.last_frame_at == 1_700_000_000.0 and fake.frames_sent == 0
        await asyncio.sleep(0)
        assert told[-1] == (True, 0), "the listeners are told"
        diag = session.diagnostics()
        assert diag.presumed_standby and diag.standby_presumptions == 1 and diag.switch_offs_assumed == 0
        # What is stored for the next start says off as well.
        assert session.snapshot().status is not None and session.snapshot().status[POWER] == 0  # type: ignore[index]

    bench.run(body)


def test_a_device_that_is_on_answers_and_nothing_is_presumed(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.registration_answer_delay = 0.15  # measured: 0.2 to 1.9 s, here scaled
        stale_off = RestoredState(status={**fake.state, POWER: 0, "D0310C": -16}, received_at=1_700_000_000.0)
        session = await bench.started(
            options=bench.options(bench.quiet, standby_presume_after=PRESUME), restored=stale_off
        )
        await bench.until(lambda: session.state is LIVE, "the registration was not answered")
        await asyncio.sleep(2 * PRESUME)
        assert not session.presumed_standby and session.diagnostics().standby_presumptions == 0
        assert session.status is not None and session.status[POWER] == 1

    bench.run(body)


def test_a_device_that_is_on_and_whose_answer_was_lost_is_corrected_by_its_next_frame(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.started(
            options=bench.options(bench.quiet, standby_presume_after=PRESUME), restored=stored_on(bench)
        )
        # The price of the rule: on although presumed off, until it reports.
        await bench.until(lambda: session.presumed_standby)
        assert fake.is_on and session.status is not None and session.status[POWER] == 0

        # Measured: a running device reports every 3.3 s on average (measurement 12).
        fake.change("D03221", 9)
        await bench.until(lambda: session.status_is_live)
        assert not session.presumed_standby and session.status[POWER] == 1 and session.status["D03221"] == 9
        diag = session.diagnostics()
        assert not diag.presumed_standby and diag.standby_presumptions == 1

    # No registration is answered here, as if the answers were lost.
    bench.run(body, answer_registration="on_change")


def test_nothing_is_presumed_about_a_device_that_does_not_answer(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.silent = True
        options = bench.options(
            probe_idle=0.05,
            probe_timeout=0.05,
            probe_retry=0.05,
            offline_min_silence=0.3,
            standby_presume_after=PRESUME,
        )
        session = bench.session(options=options, restored=stored_on(bench))
        await session.start()
        await asyncio.sleep(3 * PRESUME)
        assert session.state is OFFLINE and not session.presumed_standby
        assert session.status is not None and session.status[POWER] == 1
        assert session.diagnostics().standby_presumptions == 0

    bench.run(body)


def test_no_verdict_when_the_device_stops_answering_before_the_time_is_up(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        options = bench.options(
            probe_idle=0.1,
            probe_timeout=0.05,
            probe_retry=0.05,
            offline_min_silence=30.0,
            refresh_interval=60.0,
            standby_presume_after=PRESUME,
        )
        session = await bench.started(options=options, restored=stored_on(bench))
        fake.silent = True  # it answered once and is gone
        await bench.until(lambda: session.state is SUSPECT)
        await asyncio.sleep(2 * PRESUME)
        assert not session.presumed_standby and session.status is not None and session.status[POWER] == 1

        # It answers again. The registration that follows has a new token on
        # the socket in use, and that one proves nothing when it stays unanswered.
        registrations = len(fake.registrations)
        fake.silent = False
        await bench.until(lambda: session.state is REACHABLE)
        await bench.until(lambda: len(fake.registrations) > registrations)
        await asyncio.sleep(2 * PRESUME)
        assert not session.presumed_standby and session.diagnostics().standby_presumptions == 0

    bench.run(body)


def test_a_registration_with_a_new_token_on_the_socket_in_use_proves_nothing(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, standby_presume_after=PRESUME))
        await bench.settled()
        fake.power_off(notify=False)  # the frame that said so was lost
        # Not measured: whether a device that is on answers this registration.
        assert await session.request_status() is False
        await asyncio.sleep(2 * PRESUME)
        assert not session.presumed_standby and session.status is not None and session.status[POWER] == 1

    bench.run(body)


def test_a_socket_replaced_after_an_error_is_a_new_one(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(probe_idle=0.1, refresh_interval=60.0, standby_presume_after=PRESUME)
        session = await bench.live(options=options)
        await bench.settled()
        fake.power_off(notify=False)  # the frame that said so was lost
        protocol = session._transport._protocol
        assert protocol is not None
        protocol.error_received(OSError("network is unreachable"))
        await bench.until(lambda: session.diagnostics().socket_recreations == 1)
        # The registration from the new port is the measured kind again.
        await bench.until(lambda: session.presumed_standby, "nothing was presumed after the new socket")
        assert session.status is not None and session.status[POWER] == 0
        assert session.status_is_live, "frames were received in this session; that does not change"

    bench.run(body)


def test_after_offline_the_time_runs_from_the_moment_the_device_answers_again(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(
            probe_idle=0.05,
            probe_timeout=0.05,
            probe_retry=0.05,
            offline_min_silence=0.3,
            standby_presume_after=PRESUME,
        )
        session = await bench.live(options=options)
        fake.silent = True
        await bench.until(lambda: session.state is OFFLINE)
        # The registration from the replaced socket left while nothing answered.
        await bench.until(lambda: session.diagnostics().socket_recreations >= 1)
        await asyncio.sleep(2 * PRESUME)
        assert not session.presumed_standby, "silence of a device that is away says nothing about standby"

        fake.reboot()  # it comes back, remembers no observer...
        fake.power_off(notify=False)  # ...and is in standby
        fake.silent = False
        await bench.until(lambda: session.available)
        back_at = time.monotonic()
        assert not session.presumed_standby and session.status is not None and session.status[POWER] == 1
        await bench.until(lambda: session.presumed_standby, "nothing was presumed after the return")
        assert time.monotonic() - back_at >= PRESUME * 0.9
        assert session.status[POWER] == 0

        fake.power_on()
        await bench.until(lambda: not session.presumed_standby)
        assert session.status[POWER] == 1

    bench.run(body)


def test_nothing_is_presumed_at_another_address_of_the_host_name(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        loop = asyncio.get_running_loop()
        address = {"purifier.test": "127.0.0.1"}

        async def getaddrinfo(host: str, port: int, **_: Any) -> list[Any]:
            return [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", (address[host], port))]

        loop.getaddrinfo = getaddrinfo  # type: ignore[method-assign]
        moved = FakePurifier()
        await loop.create_datagram_endpoint(lambda: moved, local_addr=("127.0.0.2", fake.port))
        moved.power_off(notify=False)  # in standby when it turns up at its new address
        options = bench.options(
            probe_idle=0.05,
            probe_timeout=0.05,
            probe_retry=0.05,
            offline_min_silence=0.3,
            standby_presume_after=PRESUME,
        )
        session = Session("purifier.test", port=fake.port, options=options)
        try:
            await session.start()
            await bench.until(lambda: session.state is LIVE, "the name did not lead to the device")
            fake.silent = True  # the old address is dead
            await bench.until(lambda: session.state is OFFLINE)
            await bench.until(lambda: session.diagnostics().socket_recreations == 1)
            address["purifier.test"] = "127.0.0.2"
            await bench.until(lambda: session.available, "the device was not found at the new address", 3.0)
            await bench.until(lambda: bool(moved.registrations))
            await asyncio.sleep(2 * PRESUME)
            # The registration went to an address the socket was not opened for. The device
            # there may be the same one, which may still know this port: that case is not
            # the measured one, so its silence proves nothing.
            assert not session.presumed_standby and session.status is not None and session.status[POWER] == 1
        finally:
            await session.stop()
            moved.close()

    bench.run(body)


def test_a_frame_that_cannot_be_read_ends_the_watch_without_a_verdict(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.corrupt_next_frames = 1  # the answer to the registration arrives damaged
        session = await bench.started(
            options=bench.options(bench.quiet, standby_presume_after=PRESUME), restored=stored_on(bench)
        )
        await bench.until(lambda: sum(session.diagnostics().frames_dropped.values()) == 1)
        await asyncio.sleep(2 * PRESUME)
        # Something was sent, so this was not the silence of standby.
        assert not session.presumed_standby and session.status is not None and session.status[POWER] == 1

    # The registration that asks for the lost content again stays unanswered here.
    bench.run(body, answer_new_token_on_same_port=False)


def test_stop_ends_the_watch(bench: Bench) -> None:
    async def body() -> None:
        bench.fake.power_off(notify=False)
        session = await bench.started(
            options=bench.options(bench.quiet, standby_presume_after=PRESUME), restored=stored_on(bench)
        )
        assert session._standby_timer is not None, "the time was not running"
        await session.stop()
        assert session._standby_timer is None, "a timer outlived stop()"
        await asyncio.sleep(2 * PRESUME)
        assert not session.presumed_standby and session.status is not None and session.status[POWER] == 1

    bench.run(body)


# -- commands ---------------------------------------------------------------------------------------------------


def test_a_setting_waits_for_the_answer_to_the_registration_and_is_sent_when_the_device_is_on(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.registration_answer_delay = 0.15
        # Stored while the device was off; it was switched on since.
        stale_off = RestoredState(status={**fake.state, POWER: 0, "D0310C": -16}, received_at=1_700_000_000.0)
        session = await bench.started(
            options=bench.options(bench.quiet, standby_presume_after=PRESUME), restored=stale_off
        )
        assert not session.status_is_live
        result = await session.write({"D03103": 1})
        # Not refused on the status from before, and not sent before the device had said what it is.
        assert fake.state["D03103"] == 1 and not result.resent and result.duration >= 0.1
        assert session.diagnostics().commands_blocked_off == 0

    bench.run(body)


def test_a_setting_waits_for_the_answer_to_the_registration_and_is_refused_when_none_comes(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        session = await bench.started(
            options=bench.options(bench.quiet, standby_presume_after=PRESUME), restored=stored_on(bench)
        )
        began = time.monotonic()
        # The stored status says on. Sent now, the setting would be answered
        # "success", discarded, and fail after the whole confirmation time.
        with pytest.raises(DeviceOffError):
            await session.write({"D03103": 1})
        assert time.monotonic() - began >= PRESUME * 0.8, "the setting did not wait for the outcome"
        assert not fake.controls and fake.syncs_received == 0, "nothing may leave"
        assert session.presumed_standby and session.diagnostics().commands_blocked_off == 1
        # From here on it is refused at once.
        began = time.monotonic()
        with pytest.raises(DeviceOffError):
            await session.write({"D0310C": 18})
        assert time.monotonic() - began < 0.1 and not fake.controls

    bench.run(body)


def test_the_power_key_does_not_wait(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        session = await bench.started(
            options=bench.options(bench.quiet, standby_presume_after=5.0), restored=stored_on(bench)
        )
        began = time.monotonic()
        result = await session.write({POWER: 1})
        assert fake.is_on and not result.already_current and time.monotonic() - began < 1.0
        # The frame of the switch-on is the answer the watch was waiting for.
        assert session.status_is_live and not session.presumed_standby
        await session.write({"D03103": 1})
        assert fake.state["D03103"] == 1

    bench.run(body)


def test_presumed_standby_without_any_status(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)  # added while it was off: nothing was ever received
        session = bench.session(options=bench.options(bench.quiet, standby_presume_after=PRESUME))
        told: list[bool] = []
        session.add_listener(lambda: told.append(session.presumed_standby))
        await session.start()
        await bench.until(lambda: session.presumed_standby, "standby was never presumed")
        await asyncio.sleep(0)
        assert session.status is None and not session.status_is_live and told[-1] is True

        # A setting is refused unsent...
        with pytest.raises(DeviceOffError):
            await session.write({"D03103": 1})
        assert not fake.controls and fake.syncs_received == 0
        # ...switching off succeeds on the answer of the device, without waiting for a frame...
        began = time.monotonic()
        result = await session.write({POWER: 0})
        assert result.already_current and not result.assumed_off and time.monotonic() - began < 0.2
        assert fake.controls == [{POWER: 0}], "it is sent all the same"
        # ...and switching on is sent as always and brings the status.
        result = await session.write({POWER: 1})
        assert fake.is_on and not result.already_current
        assert not session.presumed_standby and session.status is not None and session.status[POWER] == 1

    bench.run(body)


def test_a_switch_off_accepted_in_silence_is_kept_when_there_is_no_status(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        # Long before the registration would settle it.
        session = await bench.started(options=bench.options(bench.quiet, standby_presume_after=30.0))
        assert session.status is None and not session.presumed_standby
        result = await session.write({POWER: 0})
        # Measured (measurement 5, rows 6 and 7): "success" to a switch-off means off either way.
        assert result.assumed_off and session.status is None
        assert session.presumed_standby, "the session forgot what it had just concluded"
        diag = session.diagnostics()
        assert diag.switch_offs_assumed == 1 and diag.standby_presumptions == 0
        with pytest.raises(DeviceOffError):
            await session.write({"D03103": 1})

    bench.run(body)


def test_a_scene_at_the_start_switches_on_and_sets_a_setting(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        fake.echo_delay = 0.05
        session = await bench.started(
            options=bench.options(bench.quiet, standby_presume_after=PRESUME), restored=stored_on(bench)
        )
        # Two calls at once while the stored status still says on: the
        # setting is held until a frame tells what the device is.
        lock, on = await asyncio.gather(session.write({"D03103": 1}), session.write({POWER: 1}))
        assert not lock.resent and not on.resent
        assert fake.controls == [{POWER: 1}, {"D03103": 1}]
        assert fake.is_on and fake.state["D03103"] == 1 and not session.presumed_standby

    bench.run(body)
