"""Reachability: the states, the probes and the way back (session rules 1 to 4)."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import socket
import time
from typing import TYPE_CHECKING, Any

import pytest
from airlink import Diagnostics, RestoredState, Session, SessionOptions, SessionState
from airlink.coap import Message
from airlink.transport import Transport
from fake_purifier import FakePurifier

if TYPE_CHECKING:
    from conftest import Bench

OFFLINE, REACHABLE, LIVE, SUSPECT = (
    SessionState.OFFLINE,
    SessionState.REACHABLE,
    SessionState.LIVE,
    SessionState.SUSPECT,
)


def record(session: Session) -> list[tuple[SessionState, Diagnostics]]:
    """Record the state and the diagnostics at every notification."""
    seen: list[tuple[SessionState, Diagnostics]] = []
    session.add_listener(lambda: seen.append((session.state, session.diagnostics())))
    return seen


def test_start_in_standby_serves_the_restored_status(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        restored = RestoredState(
            status={"D03102": 0, "D03221": 4, "DeviceId": fake.state["DeviceId"]},
            received_at=1_700_000_000.0,
            keys=frozenset({"D03102", "D03221", "DeviceId"}),
            firmware="0.2.3",
            wifi_firmware="AWS_Philips_AIR_Combo@86",
        )
        session = bench.session(restored=restored)
        assert session.state is OFFLINE and not session.available
        assert session.status == restored.status and not session.status_is_live

        await session.start()
        await bench.until(lambda: session.state is REACHABLE)
        await bench.until(lambda: bool(fake.observers), "the registration never arrived")
        await asyncio.sleep(0.5)  # a few probe and refresh cycles of a device at rest

        assert session.state is REACHABLE and session.available
        assert session.status == restored.status and not session.status_is_live
        assert session.last_frame_at == 1_700_000_000.0
        assert session.snapshot() == restored
        assert fake.frames_sent == 0
        diag = session.diagnostics()
        assert diag.frames_received == 0 and diag.probes_sent >= 2 and diag.working_refresh_mode is None
        assert diag.seconds_since_last_frame is not None and diag.seconds_since_last_frame > 1_000_000

    bench.run(body)


def test_first_frame_leads_to_live(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        session = await bench.started()
        seen = record(session)
        await bench.until(lambda: bool(fake.observers))
        assert session.state is REACHABLE and session.status is None and session.last_frame_at is None

        # A registration made in standby delivers as soon as something changes.
        before = time.time()
        fake.power_on()
        await bench.until(lambda: session.state is LIVE)
        assert session.status_is_live and session.status is not None
        assert session.status["D03102"] == 1 and session.status["D01S05"] == "AC3220/10"
        assert session.last_frame_at is not None and before <= session.last_frame_at <= time.time()
        await asyncio.sleep(0)
        assert seen and seen[-1][0] is LIVE
        snapshot = session.snapshot()
        assert snapshot.firmware == "0.2.3" and snapshot.wifi_firmware == "AWS_Philips_AIR_Combo@86"
        assert "D0310C" in snapshot.keys and snapshot.received_at == session.last_frame_at
        assert session.diagnostics().working_refresh_mode == "same_token"

    bench.run(body)


def test_long_silence_is_not_a_fault_while_probes_answer(bench: Bench) -> None:
    async def body() -> None:
        bench.fake.power_off(notify=False)
        options = bench.options(probe_idle=0.02, probe_timeout=0.5, offline_min_silence=0.2)
        session = await bench.started(options=options)
        seen = record(session)
        # Many idle periods in a row: hours of standby at the real timings.
        await bench.until(lambda: bench.fake.pings_received >= 30)
        diag = session.diagnostics()
        assert session.state is REACHABLE and session.available
        assert diag.frames_received == 0 and bench.fake.frames_sent == 0
        assert diag.probes_sent >= 30 and diag.probes_missed == 0
        assert all(state is REACHABLE for state, _ in seen)
        # The ping is enough; the counter of the device is left alone.
        assert bench.fake.syncs_received == 0

    bench.run(body)


def test_start_never_raises_when_the_device_is_unreachable(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = bench.session(options=bench.options(probe_timeout=0.05))
        began = time.monotonic()
        await session.start()
        assert time.monotonic() - began < 0.5, "start() waited for the device"
        await bench.until(lambda: session.diagnostics().probes_missed >= 4)
        assert session.state is OFFLINE and not session.available
        # The registration went out anyway, and both kinds of probe were tried.
        assert fake.registrations and fake.pings_received >= 2 and fake.syncs_received >= 2
        assert not fake.observers

        fake.silent = False
        await bench.until(lambda: session.available)
        await bench.until(lambda: bool(fake.observers), "no registration after the device appeared")
        await bench.until(lambda: session.state is LIVE, "the device is on, so its status should follow")

    bench.run(body, silent=True)


def test_offline_needs_enough_silence(bench: Bench) -> None:
    async def body() -> None:
        options = bench.options(
            probe_idle=0.05, probe_timeout=0.05, probe_retry=0.05, offline_min_misses=3, offline_min_silence=1.2
        )
        bench.fake.power_off(notify=False)
        session = await bench.started(options=options)
        seen = record(session)
        bench.fake.silent = True
        await bench.until(lambda: session.state is OFFLINE)
        await asyncio.sleep(0)
        assert [state for state, _ in seen] == [SUSPECT, OFFLINE]
        diag = seen[-1][1]
        assert diag.seconds_since_last_contact is not None and diag.seconds_since_last_contact >= 1.2
        # The misses and the failed second probe were there long before.
        assert diag.consecutive_missed_probes >= 8
        assert bench.fake.syncs_received >= 2

    bench.run(body)


def test_offline_needs_enough_misses(bench: Bench) -> None:
    async def body() -> None:
        options = bench.options(
            probe_idle=0.05, probe_timeout=0.05, probe_retry=0.15, offline_min_misses=8, offline_min_silence=0.05
        )
        bench.fake.power_off(notify=False)
        session = await bench.started(options=options)
        seen = record(session)
        bench.fake.silent = True
        await bench.until(lambda: session.state is OFFLINE)
        await asyncio.sleep(0)
        assert [state for state, _ in seen] == [SUSPECT, OFFLINE]
        suspect, offline = seen[0][1], seen[1][1]
        # At the first miss the silence was already long enough.
        assert suspect.consecutive_missed_probes == 1
        assert suspect.seconds_since_last_contact is not None and suspect.seconds_since_last_contact >= 0.05
        # Eight pings and then the sync had to fail.
        assert offline.consecutive_missed_probes == 9 and bench.fake.syncs_received == 1

    bench.run(body)


def test_offline_needs_the_other_kind_of_probe_to_fail_too(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(
            probe_idle=0.1, probe_timeout=0.05, probe_retry=0.1, offline_min_misses=3, offline_min_silence=0.2
        )
        fake.power_off(notify=False)
        session = await bench.started(options=options)
        seen = record(session)
        at_sync: list[Diagnostics] = []
        handle_sync = fake._handle_sync

        def recording_sync(msg: Message, sender: tuple[str, int]) -> None:
            at_sync.append(session.diagnostics())
            handle_sync(msg, sender)

        fake._handle_sync = recording_sync  # type: ignore[method-assign]
        fake.ping_enabled = False
        await bench.until(lambda: len(at_sync) >= 3)
        # Each time the sync was asked, the misses and the silence were enough for OFFLINE...
        for diag in at_sync:
            assert diag.consecutive_missed_probes >= 3
            assert diag.seconds_since_last_contact is not None and diag.seconds_since_last_contact >= 0.2
        # ...and its answer kept the session out of it.
        assert all(state is not OFFLINE for state, _ in seen)
        assert session.available and session.diagnostics().probes_missed >= 9

    bench.run(body)


def test_frames_keep_the_session_live_while_probes_fail(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(
            probe_idle=0.05, probe_timeout=0.05, probe_retry=0.05, offline_min_misses=3, offline_min_silence=0.6
        )
        session = await bench.live(options=options)
        seen = record(session)
        # The values with which a notification found the session LIVE. Between
        # two frames the probes fail and it is SUSPECT, so the state of the
        # moment says little; what the listeners were told does not go away.
        live_with: list[int] = []
        session.add_listener(
            lambda: live_with.append((session.status or {})["D03221"]) if session.state is LIVE else None
        )
        fake.ping_enabled = False
        fake.sync_enabled = False
        for value in range(100, 108):
            await asyncio.sleep(0.15)
            fake.change("D03221", value)
            await bench.until(lambda: session.status is not None and session.status["D03221"] == fake.state["D03221"])
            assert live_with and live_with[-1] == value, "the frame did not bring the session to LIVE"
        diag = session.diagnostics()
        assert diag.probes_missed >= 8, "the probes were supposed to fail"
        assert all(state is not OFFLINE for state, _ in seen) and session.available

        # Without frames the same device is eventually given up. Not for
        # long: it answers the registration from the new socket, so OFFLINE
        # is in what the listeners were told, not in the state of any moment.
        await bench.until(lambda: any(state is OFFLINE for state, _ in seen))

    bench.run(body)


def test_suspect_retries_at_the_retry_interval(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(
            probe_idle=0.4, probe_timeout=0.02, probe_retry=0.05, offline_min_misses=50, refresh_interval=60.0
        )
        session = await bench.started(options=options)
        fake.silent = True
        await bench.until(lambda: session.state is SUSPECT)
        pings, began = fake.pings_received, time.monotonic()
        await bench.until(lambda: fake.pings_received >= pings + 4)
        assert time.monotonic() - began < 0.8, "four retries at 0.05 s take 0.2 s; at the idle interval 1.6 s"

    bench.run(body)


def test_contact_after_a_missed_probe_registers_again_and_checks_the_identity(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(
            probe_idle=0.05, probe_timeout=0.05, probe_retry=0.05, offline_min_misses=50, refresh_interval=60.0
        )
        info = ("NON", "/sys/dev/info")
        session = await bench.live(options=options, expected_device_id=fake.state["DeviceId"])
        await bench.until(lambda: info in fake.requests)
        await bench.settled()
        await asyncio.sleep(0.1)
        registrations, infos = len(fake.registrations), fake.requests.count(info)
        fake.silent = True
        await bench.until(lambda: session.state is SUSPECT)
        assert len(fake.registrations) == registrations
        # Report 6.3: contact from OFFLINE or from SUSPECT, both the same.
        fake.silent = False
        await bench.until(lambda: session.state is LIVE)
        await bench.until(lambda: len(fake.registrations) > registrations, "no registration after the miss", 1.5)
        await bench.until(lambda: fake.requests.count(info) > infos, "no identity check after the miss", 1.5)

    bench.run(body)


def test_change_missed_during_a_short_outage_is_fetched_on_the_first_contact(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(offline_min_silence=30.0))
        await bench.settled()
        client, token = fake.registrations[-1]

        # An outage shorter than what OFFLINE takes: the socket stays, the
        # device keeps its observer, and the frame of a change is lost.
        fake.silent = True
        await bench.until(lambda: session.state is SUSPECT)
        fake.drop_next_notifications = 1
        fake.change("D03221", 77)
        assert fake.drop_next_notifications == 0
        fake.silent = False

        # The same token would get no answer from a device that still holds
        # it (measurement 8); a new one makes the registration a new one.
        await bench.until(
            lambda: session.status is not None and session.status["D03221"] == 77,
            "recovered from missed probes and still shows the old status",
            2.0,
        )
        assert session.state is LIVE
        new = fake.registrations[-1][1]
        assert new != token and list(fake.observers) == [(client, new)]
        assert session.diagnostics().socket_recreations == 0

    bench.run(body)


def test_recovery_from_offline_keeps_the_status_and_registers_again(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(probe_idle=0.05, probe_timeout=0.05, probe_retry=0.05, offline_min_silence=0.3)
        session = await bench.live(options=options, expected_device_id=fake.state["DeviceId"])
        info = ("NON", "/sys/dev/info")
        await bench.until(lambda: info in fake.requests)
        before = dict(session.status or {})
        endpoint, token = fake.registrations[-1]

        fake.silent = True
        await bench.until(lambda: session.state is OFFLINE)
        assert not session.available
        assert session.status == before and session.status_is_live

        infos = fake.requests.count(info)
        fake.reboot()  # the device comes back, remembers no observer...
        fake.power_off(notify=False)  # ...and is in standby, so it reports nothing
        fake.silent = False
        await bench.until(lambda: session.available)
        await bench.until(lambda: bool(fake.observers), "no registration after the recovery")
        await bench.until(lambda: fake.requests.count(info) > infos, "no identity check after the recovery")
        # LIVE, not REACHABLE: the cached status is kept as it was.
        assert session.state is LIVE and session.status == before
        # The socket was replaced on entering OFFLINE: a new port and a new token.
        new_endpoint, new_token = next(iter(fake.observers))
        assert session.diagnostics().socket_recreations >= 1
        assert new_endpoint != endpoint and new_token != token

        fake.power_on()
        await bench.until(lambda: session.status is not None and session.status["Runtime"] < before["Runtime"])
        assert session.diagnostics().device_restarts == 1 and not session.identity_mismatch

    bench.run(body)


def test_offline_retries_follow_the_backoff(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(probe_timeout=0.02, offline_backoff=(0.05, 0.4))
        session = bench.session(options=options)
        await session.start()
        # First attempt at once, the second after 0.05 s, the third after 0.4 s more.
        await bench.until(lambda: fake.pings_received == 2)
        second = time.monotonic()
        await bench.until(lambda: fake.pings_received == 3)
        assert time.monotonic() - second >= 0.3
        assert session.state is OFFLINE

    bench.run(body, silent=True)


def test_offline_backoff_repeats_its_last_wait(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = bench.session(options=bench.options(probe_timeout=0.02, offline_backoff=(0.05, 0.3)))
        await session.start()
        # 10, 10, 10, 30, 60 s "and then every 60 s".
        await bench.until(lambda: fake.pings_received == 3)
        third = time.monotonic()
        await bench.until(lambda: fake.pings_received == 4)
        assert time.monotonic() - third >= 0.25, "after the last wait the backoff started over"

    bench.run(body, silent=True)


def test_host_name_is_resolved_again_while_offline(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        loop = asyncio.get_running_loop()
        address = {"purifier.test": "127.0.0.1"}
        lookups = 0

        async def getaddrinfo(host: str, port: int, **_: Any) -> list[Any]:
            nonlocal lookups
            lookups += 1
            return [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", (address[host], port))]

        loop.getaddrinfo = getaddrinfo  # type: ignore[method-assign]
        moved = FakePurifier()
        await loop.create_datagram_endpoint(lambda: moved, local_addr=("127.0.0.2", fake.port))
        session = Session("purifier.test", port=fake.port, options=bench.fast)
        try:
            await session.start()
            await bench.until(lambda: session.state is LIVE, "the name did not lead to the device")
            assert lookups == 1, "a session that is not OFFLINE has no reason to ask again"

            fake.silent = True  # the old address is dead
            await bench.until(lambda: session.state is OFFLINE)
            await bench.until(lambda: session.diagnostics().socket_recreations == 1)
            await asyncio.sleep(0.2)
            assert moved.datagrams_received == 0
            # A router restart hands the purifier another address, after the
            # socket was replaced: the name service catches up later.
            address["purifier.test"] = "127.0.0.2"
            await bench.until(
                lambda: session.state is LIVE, "the device answers at the new address of its name and is not asked", 3.0
            )
            assert moved.registrations and len(moved.observers) == 1
            # The socket stayed: it is bound to no address, so it reaches the new one.
            assert session.diagnostics().socket_recreations == 1
            received = fake.datagrams_received
            await asyncio.sleep(0.3)
            assert fake.datagrams_received == received, "the old address is still asked"
        finally:
            await session.stop()
            moved.close()

    bench.run(body)


@pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant") is not None,
    reason="Home Assistant's test plugin replaces name resolution; run this on a plain Python",
)
@pytest.mark.parametrize("host", ["purifier..lan", "p" * 64 + ".lan"])
def test_start_does_not_raise_for_a_host_name_that_cannot_be_looked_up(
    bench: Bench, host: str, caplog: pytest.LogCaptureFixture
) -> None:
    async def body() -> None:
        # An empty or an over-long label: the resolver refuses to encode the
        # name, with an error that is not an OSError.
        session = Session(host, port=bench.fake.port, options=bench.options(probe_timeout=0.02))
        try:
            with caplog.at_level(logging.ERROR, logger="airlink"):
                await session.start()
                await asyncio.sleep(0.3)
            assert session.state is OFFLINE and not session.available
            assert session.diagnostics().socket_errors >= 2, "it keeps trying, quietly"
            assert not [r for r in caplog.records if r.name == "airlink"], "no traceback per attempt"
            assert await session.identify() is None
        finally:
            await session.stop()

    bench.run(body)


def test_start_survives_a_socket_that_cannot_be_opened(bench: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        real_open = Transport.open
        failures = 3

        async def flaky_open(transport: Transport) -> None:
            nonlocal failures
            if failures > 0:
                failures -= 1
                raise OSError("network is unreachable")
            await real_open(transport)

        monkeypatch.setattr(Transport, "open", flaky_open)
        session = bench.session(options=bench.options(probe_timeout=0.05, offline_backoff=(0.05,)))
        await session.start()  # the host has no network yet; this is not an error
        assert session.state is OFFLINE
        await bench.until(lambda: session.available, "the session never got its socket")
        await bench.until(lambda: bool(bench.fake.observers), "no registration from the new socket")
        diag = session.diagnostics()
        assert diag.socket_errors == 3 and diag.socket_recreations == 0

    bench.run(body)


def test_local_socket_error_replaces_the_socket(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(probe_idle=0.1))
        endpoint, token = fake.registrations[-1]
        frames = session.diagnostics().frames_received
        # What asyncio reports when a send fails, for example with ENETUNREACH.
        protocol = session._transport._protocol
        assert protocol is not None
        protocol.error_received(OSError("network is unreachable"))
        await bench.until(lambda: session.diagnostics().socket_recreations == 1)
        assert session.diagnostics().socket_errors == 1 and session.state is LIVE
        # A new endpoint with a new token takes the stream over, and the
        # device answers it with its status.
        await bench.until(lambda: session.diagnostics().frames_received == frames + 1)
        new_endpoint, new_token = next(iter(fake.observers))
        assert new_endpoint != endpoint and new_token != token and len(fake.observers) == 1
        fake.change("D03221", 21)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 21)

    bench.run(body)


def test_a_failure_in_supervision_is_logged_and_survived(bench: Bench, caplog: pytest.LogCaptureFixture) -> None:
    async def body() -> None:
        session = await bench.started(options=bench.options(probe_idle=0.05))
        probe_round = session._probe_round
        calls = 0

        async def broken_once() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("boom")
            await probe_round()

        session._probe_round = broken_once  # type: ignore[method-assign]
        with caplog.at_level(logging.ERROR, logger="airlink"):
            await bench.until(lambda: calls >= 3)
        failures = [r for r in caplog.records if r.name == "airlink" and "liveness loop failed" in r.getMessage()]
        assert len(failures) == 1 and failures[0].exc_info is not None
        assert session.available and session.diagnostics().probes_sent >= 2

    bench.run(body)


def test_options_reject_nonsense() -> None:
    with pytest.raises(ValueError, match="probe_idle"):
        SessionOptions(probe_idle=0)
    with pytest.raises(ValueError, match="offline_backoff"):
        SessionOptions(offline_backoff=())
    defaults = SessionOptions()
    # The production values of report 6.3 and 6.4.
    assert (defaults.probe_idle, defaults.probe_timeout, defaults.probe_retry) == (60.0, 3.0, 10.0)
    assert (defaults.offline_min_misses, defaults.offline_min_silence) == (3, 180.0)
    assert defaults.offline_backoff == (10.0, 10.0, 10.0, 30.0, 60.0)
    assert 65.0 <= defaults.refresh_interval <= 75.0
    assert (defaults.sync_timeout, defaults.control_timeout, defaults.write_attempts) == (1.5, 2.0, 3)
    assert (defaults.write_budget, defaults.confirm_settle, defaults.confirm_timeout) == (10.0, 2.0, 5.0)
    assert defaults.confirm_retry_wait == 3.0 and defaults.runtime_stale_window_ms == 10_000


def test_device_that_is_on_answers_the_registration(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = bench.session()
        seen = record(session)
        await session.start()
        # Nothing has to change: a new registration is answered while the device is on.
        await bench.until(lambda: session.state is LIVE, "the registration was not answered")
        assert session.status is not None and session.status["D03102"] == 1
        assert fake.frames_sent == 1 and session.diagnostics().frames_received == 1
        await asyncio.sleep(0)
        assert [state for state, _ in seen] == [REACHABLE, LIVE]

    bench.run(body)


def test_recovery_from_offline_brings_a_fresh_status_when_the_device_is_on(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(probe_idle=0.05, probe_timeout=0.05, probe_retry=0.05, offline_min_silence=0.3)
        session = await bench.live(options=options)
        fake.silent = True
        await bench.until(lambda: session.state is OFFLINE)
        fake.state["D03221"] = 87  # changed while the network was down
        fake.silent = False
        # The registration from the new socket is a new one, and those are answered.
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 87)
        assert session.state is LIVE

    bench.run(body)
