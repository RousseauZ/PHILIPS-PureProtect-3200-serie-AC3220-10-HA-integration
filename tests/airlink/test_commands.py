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
    from airlink.coap import Message
    from conftest import Bench

LIVE, REACHABLE, SUSPECT = SessionState.LIVE, SessionState.REACHABLE, SessionState.SUSPECT
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


def test_matching_restored_status_does_not_count_as_already_current(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        restored = RestoredState(status=dict(fake.state), received_at=1_700_000_000.0)
        session = await bench.started(options=bench.quiet, restored=restored)
        await bench.until(lambda: bool(fake.observers))
        await asyncio.sleep(0.05)
        assert session.state is REACHABLE and not session.status_is_live
        # Rule 6: only a status of this session may stand in for the frame.
        # Shown with the power key, which is what "switch on" writes whatever
        # the status says; a setting would first wait for the answer to the
        # registration (see test_presumed_standby.py).
        result = await session.write({"D03102": 1})  # what the restored status already says
        assert not result.already_current, "a restored value is not proof of what the device has now"
        assert session.status_is_live, "the write was confirmed by a frame"

    # A firmware that does not answer a registration, so that the status stays the restored one.
    bench.run(body, answer_registration="on_change")


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
            await session.write({"D0312A": 0})  # acknowledged and discarded by the device (measurement 14)
        assert caught.value.values == {"D0312A": 0}
        assert fake.controls == [{"D0312A": 0}, {"D0312A": 0}], "the command is sent exactly twice"
        assert exchanges(bench) == [SYNC, CONTROL, SYNC, CONTROL]
        assert len(fake.registrations) == registrations + 1, "one refresh before the resend"
        assert session.status is not None and session.status["D0312A"] == 1
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


def test_resend_of_an_older_write_does_not_override_a_newer_one(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        fake.drop_next_notifications = 1  # the echo of the first write gets lost
        first = asyncio.ensure_future(session.write({"D0310C": 18}))
        await bench.until(lambda: len(fake.controls) == 1)
        await asyncio.sleep(0.02)
        # The user picks another mode while the first one still waits for its echo.
        second = await session.write({"D0310C": 2})
        assert not second.resent and not second.superseded and fake.state["D0310C"] == 2
        # Report 6.4 item 6: per key the last value wins. The first call
        # ends there; it is not an error, and nothing of it is sent again.
        outcome = await first
        assert outcome.superseded and not outcome.resent and outcome.values == {"D0310C": 18}
        await asyncio.sleep(1.0)  # well past the moment of its resend
        assert fake.controls == [{"D0310C": 18}, {"D0310C": 2}], "an older write was sent after the newer one"
        assert fake.state["D0310C"] == 2 and session.status is not None and session.status["D0310C"] == 2
        diag = session.diagnostics()
        assert diag.commands_superseded == 1 and diag.commands_unconfirmed == 0 and diag.escalations == 0

    # The fan speed in the same frame, so that exactly one frame echoes a write.
    bench.run(body, speed_follows_after=None)


def test_two_quick_writes_of_one_key_end_with_the_newer_value(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        # Nothing is lost here. The device reports what it has at the moment
        # it reports (measured: 0.1 to 0.6 s after a write), so both echoes
        # show the second mode and the first write never sees "its" value.
        fake.echo_delay = 0.15
        session = await bench.live(options=bench.quiet)
        first = asyncio.ensure_future(session.write({"D0310C": 1}))
        await bench.until(lambda: len(fake.controls) == 1)
        second = await session.write({"D0310C": 2})  # two taps, or a slider
        assert not second.resent and fake.state["D0310C"] == 2
        assert (await first).superseded
        await asyncio.sleep(1.0)
        assert fake.controls == [{"D0310C": 1}, {"D0310C": 2}], "an older command was sent after the newer one"
        assert fake.state["D0310C"] == 2 and session.status is not None and session.status["D0310C"] == 2

    bench.run(body, speed_follows_after=None)


def test_newer_write_takes_over_only_the_keys_it_names(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        fake.drop_next_notifications = 2  # the echoes of both writes get lost
        first = asyncio.ensure_future(session.write({"D03103": 1, "D0312A": 0}))
        await bench.until(lambda: len(fake.controls) == 1)
        await asyncio.sleep(0.02)
        second = asyncio.ensure_future(session.write({"D0312A": 2}))
        one, two = await asyncio.gather(first, second)
        # The first call still had its child lock to see confirmed, and sent
        # that again on its own: the index belonged to the second call by then.
        assert one.resent and not one.superseded and not two.superseded
        assert fake.controls[:3] == [{"D03103": 1, "D0312A": 0}, {"D0312A": 2}, {"D03103": 1}]
        assert all(control.get("D0312A", 2) == 2 for control in fake.controls[1:])
        assert (fake.state["D03103"], fake.state["D0312A"]) == (1, 2)

    bench.run(body, readonly_keys=set())  # a firmware that takes the index


def test_same_value_from_a_newer_write_supersedes_nothing(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.echo_delay = 0.1
        session = await bench.live(options=bench.quiet)
        # A double tap: both calls ask for the same, both see it confirmed.
        one, two = await asyncio.gather(session.write({"D03103": 1}), session.write({"D03103": 1}))
        assert not one.superseded and not two.superseded and not one.resent and not two.resent
        assert session.diagnostics().commands_superseded == 0

    bench.run(body)


def test_newer_power_command_takes_the_whole_older_call_over(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await session.write({"D03102": 0})
        fake.drop_next_notifications = 1
        # On with turbo, and off again before the device reported the first.
        first = asyncio.ensure_future(session.write({"D03102": 1, "D0310C": 18}))
        await bench.until(lambda: len(fake.controls) == 2)
        await asyncio.sleep(0.02)
        await session.write({"D03102": 0})
        # The mode went with the switch-on; none of it is sent again.
        assert (await first).superseded
        await asyncio.sleep(1.0)
        assert fake.controls[1:] == [{"D03102": 1, "D0310C": 18}, {"D03102": 0}] and not fake.is_on
        assert session.status is not None and session.status["D03102"] == 0

    bench.run(body, speed_follows_after=None)


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
        # Off once more: that already holds, which is not an error (report
        # 6.4 item 3). The device answers "success" and stays silent
        # (measured), so no frame is waited for.
        frames = fake.frames_sent
        again = await session.write({"D03102": 0})
        assert again.already_current and not again.resent and fake.frames_sent == frames
        await session.write({"D03102": 1})
        await session.write({"D0310C": 18})
        assert fake.state["D0310C"] == 18

    bench.run(body)


def test_asking_for_what_already_holds_is_not_refused_on_a_device_that_is_off(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, confirm_timeout=5.0))
        await session.write({"D03102": 0})
        assert session.status is not None and session.status["D03102"] == 0 and not fake.is_on
        # What fan.turn_off does from an automation that does not look first.
        began = time.monotonic()
        result = await session.write({"D03102": 0})
        assert result.already_current and not result.assumed_off and time.monotonic() - began < 1.0
        # A setting that already holds is no error either...
        assert (await session.write({"D03103": 0})).already_current
        # ...one that would change is: the device would discard it.
        with pytest.raises(DeviceOffError):
            await session.write({"D03103": 1})
        assert fake.state["D03103"] == 0
        diag = session.diagnostics()
        assert diag.commands_blocked_off == 1 and diag.switch_offs_assumed == 0

    bench.run(body)


def test_switch_off_on_a_restored_status_that_says_off_returns_on_the_answer(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        options = bench.options(bench.quiet, confirm_timeout=5.0)
        session = await bench.started(options=options, restored=off_status(bench))
        await bench.until(lambda: bool(fake.observers))
        # In standby no frame can follow (measured), and "success" to a
        # switch-off means off: the restored status is enough to go by.
        began = time.monotonic()
        result = await session.write({"D03102": 0})
        assert result.already_current and time.monotonic() - began < 1.0
        assert fake.controls == [{"D03102": 0}], "it is sent all the same"
        assert session.state is REACHABLE and not session.status_is_live

    bench.run(body)


def test_switch_off_that_is_accepted_in_silence_is_taken_for_done(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        token = fake.registrations[-1][1]
        notified: list[int] = []
        session.add_listener(lambda: notified.append((session.status or {})["D03102"]))
        # The device was switched off and the frame that said so got lost, or
        # it came back from a power cut in standby: the status still says on.
        fake.power_off(notify=False)
        assert session.status is not None and session.status["D03102"] == 1

        # Measured: "success" and then nothing. No frame can ever confirm this.
        result = await session.write({"D03102": 0})
        assert result.assumed_off and not result.resent and not result.already_current
        assert fake.controls == [{"D03102": 0}], "sent once: a second answer would say no more"
        # Before believing it the device was asked with a new registration,
        # which one that is on answers and one in standby does not.
        assert fake.registrations[-1][1] != token and fake.frames_sent == 1
        await asyncio.sleep(0)
        assert session.status["D03102"] == 0 and notified == [0]
        diag = session.diagnostics()
        assert diag.switch_offs_assumed == 1 and diag.commands_unconfirmed == 0 and diag.escalations == 0

        # The session now knows that the device is off...
        with pytest.raises(DeviceOffError):
            await session.write({"D03103": 1})
        # ...and switching on is confirmed by a frame as ever.
        result = await session.write({"D03102": 1})
        assert not result.assumed_off and fake.is_on and session.status["D03102"] == 1

    bench.run(body)


def test_switch_off_is_not_assumed_while_a_frame_shows_the_device_on(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        # A device that answers "success" to the switch-off and stays on.
        # Never seen on the AC3220/10; this is the guard against it.
        fake._set_power = lambda value: False  # type: ignore[method-assign]
        with pytest.raises(NotConfirmedError):
            await session.write({"D03102": 0})
        assert fake.controls == [{"D03102": 0}, {"D03102": 0}]
        assert session.status is not None and session.status["D03102"] == 1
        diag = session.diagnostics()
        assert diag.switch_offs_assumed == 0 and diag.commands_unconfirmed == 1

    # No frame follows such a write: only the new registration is answered,
    # by firmware that answers a new token from the port it already serves.
    bench.run(body, push_on_same_value=False, answer_new_token_on_same_port=True)


def test_switch_off_is_not_assumed_on_the_measured_device_while_it_reports_on(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        # A device that answers "success" to the switch-off and stays on. The
        # AC3220/10 does not answer the new registration (measurement 13),
        # but a device that is on keeps reporting: every few seconds while it
        # runs (measurement 12), and after each write (measurement 14).
        fake._set_power = lambda value: False  # type: ignore[method-assign]

        async def sensor() -> None:
            for value in range(70, 90):
                await asyncio.sleep(0.12)
                fake.change("D03221", value)

        reporting = asyncio.ensure_future(sensor())
        try:
            with pytest.raises(NotConfirmedError):
                await session.write({"D03102": 0})
        finally:
            reporting.cancel()
        assert session.status is not None and session.status["D03102"] == 1
        assert session.diagnostics().switch_offs_assumed == 0

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


@pytest.mark.parametrize("echo_delay", [0.0, 0.05])
def test_setting_written_together_with_a_switch_on_waits_for_it(bench: Bench, echo_delay: float) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await session.write({"D03102": 0})
        # The real device reports a switch-on after 0.2 to 1.1 s.
        fake.echo_delay = echo_delay
        frames_at_control: list[int] = []
        handle_control = fake._handle_control

        def recording_control(msg: Message, sender: tuple[str, int]) -> None:
            frames_at_control.append(fake.frames_sent)
            handle_control(msg, sender)

        fake._handle_control = recording_control  # type: ignore[method-assign]
        # A scene: switch on and set the child lock, with two calls at once.
        on, lock = await asyncio.gather(session.write({"D03102": 1}), session.write({"D03103": 1}))
        assert not on.resent and not lock.resent and lock.attempts == 1
        assert fake.controls[-2:] == [{"D03102": 1}, {"D03103": 1}]
        assert fake.is_on and fake.state["D03103"] == 1
        # The setting was not refused on the status from before, and it was
        # not sent ahead of the report that the device is on either.
        assert frames_at_control[1] > frames_at_control[0]
        assert session.diagnostics().commands_blocked_off == 0

    bench.run(body)


def test_setting_written_together_with_a_switch_off_is_refused_unsent(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        fake.echo_delay = 0.05
        # The status still says on when the second call is made. Sent, it
        # would be acknowledged, discarded and fail after the full wait.
        off, lock = await asyncio.gather(
            session.write({"D03102": 0}), session.write({"D03103": 1}), return_exceptions=True
        )
        assert not isinstance(off, BaseException) and isinstance(lock, DeviceOffError)
        assert fake.controls == [{"D03102": 0}] and fake.syncs_received == 1

    bench.run(body)


def test_setting_is_refused_when_the_switch_on_it_waited_for_fails(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await session.write({"D03102": 0})
        fake.refuse_control = True
        on, lock = await asyncio.gather(
            session.write({"D03102": 1}), session.write({"D03103": 1}), return_exceptions=True
        )
        assert isinstance(on, RefusedError) and isinstance(lock, DeviceOffError)
        assert fake.controls[1:] == [{"D03102": 1}] * 3, "the setting never left"

    bench.run(body)


def test_wait_for_a_switch_on_counts_towards_the_limit_of_the_write(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, write_budget=0.5))
        await session.write({"D03102": 0})
        # The device switches on and none of its reports arrive: the switch-on
        # stays unconfirmed for longer than the setting may wait.
        fake.drop_next_notifications = 10
        began = time.monotonic()
        on = asyncio.ensure_future(session.write({"D03102": 1}))
        await asyncio.sleep(0)  # the switch-on is under way when the setting is asked for
        with pytest.raises(DeviceOffError):
            await session.write({"D03103": 1})
        assert 0.45 <= time.monotonic() - began < 0.9, "the setting waits for its limit, and no longer"
        with pytest.raises(NotConfirmedError):
            await on
        assert all(control == {"D03102": 1} for control in fake.controls[1:]), "the setting never left"

    bench.run(body)


def test_superseded_setting_does_not_wait_for_the_switch_on(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await session.write({"D03102": 0})
        fake.echo_delay = 0.3
        on = asyncio.ensure_future(session.write({"D03102": 1}))
        lock = asyncio.ensure_future(session.write({"D03103": 1}))
        await asyncio.sleep(0.02)
        unlock = asyncio.ensure_future(session.write({"D03103": 0}))
        # The first setting has nothing left to wait for: it ends at once.
        assert (await asyncio.wait_for(lock, 0.2)).superseded
        results = await asyncio.gather(on, unlock)
        assert not any(result.superseded for result in results)
        assert fake.controls[1:] == [{"D03102": 1}, {"D03103": 0}] and fake.state["D03103"] == 0

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
            await session.write({"D0312A": 0})
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


def test_frame_that_shows_the_values_confirms_a_write_whose_answers_are_lost(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        respond = fake._respond

        def lose_control_answers(
            request: Message, addr: tuple[str, int], payload: bytes, options: list[tuple[int, bytes]] | None = None
        ) -> None:
            if request.uri_path != "/sys/dev/control":
                respond(request, addr, payload, options)

        fake._respond = lose_control_answers  # type: ignore[method-assign]
        # The device applies the write and reports it; only "success" is lost.
        result = await session.write({"D03103": 1})
        assert not result.resent and not result.already_current and result.attempts == 1
        assert fake.controls == [{"D03103": 1}], "the frame was there before a second attempt"
        diag = session.diagnostics()
        assert diag.commands_unanswered == 0 and diag.commands_unconfirmed == 0

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


def test_write_budget_includes_the_wait_for_the_lock(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, sync_timeout=0.45, write_budget=0.5))
        fake.silent = True
        first = asyncio.ensure_future(session.write({"D03103": 1}))  # holds the lock until 0.5 s
        await asyncio.sleep(0.1)
        began = time.monotonic()
        second = await asyncio.gather(session.write({"D0312A": 0}), return_exceptions=True)
        waited = time.monotonic() - began
        assert isinstance(second[0], UnreachableError)
        assert isinstance((await asyncio.gather(first, return_exceptions=True))[0], UnreachableError)
        # 0.4 s for the lock and 0.1 s of its own sync. Had the limit started
        # at the lock, that sync would have run its full 0.45 s: 0.85 s.
        assert 0.45 <= waited < 0.7, f"the second write took {waited:.2f} s of a 0.5 s limit"
        assert fake.syncs_received == 3

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

    bench.run(body, readonly_keys=set())  # a firmware that takes the index


def test_liveness_sync_never_comes_between_the_sync_and_the_write(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        loop = asyncio.get_running_loop()
        options = bench.options(
            probe_idle=0.05,
            probe_timeout=0.1,
            probe_retry=0.05,
            offline_min_misses=1,
            offline_min_silence=30.0,
            refresh_interval=60.0,
        )
        session = await bench.live(options=options)
        respond = fake._respond

        def slow_sync_answer(
            request: Message, addr: tuple[str, int], payload: bytes, options: list[tuple[int, bytes]] | None = None
        ) -> None:
            # The counter is the device's current one at once; its answer takes a while.
            if request.uri_path == "/sys/dev/sync":
                fake._timers.append(loop.call_later(0.08, respond, request, addr, payload, options))
            else:
                respond(request, addr, payload, options)

        fake._respond = slow_sync_answer  # type: ignore[method-assign]
        fake.ping_enabled = False  # every probe round now ends with the sync probe
        # Measured: the last sync defines the only valid counter. A sync
        # probe that slips in behind the sync of a write gets it refused.
        for value in (1, 0, 1):
            await bench.until(lambda pings=fake.pings_received: fake.pings_received > pings)
            # The ping will time out 0.1 s after it was sent and the sync probe
            # follows; this write's sync is on its way by then.
            await asyncio.sleep(0.06)
            result = await session.write({"D03103": value})
            assert result.attempts == 1, "a liveness sync invalidated the counter of the write"
        assert session.diagnostics().commands_refused == 0
        assert fake.syncs_received > 3, "no sync probe was sent, so nothing was tested"

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
        assert diag.working_refresh_mode == "same_token"

        # The registration with a new token is answered, and shows that the write landed.
        await bench.until(lambda: session.status is not None and session.status["D03103"] == 1)
        new = fake.registrations[-1][1]
        assert new != old and list(fake.observers) == [(client, new)]
        diag = session.diagnostics()
        assert diag.working_refresh_mode == "new_token" and diag.escalations == 1
        # The old token is given up now that the new one delivers.
        await bench.until(lambda: (client, old) in fake.deregistrations)

        # Commands are confirmed again, and the new token is the one that is refreshed.
        result = await session.write({"D03103": 0})
        assert not result.resent and not result.already_current
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

        await bench.until(lambda: session.status is not None and session.status["D03103"] == 1)
        assert session.diagnostics().working_refresh_mode == "resync"
        await bench.until(lambda: len(fake.deregistrations) == 2, "both older tokens are given up")
        result = await session.write({"D03103": 0})
        assert not result.resent

    bench.run(body)


def test_unneeded_new_token_is_not_recorded_as_the_working_mode(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.started(options=bench.quiet)
        await bench.until(lambda: bool(fake.observers))
        fake.change("D03221", 60)
        await bench.until(lambda: session.status_is_live)
        # This device says nothing after a write it discards. The session
        # cannot tell that from a dead stream and climbs the ladder.
        with pytest.raises(NotConfirmedError):
            await session.write({"D0312A": 0})
        assert session.diagnostics().escalations == 1
        await bench.until(lambda: len(fake.observers) == 2, "no registration with a new token")

        # The next change arrives on both tokens: the old stream never was dead.
        fake.change("D03221", 61)
        await bench.until(lambda: len(fake.deregistrations) == 1)
        diag = session.diagnostics()
        assert diag.working_refresh_mode == "same_token" and diag.refresh_mode == "same_token"
        assert session.status is not None and session.status["D03221"] == 61

    # Other firmware than the AC3220/10: several observers per address, and
    # registrations that are answered only by the next change.
    bench.run(body, single_observer_per_ip=False, answer_registration="on_change", push_on_same_value=False)


@pytest.mark.parametrize("quirk", ["deregister_ignores_token", "deregister_registers"])
def test_giving_up_a_token_survives_a_device_that_mishandles_the_deregistration(bench: Bench, quirk: str) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        client, old = fake.registrations[-1]
        # Two ways a firmware could get Observe: 1 wrong: drop every observer
        # of the address, or take it for a registration of that token.
        fake.honour_deregister = True
        setattr(fake, quirk, True)

        assert await session.request_status() is True  # a new token, the old one is given up
        await bench.until(lambda: (client, old) in fake.deregistrations)
        new = fake.registrations[-1][1]
        await bench.until(lambda: list(fake.observers) == [(client, new)], "the new observer was lost with the old one")
        fake.change("D03221", 88)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 88)

    # Firmware that answers a new token from the port it already serves; the
    # AC3220/10 does not (measurement 13).
    bench.run(body, answer_new_token_on_same_port=True)
