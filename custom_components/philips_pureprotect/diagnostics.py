"""Diagnostics download: the session's counters and the last status, without identifiers."""

from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import PureProtectConfigEntry

TO_REDACT = {
    CONF_HOST,
    "unique_id",
    "title",
    "DeviceId",
    "ProductId",
    "D01S03",
    "D01S0D",
    "device_id",
    "product_id",
    "name",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: PureProtectConfigEntry) -> dict[str, Any]:
    """Return what helps to find out why a purifier misbehaves."""
    coordinator = entry.runtime_data
    session = coordinator.session
    identity = session.identity
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "session": session.diagnostics().as_dict(),
        "identity": None if identity is None else async_redact_data(dataclasses.asdict(identity), TO_REDACT),
        "keys": sorted(coordinator.keys),
        "keys_assumed": coordinator.keys_assumed,
        "status": async_redact_data(dict(session.status or {}), TO_REDACT),
    }
