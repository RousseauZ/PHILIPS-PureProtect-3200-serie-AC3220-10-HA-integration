"""Loading, unloading, availability and the entities of a purifier."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.philips_pureprotect.const import DOMAIN

from .conftest import until

OTHER_DEVICE = "99999999888811ef93334444555566bb"


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} does not exist"
    return found.state


async def test_setup_creates_the_entities_of_the_device(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    assert entry.state is ConfigEntryState.LOADED
    states = {found.entity_id: found.state for found in hass.states.async_all()}
    assert states == {
        "fan.woonkamer": "on",
        "binary_sensor.woonkamer_replace_filter": "off",
        "binary_sensor.woonkamer_clean_filter": "off",
        "binary_sensor.woonkamer_problem": "off",
        "select.woonkamer_light": "ambient",
        "select.woonkamer_light_brightness": "auto",
        "select.woonkamer_ambient_light_scene": "scene_4",
        "select.woonkamer_timer": "off",
        "sensor.woonkamer_last_status_received": states["sensor.woonkamer_last_status_received"],
        "sensor.woonkamer_pm2_5": "3",
        "sensor.woonkamer_allergen_index": "1",
        "sensor.woonkamer_temperature": "21.2",
        "sensor.woonkamer_humidity": "47",
        "sensor.woonkamer_filter_life_remaining": "100",
        "sensor.woonkamer_filter_cleaning_due_in": "720",
        "sensor.woonkamer_timer_ends": STATE_UNKNOWN,
        "switch.woonkamer_child_lock": "off",
        "switch.woonkamer_beep": "on",
        "switch.woonkamer_auto_plus": "off",
        "switch.woonkamer_allergy_sleep": "off",
        "switch.woonkamer_sensors_in_standby": "off",
        "switch.woonkamer_display": "on",
    }
    # Diagnostic values that few people need exist, but are switched off.
    registry = er.async_get(hass)
    for entity_id in ("sensor.woonkamer_signal_strength", "sensor.woonkamer_error_code", "sensor.woonkamer_fan_level"):
        registered = registry.async_get(entity_id)
        assert registered is not None and registered.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, fake.state["DeviceId"]), entry.entry_id)
    assert device is not None
    assert (device.manufacturer, device.model, device.sw_version, device.name) == (
        "Philips",
        "AC3220/10",
        "0.2.3",
        "Woonkamer",
    )


async def test_unload_stops_the_session(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    session = entry.runtime_data.session
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not session.available and state(hass, "fan.woonkamer") == STATE_UNAVAILABLE


async def test_a_change_on_the_device_reaches_the_entities(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D03221", 42)
    await until(hass, lambda: state(hass, "sensor.woonkamer_pm2_5") == "42")
    fake.change("D03103", 1)
    await until(hass, lambda: state(hass, "switch.woonkamer_child_lock") == "on")


async def test_setup_does_not_wait_for_a_device_that_is_away(hass: HomeAssistant, fake, setup) -> None:
    fake.silent = True
    entry = await setup(live=False)
    assert entry.state is ConfigEntryState.LOADED
    # Nothing is known and nothing answers: the entities of the model exist, unavailable.
    assert state(hass, "fan.woonkamer") == STATE_UNAVAILABLE
    assert state(hass, "sensor.woonkamer_pm2_5") == STATE_UNAVAILABLE
    fake.silent = False
    await until(hass, lambda: state(hass, "fan.woonkamer") == "on")
    assert state(hass, "sensor.woonkamer_pm2_5") == "3"


async def test_a_device_in_standby_is_available_with_unknown_values(hass: HomeAssistant, fake, setup) -> None:
    fake.power_off(notify=False)
    entry = await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    # It answers, but a purifier in standby sends no status until something changes.
    assert state(hass, "fan.woonkamer") == STATE_UNKNOWN
    assert state(hass, "switch.woonkamer_child_lock") == STATE_UNKNOWN
    fake.power_on()
    await until(hass, lambda: state(hass, "fan.woonkamer") == "on")
    assert state(hass, "switch.woonkamer_child_lock") == "off"


async def test_the_last_status_survives_a_restart(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any]
) -> None:
    entry = await setup()
    fake.change("D03221", 17)
    await until(hass, lambda: state(hass, "sensor.woonkamer_pm2_5") == "17")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["status"]["D03221"] == 17

    # While Home Assistant was down the purifier went to standby: it answers, but sends nothing.
    fake.power_off(notify=False)
    await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    assert not entry.runtime_data.session.status_is_live
    assert state(hass, "sensor.woonkamer_pm2_5") == "17"
    assert state(hass, "sensor.woonkamer_last_status_received") not in (STATE_UNKNOWN, STATE_UNAVAILABLE)


async def test_an_entity_appears_when_the_device_starts_to_report_its_key(hass: HomeAssistant, fake, setup) -> None:
    del fake.state["D03112"]
    entry = await setup()
    # Created at first on the assumption of the model, and removed when the
    # first status showed that this device has no such key.
    assert hass.states.get("switch.woonkamer_display") is None
    assert er.async_get(hass).async_get("switch.woonkamer_display") is None
    assert not entry.runtime_data.keys_assumed
    assert hass.states.get("switch.woonkamer_child_lock") is not None
    fake.change("D03112", 1)
    await until(hass, lambda: hass.states.get("switch.woonkamer_display") is not None)
    assert state(hass, "switch.woonkamer_display") == "off"


async def test_entities_go_unavailable_only_when_the_device_is_gone(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    session = entry.runtime_data.session
    fake.silent = True
    await until(hass, lambda: not session.available, "the session never went offline")
    assert state(hass, "fan.woonkamer") == STATE_UNAVAILABLE
    fake.silent = False
    await until(hass, lambda: state(hass, "fan.woonkamer") == "on", "the session never came back")


async def test_another_device_at_the_address_raises_a_repair_issue(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    issues = ir.async_get(hass)
    issue_id = f"wrong_device_{entry.entry_id}"
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    ours = fake.state["DeviceId"]
    fake.state["DeviceId"] = OTHER_DEVICE
    fake.change("D03221", 99)
    await until(hass, lambda: issues.async_get_issue(DOMAIN, issue_id) is not None, "no repair issue")
    assert state(hass, "fan.woonkamer") == STATE_UNAVAILABLE
    assert state(hass, "sensor.woonkamer_pm2_5") == STATE_UNAVAILABLE  # the other device's 99 is not shown

    fake.state["DeviceId"] = ours
    fake.change("D03221", 5)
    await until(hass, lambda: issues.async_get_issue(DOMAIN, issue_id) is None, "the repair issue stayed")
    assert state(hass, "sensor.woonkamer_pm2_5") == "5"
