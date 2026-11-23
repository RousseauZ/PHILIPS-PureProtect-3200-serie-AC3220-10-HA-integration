"""Measurements, filter state and diagnostics of the purifier."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDensity,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import LEVEL_TO_SPEED, Key
from .coordinator import PureProtectConfigEntry, PureProtectCoordinator, moment
from .entity import PureProtectEntity, add_when_reported

PARALLEL_UPDATES = 0

# A timestamp entity is rewritten only when it moved by more than this.
TIMESTAMP_STEP = timedelta(seconds=60)


@dataclass(frozen=True, kw_only=True)
class PureProtectSensorDescription(SensorEntityDescription):
    """A sensor computed from one or more keys of the status."""

    needs: tuple[str, ...]
    value_fn: Callable[[PureProtectCoordinator], StateType]
    # True for what the purifier measures itself. Off, it measures nothing
    # and reports nothing, unless "sensors in standby" is on.
    measured: bool = False


def _raw(key: str) -> Callable[[PureProtectCoordinator], StateType]:
    return lambda coordinator: coordinator.value(key)


def _temperature(coordinator: PureProtectCoordinator) -> StateType:
    tenths = coordinator.value(Key.TEMPERATURE)
    return None if tenths is None else tenths / 10


def _filter_life(coordinator: PureProtectCoordinator) -> StateType:
    left, total = coordinator.value(Key.FILTER_LIFE_LEFT), coordinator.value(Key.FILTER_LIFE_TOTAL)
    if left is None or not total:
        return None
    # Never 0 % while there are hours left.
    return min(100, max(0, math.ceil(left * 100 / total)))


def _fan_speed(coordinator: PureProtectCoordinator) -> StateType:
    """Return how hard the fan runs, as a step from 1 to 5; 0 while the purifier is off."""
    if coordinator.value(Key.POWER) == 0:
        return 0
    return LEVEL_TO_SPEED.get(coordinator.value(Key.FAN_LEVEL))  # type: ignore[arg-type]


SENSORS: tuple[PureProtectSensorDescription, ...] = (
    PureProtectSensorDescription(
        key="pm25",
        needs=(Key.PM25,),
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_raw(Key.PM25),
        measured=True,
    ),
    PureProtectSensorDescription(
        key="allergen_index",
        translation_key="allergen_index",
        needs=(Key.ALLERGEN_INDEX,),
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_raw(Key.ALLERGEN_INDEX),
        measured=True,
    ),
    PureProtectSensorDescription(
        key="temperature",
        needs=(Key.TEMPERATURE,),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_temperature,
        measured=True,
    ),
    PureProtectSensorDescription(
        key="humidity",
        needs=(Key.HUMIDITY,),
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_raw(Key.HUMIDITY),
        measured=True,
    ),
    PureProtectSensorDescription(
        key="filter_life",
        translation_key="filter_life",
        needs=(Key.FILTER_LIFE_LEFT, Key.FILTER_LIFE_TOTAL),
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_filter_life,
    ),
    PureProtectSensorDescription(
        key="filter_cleaning",
        translation_key="filter_cleaning",
        needs=(Key.FILTER_CLEAN_LEFT,),
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_raw(Key.FILTER_CLEAN_LEFT),
    ),
    PureProtectSensorDescription(
        key="signal_strength",
        needs=(Key.RSSI,),
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_raw(Key.RSSI),
    ),
    PureProtectSensorDescription(
        key="error_code",
        translation_key="error_code",
        needs=(Key.ERROR_CODE,),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_raw(Key.ERROR_CODE),
    ),
    # How hard the purifier works, which the fan entity does not show in auto
    # and sleep. The key is part of the unique id and stays what it was.
    PureProtectSensorDescription(
        key="fan_level",
        translation_key="fan_speed",
        needs=(Key.FAN_LEVEL,),
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_fan_speed,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PureProtectConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the sensors the device reports, and the one for the last status."""
    async_add_entities([LastStatusSensor(entry.runtime_data)])
    add_when_reported(entry, async_add_entities, SENSORS, lambda description: description.needs, PureProtectSensor)
    add_when_reported(
        entry,
        async_add_entities,
        [TimerEndSensor],
        lambda _: (Key.TIMER_MINUTES_LEFT,),
        lambda coordinator, cls: cls(coordinator),
    )


class PureProtectSensor(PureProtectEntity, SensorEntity):
    """A value from the status."""

    entity_description: PureProtectSensorDescription

    def __init__(self, coordinator: PureProtectCoordinator, description: PureProtectSensorDescription) -> None:
        """Create the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """Return the value the device last reported; None for a reading while nothing is measured.

        A purifier that is off keeps its last readings to itself for hours.
        Shown as current, they would draw a flat line that was never
        measured, and an automation on them could never fire.
        """
        coordinator = self.coordinator
        if (
            self.entity_description.measured
            and coordinator.value(Key.POWER) == 0
            and coordinator.value(Key.STANDBY_SENSORS) != 1
        ):
            return None
        return self.entity_description.value_fn(coordinator)


class _SteadyTimestampSensor(PureProtectEntity, SensorEntity):
    """A moment in time that is only rewritten when it really moved.

    The status arrives every few seconds; a timestamp that followed it to the
    second would fill the database.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_native_value: datetime | None = None

    def _moment(self) -> datetime | None:
        raise NotImplementedError

    @callback
    def _refresh(self) -> None:
        moment, shown = self._moment(), self._attr_native_value
        if moment is None or shown is None or abs(moment - shown) > TIMESTAMP_STEP:
            self._attr_native_value = moment

    async def async_added_to_hass(self) -> None:
        """Take the first value."""
        await super().async_added_to_hass()
        self._refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh()
        super()._handle_coordinator_update()


class LastStatusSensor(_SteadyTimestampSensor):
    """When the purifier last sent its status; shows how old the other values are."""

    _attr_translation_key = "last_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PureProtectCoordinator) -> None:
        """Create the sensor."""
        super().__init__(coordinator, "last_status")

    def _moment(self) -> datetime | None:
        return moment(self.coordinator.session.last_frame_at)


class TimerEndSensor(_SteadyTimestampSensor):
    """When the timer switches the purifier off."""

    _attr_translation_key = "timer_end"

    def __init__(self, coordinator: PureProtectCoordinator) -> None:
        """Create the sensor."""
        super().__init__(coordinator, "timer_end")

    def _moment(self) -> datetime | None:
        minutes = self.coordinator.value(Key.TIMER_MINUTES_LEFT)
        received = moment(self.coordinator.session.last_frame_at)
        if not minutes or received is None or not self.coordinator.value(Key.POWER):
            return None
        return received + timedelta(minutes=minutes)
