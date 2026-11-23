"""The session with one purifier: observation, liveness, recovery, commands.

This is the state machine of report 6.3 and 6.4 (docs/onderzoek.md), with
the adjustments that the measurements on a real AC3220/10 asked for
(docs/metingen.md). The two ideas everything else follows from:

* Silence is never a fault. The device reports on change only and says
  nothing at all in standby, so reachability is measured with probes of its
  own and nothing is torn down because the status stream is quiet.
* "success" is not proof. The device acknowledges writes it discards, so a
  command counts only once a status frame shows its effect. The one
  exception is switching off: a device in standby answers "success" to that
  and sends nothing, so there the answer has to do (measurement 5).

What the device was measured to do with observers (measurements 8 to 10):
it serves one observer per source address and the newest registration wins;
it answers a new registration with a status frame within about 2 s while it
is on, never in standby, and it does not answer a repeated registration with
the same token; it ignores a deregistration and a Reset.

A registration with a new token from the port that already holds the
observation is not answered either (measurement 13, 0 of 6), but it takes
the stream over. Where the session knows that it missed a change it still
registers with a new token: on the AC3220/10 that brings no status, and the
next report does, which comes within seconds while the device runs
(measurement 12) and carries the whole status; firmware that answers a new
token sends it at once.

Presumed standby. A device in standby cannot say that it is off, so the
session concludes it from what was measured: a registration from a newly
opened socket is answered within 2 s by a device that is on, and never by
one in standby. A reachable device that leaves such a registration without
any frame for ``standby_presume_after`` is taken to be in standby until a
frame says otherwise (``Session.presumed_standby``). The same goes for a
switch-off that the device accepted in silence.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import functools
import json
import logging
import math
import os
import time
from collections.abc import Callable, Coroutine, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeGuard

from . import crypto
from .coap import DEFAULT_PORT, GET, POST, Message, MType, build_request, code_class, code_text
from .errors import (
    DeviceOffError,
    NotConfirmedError,
    RefusedError,
    SessionStoppedError,
    TransportError,
    UnreachableError,
    WriteError,
)
from .models import (
    Diagnostics,
    Identity,
    RefreshMode,
    RestoredState,
    SessionOptions,
    SessionState,
    WriteResult,
)
from .transport import TraceCallback, Transport

# The name of the package as it was imported: "airlink" on its own, and a
# child of the integration's logger inside Home Assistant, so that the debug
# switch of the integration reaches these lines.
_LOGGER = logging.getLogger(__package__)

INFO_PATH = "/sys/dev/info"
SYNC_PATH = "/sys/dev/sync"
STATUS_PATH = "/sys/dev/status"
CONTROL_PATH = "/sys/dev/control"

POWER_KEY = "D03102"
RUNTIME_KEY = "Runtime"
DEVICE_ID_KEY = "DeviceId"
FIRMWARE_KEY = "D01S12"
WIFI_FIRMWARE_KEY = "WifiVersion"

_RESERVED_KEYS = frozenset({"CommandType", "DeviceId", "EnduserId"})
# Tokens kept alive at once while climbing the ladder of rule 6.
_MAX_OBSERVATIONS = 3


def accepted_readback(key: str, value: int) -> frozenset[int]:
    """Return what the device may report after ``value`` was written to ``key``.

    The device normalises some values (report 6.4 item 5). Only the beep is
    known to do so on a write: any non-zero value reads back as 100.
    """
    if key == "D03130" and value != 0:
        return frozenset({100})
    return frozenset({value})


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


class _ProbeKind(enum.Enum):
    PING = "ping"  # empty confirmable message; touches nothing on the device
    SYNC = "sync"  # changes the device's counter, so it is the second choice


class _FrameError(Exception):
    """A status message that is not applied; ``reason`` names the counter."""

    def __init__(self, reason: str, *, missed_change: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        # True when the content is lost, so a change may have been missed.
        self.missed_change = missed_change


@dataclass(slots=True, eq=False)
class _Observation:
    """One registration on the status resource."""

    token: bytes
    mode: RefreshMode
    created: float
    registrations: int = 0
    last_frame: float | None = None


class _FrameWaiter:
    """Waits for a status frame that shows the expected values."""

    def __init__(self, accepted: Mapping[str, frozenset[int]]) -> None:
        self.accepted = dict(accepted)
        self.frames = 0  # valid frames seen since creation
        self.matched = False
        self.mismatched = False
        # A newer write took over every key this one waited for.
        self.superseded = False
        self.stopped = False
        # From this moment on a frame without the expected values counts as
        # an answer too; None means such frames are ignored.
        self.mismatch_after: float | None = None
        self._latest: Mapping[str, Any] | None = None
        self._event = asyncio.Event()

    @property
    def settled(self) -> bool:
        """Return True when nothing is left to wait for, or to send again."""
        return self.matched or self.superseded

    def _shows(self, reported: Mapping[str, Any]) -> bool:
        return all(reported.get(key) in values for key, values in self.accepted.items())

    def offer(self, reported: Mapping[str, Any], now: float) -> None:
        self.frames += 1
        self._latest = reported
        if self.settled:
            return
        if self._shows(reported):
            self.matched = True
            self._event.set()
        elif self.mismatch_after is not None and now >= self.mismatch_after:
            self.mismatched = True
            self._event.set()

    def forget(self, keys: Iterable[str]) -> None:
        """Stop waiting for keys that a newer write took over."""
        for key in keys:
            self.accepted.pop(key, None)
        if self.settled:
            return
        if not self.accepted:
            self.superseded = True
        elif self._latest is not None and self._shows(self._latest):
            # Every frame is a full status: the last one already showed the rest.
            self.matched = True
        else:
            return
        self._event.set()

    def stop(self) -> None:
        self.stopped = True
        self._event.set()

    async def wait(self, timeout: float) -> None:
        """Return once matched, superseded, mismatched, stopped or after the timeout."""
        if self.settled or self.mismatched or self.stopped:
            return
        self._event.clear()
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                await self._event.wait()


@dataclass(slots=True, eq=False)
class _Write:
    """One call of ``write()``, from the call until it returns."""

    asked: dict[str, int]  # as validated; for the result and the errors
    # What is still this call's to send and to see confirmed. It shrinks
    # when a newer call asks another value for one of the keys.
    desired: dict[str, int]
    waiter: _FrameWaiter
    attempts: int = 0
    already_current: bool = False

    @property
    def switches_off(self) -> bool:
        """Return True for a write of the power key to 0 and nothing else."""
        return self.desired == {POWER_KEY: 0}

    def yield_to(self, newer: Mapping[str, int]) -> None:
        """Give up every key for which a newer call asks another value.

        Report 6.4 item 6: per key the last value wins. Without this an
        unconfirmed write would be sent again seconds after the user chose
        something else, and put the device back.
        """
        taken = [key for key, value in newer.items() if key in self.desired and self.desired[key] != value]
        if POWER_KEY in taken:
            # The settings in this call went with the power state it asked for.
            taken = list(self.desired)
        if not taken:
            return
        for key in taken:
            del self.desired[key]
        self.waiter.forget(taken)


@dataclass(slots=True)
class _Counters:
    probes_sent: int = 0
    probes_missed: int = 0
    frames_received: int = 0
    registrations_sent: int = 0
    refreshes_sent: int = 0
    escalations: int = 0
    device_restarts: int = 0
    commands_sent: int = 0
    commands_refused: int = 0
    commands_unanswered: int = 0
    commands_unconfirmed: int = 0
    commands_blocked_off: int = 0
    commands_superseded: int = 0
    switch_offs_assumed: int = 0
    standby_presumptions: int = 0
    sync_malformed: int = 0
    socket_recreations: int = 0
    socket_errors: int = 0
    identity_mismatches: int = 0


def _decode_status(msg: Message) -> dict[str, Any]:
    """Strictly decode a status message into its ``reported`` object."""
    if code_class(msg.code) != 2:
        raise _FrameError(f"code_{code_text(msg.code)}", missed_change=True)
    block = msg.block2
    if block is not None and (block[0] > 0 or block[1]):
        # Part of a block-wise transfer, which nothing here reassembles.
        raise _FrameError("blockwise", missed_change=True)
    if not msg.payload:
        raise _FrameError("no_payload", missed_change=True)
    try:
        text = msg.payload.decode("ascii")
    except UnicodeDecodeError:
        raise _FrameError("not_ascii", missed_change=True) from None
    try:
        _counter, plain = crypto.decrypt(text)
    except crypto.EnvelopeError as err:
        raise _FrameError(err.reason, missed_change=True) from None
    try:
        document = json.loads(plain)
    except ValueError:
        raise _FrameError("bad_json", missed_change=True) from None
    state = document.get("state") if isinstance(document, dict) else None
    reported = state.get("reported") if isinstance(state, dict) else None
    if not isinstance(reported, dict) or not reported:
        raise _FrameError("bad_shape", missed_change=True)
    return reported


class _OtherDeviceError(Exception):
    """A readable info answer that cannot come from one of these purifiers."""


def _parse_identity(msg: Message) -> Identity | None:
    """Read an info answer; None when it cannot be read at all.

    Raises _OtherDeviceError for a JSON object without the ids: that is a
    well-formed answer from something else. Anything unreadable is no
    verdict, because the purifier itself sends a damaged answer now and then.
    """
    if code_class(msg.code) != 2:
        return None
    try:
        data = json.loads(msg.payload.decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    device_id = data.get("device_id")
    product_id = data.get("product_id")
    # Report 6.5: an answer without both ids is not one of these purifiers.
    # Measured: a television on the same network answers on this port too.
    if not isinstance(device_id, str) or not device_id or not isinstance(product_id, str) or not product_id:
        raise _OtherDeviceError

    def text(key: str) -> str:
        value = data.get(key)
        return value if isinstance(value, str) else ""

    return Identity(
        device_id=device_id, product_id=product_id, model_id=text("modelid"), type=text("type"), name=text("name")
    )


class Session:
    """One purifier: its status stream, its reachability and its commands."""

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_PORT,
        options: SessionOptions | None = None,
        expected_device_id: str | None = None,
        restored: RestoredState | None = None,
        trace: TraceCallback | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._options = options if options is not None else SessionOptions()
        self._expected_id = expected_device_id
        self._transport = Transport(
            host, port, on_contact=self._handle_contact, on_error=self._handle_socket_error, trace=trace
        )

        self._state = SessionState.OFFLINE
        self._status: dict[str, Any] | None = None
        self._status_is_live = False
        self._last_frame_wall: float | None = None
        self._last_frame_mono: float | None = None
        self._keys: set[str] = set()
        self._firmware: str | None = None
        self._wifi_firmware: str | None = None
        if restored is not None:
            self._status = dict(restored.status) if restored.status is not None else None
            self._last_frame_wall = restored.received_at
            self._keys = set(restored.keys) | set(self._status or ())
            self._firmware = restored.firmware
            self._wifi_firmware = restored.wifi_firmware
        self._identity: Identity | None = None
        self._identity_mismatch = False
        self._identity_asked = 0.0  # when the info resource was last asked

        # Presumed standby (see _expect_first_frame). A registration left a
        # newly opened socket and the device has not answered anything yet:
        self._first_frame_expected = False
        # it has, and this runs out when no frame follows:
        self._standby_timer: asyncio.TimerHandle | None = None
        self._presumed_standby = False

        self._listeners: list[Callable[[], None]] = []
        self._notify_scheduled = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._identity_task: asyncio.Task[None] | None = None
        self._started = False
        self._started_wall: float | None = None
        self._stopped = False
        self._stop_done: asyncio.Event | None = None
        self._socket_lock = asyncio.Lock()
        self._socket_dirty = False
        self._socket_opened = False
        # One lock around sync-then-control: a second sync in between would
        # invalidate the counter the control message was encrypted with.
        self._exchange_lock = asyncio.Lock()
        # Every write() between its call and its return, oldest first.
        self._writes: list[_Write] = []
        # Set whenever the power state or the list of writes may have changed.
        self._power_wake = asyncio.Event()

        self._contacts = 0
        self._last_contact_mono: float | None = None
        self._last_contact_wall: float | None = None
        self._misses = 0
        self._missed_kinds: set[_ProbeKind] = set()
        self._last_probe = 0.0
        self._offline_attempt = 0
        self._next_offline_probe = 0.0
        self._loss_logged = False

        self._observations: list[_Observation] = []
        self._last_registration: float | None = None
        self._refresh_pending = False
        # The next extra registration takes a new token: a change was missed.
        self._refresh_afresh = False
        self._refresh_wake = asyncio.Event()
        self._ladder = 0
        self._working_mode: RefreshMode | None = None
        self._last_runtime: int | None = None
        self._last_runtime_mono = 0.0
        self._waiters: list[_FrameWaiter] = []

        self._counters = _Counters()
        self._dropped: dict[str, int] = {}

    # -- what the session knows --------------------------------------------

    @property
    def host(self) -> str:
        """Return the configured host."""
        return self._host

    @property
    def port(self) -> int:
        """Return the configured UDP port."""
        return self._port

    @property
    def options(self) -> SessionOptions:
        """Return the options of this session."""
        return self._options

    @property
    def state(self) -> SessionState:
        """Return the current state."""
        return self._state

    @property
    def available(self) -> bool:
        """Return False only when the device is OFFLINE."""
        return self._state is not SessionState.OFFLINE

    @property
    def status(self) -> dict[str, Any] | None:
        """Return the last known full status; do not modify it.

        This is the restored status until the first live frame arrives. It
        is what the device last sent, with one exception: while the device
        is presumed to be in standby the power key reads 0 (see
        ``presumed_standby``).
        """
        return self._status

    @property
    def status_is_live(self) -> bool:
        """Return True once a frame was received in this session."""
        return self._status_is_live

    @property
    def presumed_standby(self) -> bool:
        """Return True while the device is taken to be off without a frame that says so.

        A device in standby sends nothing, so two things stand in for the
        frame it cannot send. It is reachable and left a registration from a
        newly opened socket without any frame for ``standby_presume_after``,
        where a device that is on answers within 2 s (measured six times out
        of six). Or it answered "success" to a switch-off and stayed silent
        (``WriteResult.assumed_off``).

        While this holds, a status that exists reads power 0, a setting is
        refused unsent with DeviceOffError, switching on is sent as always
        and switching off returns on the device's answer. Any status frame
        ends it and brings the truth: a device that was on after all (its
        answer was lost) reports within seconds while it runs.
        """
        return self._presumed_standby

    @property
    def last_frame_at(self) -> float | None:
        """Return the wall-clock time of the last status frame (epoch seconds)."""
        return self._last_frame_wall

    @property
    def identity(self) -> Identity | None:
        """Return the last answer of the info resource, if it was a purifier's.

        None before the first answer, and again after an answer that cannot
        come from one of these purifiers.
        """
        return self._identity

    @property
    def identity_mismatch(self) -> bool:
        """Return True while another device answers at this address.

        Set when a status frame or the info resource shows a device id other
        than the expected one, or when the info resource is answered without
        any id (measured: a television does that on this port). Cleared when
        the expected id is seen again. An info request that stays unanswered
        changes nothing.

        While the flag is up the session leaves that device alone: it sends
        no registration and no sync, because the device may be a purifier
        that another session serves, and the newest registration and the
        latest sync would take its status stream and its counter away
        (measurement 9). It probes with the ping only and asks the info
        resource again every ``probe_idle``, and registers again as soon as
        the expected device answers. It does not block commands; the caller
        decides what to do (report 6.3: show a repair issue). ``available``
        then only says that something answers at the address.
        """
        return self._identity_mismatch

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Call back after every status change and every state change.

        Changes made while one datagram is handled arrive as one call. Returns
        a function that removes the listener.
        """
        self._listeners.append(callback)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(callback)

        return remove

    def snapshot(self) -> RestoredState:
        """Return what to persist so that a restart can begin with it."""
        return RestoredState(
            status=dict(self._status) if self._status is not None else None,
            received_at=self._last_frame_wall,
            keys=frozenset(self._keys),
            firmware=self._firmware,
            wifi_firmware=self._wifi_firmware,
        )

    def diagnostics(self) -> Diagnostics:
        """Return the counters and timestamps of this session."""
        now = time.monotonic()
        since_frame: float | None = None
        if self._last_frame_mono is not None:
            since_frame = now - self._last_frame_mono
        elif self._last_frame_wall is not None:
            since_frame = max(0.0, time.time() - self._last_frame_wall)
        counters = self._counters
        wire = self._transport.counters
        return Diagnostics(
            state=self._state.value,
            status_is_live=self._status_is_live,
            identity_mismatch=self._identity_mismatch,
            started_at=self._started_wall,
            last_frame_at=self._last_frame_wall,
            last_contact_at=self._last_contact_wall,
            seconds_since_last_frame=since_frame,
            seconds_since_last_contact=None if self._last_contact_mono is None else now - self._last_contact_mono,
            probes_sent=counters.probes_sent,
            probes_missed=counters.probes_missed,
            consecutive_missed_probes=self._misses,
            frames_received=counters.frames_received,
            frames_dropped=dict(self._dropped),
            registrations_sent=counters.registrations_sent,
            refreshes_sent=counters.refreshes_sent,
            refresh_mode=(self._observations[-1].mode if self._observations else RefreshMode.SAME_TOKEN).value,
            working_refresh_mode=None if self._working_mode is None else self._working_mode.value,
            escalations=counters.escalations,
            device_restarts=counters.device_restarts,
            commands_sent=counters.commands_sent,
            commands_refused=counters.commands_refused,
            commands_unanswered=counters.commands_unanswered,
            commands_unconfirmed=counters.commands_unconfirmed,
            commands_blocked_off=counters.commands_blocked_off,
            commands_superseded=counters.commands_superseded,
            switch_offs_assumed=counters.switch_offs_assumed,
            presumed_standby=self._presumed_standby,
            standby_presumptions=counters.standby_presumptions,
            sync_malformed=counters.sync_malformed,
            socket_recreations=counters.socket_recreations,
            socket_errors=counters.socket_errors,
            identity_mismatches=counters.identity_mismatches,
            datagrams_sent=wire.sent,
            datagrams_received=wire.received,
            foreign_datagrams=wire.foreign,
            malformed_datagrams=wire.malformed,
            unknown_token_resets=wire.unknown_token,
        )

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Register for status and start supervising; never waits for the device.

        The state is OFFLINE until the device answers anything, which a
        reachable device does within a fraction of a second. A device that
        is on then sends its status within about 2 s (measurement 8); one
        in standby sends nothing until something changes, and is presumed
        to be in standby after ``standby_presume_after``.
        """
        if self._stopped:
            raise SessionStoppedError("a stopped session cannot be started again")
        if self._started:
            return
        self._started = True
        self._started_wall = time.time()
        try:
            opened = await self._ensure_socket()
        except SessionStoppedError:
            return  # stop() won the race
        except BaseException:
            # Cancelled half-way: leave a session that can be started again.
            self._started = False
            raise
        if self._stopped:
            return  # stop() ran while no socket could be opened; it left nothing to supervise
        if opened and not self._observations:
            # Rule 5: the registration always goes out, whether or not any
            # probe gets an answer. A socket opened here has sent it already;
            # one that identify() opened earlier has not, and to the device
            # it is as new: nothing was registered from it.
            self._observe_from_new_endpoint(new_socket=True)
        self._spawn(self._run_forever("liveness", self._liveness_step))
        self._spawn(self._run_forever("refresh", self._refresh_step))

    async def stop(self) -> None:
        """Deregister, cancel every task and close the socket; idempotent.

        The AC3220/10 ignores the deregistration (measurement 10) and keeps
        sending to the last observer until another one registers, which is
        harmless. It is sent for firmware that does listen.
        """
        if self._stop_done is not None:
            await self._stop_done.wait()
            return
        self._stop_done = asyncio.Event()
        self._stopped = True
        try:
            self._forget_first_frame()
            for waiter in self._waiters:
                waiter.stop()
            self._power_wake.set()
            while tasks := [task for task in self._tasks if task is not asyncio.current_task()]:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            # The lock is only ever held for the bounded time of opening a socket.
            async with self._socket_lock:
                # Best effort: nothing is awaited.
                for observation in self._observations:
                    self._send_deregistration(observation)
        finally:
            # Also when this call itself is cancelled.
            self._transport.close()
            self._state = SessionState.OFFLINE
            self._stop_done.set()

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run_forever(self, name: str, step: Callable[[], Coroutine[Any, Any, None]]) -> None:
        while not self._stopped:
            try:
                await step()
            except SessionStoppedError:
                return
            except Exception:
                _LOGGER.exception("%s: the %s loop failed and continues", self._host, name)
                await asyncio.sleep(self._options.error_pause)
            # A step that returns without waiting must not starve the loop.
            await asyncio.sleep(0)

    async def _run_once(self, name: str, work: Callable[[], Coroutine[Any, Any, object]]) -> None:
        # The coroutine is made here, inside the task: one handed in from
        # outside would never be awaited when stop() cancels the task before
        # its first step, and Python warns about that.
        try:
            await work()
        except SessionStoppedError:
            return
        except Exception:
            _LOGGER.exception("%s: %s failed", self._host, name)

    def _check_running(self) -> None:
        if self._stopped or not self._started:
            raise SessionStoppedError("the session is not running")

    # -- socket ------------------------------------------------------------

    async def _ensure_socket(self) -> bool:
        """Open the socket, or replace it after a local error (rule 4).

        Returns False when there is no socket for now.
        """
        async with self._socket_lock:
            if self._stopped:
                raise SessionStoppedError("the session is stopped")
            if self._transport.is_open and not self._socket_dirty:
                return True
            self._transport.close()
            self._socket_dirty = False
            try:
                async with asyncio.timeout(self._options.socket_timeout):
                    await self._transport.open()
            except (OSError, TimeoutError) as err:
                self._counters.socket_errors += 1
                _LOGGER.debug("%s: cannot open a socket: %r", self._host, err)
                return False
            if self._stopped:
                self._transport.close()
                raise SessionStoppedError("the session is stopped")
            if self._socket_opened:
                self._counters.socket_recreations += 1
            self._socket_opened = True
            if self._started:
                self._observe_from_new_endpoint(new_socket=True)
            return True

    def _handle_socket_error(self, exc: Exception) -> None:
        # The socket is replaced by the next liveness step or write attempt.
        self._counters.socket_errors += 1
        self._socket_dirty = True
        _LOGGER.debug("%s: socket error: %r", self._host, exc)

    def _send(self, msg: Message) -> bool:
        try:
            self._transport.send(msg)
        except TransportError:
            self._socket_dirty = True
            return False
        return True

    async def _request(self, code: int, path: str, payload: bytes, timeout: float) -> Message | None:
        """Send one request; None means no answer, a Reset or no socket."""
        msg = build_request(
            MType.NON, code, self._transport.next_mid(), self._transport.new_token(), path, payload=payload
        )
        try:
            reply = await self._transport.request(msg, timeout)
        except TransportError:
            self._socket_dirty = True
            return None
        if reply is None or reply.mtype is MType.RST:
            return None
        return reply

    # -- listeners ---------------------------------------------------------

    def _schedule_notify(self) -> None:
        if self._notify_scheduled or self._stopped:
            return
        self._notify_scheduled = True
        asyncio.get_running_loop().call_soon(self._notify_listeners)

    def _notify_listeners(self) -> None:
        self._notify_scheduled = False
        if self._stopped:
            return
        for callback in tuple(self._listeners):
            try:
                callback()
            except Exception:
                _LOGGER.exception("%s: a listener failed", self._host)

    def _set_state(self, state: SessionState) -> None:
        if state is self._state:
            return
        _LOGGER.debug("%s: %s -> %s", self._host, self._state.value, state.value)
        self._state = state
        self._schedule_notify()

    # -- contact and liveness (rules 1 to 4) -------------------------------

    def _handle_contact(self) -> None:
        """Rule 1: any well-formed datagram from the device address."""
        if self._stopped:
            return
        self._contacts += 1
        self._last_contact_mono = time.monotonic()
        self._last_contact_wall = time.time()
        after_misses = self._misses > 0
        self._misses = 0
        self._missed_kinds.clear()
        if self._first_frame_expected:
            # Reachable. From here on a device that is on has the time to
            # answer the registration; see _expect_first_frame.
            self._first_frame_expected = False
            self._standby_timer = asyncio.get_running_loop().call_later(
                self._options.standby_presume_after, self._presume_standby
            )
        if not self._started or self._state not in (SessionState.OFFLINE, SessionState.SUSPECT):
            return
        self._offline_attempt = 0
        if self._loss_logged:
            self._loss_logged = False
            _LOGGER.info("%s: the device answers again", self._host)
        # Rule 4: the cached status is kept, however old it is.
        self._set_state(SessionState.LIVE if self._status_is_live else SessionState.REACHABLE)
        # After missed probes the observer may be gone and changes may have
        # been missed, so register at once, and with a new token: if the
        # device still holds the old one it would not answer that
        # (measurement 8). The first contact after start() follows its
        # registration within milliseconds; that one may wait for the usual
        # gap and keeps its token.
        self._request_refresh(force=after_misses, afresh=after_misses)
        self._start_identity_check()

    async def _liveness_step(self) -> None:
        opts = self._options
        await self._ensure_socket()
        now = time.monotonic()
        if self._state is SessionState.OFFLINE:
            due = self._next_offline_probe
        elif self._state is SessionState.SUSPECT:
            due = self._last_probe + opts.probe_retry
        else:
            due = (self._last_contact_mono if self._last_contact_mono is not None else now) + opts.probe_idle
        if self._identity_mismatch and self._state is not SessionState.OFFLINE:
            # Another device answers here. Only the info resource can tell
            # when the expected one is back, because nothing is registered
            # there (see identity_mismatch): ask it every probe interval,
            # also while frames of the other device keep the probes away.
            ask = self._identity_asked + opts.probe_idle
            if ask <= now:
                self._start_identity_check()
                ask = now + opts.probe_idle
            due = min(due, ask) if due > now else due
        if due > now:
            await asyncio.sleep(due - now)
            return
        await self._probe_round()

    async def _probe_round(self) -> None:
        opts = self._options
        was_offline = self._state is SessionState.OFFLINE
        if was_offline and self._offline_attempt:
            # Not on the first attempt: the socket was opened just before
            # it, and that looked the name up.
            await self._follow_host_name()
        self._last_probe = time.monotonic()
        if await self._probe(_ProbeKind.PING):
            return
        if self._state in (SessionState.LIVE, SessionState.REACHABLE):
            self._set_state(SessionState.SUSPECT)
        if not was_offline and self._misses < opts.offline_min_misses:
            return
        # The ping keeps failing: ask in the other way before believing it.
        # Not a device that is not ours: a sync would take the counter away
        # from the session that does serve it (measurement 9).
        kinds = {_ProbeKind.PING} if self._identity_mismatch else set(_ProbeKind)
        if _ProbeKind.SYNC in kinds and await self._probe(_ProbeKind.SYNC):
            return
        now = time.monotonic()
        if not was_offline:
            silence = math.inf if self._last_contact_mono is None else now - self._last_contact_mono
            if (
                self._misses < opts.offline_min_misses
                or silence < opts.offline_min_silence
                or not self._missed_kinds >= kinds
            ):
                return
            self._set_state(SessionState.OFFLINE)
            self._offline_attempt = 0
            # Rule 4: a fresh socket, in case the fault is on this side.
            self._socket_dirty = True
        if not self._loss_logged:
            self._loss_logged = True
            _LOGGER.info("%s: the device does not answer", self._host)
        backoff = opts.offline_backoff
        self._next_offline_probe = now + backoff[min(self._offline_attempt, len(backoff) - 1)]
        self._offline_attempt += 1

    async def _follow_host_name(self) -> None:
        """Look the host name up again while OFFLINE; an address is left alone.

        The socket is replaced once, on entering OFFLINE, and that is often
        too early: the router that caused the outage is still coming back
        and hands the device another address afterwards.
        """
        try:
            async with self._socket_lock, asyncio.timeout(self._options.socket_timeout):
                if self._stopped:
                    raise SessionStoppedError("the session is stopped")
                if not self._transport.is_open:
                    return  # opening the socket resolves the name anyway
                moved = await self._transport.resolve_again()
        except (OSError, TimeoutError) as err:
            _LOGGER.debug("%s: cannot resolve the name: %r", self._host, err)
            return
        if moved:
            _LOGGER.info("%s: the name leads to another address now", self._host)
            # To the device at that address this is an endpoint it never saw.
            self._observe_from_new_endpoint()

    async def _probe(self, kind: _ProbeKind) -> bool:
        """Send one probe; True when the device made contact in its window."""
        opts = self._options
        contacts = self._contacts
        self._counters.probes_sent += 1
        try:
            if kind is _ProbeKind.PING:
                await self._transport.ping(opts.probe_timeout)
            else:
                async with asyncio.timeout(opts.probe_timeout), self._exchange_lock:
                    await self._sync(opts.probe_timeout)
        except TimeoutError:
            pass
        except TransportError:
            self._socket_dirty = True
        # Any datagram counts, also a frame that arrived instead of the answer.
        if self._contacts != contacts:
            return True
        self._counters.probes_missed += 1
        self._misses += 1
        self._missed_kinds.add(kind)
        return False

    # -- identity (rule 8) -------------------------------------------------

    async def identify(self) -> Identity | None:
        """Read the plaintext info resource; None when it does not answer.

        Works without ``start()``: the request neither registers an observer
        nor touches the counter, so it is safe towards a device that another
        session already serves (report 6.5). It opens the socket, so call
        ``stop()`` afterwards in that case too; a ``start()`` that follows
        uses that socket and registers on it.

        With an expected device id, an answer from something else raises
        ``identity_mismatch``: another id, or no id at all. No answer, or one
        that cannot be read, changes nothing.
        """
        if self._stopped:
            raise SessionStoppedError("the session is stopped")
        opts = self._options
        for _ in range(opts.info_attempts):
            if not await self._ensure_socket():
                return None
            reply = await self._request(GET, INFO_PATH, b"", opts.info_timeout)
            if reply is None:
                continue
            try:
                identity = _parse_identity(reply)
            except _OtherDeviceError:
                # Something else has this address now. That is an answer, not
                # a missing one: asking again would not change it.
                self._identity = None
                self._judge_device_id(None)
                return None
            if identity is None:
                continue
            self._identity = identity
            was_another = self._identity_mismatch
            if self._judge_device_id(identity.device_id) and was_another:
                # Nothing was registered while the other device answered.
                # With a new token, so that a device that is on may answer.
                self._request_refresh(force=True, afresh=True)
            return identity
        return None

    def _start_identity_check(self) -> None:
        if self._expected_id is None or self._identity_task is not None:
            return
        self._identity_asked = time.monotonic()
        task = self._spawn(self._run_once("the identity check", self.identify))
        self._identity_task = task
        task.add_done_callback(self._identity_checked)

    def _identity_checked(self, task: asyncio.Task[None]) -> None:
        if self._identity_task is task:
            self._identity_task = None

    def _judge_device_id(self, device_id: str | None) -> bool:
        """Compare with the expected device; returns False on a mismatch.

        None stands for an answer that carries no device id at all.
        """
        if self._expected_id is None:
            return True
        if device_id is not None and device_id.casefold() == self._expected_id.casefold():
            if self._identity_mismatch:
                self._identity_mismatch = False
                _LOGGER.info("%s: the expected device answers again", self._host)
                self._schedule_notify()
            return True
        self._counters.identity_mismatches += 1
        if not self._identity_mismatch:
            self._identity_mismatch = True
            # Whatever that device does says nothing about ours.
            self._forget_first_frame()
            _LOGGER.warning("%s: another device answers at this address", self._host)
            self._schedule_notify()
        return False

    # -- observation (rules 5 and 6) ---------------------------------------

    def _observe_from_new_endpoint(self, *, new_socket: bool = False) -> None:
        """Start over with a fresh token, on a new socket or towards a new address.

        The token is fixed for as long as the socket lives (rule 5). A new
        socket is a new endpoint to the device, and a new token makes its
        registration exactly the kind that was measured to take the stream
        over and to be answered (measurements 8 and 9). The same token from
        another port was never tried.

        Only with ``new_socket`` is the registration the measured kind for
        certain. A name that leads to another address may lead to the same
        device, which then still knows this port.
        """
        for observation in self._observations:
            self._transport.remove_stream(observation.token)
        self._observations = []
        self._ladder = 0
        self._forget_first_frame()
        self._register_new_token(RefreshMode.SAME_TOKEN)
        if new_socket and self._observations[-1].registrations:
            self._expect_first_frame()

    # -- presumed standby --------------------------------------------------

    def _expect_first_frame(self) -> None:
        """Watch what the device does with a registration from a newly opened socket.

        Measured (docs/metingen.md, "Eerste statusbericht na een nieuw
        abonnement"): a device that is on answers such a registration with
        a status frame after 0.2 to 1.9 s, six times out of six, and while
        it runs it reports every few seconds anyway (measurement 12). One in
        standby answers every probe and sends no frame at all. So a device
        that demonstrably answers something and then lets
        ``standby_presume_after`` pass without a frame is in standby.

        The time runs from the first answer, not from the registration. The
        registration may have left while the device was away (a socket
        replaced on entering OFFLINE); the one that follows its return (see
        _handle_contact) is then the first it gets from this port. At a
        start a second registration follows after ``refresh_min_gap``, for
        when the first one was lost.

        Nothing is concluded from a registration with a new token on a
        socket in use: the AC3220/10 does not answer that one, on or off
        (measurement 13).
        """
        self._first_frame_expected = True

    def _forget_first_frame(self) -> None:
        """Stop watching for the answer to a registration; no verdict follows."""
        self._first_frame_expected = False
        if self._standby_timer is not None:
            self._standby_timer.cancel()
            self._standby_timer = None
            self._power_wake.set()

    def _presume_standby(self) -> None:
        """The time for a frame is up: a reachable device that sent none is in standby."""
        self._standby_timer = None
        self._power_wake.set()
        if self._stopped or self._misses or self._identity_mismatch:
            # No verdict about a device that stopped answering meanwhile,
            # or that is not ours.
            return
        self._counters.standby_presumptions += 1
        _LOGGER.debug("%s: reachable and no status frame after a new registration; presuming standby", self._host)
        self._take_for_off()

    def _take_for_off(self) -> None:
        """Record that the device is off although no frame said so (see ``presumed_standby``)."""
        status = self._status
        if status is not None and status.get(POWER_KEY) != 0:
            self._status = {**status, POWER_KEY: 0}
        elif self._presumed_standby:
            return  # nothing new to tell
        self._presumed_standby = True
        self._power_wake.set()
        self._schedule_notify()

    def _known_power(self) -> Any:
        """Return the power state the session goes by; None when it has none."""
        if self._status is not None:
            return self._status.get(POWER_KEY)
        return 0 if self._presumed_standby else None

    # -- registrations -----------------------------------------------------

    def _send_registration(self) -> None:
        """Send the registration for the newest token; no answer is expected.

        In standby a registration is answered only by the next change, and a
        repeated one is not answered at all (measurements 2 and 8), so
        waiting for an answer would be the mistake that makes the existing
        integrations flap.
        """
        if not self._observations and self._started and self._transport.is_open:
            # A socket without an observation: make the first one, which
            # comes back here to send it.
            self._observe_from_new_endpoint()
            return
        # Without a socket there is no observation yet; opening one registers.
        # Nothing is registered at a device that is not ours: it would take
        # the stream away from the session that serves it (measurement 9).
        if self._observations and not self._identity_mismatch:
            observation = self._observations[-1]
            msg = build_request(MType.NON, GET, self._transport.next_mid(), observation.token, STATUS_PATH, observe=0)
            if self._send(msg):
                self._counters.registrations_sent += 1
                if observation.registrations:
                    self._counters.refreshes_sent += 1
                observation.registrations += 1
        self._last_registration = time.monotonic()
        self._refresh_pending = False
        self._refresh_afresh = False

    def _register_afresh(self) -> None:
        """Register with a new token, to be sent the status if the device is on.

        A repeated registration with the same token gets no answer while the
        device still holds it (measurement 8). A new token takes the stream
        over at once (measured). The AC3220/10 does not answer it from the
        same port (measurement 13), so nothing is gained there but the
        stream; firmware that does answer sends the status at once. In
        standby nothing answers.

        Not a step on the ladder of rule 6: the label stays.
        """
        if self._observations:
            self._register_new_token(self._observations[-1].mode)
        else:
            self._send_registration()

    def _send_deregistration(self, observation: _Observation) -> None:
        if self._identity_mismatch:
            return  # not our device; some firmware takes this for a registration
        self._send(build_request(MType.NON, GET, self._transport.next_mid(), observation.token, STATUS_PATH, observe=1))

    def _request_refresh(self, *, force: bool = False, afresh: bool = False) -> None:
        """Ask for an extra registration (rule 5).

        Unless forced it keeps ``refresh_min_gap`` to the previous one; the
        refresh loop then sends it as soon as the gap has passed. With
        ``afresh`` it takes a new token: a change is known to be missed, and
        that is the registration a running device may answer.
        """
        if not self._started or self._stopped:
            return
        self._refresh_afresh = self._refresh_afresh or afresh
        last = self._last_registration
        if force or last is None or time.monotonic() - last >= self._options.refresh_min_gap:
            self._send_refresh()
        else:
            self._refresh_pending = True
            self._refresh_wake.set()

    def _send_refresh(self) -> None:
        if self._refresh_afresh:
            self._register_afresh()
        else:
            self._send_registration()

    async def _refresh_step(self) -> None:
        opts = self._options
        now = time.monotonic()
        wait = opts.refresh_min_gap if self._refresh_pending else opts.refresh_interval
        due = now if self._last_registration is None else self._last_registration + wait
        if due <= now:
            # Rule 5: mandatory, also when everything looks fine. It is the
            # only repair after a short device restart or an evicted observer.
            # The periodic one keeps its token; only a missed change asks
            # for a new one.
            self._send_refresh()
            return
        self._refresh_wake.clear()
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(due - now):
                await self._refresh_wake.wait()

    def _register_new_token(self, mode: RefreshMode) -> None:
        observation = _Observation(self._transport.new_token(), mode, time.monotonic())
        self._observations.append(observation)
        self._transport.add_stream(observation.token, functools.partial(self._handle_stream, observation))
        while len(self._observations) > _MAX_OBSERVATIONS:
            self._retire(self._observations.pop(0))
        self._send_registration()

    def _retire(self, observation: _Observation) -> None:
        """Give up a token; the caller registers the newest one right after.

        The AC3220/10 does not honour a deregistration (measurement 10), and
        what it does with one instead is not known. Because the newest
        registration wins there, the registration that follows settles it.
        """
        self._send_deregistration(observation)
        # From here on the transport answers this token with a Reset.
        self._transport.remove_stream(observation.token)

    def _escalate(self) -> None:
        """Rule 6: an accepted command had no visible effect at all.

        The same-token refresh was already tried while the command waited,
        so the first step here is a new token, and the next a fresh sync
        followed by another new token. On the AC3220/10 a new token replaces
        the old observer at once (measurement 8).
        """
        self._counters.escalations += 1
        self._ladder = min(self._ladder + 1, 2)
        if self._ladder == 1:
            self._register_new_token(RefreshMode.NEW_TOKEN)
        else:
            self._spawn(self._run_once("the resync", self._resync_and_register))

    async def _resync_and_register(self) -> None:
        opts = self._options
        try:
            async with asyncio.timeout(opts.write_budget), self._exchange_lock:
                await self._sync(opts.sync_timeout)
                # Still inside the lock, so that no other sync comes between.
                self._register_new_token(RefreshMode.RESYNC)
        except TimeoutError:
            # Commands kept the lock busy; the registration goes out anyway.
            self._register_new_token(RefreshMode.RESYNC)

    def _mark_delivered(self, observation: _Observation, now: float) -> None:
        observation.last_frame = now
        newest = self._observations[-1]
        if observation is newest:
            self._ladder = 0
            older = self._observations[:-1]
            if older:
                # The new token delivers, so the old ones can go. If an old
                # one delivered after the new one was made, the stream never
                # was dead and the new token did not repair anything.
                alive = [o for o in older if o.last_frame is not None and o.last_frame >= newest.created]
                if alive:
                    newest.mode = alive[-1].mode
                for old in older:
                    self._retire(old)
                self._observations = [newest]
                self._send_registration()
        self._working_mode = observation.mode

    # -- status frames (rules 2, 7 and 8) ----------------------------------

    def _handle_stream(self, observation: _Observation, msg: Message) -> None:
        if self._stopped:
            return
        try:
            reported = _decode_status(msg)
            self._check_frame(reported)
        except _FrameError as err:
            self._dropped[err.reason] = self._dropped.get(err.reason, 0) + 1
            _LOGGER.debug("%s: status frame dropped: %s", self._host, err.reason)
            # Something was sent, so this is not the silence of standby.
            self._forget_first_frame()
            if err.missed_change:
                # The device holds this observer, so it would not answer the
                # same token again: ask with a new one.
                self._request_refresh(afresh=True)
            return
        self._accept_frame(observation, reported)

    def _check_frame(self, reported: dict[str, Any]) -> None:
        device_id = reported.get(DEVICE_ID_KEY)
        if isinstance(device_id, str) and not self._judge_device_id(device_id):
            raise _FrameError("identity_mismatch", missed_change=False)
        runtime = reported.get(RUNTIME_KEY)
        last = self._last_runtime
        window = self._options.runtime_stale_window_ms
        if (
            _is_int(runtime)
            and last is not None
            and 0 < last - runtime < window
            and (time.monotonic() - self._last_runtime_mono) * 1000 < window
        ):
            # Slightly older than what is already applied, and right behind
            # it: a reordered frame. Reordering cannot span more time than
            # the window; a lower uptime that arrives later is a restart
            # soon after the previous one, and that frame is the new truth.
            raise _FrameError("stale", missed_change=False)

    def _accept_frame(self, observation: _Observation, reported: dict[str, Any]) -> None:
        now = time.monotonic()
        runtime = reported.get(RUNTIME_KEY)
        restarted = False
        if _is_int(runtime):
            # A fall of the uptime that was not dropped as stale is a device
            # restart (rule 7).
            restarted = self._last_runtime is not None and runtime < self._last_runtime
            self._last_runtime = runtime
            self._last_runtime_mono = now
        self._status = reported
        self._status_is_live = True
        # A frame is the truth: it ends the watch and whatever was presumed.
        self._forget_first_frame()
        self._presumed_standby = False
        self._last_frame_mono = now
        self._last_frame_wall = time.time()
        self._keys.update(reported)
        firmware = reported.get(FIRMWARE_KEY)
        if isinstance(firmware, str):
            self._firmware = firmware
        wifi_firmware = reported.get(WIFI_FIRMWARE_KEY)
        if isinstance(wifi_firmware, str):
            self._wifi_firmware = wifi_firmware
        self._counters.frames_received += 1
        self._mark_delivered(observation, now)
        self._set_state(SessionState.LIVE)
        for waiter in tuple(self._waiters):
            waiter.offer(reported, now)
        self._power_wake.set()
        self._schedule_notify()
        if restarted:
            self._counters.device_restarts += 1
            self._request_refresh()

    async def request_status(self) -> bool:
        """Ask for a fresh status; True when a frame arrived in time.

        This registers again with a new token, which changes nothing on the
        device but the token it reports to. In standby nothing answers, so
        False is the normal result for a device that is off.

        Measured on the AC3220/10 (measurement 13): a new token from the
        port in use is not answered, on or off, so there this returns False
        whatever the device does, and nothing should be built on it. Only a
        registration from a new port is answered (0.2 to 2.1 s).
        """
        self._check_running()
        waiter = _FrameWaiter({})
        self._waiters.append(waiter)
        try:
            self._register_afresh()
            await waiter.wait(self._options.request_status_timeout)
            self._check_running()
            return waiter.matched
        finally:
            self._waiters.remove(waiter)

    # -- commands (report 6.4) ---------------------------------------------

    async def write(self, values: Mapping[str, int]) -> WriteResult:
        """Write values and wait until the device reports them.

        Raises DeviceOffError, RefusedError, UnreachableError or
        NotConfirmedError. An unconfirmed write takes about 11 s at the
        default timings: 5 s, a refresh, 3 s, one resend and 3 s more.

        Commands are serialised by the exchange lock, and several keys in one
        call travel in one message. Calls that overlap are not merged into
        one message (report 6.4 item 6), but its rule holds: per key the
        last value wins. A call gives up a key as soon as a newer call asks
        another value for it and sends nothing for that key from then on;
        with no key left it returns at once with ``superseded`` set.

        A setting waits while another call of this session switches the
        device on or off, and is then judged by what that call brought, so
        that a scene can switch on and set a mode with two calls at once.
        It also waits while a registration from a new socket is still open
        (see ``presumed_standby``), instead of being judged on a status
        from before. Both waits count towards the limit of the write.

        Switching off does not fail for want of a frame: a device that
        already is in standby answers "success" and sends nothing, and that
        answer is then taken for it (``WriteResult.assumed_off``).
        """
        self._check_running()
        write = self._issue(self._validated(values))
        waiter = write.waiter
        opts = self._options
        loop = asyncio.get_running_loop()
        started = loop.time()

        def done(
            *, already_current: bool = False, resent: bool = False, superseded: bool = False, assumed_off: bool = False
        ) -> WriteResult:
            if superseded:
                self._counters.commands_superseded += 1
            return WriteResult(
                write.asked,
                already_current,
                resent,
                write.attempts,
                loop.time() - started,
                superseded=superseded,
                assumed_off=assumed_off,
            )

        try:
            try:
                await self._hold_for_power(write, started + opts.write_budget)
                if write.desired:
                    # At once: a refusal does not have to wait for the lock.
                    self._judge(write)
                await self._exchange(write, started + opts.write_budget)
            except DeviceOffError:
                self._counters.commands_blocked_off += 1
                raise
            if waiter.superseded:
                return done(superseded=True)
            if write.already_current or waiter.matched:
                # Nothing changes on the device, so no frame has to follow;
                # or a frame showed the values before the answer was in.
                return done(already_current=write.already_current)
            frames_at_answer = waiter.frames
            # Frames in the settle window may predate the write (the Wi-Fi
            # module polls the main processor about once per second).
            waiter.mismatch_after = time.monotonic() + opts.confirm_settle
            await waiter.wait(opts.confirm_timeout)
            if not waiter.settled:
                self._check_running()
                if write.switches_off and not waiter.mismatched:
                    # Accepted, and then silence: what a device that already
                    # was in standby does. One that is on may answer a new
                    # registration, and from here on any frame is an answer:
                    # it says off, or it says that the device is still on.
                    waiter.mismatch_after = time.monotonic()
                    self._register_afresh()
                    await waiter.wait(opts.confirm_retry_wait)
                    if not waiter.settled and not waiter.mismatched:
                        self._check_running()
                        self._assume_off()
                        return done(assumed_off=True)
                else:
                    waiter.mismatch_after = None
                    waiter.mismatched = False
                    self._request_refresh(force=True)
                    await waiter.wait(opts.confirm_retry_wait)
            resent = False
            if not waiter.settled:
                self._check_running()
                waiter.mismatch_after = None
                waiter.mismatched = False
                resent = True
                try:
                    # What is left of it: nothing that a newer write took over.
                    await self._exchange(write, loop.time() + opts.write_budget)
                except WriteError as err:
                    _LOGGER.debug("%s: the resend failed: %s", self._host, err)
                await waiter.wait(opts.confirm_retry_wait)
            self._check_running()
            if waiter.matched:
                return done(resent=resent)
            if waiter.superseded:
                return done(resent=resent, superseded=True)
            self._counters.commands_unconfirmed += 1
            if waiter.frames == frames_at_answer:
                # Not one frame since the device said "success": the stream
                # itself is suspect. With frames arriving it is alive and the
                # device simply did not apply the values.
                self._escalate()
            raise NotConfirmedError("accepted but not confirmed", write.asked)
        finally:
            self._writes.remove(write)
            self._waiters.remove(waiter)
            self._power_wake.set()

    def _issue(self, desired: dict[str, int]) -> _Write:
        """Enter a call in the list of writes; older calls yield to it."""
        for older in self._writes:
            older.yield_to(desired)
        accepted = {key: accepted_readback(key, value) for key, value in desired.items()}
        # The waiter exists before anything is sent, so that no frame can slip by.
        write = _Write(dict(desired), desired, _FrameWaiter(accepted))
        self._writes.append(write)
        self._waiters.append(write.waiter)
        self._power_wake.set()
        return write

    def _power_in_transition(self, write: _Write) -> bool:
        """Return True while another call is changing the power state."""
        known = self._known_power()
        return any(other is not write and other.desired.get(POWER_KEY, known) != known for other in self._writes)

    async def _hold_for_power(self, write: _Write, deadline: float) -> None:
        """Hold a setting back while it is open whether the device is on.

        The device discards a setting it gets in standby and still answers
        "success" (measurement 5), and it reports a switch-on only after 0.2
        to 1.1 s. A setting that comes together with a switch-on is neither
        refused on the status from before nor sent ahead of that report: it
        waits for the outcome and is judged by it. The same goes for one
        that comes together with a switch-off.

        It is open as well while a reachable device has the time to answer
        a registration from a new socket (see _expect_first_frame): the
        status is then one from before, and within seconds a frame or the
        lack of one says what the device is now.

        The wait counts towards the limit of the write.
        """
        if POWER_KEY in write.desired:
            return
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout_at(deadline):
                # A write that a newer one took over has nothing to wait for.
                while write.desired and (self._power_in_transition(write) or self._standby_timer is not None):
                    self._power_wake.clear()
                    await self._power_wake.wait()
                    self._check_running()

    def _judge(self, write: _Write) -> bool:
        """Return True when the status already shows what this write asks for.

        Raises DeviceOffError when the known status says off and the write
        would be discarded: a setting written in standby is answered with
        "success" and not applied (measurement 5). A value that already
        holds comes first (report 6.4 item 3): asking for what is there is
        not an error, also not on a device that is off. That covers
        switching off a device that is off, which is never refused.
        """
        status = self._status
        desired = write.desired
        if status is None:
            if not self._presumed_standby:
                return False
            # Never a status, and presumed to be in standby: off is all
            # that is known. Only switching on can change anything.
            if write.switches_off:
                return True
            if desired.get(POWER_KEY) != 1:
                raise DeviceOffError("the device is off and would discard this", write.asked)
            return False
        accepted = write.waiter.accepted
        shown = all(status.get(key) in accepted[key] for key in desired)
        # Only a status of this session shows what the device has now. For a
        # switch-off the restored one will do: "success" means off whatever
        # the device was, and in standby no frame follows to wait for.
        if shown and (self._status_is_live or write.switches_off):
            return True
        if status.get(POWER_KEY) == 0 and desired.get(POWER_KEY) != 1:
            raise DeviceOffError("the device is off and would discard this", write.asked)
        return False

    def _assume_off(self) -> None:
        """Take a switch-off that was accepted and followed by silence for done.

        Measured (measurement 5, rows 6 and 7): "success" to a switch-off
        means off either way. A device that was on reports it within 0.1 s;
        one that already was in standby sends nothing, so no frame can ever
        confirm it. That is where a session stands whose status says on
        after the off-frame was lost, or after a power cut left the device
        in standby: without this every switch-off would fail and the status
        would go on saying on. If the device is on after all, its next frame
        says so. A session that never had a status keeps it as
        ``presumed_standby``.
        """
        self._counters.switch_offs_assumed += 1
        _LOGGER.debug("%s: switched off without a status frame; taking the answer for it", self._host)
        self._take_for_off()

    @staticmethod
    def _validated(values: Mapping[str, int]) -> dict[str, int]:
        if not values:
            raise ValueError("nothing to write")
        for key, value in values.items():
            if not isinstance(key, str) or not key or key in _RESERVED_KEYS:
                raise ValueError(f"not a writable key: {key!r}")
            if not _is_int(value):
                # Strings are ignored by the device, which may still answer
                # "success" (report 3.1, measured on a CX3120).
                raise TypeError(f"{key}: the device only takes integers, not {value!r}")
        # Power first, so that it comes before the settings that depend on it.
        ordered = {POWER_KEY: values[POWER_KEY]} if POWER_KEY in values else {}
        ordered.update(values)
        return ordered

    async def _exchange(self, write: _Write, deadline: float) -> None:
        """Sync, then control with counter plus one, for what is left of a write.

        Returns when the device answered "success", when a frame shows the
        values, or when a newer write left nothing to send. Raises
        DeviceOffError before anything is sent, and RefusedError or
        UnreachableError when the attempts are used up.

        Every attempt has its own sync and a newly encrypted payload, because
        each sync returns a fresh, unrelated counter (metingen.md,
        measurement 2). The deadline includes the wait for the lock.
        """
        opts = self._options
        waiter = write.waiter
        loop = asyncio.get_running_loop()
        refused = False
        judged = False
        try:
            async with asyncio.timeout_at(deadline), self._exchange_lock:
                for _ in range(opts.write_attempts):
                    self._check_running()
                    if waiter.superseded or loop.time() >= deadline:
                        break
                    if write.attempts and waiter.matched:
                        # The answer was lost and the echo was not. A frame
                        # that shows the values is the better proof anyway.
                        break
                    if not judged:
                        # With the lock in hand: the status of the moment of
                        # the call may be out of date after the wait for it.
                        current = self._judge(write)
                        judged = True
                        if not write.attempts:
                            write.already_current = current
                            self._counters.commands_sent += 1
                    write.attempts += 1
                    if not await self._ensure_socket():
                        continue
                    counter = await self._sync(opts.sync_timeout)
                    if counter is None:
                        continue
                    values = dict(write.desired)
                    if not values:
                        break  # a newer write took every key over during the sync
                    answer = await self._control(crypto.next_counter(counter), values, opts.control_timeout)
                    if answer == "success":
                        return
                    refused = refused or answer == "failed"
        except TimeoutError:
            pass
        self._check_running()
        if waiter.settled:
            return
        if refused:
            self._counters.commands_refused += 1
            raise RefusedError("the device refused the command", write.asked)
        self._counters.commands_unanswered += 1
        raise UnreachableError("no usable answer from the device", write.asked)

    async def _sync(self, timeout: float) -> str | None:
        """Run the handshake; None unless the reply is exactly 8 hex characters.

        A malformed reply is contact all the same, which the transport has
        already recorded (rule 1).
        """
        nonce = os.urandom(4).hex().upper().encode()
        reply = await self._request(POST, SYNC_PATH, nonce, timeout)
        if reply is None:
            return None
        text = reply.payload.decode("latin-1")
        if code_class(reply.code) != 2 or len(text) != 8 or not crypto.is_valid_counter(text):
            self._counters.sync_malformed += 1
            return None
        return text.upper()

    async def _control(self, counter: str, values: Mapping[str, int], timeout: float) -> str | None:
        """Send the write; returns "success", "failed" or None."""
        document = {"state": {"desired": {"CommandType": "app", "DeviceId": "", "EnduserId": "", **values}}}
        envelope = crypto.encrypt(counter, json.dumps(document))
        reply = await self._request(POST, CONTROL_PATH, envelope.encode(), timeout)
        if reply is None or code_class(reply.code) != 2:
            return None
        try:
            answer = json.loads(reply.payload.decode("utf-8", "replace"))
        except ValueError:
            return None
        result = answer.get("status") if isinstance(answer, dict) else None
        return result if result in ("success", "failed") else None
