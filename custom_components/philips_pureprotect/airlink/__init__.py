"""Protocol and session layer for Philips PureProtect air purifiers.

A self-contained asyncio package: one UDP socket per device, a small CoAP
codec, the payload envelope and the session state machine of
docs/onderzoek.md chapter 6. It imports nothing from Home Assistant, so it
can be tested against a simulated device and published on its own later.
"""

from .discovery import discover, parse_info
from .errors import (
    AirlinkError,
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
from .session import POWER_KEY, Session, accepted_readback
from .transport import TraceCallback

__all__ = [
    "POWER_KEY",
    "AirlinkError",
    "DeviceOffError",
    "Diagnostics",
    "Identity",
    "NotConfirmedError",
    "RefreshMode",
    "RefusedError",
    "RestoredState",
    "Session",
    "SessionOptions",
    "SessionState",
    "SessionStoppedError",
    "TraceCallback",
    "TransportError",
    "UnreachableError",
    "WriteError",
    "WriteResult",
    "accepted_readback",
    "discover",
    "parse_info",
]
