"""Philips PureProtect air purifiers, controlled over the local network."""

from __future__ import annotations

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from .coordinator import PureProtectConfigEntry, PureProtectCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.FAN, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: PureProtectConfigEntry) -> bool:
    """Start the session of one purifier; never waits for the device."""
    coordinator = PureProtectCoordinator(hass, entry)
    await coordinator.async_start()
    entry.runtime_data = coordinator

    async def stop(_: Event) -> None:
        await coordinator.async_stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_stop()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PureProtectConfigEntry) -> bool:
    """Stop the session of one purifier."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
        entry.runtime_data.async_clear_issue()
    return unload_ok
