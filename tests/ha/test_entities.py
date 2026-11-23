"""What Home Assistant is told about each entity: its unique id, class, unit and place on the device page.

With a changed unique id an update gives the owner a second set of entities and leaves the old ones, with
their history and automations, behind as "no longer provided". A changed state class, unit or category
stops long-term graphs, shows hours as minutes, or moves entities between the sections of the device page.
These tables are changed on purpose only.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

# entity: the part of the unique id after the device id
UNIQUE_IDS = {
    "fan.woonkamer": "fan",
    "binary_sensor.woonkamer_replace_filter": "filter_replace",
    "binary_sensor.woonkamer_clean_filter": "filter_clean",
    "binary_sensor.woonkamer_fault": "problem",
    "select.woonkamer_light": "light_mode",
    "select.woonkamer_light_brightness": "light_brightness",
    "select.woonkamer_ambient_light_scene": "light_scene",
    "select.woonkamer_timer": "timer",
    "sensor.woonkamer_pm2_5": "pm25",
    "sensor.woonkamer_allergen_index": "allergen_index",
    "sensor.woonkamer_temperature": "temperature",
    "sensor.woonkamer_humidity": "humidity",
    "sensor.woonkamer_filter_life_remaining": "filter_life",
    "sensor.woonkamer_filter_cleaning_due_in": "filter_cleaning",
    "sensor.woonkamer_signal_strength": "signal_strength",
    "sensor.woonkamer_error_code": "error_code",
    "sensor.woonkamer_fan_speed": "fan_level",  # the id of the "fan level" sensor it replaced
    "sensor.woonkamer_last_status_received": "last_status",
    "sensor.woonkamer_timer_ends": "timer_end",
    "switch.woonkamer_child_lock": "child_lock",
    "switch.woonkamer_beep": "beep",
    "switch.woonkamer_auto_plus": "auto_plus",
    "switch.woonkamer_allergy_sleep": "allergy_sleep",
    "switch.woonkamer_sensors_in_standby": "standby_sensors",
    "switch.woonkamer_display": "display",
}

# entity: (device class, state class, unit, section of the device page)
DESCRIBED = {
    "fan.woonkamer": (None, None, None, None),
    "sensor.woonkamer_pm2_5": ("pm25", "measurement", "μg/m³", None),
    "sensor.woonkamer_allergen_index": (None, "measurement", None, None),
    "sensor.woonkamer_temperature": ("temperature", "measurement", "°C", None),
    "sensor.woonkamer_humidity": ("humidity", "measurement", "%", None),
    "sensor.woonkamer_fan_speed": (None, "measurement", None, None),
    "sensor.woonkamer_timer_ends": ("timestamp", None, None, None),
    "sensor.woonkamer_filter_life_remaining": (None, None, "%", "diagnostic"),
    "sensor.woonkamer_filter_cleaning_due_in": ("duration", None, "h", "diagnostic"),
    "sensor.woonkamer_last_status_received": ("timestamp", None, None, "diagnostic"),
    "sensor.woonkamer_signal_strength": ("signal_strength", "measurement", "dBm", "diagnostic"),
    "sensor.woonkamer_error_code": (None, None, None, "diagnostic"),
    "binary_sensor.woonkamer_replace_filter": ("problem", None, None, "diagnostic"),
    "binary_sensor.woonkamer_clean_filter": ("problem", None, None, "diagnostic"),
    "binary_sensor.woonkamer_fault": ("problem", None, None, "diagnostic"),
    "switch.woonkamer_child_lock": (None, None, None, "config"),
    "switch.woonkamer_beep": (None, None, None, "config"),
    "switch.woonkamer_auto_plus": (None, None, None, "config"),
    "switch.woonkamer_allergy_sleep": (None, None, None, "config"),
    "switch.woonkamer_sensors_in_standby": (None, None, None, "config"),
    "switch.woonkamer_display": (None, None, None, "config"),
    "select.woonkamer_light": (None, None, None, "config"),
    "select.woonkamer_light_brightness": (None, None, None, "config"),
    "select.woonkamer_ambient_light_scene": (None, None, None, "config"),
    "select.woonkamer_timer": (None, None, None, "config"),
}

# Diagnostic values that few people need: they exist, switched off.
DISABLED = {"sensor.woonkamer_signal_strength", "sensor.woonkamer_error_code"}


async def test_unique_ids_are_the_device_id_and_a_name_that_never_changes(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    registered = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    device_id = fake.state["DeviceId"]
    assert {found.entity_id: found.unique_id for found in registered} == {
        entity_id: f"{device_id}_{name}" for entity_id, name in UNIQUE_IDS.items()
    }
    assert {found.entity_id for found in registered if found.disabled_by is not None} == DISABLED


async def test_what_home_assistant_is_told_about_each_entity(
    hass: HomeAssistant, fake, setup, entity_registry_enabled_by_default: None
) -> None:
    entry = await setup()
    assert set(DESCRIBED) == set(UNIQUE_IDS)
    found: dict[str, tuple[Any, ...]] = {}
    for registered in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        attributes = hass.states.get(registered.entity_id).attributes
        category = registered.entity_category
        found[registered.entity_id] = (
            attributes.get("device_class"),
            attributes.get("state_class"),
            attributes.get("unit_of_measurement"),
            None if category is None else category.value,
        )
    assert found == DESCRIBED
