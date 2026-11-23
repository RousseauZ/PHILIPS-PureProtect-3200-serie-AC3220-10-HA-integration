"""Settings of the purifier with a few fixed choices."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import Key
from .coordinator import PureProtectConfigEntry, PureProtectCoordinator
from .entity import PureProtectEntity, add_when_reported

PARALLEL_UPDATES = 0

BRIGHTNESS_OFF = 0
BRIGHTNESS_AUTO = 101
LIGHT_OFF, LIGHT_AIR_QUALITY, LIGHT_AMBIENT = 0, 1, 2


@dataclass(frozen=True, kw_only=True)
class PureProtectSelectDescription(SelectEntityDescription):
    """A setting stored under one key, with a value per choice."""

    status_key: str
    choices: Mapping[str, int]
    # What to send for a choice. The default is the one key with its value.
    write_fn: Callable[[PureProtectCoordinator, int], dict[str, int]] | None = None


def _light_mode(coordinator: PureProtectCoordinator, mode: int) -> dict[str, int]:
    """Write the light the way the Air+ app does.

    Off is brightness 0 together with mode 0. Coming back from off needs a
    brightness again, or the light would stay dark.
    """
    if mode == LIGHT_OFF:
        return {Key.BRIGHTNESS: BRIGHTNESS_OFF, Key.LIGHT_MODE: LIGHT_OFF}
    values = {Key.LIGHT_MODE: mode}
    if coordinator.value(Key.BRIGHTNESS) == BRIGHTNESS_OFF:
        values[Key.BRIGHTNESS] = BRIGHTNESS_AUTO
    return values


def _light_scene(coordinator: PureProtectCoordinator, scene: int) -> dict[str, int]:
    """Choose a scene the way the Air+ app does: with the ambient light on, at automatic brightness."""
    return {Key.LIGHT_SCENE: scene, Key.BRIGHTNESS: BRIGHTNESS_AUTO, Key.LIGHT_MODE: LIGHT_AMBIENT}


SELECTS: tuple[PureProtectSelectDescription, ...] = (
    PureProtectSelectDescription(
        key="light_mode",
        translation_key="light_mode",
        status_key=Key.LIGHT_MODE,
        choices={"off": LIGHT_OFF, "air_quality": LIGHT_AIR_QUALITY, "ambient": LIGHT_AMBIENT},
        write_fn=_light_mode,
    ),
    PureProtectSelectDescription(
        key="light_brightness",
        translation_key="light_brightness",
        status_key=Key.BRIGHTNESS,
        choices={"auto": BRIGHTNESS_AUTO, "low": 115, "bright": 123},
    ),
    PureProtectSelectDescription(
        key="light_scene",
        translation_key="light_scene",
        status_key=Key.LIGHT_SCENE,
        choices={"scene_1": 1, "scene_2": 2, "scene_3": 3, "scene_4": 4},
        write_fn=_light_scene,
    ),
    PureProtectSelectDescription(
        key="timer",
        translation_key="timer",
        status_key=Key.TIMER,
        # The device counts from 2: 2 is one hour, 13 is twelve hours.
        choices={"off": 0} | {f"hours_{hours}": hours + 1 for hours in range(1, 13)},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PureProtectConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the selects the device reports."""
    add_when_reported(
        entry, async_add_entities, SELECTS, lambda description: (description.status_key,), PureProtectSelect
    )


class PureProtectSelect(PureProtectEntity, SelectEntity):
    """A setting with fixed choices."""

    entity_description: PureProtectSelectDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PureProtectCoordinator, description: PureProtectSelectDescription) -> None:
        """Create the select."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_options = list(description.choices)

    @property
    def current_option(self) -> str | None:
        """Return the choice the device reports; None for a value without a name."""
        value = self.coordinator.value(self.entity_description.status_key)
        return next((name for name, number in self.entity_description.choices.items() if number == value), None)

    async def async_select_option(self, option: str) -> None:
        """Send the choice to the device."""
        description = self.entity_description
        value = description.choices[option]
        values = (
            description.write_fn(self.coordinator, value) if description.write_fn else {description.status_key: value}
        )
        await self.coordinator.async_write(values)
