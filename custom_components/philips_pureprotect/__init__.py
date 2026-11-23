"""Philips PureProtect air purifiers, controlled over the local network."""

from __future__ import annotations

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback

from .coordinator import PureProtectConfigEntry, PureProtectCoordinator, status_store

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.FAN, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: PureProtectConfigEntry) -> bool:
    """Start the session of one purifier; never waits for the device."""
    coordinator = PureProtectCoordinator(hass, entry)
    await coordinator.async_start()
    entry.runtime_data = coordinator

    stop_listener: CALLBACK_TYPE | None = None

    async def stop(_: Event) -> None:
        nonlocal stop_listener
        stop_listener = None  # a one-time listener is gone once it has fired
        await coordinator.async_stop()

    @callback
    def remove_stop_listener() -> None:
        if stop_listener is not None:
            stop_listener()

    stop_listener = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    entry.async_on_unload(remove_stop_listener)
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


async def async_remove_entry(hass: HomeAssistant, entry: PureProtectConfigEntry) -> None:
    """Remove the stored status of a purifier that is removed.

    Here and not at unload: unloading writes that file, for the next start.
    """
    await status_store(hass, entry.entry_id).async_remove()
