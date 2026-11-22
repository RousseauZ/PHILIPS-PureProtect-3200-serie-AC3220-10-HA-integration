"""Event log: every datagram and every observation, as JSON lines."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from typing import Any, TextIO

# Fields that identify a device or a household. They are replaced by a short
# stable hash, so equality between two values stays visible.
REDACT_KEYS = frozenset(
    {"DeviceId", "ProductId", "D01S03", "device_id", "product_id", "name", "mac"}
)


def redact_value(value: Any) -> str:
    """Return a short stable hash of a value."""
    digest = hashlib.sha256(str(value).encode()).hexdigest()[:10]
    return f"h:{digest}"


def redact(data: dict[str, Any], enabled: bool = True) -> dict[str, Any]:
    """Return a copy of a status or info dict with identifying fields hashed."""
    if not enabled:
        return dict(data)
    return {k: (redact_value(v) if k in REDACT_KEYS else v) for k, v in data.items()}


class EventLog:
    """Collects events in memory and writes them to a JSON-lines file."""

    def __init__(self, path: Path | None = None, *, quiet: bool = False) -> None:
        self.path = path
        self.quiet = quiet
        self.events: list[dict[str, Any]] = []
        self._start = time.monotonic()
        self._file: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("w", encoding="utf-8")

    def now(self) -> float:
        """Seconds since the log was opened (monotonic clock)."""
        return time.monotonic() - self._start

    def write(self, ev: str, **fields: Any) -> dict[str, Any]:
        """Record one event and return it."""
        event: dict[str, Any] = {
            "t": round(self.now(), 4),
            "wall": dt.datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "ev": ev,
        }
        event.update(fields)
        self.events.append(event)
        if self._file is not None:
            self._file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            self._file.flush()
        return event

    def say(self, text: str) -> None:
        """Show a line to the person running the tool and record it."""
        self.write("note", text=text)
        if not self.quiet:
            print(f"[{self.now():8.1f}s] {text}", flush=True)

    def close(self) -> None:
        """Close the file."""
        if self._file is not None:
            self._file.close()
            self._file = None
