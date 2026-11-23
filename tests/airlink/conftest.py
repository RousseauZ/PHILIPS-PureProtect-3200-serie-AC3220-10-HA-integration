"""Test bench for the airlink package.

The package is imported as top-level ``airlink``, never through
``custom_components``: that package's ``__init__`` imports Home Assistant,
which these tests must not need.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_PACKAGE = _HERE.parents[1] / "custom_components" / "philips_pureprotect" / "airlink"
if "airlink" not in sys.modules:
    # Loaded by path, not by putting the integration's folder on sys.path:
    # that folder also holds a select.py, which would shadow the standard library.
    _spec = importlib.util.spec_from_file_location("airlink", _PACKAGE / "__init__.py", submodule_search_locations=[str(_PACKAGE)])
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["airlink"] = _module
    _spec.loader.exec_module(_module)
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))  # for fake_purifier, whatever the import mode

from airlink import RestoredState, Session, SessionOptions, SessionState, TraceCallback  # noqa: E402
from airlink.transport import Transport  # noqa: E402
from fake_purifier import FakePurifier  # noqa: E402

# The production timings divided by a few hundred, so that a test takes a
# second or two. The loopback answers within a millisecond.
FAST = SessionOptions(
    probe_idle=0.2,
    probe_timeout=0.1,
    probe_retry=0.1,
    offline_min_misses=3,
    offline_min_silence=0.6,
    offline_backoff=(0.1, 0.1, 0.2),
    refresh_interval=0.3,
    refresh_min_gap=0.05,
    sync_timeout=0.25,
    control_timeout=0.25,
    write_attempts=3,
    write_budget=2.0,
    confirm_settle=0.1,
    confirm_timeout=0.4,
    confirm_retry_wait=0.3,
    info_timeout=0.25,
    info_attempts=2,
    request_status_timeout=0.3,
    standby_presume_after=0.5,
    socket_timeout=1.0,
    error_pause=0.05,
)
# The same, without any periodic traffic: no probes and no refreshes unless
# something asks for them.
QUIET = dataclasses.replace(FAST, probe_idle=60.0, refresh_interval=60.0)


def _spinning(signum: int, frame: object) -> None:
    raise AssertionError("the event loop is blocked: something spins without yielding")


class Bench:
    """One simulated purifier on the loopback and the sessions talking to it."""

    fake: FakePurifier

    def __init__(self) -> None:
        self.fast = FAST
        self.quiet = QUIET
        self._sessions: list[Session] = []
        self._transports: list[Transport] = []

    def options(self, base: SessionOptions = FAST, **changes: Any) -> SessionOptions:
        """Return the fast options with some values replaced."""
        return dataclasses.replace(base, **changes)

    def session(
        self,
        *,
        options: SessionOptions = FAST,
        restored: RestoredState | None = None,
        expected_device_id: str | None = None,
        trace: TraceCallback | None = None,
    ) -> Session:
        """Create a session towards the simulated device; the bench stops it."""
        session = Session(
            "127.0.0.1",
            port=self.fake.port,
            options=options,
            restored=restored,
            expected_device_id=expected_device_id,
            trace=trace,
        )
        self._sessions.append(session)
        return session

    async def started(self, **kwargs: Any) -> Session:
        """Create and start a session, and wait until the device answered."""
        session = self.session(**kwargs)
        await session.start()
        await self.until(lambda: session.available, "the session never became reachable")
        return session

    async def live(self, **kwargs: Any) -> Session:
        """Return a started session that has the status of a device that is on.

        Nothing has to change for that: the device answers a new registration.
        """
        assert self.fake.is_on, "a device in standby does not answer a registration"
        session = await self.started(**kwargs)
        await self.until(lambda: session.state is SessionState.LIVE, "the registration was not answered")
        return session

    async def settled(self) -> None:
        """Wait until the registrations of a start are out: the one of start()
        itself and the one that follows the first contact."""
        await self.until(lambda: len(self.fake.registrations) >= 2, "the start never settled")
        await asyncio.sleep(0.02)

    def transport(self, **kwargs: Any) -> Transport:
        """Create a bare transport towards the simulated device; the bench closes it."""
        transport = Transport("127.0.0.1", self.fake.port, bind_host="127.0.0.1", **kwargs)
        self._transports.append(transport)
        return transport

    @staticmethod
    async def until(predicate: Callable[[], bool], what: str = "condition not met", timeout: float = 5.0) -> None:
        """Poll until the predicate holds; fail the test after the timeout."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(what)
            await asyncio.sleep(0.005)

    def client_addr(self) -> tuple[str, int]:
        """Return the address the device sees the (only) client at."""
        assert self.fake.registrations, "no registration seen yet"
        return self.fake.registrations[-1][0]

    def run(self, body: Callable[[], Awaitable[None]], *, timeout: float = 20.0, **quirks: Any) -> None:
        """Run a test body against a fresh simulated device.

        Afterwards every session is stopped and the loop must be empty: no
        task may outlive ``stop()``.
        """

        async def main() -> None:
            self.fake = await FakePurifier.start()
            for name, value in quirks.items():
                assert hasattr(self.fake, name), f"unknown quirk {name}"
                setattr(self.fake, name, value)
            try:
                await asyncio.wait_for(body(), timeout)
            finally:
                for session in self._sessions:
                    await session.stop()
                for transport in self._transports:
                    transport.close()
                self.fake.close()
            leftover = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            assert not leftover, f"tasks outlived stop(): {leftover}"

        # A session bug that spins without ever yielding would block the event
        # loop and with it every asyncio timeout; only a signal gets through.
        watchdog = hasattr(signal, "SIGALRM")
        if watchdog:
            signal.signal(signal.SIGALRM, _spinning)
            signal.alarm(int(timeout) + 10)
        try:
            asyncio.run(main())
        finally:
            if watchdog:
                signal.alarm(0)


try:
    import pytest_socket  # noqa: F401
except ImportError:
    pass
else:

    @pytest.fixture(autouse=True)
    def _allow_sockets(socket_enabled: None) -> None:
        """Next to Home Assistant's test plugin, which blocks sockets, allow the loopback."""


@pytest.fixture
def bench() -> Bench:
    """Return the test bench; call ``bench.run(body)`` with an async body."""
    return Bench()
