"""The session with one purifier: observation, liveness, recovery, commands.

This is the state machine of report 6.3 and 6.4 (docs/onderzoek.md), with
the adjustments that the measurements on a real AC3220/10 asked for
(docs/metingen.md). The two ideas everything else follows from:

* Silence is never a fault. The device reports on change only and says
  nothing at all in standby, so reachability is measured with probes of its
  own and nothing is torn down because the status stream is quiet.
* "success" is not proof. The device acknowledges writes it discards, so a
  command counts only once a status frame shows its effect.

What the device was measured to do with observers (measurements 8 to 10):
it serves one observer per source address and the newest registration wins;
it answers a new registration with a status frame within about 2 s while it
is on, never in standby, and it does not answer a repeated registration with
the same token; it ignores a deregistration and a Reset.
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
from collections.abc import Callable, Coroutine, Mapping
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

_LOGGER = logging.getLogger("airlink")

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
        self.accepted = accepted
        self.frames = 0  # valid frames seen since creation
        self.matched = False
        self.mismatched = False
        self.stopped = False
        # From this moment on a frame without the expected values counts as
        # an answer too; None means such frames are ignored.
        self.mismatch_after: float | None = None
        self._event = asyncio.Event()

    def offer(self, reported: Mapping[str, Any], now: float) -> None:
        self.frames += 1
        if self.matched:
            return
        if all(reported.get(key) in values for key, values in self.accepted.items()):
            self.matched = True
            self._event.set()
        elif self.mismatch_after is not None and now >= self.mismatch_after:
            self.mismatched = True
            self._event.set()

    def stop(self) -> None:
        self.stopped = True
        self._event.set()

    async def wait(self, timeout: float) -> None:
        """Return once matched, mismatched, stopped or after the timeout."""
        if self.matched or self.mismatched or self.stopped:
            return
        self._event.clear()
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                await self._event.wait()


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


def _parse_identity(msg: Message) -> Identity | None:
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
        return None

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
        self._refresh_wake = asyncio.Event()
        self._ladder = 0
        self._working_mode: RefreshMode | None = None
        self._last_runtime: int | None = None
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

        This is the restored status until the first live frame arrives.
        """
        return self._status

    @property
    def status_is_live(self) -> bool:
        """Return True once a frame was received in this session."""
        return self._status_is_live

    @property
    def last_frame_at(self) -> float | None:
        """Return the wall-clock time of the last status frame (epoch seconds)."""
        return self._last_frame_wall

    @property
    def identity(self) -> Identity | None:
        """Return the last answer of the info resource, if any."""
        return self._identity

    @property
    def identity_mismatch(self) -> bool:
        """Return True while another device answers at this address.

        Set when a status frame or the info resource shows a device id other
        than the expected one, cleared when the expected id is seen again.
        The session keeps running and does not block commands; the caller
        decides what to do (report 6.3: show a repair issue).
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
        in standby sends nothing until something changes.
        """
        if self._stopped:
            raise SessionStoppedError("a stopped session cannot be started again")
        if self._started:
            return
        self._started = True
        self._started_wall = time.time()
        try:
            # Opening the socket also sends the registration (rule 5: always,
            # whether or not any probe gets an answer).
            await self._ensure_socket()
        except SessionStoppedError:
            return  # stop() won the race
        except BaseException:
            # Cancelled half-way: leave a session that can be started again.
            self._started = False
            raise
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
            for waiter in self._waiters:
                waiter.stop()
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

    async def _run_once(self, name: str, coro: Coroutine[Any, Any, None]) -> None:
        try:
            await coro
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
                self._observe_from_new_endpoint()
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
        if not self._started or self._state not in (SessionState.OFFLINE, SessionState.SUSPECT):
            return
        self._offline_attempt = 0
        if self._loss_logged:
            self._loss_logged = False
            _LOGGER.info("%s: the device answers again", self._host)
        # Rule 4: the cached status is kept, however old it is.
        self._set_state(SessionState.LIVE if self._status_is_live else SessionState.REACHABLE)
        # After missed probes the observer may be gone, so register at once.
        # The first contact after start() follows its registration within
        # milliseconds; that one may wait for the usual gap.
        self._request_refresh(force=after_misses)
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
        if due > now:
            await asyncio.sleep(due - now)
            return
        await self._probe_round()

    async def _probe_round(self) -> None:
        opts = self._options
        was_offline = self._state is SessionState.OFFLINE
        self._last_probe = time.monotonic()
        if await self._probe(_ProbeKind.PING):
            return
        if self._state in (SessionState.LIVE, SessionState.REACHABLE):
            self._set_state(SessionState.SUSPECT)
        if not was_offline and self._misses < opts.offline_min_misses:
            return
        # The ping keeps failing: ask in the other way before believing it.
        if await self._probe(_ProbeKind.SYNC):
            return
        now = time.monotonic()
        if not was_offline:
            silence = math.inf if self._last_contact_mono is None else now - self._last_contact_mono
            if (
                self._misses < opts.offline_min_misses
                or silence < opts.offline_min_silence
                or self._missed_kinds != set(_ProbeKind)
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
        ``stop()`` afterwards in that case too.
        """
        if self._stopped:
            raise SessionStoppedError("the session is stopped")
        opts = self._options
        for _ in range(opts.info_attempts):
            if not await self._ensure_socket():
                return None
            reply = await self._request(GET, INFO_PATH, b"", opts.info_timeout)
            identity = _parse_identity(reply) if reply is not None else None
            if identity is None:
                continue
            self._identity = identity
            self._judge_device_id(identity.device_id)
            return identity
        return None

    def _start_identity_check(self) -> None:
        if self._expected_id is None or self._identity_task is not None:
            return
        self._identity_task = self._spawn(self._run_once("the identity check", self._check_identity()))

    async def _check_identity(self) -> None:
        try:
            await self.identify()
        finally:
            self._identity_task = None

    def _judge_device_id(self, device_id: str) -> bool:
        """Compare with the expected device; returns False on a mismatch."""
        if self._expected_id is None:
            return True
        if device_id.casefold() == self._expected_id.casefold():
            if self._identity_mismatch:
                self._identity_mismatch = False
                _LOGGER.info("%s: the expected device answers again", self._host)
                self._schedule_notify()
            return True
        self._counters.identity_mismatches += 1
        if not self._identity_mismatch:
            self._identity_mismatch = True
            _LOGGER.warning("%s: another device answers at this address", self._host)
            self._schedule_notify()
        return False

    # -- observation (rules 5 and 6) ---------------------------------------

    def _observe_from_new_endpoint(self) -> None:
        """Start over with a fresh token on a socket that was just opened.

        The token is fixed for as long as the socket lives (rule 5). A new
        socket is a new endpoint to the device, and a new token makes its
        registration exactly the kind that was measured to take the stream
        over and to be answered (measurements 8 and 9). The same token from
        another port was never tried.
        """
        for observation in self._observations:
            self._transport.remove_stream(observation.token)
        self._observations = []
        self._ladder = 0
        self._register_new_token(RefreshMode.SAME_TOKEN)

    def _send_registration(self) -> None:
        """Send the registration for the newest token; no answer is expected.

        In standby a registration is answered only by the next change, and a
        repeated one is not answered at all (measurements 2 and 8), so
        waiting for an answer would be the mistake that makes the existing
        integrations flap.
        """
        # Without a socket there is no observation yet; opening one registers.
        if self._observations:
            observation = self._observations[-1]
            msg = build_request(MType.NON, GET, self._transport.next_mid(), observation.token, STATUS_PATH, observe=0)
            if self._send(msg):
                self._counters.registrations_sent += 1
                if observation.registrations:
                    self._counters.refreshes_sent += 1
                observation.registrations += 1
        self._last_registration = time.monotonic()
        self._refresh_pending = False

    def _send_deregistration(self, observation: _Observation) -> None:
        self._send(build_request(MType.NON, GET, self._transport.next_mid(), observation.token, STATUS_PATH, observe=1))

    def _request_refresh(self, *, force: bool = False) -> None:
        """Ask for an extra registration (rule 5).

        Unless forced it keeps ``refresh_min_gap`` to the previous one; the
        refresh loop then sends it as soon as the gap has passed.
        """
        if not self._started or self._stopped:
            return
        last = self._last_registration
        if force or last is None or time.monotonic() - last >= self._options.refresh_min_gap:
            self._send_registration()
        else:
            self._refresh_pending = True
            self._refresh_wake.set()

    async def _refresh_step(self) -> None:
        opts = self._options
        now = time.monotonic()
        wait = opts.refresh_min_gap if self._refresh_pending else opts.refresh_interval
        due = now if self._last_registration is None else self._last_registration + wait
        if due <= now:
            # Rule 5: mandatory, also when everything looks fine. It is the
            # only repair after a short device restart or an evicted observer.
            self._send_registration()
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
            self._spawn(self._run_once("the resync", self._resync_and_register()))

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
            if err.missed_change:
                self._request_refresh()
            return
        self._accept_frame(observation, reported)

    def _check_frame(self, reported: dict[str, Any]) -> None:
        device_id = reported.get(DEVICE_ID_KEY)
        if isinstance(device_id, str) and not self._judge_device_id(device_id):
            raise _FrameError("identity_mismatch", missed_change=False)
        runtime = reported.get(RUNTIME_KEY)
        last = self._last_runtime
        if _is_int(runtime) and last is not None and 0 < last - runtime < self._options.runtime_stale_window_ms:
            # Slightly older than what is already applied: a reordered frame.
            raise _FrameError("stale", missed_change=False)

    def _accept_frame(self, observation: _Observation, reported: dict[str, Any]) -> None:
        now = time.monotonic()
        runtime = reported.get(RUNTIME_KEY)
        restarted = False
        if _is_int(runtime):
            # A large fall of the uptime is a device restart (rule 7).
            restarted = self._last_runtime is not None and runtime < self._last_runtime
            self._last_runtime = runtime
        self._status = reported
        self._status_is_live = True
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
        self._schedule_notify()
        if restarted:
            self._counters.device_restarts += 1
            self._request_refresh()

    async def request_status(self) -> bool:
        """Ask for a fresh status; True when a frame arrived in time.

        This registers again with a new token, which changes nothing on the
        device but the token it reports to. A device that is on answers a
        new registration within about 2 s; a repeated registration with the
        same token gets no answer (measurement 8). In standby nothing
        answers, so False is the normal result for a device that is off.
        """
        self._check_running()
        waiter = _FrameWaiter({})
        self._waiters.append(waiter)
        try:
            if self._observations:
                # Not a step on the ladder of rule 6: the label stays.
                self._register_new_token(self._observations[-1].mode)
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

        Commands are serialised by the exchange lock. Merging several pending
        writes into one message (report 6.4 item 6) is not done yet; several
        keys in one call do travel in one message.
        """
        self._check_running()
        desired = self._validated(values)
        opts = self._options
        started = time.monotonic()
        status = self._status
        if status is not None and status.get(POWER_KEY) == 0 and desired.get(POWER_KEY) != 1:
            self._counters.commands_blocked_off += 1
            raise DeviceOffError("the device is off and would discard this", desired)
        accepted = {key: accepted_readback(key, value) for key, value in desired.items()}
        already_current = (
            self._status_is_live and status is not None and all(status.get(key) in ok for key, ok in accepted.items())
        )
        # Registered before anything is sent, so that no frame can slip by.
        waiter = _FrameWaiter(accepted)
        self._waiters.append(waiter)
        self._counters.commands_sent += 1
        try:
            attempts = await self._exchange(desired)
            if already_current:
                # Nothing changes on the device, so no frame has to follow.
                return WriteResult(desired, True, False, attempts, time.monotonic() - started)
            frames_at_answer = waiter.frames
            # Frames in the settle window may predate the write (the Wi-Fi
            # module polls the main processor about once per second).
            waiter.mismatch_after = time.monotonic() + opts.confirm_settle
            await waiter.wait(opts.confirm_timeout)
            resent = False
            if not waiter.matched:
                self._check_running()
                waiter.mismatch_after = None
                waiter.mismatched = False
                self._request_refresh(force=True)
                await waiter.wait(opts.confirm_retry_wait)
            if not waiter.matched:
                self._check_running()
                resent = True
                try:
                    attempts += await self._exchange(desired)
                except WriteError as err:
                    _LOGGER.debug("%s: the resend failed: %s", self._host, err)
                await waiter.wait(opts.confirm_retry_wait)
            self._check_running()
            if waiter.matched:
                return WriteResult(desired, False, resent, attempts, time.monotonic() - started)
            self._counters.commands_unconfirmed += 1
            if waiter.frames == frames_at_answer:
                # Not one frame since the device said "success": the stream
                # itself is suspect. With frames arriving it is alive and the
                # device simply did not apply the values.
                self._escalate()
            raise NotConfirmedError("accepted but not confirmed", desired)
        finally:
            self._waiters.remove(waiter)

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

    async def _exchange(self, values: Mapping[str, int]) -> int:
        """Sync, then control with counter plus one; returns the attempts used.

        Every attempt has its own sync and a newly encrypted payload, because
        each sync returns a fresh, unrelated counter (metingen.md,
        measurement 2). The budget includes the wait for the lock.
        """
        opts = self._options
        refused = False
        try:
            async with asyncio.timeout(opts.write_budget), self._exchange_lock:
                for attempt in range(1, opts.write_attempts + 1):
                    self._check_running()
                    if not await self._ensure_socket():
                        continue
                    counter = await self._sync(opts.sync_timeout)
                    if counter is None:
                        continue
                    answer = await self._control(crypto.next_counter(counter), values, opts.control_timeout)
                    if answer == "success":
                        return attempt
                    refused = refused or answer == "failed"
        except TimeoutError:
            pass
        self._check_running()
        if refused:
            self._counters.commands_refused += 1
            raise RefusedError("the device refused the command", values)
        self._counters.commands_unanswered += 1
        raise UnreachableError("no usable answer from the device", values)

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
