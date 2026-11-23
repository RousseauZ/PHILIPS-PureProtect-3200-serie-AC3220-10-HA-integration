"""Warnings of the purifier."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import Key
from .coordinator import PureProtectConfigEntry, PureProtectCoordinator
from .entity import PureProtectEntity, add_when_reported

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PureProtectBinarySensorDescription(BinarySensorEntityDescription):
    """A warning derived from one key of the status."""

    status_key: str
    is_on_fn: Callable[[int], bool]


BINARY_SENSORS: tuple[PureProtectBinarySensorDescription, ...] = (
    PureProtectBinarySensorDescription(
        key="filter_replace",
        translation_key="filter_replace",
        status_key=Key.FILTER_LIFE_LEFT,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda hours: hours <= 0,
    ),
    PureProtectBinarySensorDescription(
        key="filter_clean",
        translation_key="filter_clean",
        status_key=Key.FILTER_CLEAN_LEFT,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda hours: hours <= 0,
    ),
    PureProtectBinarySensorDescription(
        key="problem",
        translation_key="fault",
        status_key=Key.ERROR_CODE,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda code: code != 0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PureProtectConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the warnings the device reports."""
    add_when_reported(
        entry,
        async_add_entities,
        BINARY_SENSORS,
        lambda description: (description.status_key,),
        PureProtectBinarySensor,
    )


class PureProtectBinarySensor(PureProtectEntity, BinarySensorEntity):
    """A warning."""

    entity_description: PureProtectBinarySensorDescription

    def __init__(self, coordinator: PureProtectCoordinator, description: PureProtectBinarySensorDescription) -> None:
        """Create the warning."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return whether the warning is up."""
        value = self.coordinator.value(self.entity_description.status_key)
        return None if value is None else self.entity_description.is_on_fn(value)
