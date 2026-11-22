"""Small typed data classes shared by the session and its users."""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class SessionState(enum.StrEnum):
    """Where the session stands (report 6.3)."""

    OFFLINE = "offline"  # no answer; entities unavailable
    REACHABLE = "reachable"  # the device answers, no live status frame yet
    LIVE = "live"  # at least one status frame was received in this session
    SUSPECT = "suspect"  # a liveness probe was missed; entities stay available


class RefreshMode(enum.StrEnum):
    """Rungs of the recovery ladder for a dead observation (session rule 6)."""

    SAME_TOKEN = "same_token"
    NEW_TOKEN = "new_token"
    RESYNC = "resync"


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionOptions:
    """Every duration and limit of a session, in seconds unless named otherwise.

    The defaults are the production values of report 6.3 and 6.4. They are
    choices within the range of existing implementations, not measured optima.
    """

    # Liveness (rule 3). OFFLINE needs all three: the misses, the silence and
    # a failed probe of the other kind.
    probe_idle: float = 60.0
    probe_timeout: float = 3.0
    probe_retry: float = 10.0
    offline_min_misses: int = 3
    offline_min_silence: float = 180.0
    # Waits between attempts while OFFLINE (rule 4); the last one repeats.
    offline_backoff: tuple[float, ...] = (10.0, 10.0, 10.0, 30.0, 60.0)

    # Observation (rule 5). The report allows 65-75 s for the interval. On
    # the AC3220/10 the refresh is a safety net: a registration kept
    # delivering for 20 minutes without it (measurement 4).
    refresh_interval: float = 70.0
    # Extra refreshes asked for by frames are spaced at least this far apart,
    # so that a firmware answering every registration with a bad frame cannot
    # start a ping-pong.
    refresh_min_gap: float = 5.0

    # Frame ordering (rule 7), in milliseconds of device time.
    runtime_stale_window_ms: int = 10_000

    # Commands (report 6.4).
    sync_timeout: float = 1.5
    control_timeout: float = 2.0
    write_attempts: int = 3
    write_budget: float = 10.0
    confirm_settle: float = 2.0
    confirm_timeout: float = 5.0
    confirm_retry_wait: float = 3.0

    # Identity. The info resource answers after about 0.5 s and often not at
    # all, more so when asked several times at once (metingen.md, 1 and 11):
    # a few attempts, one at a time.
    info_timeout: float = 2.0
    info_attempts: int = 4
    # A new registration was answered after 0.2 to 1.9 s (measurement 8).
    request_status_timeout: float = 3.0

    # Local housekeeping.
    socket_timeout: float = 3.0
    error_pause: float = 1.0

    def __post_init__(self) -> None:
        for item in dataclasses.fields(self):
            value = getattr(self, item.name)
            if item.name == "offline_backoff":
                if not value or any(wait <= 0 for wait in value):
                    raise ValueError("offline_backoff needs at least one positive wait")
            elif item.name in ("confirm_settle", "refresh_min_gap", "runtime_stale_window_ms"):
                if value < 0:
                    raise ValueError(f"{item.name} must not be negative")
            elif value <= 0:
                raise ValueError(f"{item.name} must be positive")


@dataclass(frozen=True, slots=True)
class Identity:
    """What the plaintext info resource says about the device (report 6.5)."""

    device_id: str
    product_id: str
    model_id: str
    type: str
    name: str


@dataclass(frozen=True, slots=True)
class RestoredState:
    """What a session persists and takes back after a restart (report 6.3).

    ``received_at`` is the wall-clock time (seconds since the epoch) at which
    ``status`` was received.
    """

    status: Mapping[str, Any] | None = None
    received_at: float | None = None
    keys: frozenset[str] = frozenset()
    firmware: str | None = None
    wifi_firmware: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable form."""
        return {
            "status": dict(self.status) if self.status is not None else None,
            "received_at": self.received_at,
            "keys": sorted(self.keys),
            "firmware": self.firmware,
            "wifi_firmware": self.wifi_firmware,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RestoredState:
        """Rebuild from ``as_dict`` output; anything of the wrong shape is left out."""
        status = data.get("status")
        received_at = data.get("received_at")
        keys = data.get("keys")
        firmware = data.get("firmware")
        wifi_firmware = data.get("wifi_firmware")
        return cls(
            status=dict(status) if isinstance(status, Mapping) else None,
            received_at=float(received_at)
            if isinstance(received_at, (int, float)) and not isinstance(received_at, bool)
            else None,
            keys=frozenset(key for key in keys if isinstance(key, str))
            if isinstance(keys, (list, tuple, set, frozenset))
            else frozenset(),
            firmware=firmware if isinstance(firmware, str) else None,
            wifi_firmware=wifi_firmware if isinstance(wifi_firmware, str) else None,
        )


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Outcome of a successful write."""

    values: Mapping[str, int]
    # True: the live status already showed these values, so the device's
    # "success" was the whole confirmation and no frame was awaited.
    already_current: bool
    # True: the command had to be sent a second time before it was confirmed.
    resent: bool
    # Sync-plus-control attempts used, over both sends.
    attempts: int
    duration: float


@dataclass(frozen=True, slots=True)
class Diagnostics:
    """Counters and timestamps of a session; times are seconds."""

    state: str
    status_is_live: bool
    identity_mismatch: bool
    started_at: float | None
    last_frame_at: float | None
    last_contact_at: float | None
    seconds_since_last_frame: float | None
    seconds_since_last_contact: float | None
    probes_sent: int
    probes_missed: int
    consecutive_missed_probes: int
    frames_received: int
    frames_dropped: dict[str, int] = field(default_factory=dict)
    registrations_sent: int = 0
    refreshes_sent: int = 0
    refresh_mode: str = RefreshMode.SAME_TOKEN.value
    working_refresh_mode: str | None = None
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
    datagrams_sent: int = 0
    datagrams_received: int = 0
    foreign_datagrams: int = 0
    malformed_datagrams: int = 0
    unknown_token_resets: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable form."""
        return dataclasses.asdict(self)
