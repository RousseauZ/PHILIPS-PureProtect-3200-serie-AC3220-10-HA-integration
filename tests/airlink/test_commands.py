"""Commands: the exchange, the confirmation and the recovery ladder (report 6.4, rule 6)."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest
from airlink import (
    DeviceOffError,
    NotConfirmedError,
    RefusedError,
    RestoredState,
    SessionState,
    SessionStoppedError,
    UnreachableError,
    crypto,
)

if TYPE_CHECKING:
    from conftest import Bench

LIVE, SUSPECT = SessionState.LIVE, SessionState.SUSPECT
SYNC, CONTROL = ("NON", "/sys/dev/sync"), ("NON", "/sys/dev/control")


def exchanges(bench: Bench) -> list[tuple[str, str]]:
    return [request for request in bench.fake.requests if request in (SYNC, CONTROL)]


def off_status(bench: Bench) -> RestoredState:
    return RestoredState(status={**bench.fake.state, "D03102": 0, "D0310C": -16}, received_at=1_700_000_000.0)


def test_write_is_confirmed_by_the_status_frame(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        result = await session.write({"D0310C": 18})
        assert fake.state["D0310C"] == 18
        assert session.status is not None and session.status["D0310C"] == 18
        assert result.values == {"D0310C": 18} and not result.already_current and not result.resent
        # The fan speed follows in a frame of its own; the write did not wait for it.
        assert session.status["D0310D"] == 1
        await bench.until(lambda: session.status is not None and session.status["D0310D"] == 18)
        assert result.attempts == 1 and result.duration < 1.0
        # One sync right before the write, and the counter of that sync plus one.
        assert exchanges(bench) == [SYNC, CONTROL] and fake.controls == [{"D0310C": 18}]
        diag = session.diagnostics()
        assert diag.commands_sent == 1 and diag.commands_unconfirmed == 0 and diag.escalations == 0

    bench.run(body)


def test_write_of_the_current_value_succeeds_without_a_frame(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        # Other firmware stays silent after such a write; no frame may be needed.
        fake.push_on_same_value = False
        session = await bench.live(options=bench.options(bench.quiet, confirm_timeout=5.0))
        frames = fake.frames_sent
        began = time.monotonic()
        result = await session.write({"D03103": 0})
        assert result.already_current and not result.resent and time.monotonic() - began < 1.0
        assert fake.controls == [{"D03103": 0}], "the command is sent all the same"
        assert fake.frames_sent == frames

    bench.run(body)


def test_normalised_readback_counts_as_confirmation(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.state["D03130"] = 0
        session = await bench.live(options=bench.quiet)
        # The beep reads back as 100 whatever non-zero value was written.
        result = await session.write({"D03130": 1})
        assert not result.already_current and session.status is not None and session.status["D03130"] == 100
        again = await session.write({"D03130": 1})
        assert again.already_current

    bench.run(body)


def test_discarded_write_is_not_confirmed_after_exactly_one_resend(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        registrations = len(fake.registrations)
        with pytest.raises(NotConfirmedError, match="accepted but not confirmed") as caught:
            await session.write({"D03105": 0})  # acknowledged and discarded by the device
        assert caught.value.values == {"D03105": 0}
        assert fake.controls == [{"D03105": 0}, {"D03105": 0}], "the command is sent exactly twice"
        assert exchanges(bench) == [SYNC, CONTROL, SYNC, CONTROL]
        assert len(fake.registrations) == registrations + 1, "one refresh before the resend"
        assert session.status is not None and session.status["D03105"] == 101
        diag = session.diagnostics()
        assert diag.commands_unconfirmed == 1
        # Frames kept arriving, so the stream is fine and the ladder stays where it is.
        assert diag.escalations == 0 and diag.refresh_mode == "same_token"

    bench.run(body)


def test_lost_echo_is_healed_by_the_resend(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        fake.drop_next_notifications = 1
        result = await session.write({"D03103": 1})
        assert result.resent and len(fake.controls) == 2
        assert session.status is not None and session.status["D03103"] == 1
        assert session.diagnostics().escalations == 0

    bench.run(body)


def test_device_off_is_raised_without_sending_anything(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        session = await bench.started(options=bench.quiet, restored=off_status(bench))
        await bench.settled()
        sent = session.diagnostics().datagrams_sent
        with pytest.raises(DeviceOffError) as caught:
            await session.write({"D03103": 1})
        assert caught.value.values == {"D03103": 1}
        with pytest.raises(DeviceOffError):
            await session.write({"D03102": 0, "D03103": 1})
        assert session.diagnostics().datagrams_sent == sent, "not one datagram may leave"
        assert fake.syncs_received == 0 and not fake.controls
        assert session.diagnostics().commands_blocked_off == 2 and session.diagnostics().commands_sent == 0

    bench.run(body)


def test_device_off_follows_the_live_status(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        # Measured: switching off over the network is reported within 0.1 s.
        result = await session.write({"D03102": 0})
        assert not result.resent and not fake.is_on
        assert session.status is not None and session.status["D0310C"] == -16
        with pytest.raises(DeviceOffError):
            await session.write({"D0310C": 18})
        # Off once more: nothing to send. The device would answer "success"
        # and stay silent (measured), which could never be confirmed.
        controls = len(fake.controls)
        with pytest.raises(DeviceOffError):
            await session.write({"D03102": 0})
        assert len(fake.controls) == controls
        await session.write({"D03102": 1})
        await session.write({"D0310C": 18})
        assert fake.state["D0310C"] == 18

    bench.run(body)


def test_power_on_from_standby_is_confirmed(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        session = await bench.started(options=bench.quiet, restored=off_status(bench))
        await bench.until(lambda: bool(fake.observers))
        result = await session.write({"D03102": 1})
        assert fake.is_on and not result.resent and not result.already_current
        assert session.state is LIVE and session.status is not None
        assert session.status["D03102"] == 1 and session.status["D0310C"] == 0

    bench.run(body)


def test_power_on_travels_first_in_a_combined_write(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        session = await bench.started(options=bench.quiet, restored=off_status(bench))
        await bench.until(lambda: bool(fake.observers))
        await session.write({"D0310C": 18, "D03102": 1})
        assert list(fake.controls[0]) == ["D03102", "D0310C"]
        assert session.status is not None and session.status["D03102"] == 1 and session.status["D0310C"] == 18

    bench.run(body)


def test_stale_frame_before_the_echo_is_ignored(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        # The Wi-Fi module reports once more what it read before the write landed.
        fake.stale_frame_before_echo = True
        fake.echo_delay = 0.08
        session = await bench.live(options=bench.options(bench.quiet, confirm_settle=0.5, confirm_timeout=2.0))
        frames = session.diagnostics().frames_received
        result = await session.write({"D03103": 1})
        assert not result.resent and len(fake.controls) == 1 and result.duration >= 0.05
        assert session.diagnostics().frames_received == frames + 2
        assert session.status is not None and session.status["D03103"] == 1

    bench.run(body)


def test_frame_without_the_value_after_the_settle_window_ends_the_wait(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(bench.quiet, confirm_settle=0.05, confirm_timeout=30.0, confirm_retry_wait=0.1)
        session = await bench.live(options=options)

        async def later_frame() -> None:
            await asyncio.sleep(0.2)
            fake.change("D03221", 44)  # the device reports again, still without the new value

        began = time.monotonic()
        ticker = asyncio.ensure_future(later_frame())
        with pytest.raises(NotConfirmedError):
            await session.write({"D03105": 0})
        await ticker
        assert time.monotonic() - began < 5.0, "the 30 s deadline was not waited out"
        assert len(fake.controls) == 2

    bench.run(body)


def test_malformed_sync_reply_is_retried(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        fake.malformed_next_syncs = 1
        result = await session.write({"D03103": 1})
        assert result.attempts == 2 and not result.resent
        assert exchanges(bench) == [SYNC, SYNC, CONTROL], "no write with the padded counter"
        assert session.diagnostics().sync_malformed == 1

    bench.run(body)


def test_refused_attempt_is_retried_with_a_new_sync_and_payload(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        fake.fail_next_controls = 2
        result = await session.write({"D03103": 1})
        assert result.attempts == 3 and exchanges(bench) == [SYNC, CONTROL] * 3
        counters = [crypto.decrypt(envelope)[0] for envelope in fake.control_envelopes]
        assert len(set(counters)) == 3 and len(set(fake.control_envelopes)) == 3

    bench.run(body)


def test_refused_after_all_attempts(bench: Bench) -> None:
    async def body() -> None:
        session = await bench.live(options=bench.quiet)
        with pytest.raises(RefusedError) as caught:
            await session.write({"D03103": 1})
        assert caught.value.values == {"D03103": 1}
        assert exchanges(bench) == [SYNC, CONTROL] * 3
        diag = session.diagnostics()
        assert diag.commands_refused == 1 and diag.commands_unconfirmed == 0 and diag.escalations == 0

    bench.run(body, refuse_control=True)


def test_unreachable_when_the_write_gets_no_answer(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        fake.control_enabled = False
        with pytest.raises(UnreachableError):
            await session.write({"D03103": 1})
        assert exchanges(bench) == [SYNC, CONTROL] * 3
        assert session.diagnostics().commands_unanswered == 1

    bench.run(body)


def test_write_gives_up_at_the_hard_limit(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, sync_timeout=0.4, write_budget=0.5))
        fake.silent = True
        began = time.monotonic()
        with pytest.raises(UnreachableError):
            await session.write({"D03103": 1})
        assert 0.45 <= time.monotonic() - began < 1.0, "three attempts would have taken 1.2 s"
        assert fake.syncs_received == 2

    bench.run(body)


def test_writes_are_serialised(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        results = await asyncio.gather(
            session.write({"D03103": 1}), session.write({"D0310C": 18}), session.write({"D0312A": 0})
        )
        assert all(not result.resent and result.attempts == 1 for result in results)
        # Never a second sync between a sync and its write.
        assert exchanges(bench) == [SYNC, CONTROL] * 3
        assert (fake.state["D03103"], fake.state["D0310C"], fake.state["D0312A"]) == (1, 18, 0)

    bench.run(body)


def test_write_while_suspect_works_and_counts_as_contact(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(probe_idle=0.05, probe_timeout=0.05, probe_retry=5.0, offline_min_misses=50)
        session = await bench.live(options=options)
        fake.ping_enabled = False
        await bench.until(lambda: session.state is SUSPECT)
        assert session.available
        result = await session.write({"D03103": 1})
        assert not result.resent and session.state is LIVE
        assert session.diagnostics().consecutive_missed_probes == 0

    bench.run(body)


def test_only_integers_are_written(bench: Bench) -> None:
    async def body() -> None:
        session = await bench.live(options=bench.quiet)
        for bad in ({"D03103": "1"}, {"D03103": True}, {"D03103": 1.0}):
            with pytest.raises(TypeError):
                await session.write(bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="nothing to write"):
            await session.write({})
        for reserved in ({"DeviceId": 1}, {"": 1}):
            with pytest.raises(ValueError, match="not a writable key"):
                await session.write(reserved)
        assert not bench.fake.controls and session.diagnostics().commands_sent == 0

    bench.run(body)


def test_write_needs_a_running_session(bench: Bench) -> None:
    async def body() -> None:
        session = bench.session()
        with pytest.raises(SessionStoppedError):
            await session.write({"D03103": 1})
        with pytest.raises(SessionStoppedError):
            await session.request_status()
        await session.start()
        await session.stop()
        with pytest.raises(SessionStoppedError):
            await session.write({"D03103": 1})
        assert not bench.fake.controls

    bench.run(body)


def test_dead_stream_escalates_to_a_new_token(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        client, old = fake.registrations[-1]
        # The device lost the observer and does not take that token back.
        fake.reboot()
        fake.blocked_tokens.add(old)

        with pytest.raises(NotConfirmedError):
            await session.write({"D03103": 1})
        assert fake.state["D03103"] == 1, "the device did apply it; only the report is missing"
        diag = session.diagnostics()
        assert diag.escalations == 1 and diag.refresh_mode == "new_token"
        await bench.until(lambda: fake.registrations[-1][1] != old, "no registration with a new token")
        new = fake.registrations[-1][1]
        assert (client, new) in fake.observers and diag.working_refresh_mode == "same_token"

        # The user tries again: the frame now arrives on the new token.
        result = await session.write({"D03103": 1})
        assert not result.resent and session.status is not None and session.status["D03103"] == 1
        diag = session.diagnostics()
        assert diag.working_refresh_mode == "new_token" and diag.escalations == 1
        # The old token is deregistered now that the new one delivers.
        await bench.until(lambda: (client, old) in fake.deregistrations)
        assert (client, new) in fake.observers

        # From here on the new token is the one that is refreshed.
        assert await session.request_status() is False
        assert fake.registrations[-1] == (client, new)

    bench.run(body)


def test_dead_stream_escalates_to_a_resync(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        # After its restart this device only takes a registration right after a sync.
        fake.reboot()
        fake.observe_requires_fresh_sync = True

        with pytest.raises(NotConfirmedError):
            await session.write({"D03103": 1})
        # First rung: a new token, which this device ignores as well.
        assert session.diagnostics().refresh_mode == "new_token"
        with pytest.raises(NotConfirmedError):
            await session.write({"D03103": 1})
        assert not fake.observers
        # Second rung: a sync, and a registration right behind it.
        await bench.until(lambda: session.diagnostics().refresh_mode == "resync")
        await bench.until(lambda: bool(fake.observers), "the resync did not bring the observer back")
        assert session.diagnostics().escalations == 2

        result = await session.write({"D03103": 1})
        assert not result.resent
        assert session.diagnostics().working_refresh_mode == "resync"
        await bench.until(lambda: len(fake.deregistrations) == 2, "both older tokens are given up")

    bench.run(body)


def test_escalation_survives_a_device_that_deregisters_by_address(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        client, old = fake.registrations[-1]
        fake.reboot()
        fake.blocked_tokens.add(old)
        with pytest.raises(NotConfirmedError):
            await session.write({"D03103": 1})
        await bench.until(lambda: fake.registrations[-1][1] != old, "no registration with a new token")
        new = fake.registrations[-1][1]

        # This device drops every observer of an address on any deregistration.
        fake.deregister_ignores_token = True
        await session.write({"D03103": 1})
        await bench.until(lambda: (client, old) in fake.deregistrations)
        await bench.until(lambda: (client, new) in fake.observers, "the new observer was lost with the old one")
        fake.change("D03221", 88)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 88)

    bench.run(body)


def test_unneeded_new_token_is_not_recorded_as_the_working_mode(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        # A device that says nothing after a write it discards: the session
        # cannot tell that from a dead stream and climbs the ladder.
        fake.push_on_same_value = False
        session = await bench.live(options=bench.quiet)
        with pytest.raises(NotConfirmedError):
            await session.write({"D03105": 0})
        assert session.diagnostics().escalations == 1
        await bench.until(lambda: len(fake.observers) == 2, "no registration with a new token")

        # The next change arrives on both tokens: the old stream never was dead.
        fake.change("D03221", 61)
        await bench.until(lambda: len(fake.deregistrations) == 1)
        diag = session.diagnostics()
        assert diag.working_refresh_mode == "same_token" and diag.refresh_mode == "same_token"
        assert session.status is not None and session.status["D03221"] == 61
        assert len(fake.observers) == 1

    bench.run(body)
