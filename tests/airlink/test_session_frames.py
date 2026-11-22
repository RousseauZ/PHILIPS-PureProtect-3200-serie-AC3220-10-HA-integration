"""Observation, status frames and identity (session rules 5, 7, 8 and 9)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest
from airlink import Identity, RestoredState, SessionState, SessionStoppedError
from airlink.coap import GET, MType, build_request

if TYPE_CHECKING:
    from conftest import Bench

REACHABLE, LIVE = SessionState.REACHABLE, SessionState.LIVE
OTHER_DEVICE = "99999999888811ef93334444555566ff"


def test_registration_is_refreshed_with_the_same_token_without_any_answer(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(refresh_interval=0.08))
        await bench.until(lambda: len(fake.registrations) >= 6)
        assert len(set(fake.registrations)) == 1, "one endpoint and one token for as long as the socket lives"
        assert len(fake.observers) == 1
        # Only the first registration was answered; the refreshes were not,
        # and nothing was torn down because of that.
        assert fake.frames_sent == 1 and session.state is LIVE
        diag = session.diagnostics()
        assert diag.refreshes_sent >= 5 and diag.socket_recreations == 0 and diag.refresh_mode == "same_token"

    bench.run(body)


def test_device_restart_is_healed_by_the_periodic_refresh(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        # No probe will be sent: only the mandatory refresh can repair this.
        session = await bench.live(options=bench.options(probe_idle=60.0, refresh_interval=0.15))
        before = dict(session.status or {})
        fake.reboot()
        fake.state["D03221"] = 77  # and something changed meanwhile
        assert not fake.observers
        await bench.until(lambda: bool(fake.observers), "the refresh did not register again")
        # To the restarted device the refresh is a new registration, so it answers.
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 77)
        assert session.status["Runtime"] < before["Runtime"]
        diag = session.diagnostics()
        # The fallen Runtime is recognised as a restart, not dropped as a stale frame.
        assert diag.device_restarts == 1 and diag.frames_dropped == {}
        assert session.state is LIVE

    bench.run(body)


def test_refresh_keeps_a_lapsing_observation_alive(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(refresh_interval=0.1))
        await asyncio.sleep(0.8)  # several times the lapse of this firmware
        fake.change("D03221", 55)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 55)

    bench.run(body, lapse_after=0.3)


def test_refresh_takes_the_stream_back_from_another_client(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(probe_idle=60.0, refresh_interval=0.15))
        ours = fake.registrations[-1]
        # Another program on this host registers. Measured: one observer per
        # address, and the newest wins.
        intruder = bench.transport()
        await intruder.open()
        token = intruder.new_token()
        intruder.add_stream(token, lambda msg: None)
        intruder.send(build_request(MType.NON, GET, intruder.next_mid(), token, "/sys/dev/status", observe=0))
        await bench.until(lambda: ours not in fake.observers)
        await bench.until(lambda: ours in fake.observers, "the refresh did not take the stream back")
        fake.change("D03221", 66)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 66)

    bench.run(body)


def test_corrupt_frame_is_dropped_and_followed_by_a_refresh(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        registrations = len(fake.registrations)
        before = dict(session.status or {})
        notified: list[int] = []
        session.add_listener(lambda: notified.append(1))

        fake.corrupt_next_frames = 1
        fake.change("D03221", 55)
        await bench.until(lambda: session.diagnostics().frames_dropped == {"bad_ciphertext": 1})
        assert session.status == before and not notified, "a damaged frame must not touch the status"
        assert session.state is LIVE
        # The change is lost, so the registration is sent again.
        await bench.until(lambda: len(fake.registrations) == registrations + 1)

        fake.change("D03221", 56)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 56)
        assert session.diagnostics().frames_dropped == {"bad_ciphertext": 1}

    bench.run(body)


def test_a_storm_of_corrupt_frames_cannot_start_a_ping_pong(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        # A firmware that answers every registration at once, and badly.
        fake.corrupt_next_frames = 10_000
        session = await bench.started(options=bench.options(bench.quiet, refresh_min_gap=0.2))
        await asyncio.sleep(0.7)
        dropped = session.diagnostics().frames_dropped["bad_ciphertext"]
        assert 2 <= dropped <= 6, "extra refreshes must keep their distance"
        assert session.state is REACHABLE and session.status is None

    bench.run(body, answer_registration="immediate")


def test_reordered_older_frame_is_dropped_as_stale(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        fake.change("D03221", 50)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 50)
        await bench.settled()
        frames = session.diagnostics().frames_received
        registrations = len(fake.registrations)

        # A frame from half a second of device time ago arrives late.
        fake.push(runtime_shift_ms=-500, state={**fake.state, "D03221": 49})
        await bench.until(lambda: session.diagnostics().frames_dropped == {"stale": 1})
        assert session.status is not None and session.status["D03221"] == 50
        assert session.diagnostics().frames_received == frames and session.diagnostics().device_restarts == 0
        # Nothing was lost, so no refresh either.
        await asyncio.sleep(0.15)
        assert len(fake.registrations) == registrations

    bench.run(body)


def test_frame_for_another_device_is_dropped_and_flagged(bench: Bench, caplog: pytest.LogCaptureFixture) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        session = await bench.started(options=bench.quiet, expected_device_id=OTHER_DEVICE)
        notified: list[bool] = []
        session.add_listener(lambda: notified.append(session.identity_mismatch))
        await bench.until(lambda: bool(fake.observers))
        assert not session.identity_mismatch

        with caplog.at_level(logging.WARNING, logger="airlink"):
            fake.power_on()
            await bench.until(lambda: session.identity_mismatch)
            fake.change("D03221", 10)
            await bench.until(lambda: session.diagnostics().identity_mismatches == 2)
        await asyncio.sleep(0)
        assert session.status is None and not session.status_is_live and session.state is REACHABLE
        assert session.diagnostics().frames_dropped == {"identity_mismatch": 2}
        assert notified == [True], "the listeners are told once, when the flag changes"
        assert len([r for r in caplog.records if "another device" in r.getMessage()]) == 1

    # Without the info resource only the frames can give the device away.
    bench.run(body, info_enabled=False)


def test_identity_check_on_first_contact_flags_another_device(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)  # no frame will ever come
        session = await bench.started(options=bench.quiet, expected_device_id=OTHER_DEVICE)
        await bench.until(lambda: session.identity_mismatch, "the info answer was not checked")
        assert session.identity is not None and session.identity.device_id == fake.state["DeviceId"]
        assert session.diagnostics().identity_mismatches == 1 and session.available

    bench.run(body)


def test_expected_device_is_accepted_and_clears_the_flag(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        expected = fake.state["DeviceId"]
        # The stored id differs in case only; that is the same device.
        session = await bench.live(options=bench.quiet, expected_device_id=expected.upper())
        assert not session.identity_mismatch and session.diagnostics().identity_mismatches == 0

        fake.state["DeviceId"] = OTHER_DEVICE  # another purifier got this address
        fake.change("D03221", 70)
        await bench.until(lambda: session.identity_mismatch)
        assert session.status is not None and session.status["D03221"] != 70

        fake.state["DeviceId"] = expected  # and the right one is back
        fake.change("D03221", 71)
        await bench.until(lambda: not session.identity_mismatch)
        assert session.status["D03221"] == 71

    bench.run(body)


def test_unknown_token_is_answered_with_a_reset(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        frames = session.diagnostics().frames_received
        # The device still serves an observer of an earlier run of the integration.
        fake.send_stray_notification(bench.client_addr())
        await bench.until(lambda: fake.resets_received == 1)
        diag = session.diagnostics()
        assert diag.unknown_token_resets == 1 and diag.frames_received == frames

    bench.run(body)


def test_datagrams_from_another_address_are_ignored(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        before = dict(session.status or {})
        sent = session.diagnostics().datagrams_sent

        fake.reply_from_other_port = True  # valid frames, right token, wrong sender
        fake.change("D03221", 90)
        await bench.until(lambda: session.diagnostics().foreign_datagrams == 1)
        assert session.status == before
        assert session.diagnostics().datagrams_sent == sent, "a foreign sender gets no answer at all"

        fake.reply_from_other_port = False
        fake.change("D03221", 91)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 91)

    bench.run(body)


def test_confirmable_notifications_are_acknowledged(bench: Bench) -> None:
    async def body() -> None:
        session = await bench.live()
        await bench.until(lambda: bench.fake.acks_received >= 1)
        assert session.state is LIVE and bench.fake.resets_received == 0

    bench.run(body, notify_con=True)


def test_identify_reads_the_info_resource(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        expected = Identity(
            device_id=fake.state["DeviceId"],
            product_id=fake.state["ProductId"],
            model_id="AC3220/10",
            type="Unicorn",
            name="Testkamer",
        )
        # As a config flow would: no start, so no observer and no sync on the device.
        session = bench.session()
        assert await session.identify() == expected
        assert session.identity == expected
        assert fake.requests == [("NON", "/sys/dev/info")] and not fake.observers
        assert session.state is SessionState.OFFLINE, "identifying is not supervising"

        # One request in six went unanswered on the real device: a second try.
        fake.drop_next_infos = 1
        assert await session.identify() == expected
        assert fake.requests.count(("NON", "/sys/dev/info")) == 3

        fake.info_enabled = False
        assert await session.identify() is None
        await session.stop()
        with pytest.raises(SessionStoppedError):
            await session.identify()

    bench.run(body)


def test_snapshot_survives_a_restart(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        first = await bench.live()
        snapshot = first.snapshot()
        await first.stop()
        assert snapshot.status is not None and snapshot.status["DeviceId"] == fake.state["DeviceId"]
        assert snapshot.keys == frozenset(snapshot.status)

        stored = snapshot.as_dict()  # what goes to disk
        restored = RestoredState.from_dict(stored)
        assert restored == snapshot
        assert RestoredState.from_dict({"status": "nonsense", "keys": 3}) == RestoredState()

        fake.power_off(notify=False)  # switched off while Home Assistant was down
        second = await bench.started(restored=restored)
        assert second.status == snapshot.status and not second.status_is_live
        assert second.last_frame_at == snapshot.received_at and second.state is REACHABLE
        # The first live frame replaces what was restored.
        fake.power_on()
        await bench.until(lambda: second.status_is_live)
        assert second.status is not None and second.status["Runtime"] > snapshot.status["Runtime"]

    bench.run(body)


def test_listeners_are_called_and_a_failing_one_breaks_nothing(bench: Bench, caplog: pytest.LogCaptureFixture) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.power_off(notify=False)
        session = bench.session(options=bench.quiet)
        calls: list[tuple[SessionState, int | None]] = []

        def failing() -> None:
            raise RuntimeError("a broken listener")

        def good() -> None:
            calls.append((session.state, None if session.status is None else session.status["D03221"]))

        session.add_listener(failing)
        remove = session.add_listener(good)
        await session.start()
        with caplog.at_level(logging.ERROR, logger="airlink"):
            await bench.until(lambda: calls == [(REACHABLE, None)])
            await bench.until(lambda: bool(fake.observers))
            fake.state["D03221"] = 30
            fake.power_on()
            await bench.until(lambda: len(calls) == 2)
            fake.change("D03221", 31)
            await bench.until(lambda: len(calls) == 3)
        # One call per frame: the state change and the status arrive together.
        assert calls == [(REACHABLE, None), (LIVE, 30), (LIVE, 31)]
        assert len([r for r in caplog.records if "listener failed" in r.getMessage()]) == 3

        remove()
        remove()  # removing twice is harmless
        fake.change("D03221", 32)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 32)
        await asyncio.sleep(0.01)
        assert len(calls) == 3

    bench.run(body)


def test_trace_callback_sees_the_datagrams_of_a_session(bench: Bench) -> None:
    async def body() -> None:
        seen: list[tuple[str, tuple[str, int], int]] = []
        session = bench.session(trace=lambda direction, addr, data: seen.append((direction, addr, len(data))))
        await session.start()
        await bench.until(lambda: session.available)
        device = ("127.0.0.1", bench.fake.port)
        assert ("tx", device) == seen[0][:2], "the registration goes out first"
        assert any(direction == "rx" and addr == device for direction, addr, _ in seen)

    bench.run(body)


def test_diagnostics_are_serialisable(bench: Bench) -> None:
    async def body() -> None:
        import json

        session = await bench.live()
        data = session.diagnostics().as_dict()
        assert json.loads(json.dumps(data)) == data
        assert data["state"] == "live" and data["frames_received"] == 1
        assert data["working_refresh_mode"] == "same_token" and data["frames_dropped"] == {}
        assert data["seconds_since_last_frame"] < 5 and data["seconds_since_last_contact"] < 5

    bench.run(body)


def test_request_status_registers_anew_and_reports_whether_a_frame_came(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.quiet)
        await bench.settled()
        client, token = fake.registrations[-1]
        syncs, controls = fake.syncs_received, len(fake.controls)

        # While the device is on it answers a new registration: this is a poll.
        fake.state["D03221"] = 123  # changed while nobody was told
        assert await session.request_status() is True
        assert session.status is not None and session.status["D03221"] == 123
        new_token = fake.registrations[-1][1]
        assert new_token != token and list(fake.observers) == [(client, new_token)]
        # No side effects: no sync, no write, and not a step on the recovery ladder.
        assert fake.syncs_received == syncs and len(fake.controls) == controls
        diag = session.diagnostics()
        assert diag.escalations == 0 and diag.refresh_mode == "same_token" and diag.working_refresh_mode == "same_token"

        # In standby nothing answers, and nothing is waited for beyond the deadline.
        await session.write({"D03102": 0})
        fake.state["D03221"] = 124
        assert await session.request_status() is False
        assert session.status["D03221"] == 123

    bench.run(body)
