"""Another device at the address: the session leaves it alone and finds its own device back.

The device at the address may be a purifier that another session serves. It
keeps one observer per source address, the newest registration wins, and the
latest sync decides the counter for every client of that address
(docs/metingen.md, measurement 9). So a session that knows it is talking to
the wrong device registers nothing and syncs nothing there.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from airlink import SessionState

if TYPE_CHECKING:
    from conftest import Bench

OFFLINE, REACHABLE, LIVE = SessionState.OFFLINE, SessionState.REACHABLE, SessionState.LIVE
EXPECTED = "99999999888811ef93334444555566bb"
INFO = ("NON", "/sys/dev/info")
SYNC = ("NON", "/sys/dev/sync")


def test_a_device_that_is_not_ours_gets_no_registration_and_no_sync(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake  # another purifier: it answers with its own id
        options = bench.options(probe_idle=0.1, refresh_interval=0.1, refresh_min_gap=0.02)
        session = await bench.started(options=options, expected_device_id=EXPECTED)
        await bench.until(lambda: session.identity_mismatch, "the other device was not noticed")
        # The registration of the start could not be helped: it did not know yet.
        await asyncio.sleep(0.05)
        registrations, infos = len(fake.registrations), fake.requests.count(INFO)

        # Five refresh intervals and five probe intervals later...
        await asyncio.sleep(0.5)
        assert len(fake.registrations) == registrations, "it registered at a device that is not ours"
        assert fake.syncs_received == 0 and SYNC not in fake.requests
        # ...it has asked who is there about once per probe interval, and nothing else.
        asked = fake.requests.count(INFO) - infos
        assert 3 <= asked <= 7, f"asked {asked} times in five probe intervals"
        assert {path for _, path in fake.requests} == {"/sys/dev/status", "/sys/dev/info"}
        assert session.available and session.status is None

        await session.stop()
        await asyncio.sleep(0.05)  # what stop() sent has arrived by now
        assert not fake.deregistrations, "and it leaves without a word"

    bench.run(body)


def test_the_session_registers_again_when_the_expected_device_answers(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(probe_idle=0.1, refresh_interval=60.0)
        session = await bench.started(options=options, expected_device_id=EXPECTED)
        await bench.until(lambda: session.identity_mismatch)
        fake.observers.clear()  # whoever serves that device took its stream back
        registrations = len(fake.registrations)
        await asyncio.sleep(0.3)
        assert len(fake.registrations) == registrations and session.state is REACHABLE

        # The address is ours again: only the info resource can tell, because
        # nothing is registered and a device at rest sends nothing.
        fake.state["DeviceId"] = EXPECTED
        await bench.until(lambda: not session.identity_mismatch, "the expected device was not found back")
        await bench.until(lambda: session.state is LIVE, "no registration followed")
        # With a new token, which a device that is on may answer.
        assert len(fake.registrations) > registrations
        assert fake.registrations[-1][1] != fake.registrations[registrations - 1][1]
        assert session.status is not None and session.status["DeviceId"] == EXPECTED
        fake.change("D03221", 12)
        await bench.until(lambda: session.status is not None and session.status["D03221"] == 12)

    bench.run(body)


def test_the_identity_is_asked_again_while_frames_of_the_other_device_keep_the_probes_away(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(probe_idle=0.2, refresh_interval=60.0)
        session = await bench.started(options=options, expected_device_id=EXPECTED)
        await bench.until(lambda: session.identity_mismatch)
        assert fake.observers, "the registration of the start is still served"
        await asyncio.sleep(0.05)  # the answer to that registration is in
        pings, infos = fake.pings_received, fake.requests.count(INFO)
        dropped = session.diagnostics().frames_dropped.get("identity_mismatch", 0)
        # A running purifier reports every few seconds; every frame is contact.
        for value in range(20):
            fake.change("D03221", value)
            await asyncio.sleep(0.04)
        assert fake.pings_received == pings, "the frames were not taken for contact"
        assert fake.requests.count(INFO) >= infos + 2, "nobody asked whether the expected device is back"
        assert session.diagnostics().frames_dropped == {"identity_mismatch": dropped + 20}
        assert session.status is None

    bench.run(body)


def test_a_device_that_is_not_ours_goes_offline_on_the_ping_alone(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        options = bench.options(
            probe_idle=0.05, probe_timeout=0.05, probe_retry=0.05, offline_min_silence=0.3, refresh_interval=60.0
        )
        session = await bench.started(options=options, expected_device_id=EXPECTED)
        await bench.until(lambda: session.identity_mismatch)
        registrations = len(fake.registrations)
        fake.silent = True
        await bench.until(lambda: session.state is OFFLINE, "it never gave up")
        await bench.until(lambda: session.diagnostics().socket_recreations >= 1)
        await asyncio.sleep(0.2)
        # Not even from the new socket: the flag stays until someone says who is there.
        assert fake.syncs_received == 0 and len(fake.registrations) == registrations
        assert session.identity_mismatch

        fake.state["DeviceId"] = EXPECTED
        fake.silent = False
        await bench.until(lambda: not session.identity_mismatch, "the identity was not checked on the return")
        await bench.until(lambda: session.state is LIVE)
        assert len(fake.registrations) > registrations

    bench.run(body)
