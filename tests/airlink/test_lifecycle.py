"""Starting and stopping: nothing may outlive ``stop()``.

Every test here also passes through the check in ``Bench.run`` that the event
loop holds no task once the sessions are stopped.
"""

from __future__ import annotations

import asyncio
import gc
import time
import warnings
from typing import TYPE_CHECKING

import pytest
from airlink import NotConfirmedError, SessionState, SessionStoppedError
from airlink.transport import Transport

if TYPE_CHECKING:
    from conftest import Bench


def other_tasks() -> list[asyncio.Task[object]]:
    return [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]


async def assert_quiet(bench: Bench, duration: float = 0.3) -> None:
    """Assert that nothing reaches the device any more."""
    await asyncio.sleep(0.02)
    received = bench.fake.datagrams_received
    await asyncio.sleep(duration)
    assert bench.fake.datagrams_received == received, "the stopped session still sends"


@pytest.mark.parametrize("honoured", [False, True])
def test_stop_deregisters_cancels_and_closes(bench: Bench, honoured: bool) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.honour_deregister = honoured
        session = await bench.live(options=bench.options(probe_idle=0.05, refresh_interval=0.05))
        observer = fake.registrations[-1]
        assert other_tasks(), "the supervision is running"
        await session.stop()
        assert not other_tasks(), "a task outlived stop()"
        assert session.state is SessionState.OFFLINE and not session.available
        # The deregistration is sent, best effort. The AC3220/10 ignores it
        # and keeps the observer (measured); other firmware lets go.
        await bench.until(lambda: observer in fake.deregistrations)
        assert (observer not in fake.observers) is honoured
        await assert_quiet(bench)
        # The last status stays readable, for a final snapshot.
        assert session.status is not None and session.snapshot().status == session.status

    bench.run(body)


def test_stop_twice_and_concurrently(bench: Bench) -> None:
    async def body() -> None:
        session = await bench.live()
        await asyncio.gather(session.stop(), session.stop())
        await session.stop()
        assert not other_tasks()
        assert len(bench.fake.deregistrations) == 1, "one deregistration, not three"

    bench.run(body)


def test_stop_during_start(bench: Bench) -> None:
    async def body() -> None:
        session = bench.session()
        starting = asyncio.ensure_future(session.start())
        await asyncio.sleep(0)  # start() is now waiting for its socket
        assert not starting.done()
        await session.stop()
        await starting  # returns quietly; the stop won
        assert not other_tasks()
        assert session.state is SessionState.OFFLINE
        await assert_quiet(bench)
        with pytest.raises(SessionStoppedError):
            await session.start()

    bench.run(body)


def test_stop_during_a_start_whose_socket_cannot_be_opened(bench: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        async def failing_open(transport: Transport) -> None:
            await asyncio.sleep(0.05)
            raise OSError(24, "Too many open files")

        monkeypatch.setattr(Transport, "open", failing_open)
        session = bench.session()
        starting = asyncio.ensure_future(session.start())
        await asyncio.sleep(0.01)  # start() is inside the open and holds the socket lock
        await session.stop()
        # start() goes on after the failed open. It must not begin to
        # supervise a session that stop() has already left.
        left = [task for task in other_tasks() if task is not starting]
        assert not left, f"stop() returned with tasks of the session alive: {left}"
        await starting
        assert not other_tasks() and session.state is SessionState.OFFLINE

    bench.run(body)


def test_stop_right_after_start(bench: Bench) -> None:
    async def body() -> None:
        session = bench.session()
        await session.start()
        await session.stop()  # before the first probe was answered
        assert not other_tasks()
        await assert_quiet(bench)

    bench.run(body)


def test_stop_without_start_and_start_twice(bench: Bench) -> None:
    async def body() -> None:
        idle = bench.session()
        await idle.stop()
        assert bench.fake.datagrams_received == 0

        session = bench.session(options=bench.quiet)
        await session.start()
        await session.start()  # no second registration, no second supervision
        await bench.settled()
        assert len(set(bench.fake.registrations)) == 1 and len(other_tasks()) == 2

    bench.run(body)


def test_stop_ends_a_write_that_waits_for_the_device(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, sync_timeout=5.0, write_budget=30.0))
        fake.silent = True
        writing = asyncio.ensure_future(session.write({"D03103": 1}))
        await bench.until(lambda: fake.syncs_received == 1)
        began = time.monotonic()
        await session.stop()
        with pytest.raises(SessionStoppedError):
            await asyncio.wait_for(writing, 1.0)
        assert time.monotonic() - began < 1.0 and not other_tasks()

    bench.run(body)


