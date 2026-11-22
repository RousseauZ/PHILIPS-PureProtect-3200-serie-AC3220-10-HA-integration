"""The device functions against the simulated purifier."""

import asyncio
from collections.abc import Awaitable, Callable

from fake_purifier import FakePurifier
from pureprotect_probe.device import Purifier
from pureprotect_probe.endpoint import Endpoint
from pureprotect_probe.eventlog import EventLog


def run(test: Callable[[FakePurifier, Purifier, EventLog], Awaitable[None]], **quirks: object) -> None:
    async def main() -> None:
        fake = await FakePurifier.start()
        for name, value in quirks.items():
            setattr(fake, name, value)
        log = EventLog(None, quiet=True)
        endpoint = await Endpoint.open(log, "A", peer_ip="127.0.0.1", bind_host="127.0.0.1")
        device = Purifier(endpoint, "127.0.0.1", fake.port)
        try:
            await asyncio.wait_for(test(fake, device, log), 20)
        finally:
            endpoint.close()
            fake.close()

    asyncio.run(main())


def test_info_non_and_con() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        reply = await dev.info()
        assert reply.ok and reply.mtype == "NON" and reply.data["modelid"] == "AC3220/10"
        reply = await dev.info(con=True)
        assert reply.ok and reply.mtype == "ACK" and reply.data["type"] == "Unicorn"

    run(body)


def test_info_timeout_when_silent() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        reply = await dev.info(timeout=0.2)
        assert not reply.ok and reply.kind == "timeout" and reply.latency is None

    run(body, silent=True)


def test_sync_sets_counter_and_rejects_malformed() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        reply = await dev.sync()
        assert reply.ok and dev.counter == reply.data and len(reply.data) == 8
        good = dev.counter
        fake.malformed_next_syncs = 1
        reply = await dev.sync()
        assert not reply.ok and reply.kind == "response" and dev.counter == good
        assert any(e["ev"] == "sync" and e.get("raw_hex") for e in log.events)

    run(body)


def test_ping_gets_reset() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        reply = await dev.ping()
        assert reply.ok and reply.kind == "reset"
        fake.ping_enabled = False
        assert not (await dev.ping(timeout=0.2)).ok

    run(body)


def test_observe_immediate_and_change() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        token = dev.ep.new_token()
        dev.register(token)
        first = await dev.wait_frame(since=0, timeout=2)
        assert first is not None and first.decode == "ok" and first.max_age == 60
        assert first.reported["D01S05"] == "AC3220/10" and dev.device_id == fake.state["DeviceId"]
        fake.change("D0310C", 18)
        second = await dev.wait_frame(since=1, timeout=2)
        assert second is not None and second.changed == {"D0310C": 18} and not second.identical
        assert second.observe == first.observe + 1

    run(body)


def test_push_on_change_registration_is_not_answered() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        dev.register(dev.ep.new_token())
        assert await dev.wait_frame(since=0, timeout=0.3) is None
        fake.change("D03221", 9)
        assert await dev.wait_frame(since=0, timeout=2) is not None

    run(body, answer_registration="on_change")


def test_plain_get_is_never_answered() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        dev.plain_status_get(dev.ep.new_token())
        assert await dev.wait_frame(since=0, timeout=0.3) is None

    run(body)


def test_control_changes_state_and_echoes() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        dev.register(dev.ep.new_token())
        await dev.wait_frame(since=0, timeout=2)
        reply = await dev.control({"D0310C": 5})
        assert reply.ok and reply.data == "success"
        echo = await dev.wait_frame(since=1, timeout=2)
        assert echo is not None and echo.reported["StatusType"] == "control"
        assert echo.reported["D0310C"] == 5 and echo.reported["D0310D"] == 18

    run(body)


def test_control_same_value_gives_no_frame() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        dev.register(dev.ep.new_token())
        await dev.wait_frame(since=0, timeout=2)
        assert (await dev.control({"D03103": 0})).ok
        assert await dev.wait_frame(since=1, timeout=0.3) is None

    run(body)


def test_control_readonly_key_is_acked_and_discarded() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        assert (await dev.control({"D03105": 0})).ok
        assert fake.state["D03105"] == 101

    run(body)


def test_control_with_stale_counter_fails() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        await dev.sync()
        dev.counter = "00000000"
        reply = await dev.control({"D03103": 1}, sync_first=False)
        assert not reply.ok and reply.data == "failed"
        assert (await dev.control({"D03103": 1})).ok and fake.state["D03103"] == 1

    run(body)


def test_confirmable_notifications_are_acknowledged() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        dev.register(dev.ep.new_token())
        frame = await dev.wait_frame(since=0, timeout=2)
        assert frame is not None and frame.mtype.name == "CON"
        await asyncio.sleep(0.1)
        assert fake.acks_received == 1

    run(body, notify_con=True)


def test_unknown_confirmable_notification_gets_reset() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        token = dev.ep.new_token()
        dev.register(token)
        await dev.wait_frame(since=0, timeout=2)
        dev.ep.remove_stream(token)
        fake.change("D03221", 8)
        await asyncio.sleep(0.2)
        assert fake.resets_received == 1 and not fake.observers

    run(body, notify_con=True)


def test_reject_next_sends_reset_once() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        token = dev.ep.new_token()
        dev.register(token)
        await dev.wait_frame(since=0, timeout=2)
        dev.ep.reject_next(token)
        fake.change("D03221", 8)
        assert await dev.wait_frame(since=1, timeout=2) is not None
        await asyncio.sleep(0.1)
        assert fake.resets_received == 1 and not fake.observers
        fake.change("D03221", 9)
        assert await dev.wait_frame(since=2, timeout=0.3) is None

    run(body)


def test_corrupt_frame_is_reported_not_raised() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        fake.corrupt_next_frames = 1
        dev.register(dev.ep.new_token())
        frame = await dev.wait_frame(since=0, timeout=2)
        assert frame is not None and frame.decode == "err:bad_ciphertext" and frame.reported is None
        fake.change("D03221", 8)
        good = await dev.wait_frame(since=1, timeout=2)
        assert good is not None and good.decode == "ok"

    run(body)


def test_foreign_senders_are_ignored() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        dev.ep.peer_ip = "192.0.2.1"
        assert not (await dev.info(timeout=0.3)).ok
        assert any(e["ev"] == "rx" and e.get("foreign") for e in log.events)

    run(body)


def test_identifiers_are_redacted_in_the_log() -> None:
    async def body(fake: FakePurifier, dev: Purifier, log: EventLog) -> None:
        await dev.info()
        dev.register(dev.ep.new_token())
        await dev.wait_frame(since=0, timeout=2)
        text = repr(log.events)
        assert fake.state["DeviceId"] not in text and "Testkamer" not in text
        info = next(e for e in log.events if e["ev"] == "info")
        frame = next(e for e in log.events if e["ev"] == "frame")
        assert info["data"]["device_id"] == frame["reported"]["DeviceId"]

    run(body)
