"""Exception types of the airlink package."""

from __future__ import annotations

from collections.abc import Mapping


class AirlinkError(Exception):
    """Base class of every error this package raises on purpose."""


class TransportError(AirlinkError):
    """The local UDP socket is closed or could not send."""


class SessionStoppedError(AirlinkError):
    """The session is not running: it was stopped, or never started."""


class WriteError(AirlinkError):
    """Base class of the ways a write can fail; ``values`` is what was asked."""

    def __init__(self, message: str, values: Mapping[str, int]) -> None:
        super().__init__(message)
        self.values: dict[str, int] = dict(values)


class DeviceOffError(WriteError):
    """Nothing was sent: the device is off and would discard the setting.

    Measured on the AC3220/10 (docs/metingen.md, measurement 5): a setting
    written in standby is answered with "success" and not applied.
    """


class UnreachableError(WriteError):
    """No usable answer from the device within the time limit of a write."""


class RefusedError(WriteError):
    """The device answered "failed" to every attempt."""


class NotConfirmedError(WriteError):
    """The device answered "success" but never reported the new values."""
