"""Sensors and warnings computed from the status."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import until


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} does not exist"
    return found.state


async def test_measurements(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D03224", 198)
    await until(hass, lambda: state(hass, "sensor.woonkamer_temperature") == "19.8")
    fake.change("D03125", 55)
    fake.change("D03120", 7)
    await until(hass, lambda: state(hass, "sensor.woonkamer_allergen_index") == "7")
    assert state(hass, "sensor.woonkamer_humidity") == "55"
    unit = hass.states.get("sensor.woonkamer_pm2_5").attributes["unit_of_measurement"]
    assert unit == "μg/m³"


async def test_filter_life_is_never_zero_while_hours_are_left(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D0540E", 4800)
    await until(hass, lambda: state(hass, "sensor.woonkamer_filter_life_remaining") == "50")
    fake.change("D0540E", 3)
    await until(hass, lambda: state(hass, "sensor.woonkamer_filter_life_remaining") == "1")
    assert state(hass, "binary_sensor.woonkamer_replace_filter") == "off"
    fake.change("D0540E", 0)
    await until(hass, lambda: state(hass, "binary_sensor.woonkamer_replace_filter") == "on")
    assert state(hass, "sensor.woonkamer_filter_life_remaining") == "0"


async def test_warnings(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D0520D", 0)
    await until(hass, lambda: state(hass, "binary_sensor.woonkamer_clean_filter") == "on")
    fake.change("D03240", 49408)
    await until(hass, lambda: state(hass, "binary_sensor.woonkamer_problem") == "on")


async def test_timer_end_is_a_moment_that_does_not_creep(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    assert state(hass, "sensor.woonkamer_timer_ends") == "unknown"
    fake.change("D03211", 120)
    await until(hass, lambda: state(hass, "sensor.woonkamer_timer_ends") != "unknown")
    first = state(hass, "sensor.woonkamer_timer_ends")
    ends = dt_util.parse_datetime(first)
    assert ends is not None and abs(ends - (dt_util.utcnow() + timedelta(minutes=120))) < timedelta(seconds=10)

    # Other news from the device does not move the moment by the seconds that passed.
    fake.change("D03221", 30)
    await until(hass, lambda: state(hass, "sensor.woonkamer_pm2_5") == "30")
    assert state(hass, "sensor.woonkamer_timer_ends") == first
    # A timer that is set again does.
    fake.change("D03211", 60)
    await until(hass, lambda: state(hass, "sensor.woonkamer_timer_ends") != first)
    fake.change("D03211", 0)
    await until(hass, lambda: state(hass, "sensor.woonkamer_timer_ends") == "unknown")


async def test_last_status_is_not_rewritten_with_every_frame(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    first = state(hass, "sensor.woonkamer_last_status_received")
    assert first not in ("unknown", "unavailable")
    for value in (10, 11, 12):
        fake.change("D03221", value)
        await until(hass, lambda value=value: state(hass, "sensor.woonkamer_pm2_5") == str(value))
    assert state(hass, "sensor.woonkamer_last_status_received") == first
