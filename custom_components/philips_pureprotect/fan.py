"""The purifier itself: power, mode and speed."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import Key
from .coordinator import PureProtectConfigEntry, PureProtectCoordinator
from .entity import PureProtectEntity

PARALLEL_UPDATES = 0

# Modes that are a choice of the device, not a fixed speed.
PRESET_MODES = {"auto": 0, "sleep": 17}
# The five fixed speeds, written as a mode.
SPEEDS = (1, 2, 3, 4, 5)
# What the device reports as running speed (Key.FAN_LEVEL), mapped to a speed.
# Measured: speed 5 and turbo both report 18; medium reports 3.
LEVEL_TO_SPEED = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 18: 5}
# Modes that stand for a fixed speed, for when the running speed is unknown.
MODE_TO_SPEED = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 19: 3, 18: 5}


async def async_setup_entry(
    hass: HomeAssistant, entry: PureProtectConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the fan; it exists for every purifier."""
    async_add_entities([PureProtectFan(entry.runtime_data)])


class PureProtectFan(PureProtectEntity, FanEntity):
    """The purifier as a fan with five speeds and the modes auto and sleep."""

    _attr_name = None
    _attr_translation_key = "purifier"
    _attr_preset_modes = list(PRESET_MODES)  # noqa: RUF012
    _attr_speed_count = len(SPEEDS)
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: PureProtectCoordinator) -> None:
        """Create the fan of a purifier."""
        super().__init__(coordinator, "fan")

    @property
    def is_on(self) -> bool | None:
        """Return whether the purifier runs."""
        power = self.coordinator.value(Key.POWER)
        return None if power is None else power != 0

    @property
    def preset_mode(self) -> str | None:
        """Return auto or sleep, or None at a fixed speed."""
        if not self.is_on:
            return None
        mode = self.coordinator.value(Key.MODE)
        return next((name for name, value in PRESET_MODES.items() if value == mode), None)

    @property
    def percentage(self) -> int | None:
        """Return the running speed, in every mode."""
        if self.is_on is None:
            return None
        if not self.is_on:
            return 0
        speed = LEVEL_TO_SPEED.get(self.coordinator.value(Key.FAN_LEVEL))  # type: ignore[arg-type]
        if speed is None:
            speed = MODE_TO_SPEED.get(self.coordinator.value(Key.MODE))  # type: ignore[arg-type]
        return None if speed is None else round(speed * 100 / len(SPEEDS))

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any) -> None:
        """Switch on, optionally in a mode or at a speed."""
        if percentage == 0:
            await self.async_turn_off()
            return
        # Power first and on its own: the device discards a setting it gets
        # while it is off, and whether it takes one in the same message as the
        # power key is not measured yet.
        if not self.is_on:
            await self.coordinator.async_write({Key.POWER: 1})
        if preset_mode is not None:
            await self.coordinator.async_write({Key.MODE: PRESET_MODES[preset_mode]})
        elif percentage is not None:
            await self.coordinator.async_write({Key.MODE: _speed_for(percentage)})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch off."""
        await self.coordinator.async_write({Key.POWER: 0})

    async def async_set_percentage(self, percentage: int) -> None:
        """Set a fixed speed; 0 switches off."""
        await self.async_turn_on(percentage=percentage)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set auto or sleep; switches on when needed."""
        await self.async_turn_on(preset_mode=preset_mode)


def _speed_for(percentage: int) -> int:
    """Return the speed for a percentage; anything above 0 is at least speed 1."""
    return min(len(SPEEDS), max(1, math.ceil(percentage * len(SPEEDS) / 100)))