def test_stop_ends_a_write_that_waits_for_its_confirmation(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.push_on_same_value = False  # no frame at all after the discarded write
        session = await bench.live(options=bench.options(bench.quiet, confirm_timeout=30.0))
        writing = asyncio.ensure_future(session.write({"D0312A": 0}))  # will never be confirmed
        await bench.until(lambda: len(fake.controls) == 1)
        await asyncio.sleep(0.05)
        assert not writing.done()
        await session.stop()
        with pytest.raises(SessionStoppedError):
            await asyncio.wait_for(writing, 1.0)
        assert not other_tasks()
        assert session.diagnostics().commands_unconfirmed == 0, "a stopped write is not a verdict on the device"

    bench.run(body)


def test_stop_ends_a_write_that_waits_for_the_lock(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, sync_timeout=5.0, write_budget=30.0))
        fake.silent = True
        first = asyncio.ensure_future(session.write({"D03103": 1}))
        second = asyncio.ensure_future(session.write({"D0310C": 18}))
        await bench.until(lambda: fake.syncs_received == 1)
        await session.stop()
        for writing in (first, second):
            with pytest.raises(SessionStoppedError):
                await asyncio.wait_for(writing, 1.0)
        assert fake.syncs_received == 1 and not other_tasks()

    bench.run(body)


def test_stop_before_a_one_shot_task_ran_leaves_no_unawaited_coroutine(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, confirm_timeout=0.1, confirm_retry_wait=0.1))
        await bench.settled()
        # The device went to standby and the frame that said so was lost: two
        # writes in a row are acknowledged and never confirmed. The second
        # one climbs to the resync, which runs as a task of its own...
        fake.power_off(notify=False)
        for _ in range(2):
            with pytest.raises(NotConfirmedError):
                await session.write({"D03103": 1})
        assert session.diagnostics().escalations == 2
        # ...and the caller stops the session before that task took a step.
        await session.stop()
        assert not other_tasks()

    # A coroutine that was made and never awaited is reported when it is
    # collected: a RuntimeWarning in the log, an error where warnings are errors.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bench.run(body)
        gc.collect()
    leaked = [str(item.message) for item in caught if "never awaited" in str(item.message)]
    assert not leaked, leaked


def test_cancelled_write_leaves_the_session_usable(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        session = await bench.live(options=bench.options(bench.quiet, sync_timeout=5.0, write_budget=30.0))
        fake.silent = True
        writing = asyncio.ensure_future(session.write({"D03103": 1}))
        await bench.until(lambda: fake.syncs_received == 1)
        writing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writing
        fake.silent = False
        result = await session.write({"D03103": 1})  # the lock was released
        assert not result.resent and fake.state["D03103"] == 1

    bench.run(body)


def test_cancelled_start_and_cancelled_stop_leave_nothing_behind(bench: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        real_open = Transport.open
        hang = True

        async def slow_open(transport: Transport) -> None:
            if hang:
                await asyncio.sleep(30)
            await real_open(transport)

        monkeypatch.setattr(Transport, "open", slow_open)
        session = bench.session(options=bench.options(socket_timeout=30.0))
        starting = asyncio.ensure_future(session.start())
        await asyncio.sleep(0.01)
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert not other_tasks() and bench.fake.datagrams_received == 0

        # The same session can still be started...
        hang = False
        await session.start()
        await bench.until(lambda: session.available)
        assert len(set(bench.fake.registrations)) == 1
        # The registration is answered: from here a setting is sent at once.
        await bench.until(lambda: session.status_is_live)

        # ...and a stop() that is cancelled half-way still ends everything.
        hang = True
        protocol = session._transport._protocol
        assert protocol is not None
        protocol.error_received(OSError("network is unreachable"))  # the next write wants a new socket
        writing = asyncio.ensure_future(session.write({"D03103": 1}))
        await asyncio.sleep(0.01)  # the write now holds the socket lock, inside the slow open
        stopping = asyncio.ensure_future(session.stop())
        await asyncio.sleep(0.01)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        await session.stop()  # does not hang on the cancelled one
        assert session.state is SessionState.OFFLINE
        writing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writing
        assert not other_tasks()
        await assert_quiet(bench)

    bench.run(body)


def test_stopped_session_ignores_late_datagrams_and_listeners(bench: Bench) -> None:
    async def body() -> None:
        fake = bench.fake
        fake.honour_deregister = False  # this device keeps sending after a deregistration
        session = await bench.live()
        calls: list[int] = []
        session.add_listener(lambda: calls.append(1))
        before = dict(session.status or {})
        await session.stop()
        fake.change("D03221", 99)
        await asyncio.sleep(0.05)
        assert session.status == before and not calls

    bench.run(body)


def test_stop_ends_a_status_request_that_waits_for_a_frame(bench: Bench) -> None:
    async def body() -> None:
        bench.fake.power_off(notify=False)  # in standby nothing will answer
        session = await bench.started(options=bench.options(bench.quiet, request_status_timeout=30.0))
        waiting = asyncio.ensure_future(session.request_status())
        await asyncio.sleep(0.05)
        assert not waiting.done()
        await session.stop()
        with pytest.raises(SessionStoppedError):
            await asyncio.wait_for(waiting, 1.0)
        assert not other_tasks()

    bench.run(body)
