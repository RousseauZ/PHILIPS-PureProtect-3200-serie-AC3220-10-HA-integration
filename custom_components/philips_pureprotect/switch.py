"""Settings of the purifier that are on or off."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import Key
from .coordinator import PureProtectConfigEntry, PureProtectCoordinator
from .entity import PureProtectEntity, add_when_reported

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PureProtectSwitchDescription(SwitchEntityDescription):
    """A setting stored under one key."""

    status_key: str
    on_value: int = 1
    off_value: int = 0


SWITCHES: tuple[PureProtectSwitchDescription, ...] = (
    PureProtectSwitchDescription(key="child_lock", translation_key="child_lock", status_key=Key.CHILD_LOCK),
    PureProtectSwitchDescription(key="beep", translation_key="beep", status_key=Key.BEEP, on_value=100),
    PureProtectSwitchDescription(key="auto_plus", translation_key="auto_plus", status_key=Key.AUTO_PLUS),
    PureProtectSwitchDescription(key="allergy_sleep", translation_key="allergy_sleep", status_key=Key.ALLERGY_SLEEP),
    PureProtectSwitchDescription(
        key="standby_sensors", translation_key="standby_sensors", status_key=Key.STANDBY_SENSORS
    ),
    # The device stores the opposite: 1 means the display is off.
    PureProtectSwitchDescription(
        key="display", translation_key="display", status_key=Key.DISPLAY_OFF, on_value=0, off_value=1
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PureProtectConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the switches the device reports."""
    add_when_reported(
        entry, async_add_entities, SWITCHES, lambda description: (description.status_key,), PureProtectSwitch
    )


class PureProtectSwitch(PureProtectEntity, SwitchEntity):
    """A setting that is on or off."""

    entity_description: PureProtectSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PureProtectCoordinator, description: PureProtectSwitchDescription) -> None:
        """Create the switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the setting as the device reports it."""
        value = self.coordinator.value(self.entity_description.status_key)
        return None if value is None else value != self.entity_description.off_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the setting on."""
        await self.coordinator.async_write({self.entity_description.status_key: self.entity_description.on_value})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the setting off."""
        await self.coordinator.async_write({self.entity_description.status_key: self.entity_description.off_value})
