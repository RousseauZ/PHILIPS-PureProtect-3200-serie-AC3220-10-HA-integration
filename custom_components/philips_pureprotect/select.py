"""Settings of the purifier with a few fixed choices."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DEVICE_MODES, Key
from .coordinator import PureProtectConfigEntry, PureProtectCoordinator
from .entity import PureProtectEntity, add_when_reported

PARALLEL_UPDATES = 0

BRIGHTNESS_OFF = 0
BRIGHTNESS_AUTO = 101
LIGHT_OFF, LIGHT_AIR_QUALITY, LIGHT_AMBIENT = 0, 1, 2


@dataclass(frozen=True)
class Companion:
    """A key that is written in the same message as a choice."""

    key: str
    value: int
    # Only when the status shows one of these values for the key; None is always.
    when_status_shows: frozenset[int] | None = None


@dataclass(frozen=True, kw_only=True)
class PureProtectSelectDescription(SelectEntityDescription):
    """A setting stored under one key, with a value per choice."""

    status_key: str
    choices: Mapping[str, int]
    # What travels along with a choice, per choice. A command is confirmed
    # only when the device reports every key that was sent, so each key here
    # has to be one the device takes from the network.
    companions: Mapping[str, tuple[Companion, ...]] = field(default_factory=dict)


# What the light selects send along. The AC3220/10 takes brightness, lamp
# function and scene from the network, alone and together (docs/metingen.md,
# measurement 14). The Air+ app switches the light off with brightness 0 and
# lamp function 0 in one message (measurements 6 and 7), and so does this.
#
# Coming back from off needs both again: a light mode brings automatic
# brightness along when the brightness is 0, and a brightness brings the
# air-quality light along when the lamp function is off. A scene is a colour
# of the ambient light, so it switches that on; unlike the app it keeps a
# brightness that was chosen.
_LIGHT_OFF = (Companion(Key.LIGHT_MODE, LIGHT_OFF),)
_BRIGHTNESS_BACK_ON = (Companion(Key.BRIGHTNESS, BRIGHTNESS_AUTO, when_status_shows=frozenset({BRIGHTNESS_OFF})),)
_LIGHT_BACK_ON = (Companion(Key.LIGHT_MODE, LIGHT_AIR_QUALITY, when_status_shows=frozenset({LIGHT_OFF})),)
LIGHT_MODE_COMPANIONS: Mapping[str, tuple[Companion, ...]] = {
    "off": (Companion(Key.BRIGHTNESS, BRIGHTNESS_OFF),),
    "air_quality": _BRIGHTNESS_BACK_ON,
    "ambient": _BRIGHTNESS_BACK_ON,
}
BRIGHTNESS_COMPANIONS: Mapping[str, tuple[Companion, ...]] = {
    "auto": _LIGHT_BACK_ON,
    "low": _LIGHT_BACK_ON,
    "bright": _LIGHT_BACK_ON,
    "off": _LIGHT_OFF,
}
_SCENE_LIGHT = (Companion(Key.LIGHT_MODE, LIGHT_AMBIENT), *_BRIGHTNESS_BACK_ON)
LIGHT_SCENE_COMPANIONS: Mapping[str, tuple[Companion, ...]] = {f"scene_{scene}": _SCENE_LIGHT for scene in (1, 2, 3, 4)}

SELECTS: tuple[PureProtectSelectDescription, ...] = (
    PureProtectSelectDescription(
        key="light_mode",
        translation_key="light_mode",
        status_key=Key.LIGHT_MODE,
        choices={"off": LIGHT_OFF, "air_quality": LIGHT_AIR_QUALITY, "ambient": LIGHT_AMBIENT},
        companions=LIGHT_MODE_COMPANIONS,
    ),
    PureProtectSelectDescription(
        key="light_brightness",
        translation_key="light_brightness",
        status_key=Key.BRIGHTNESS,
        choices={"auto": BRIGHTNESS_AUTO, "low": 115, "bright": 123, "off": BRIGHTNESS_OFF},
        companions=BRIGHTNESS_COMPANIONS,
    ),
    PureProtectSelectDescription(
        key="light_scene",
        translation_key="light_scene",
        status_key=Key.LIGHT_SCENE,
        choices={"scene_1": 1, "scene_2": 2, "scene_3": 3, "scene_4": 4},
        companions=LIGHT_SCENE_COMPANIONS,
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
    add_when_reported(
        entry,
        async_add_entities,
        [ModeSelect],
        lambda _: (Key.POWER, Key.MODE),
        lambda coordinator, cls: cls(coordinator),
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
        """Send the choice to the device, with what has to travel along."""
        description = self.entity_description
        values = {description.status_key: description.choices[option]}
        for companion in description.companions.get(option, ()):
            shown = companion.when_status_shows
            if shown is None or self.coordinator.value(companion.key) in shown:
                values[companion.key] = companion.value
        await self.coordinator.async_write(values)


MODE_OFF = "off"
MODE_OPTIONS = [MODE_OFF, *DEVICE_MODES]


class ModeSelect(PureProtectEntity, SelectEntity):
    """Every mode of the purifier in one list, with the names of its buttons.

    The fan entity follows Home Assistant's model: auto and sleep as preset
    modes, and medium and turbo as the speeds they run at. This select shows
    the device's own modes, on the device page and for dashboards, and also
    switches the purifier on and off.
    """

    _attr_translation_key = "mode"
    _attr_options = MODE_OPTIONS

    def __init__(self, coordinator: PureProtectCoordinator) -> None:
        """Create the select."""
        super().__init__(coordinator, "mode")

    @property
    def current_option(self) -> str | None:
        """Return the mode the device reports, or off."""
        power = self.coordinator.value(Key.POWER)
        if power is None:
            return None
        if power == 0:
            return MODE_OFF
        mode = self.coordinator.value(Key.MODE)
        return next((name for name, value in DEVICE_MODES.items() if value == mode), None)

    async def async_select_option(self, option: str) -> None:
        """Switch to a mode, switching the purifier on in the same message when needed."""
        if option == MODE_OFF:
            await self.coordinator.async_write({Key.POWER: 0})
            return
        values = {Key.MODE: DEVICE_MODES[option]}
        # As for the fan: only a status received in this session proves that
        # the purifier is on. A switch-on carries the mode along (measurement 14).
        if not (self.coordinator.value(Key.POWER) == 1 and self.coordinator.session.status_is_live):
            values[Key.POWER] = 1
        await self.coordinator.async_write(values)
