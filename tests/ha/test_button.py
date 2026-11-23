"""The button for a cleaned filter."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import until

BUTTON = "button.woonkamer_filter_cleaned"


async def press(hass: HomeAssistant) -> None:
    await hass.services.async_call("button", "press", {"entity_id": BUTTON}, blocking=True)


async def test_filter_cleaned_sets_the_counter_back_as_the_app_does(hass: HomeAssistant, fake, setup) -> None:
    fake.state["D0520D"] = 12
    await setup()
    assert hass.states.get("sensor.woonkamer_filter_cleaning_due_in").state == "12"
    await press(hass)
    # The full interval, which the device reports itself (measurements 7 and 14).
    assert fake.controls[-1] == {"D0520D": 720} and fake.state["D0520D"] == 720
    assert hass.states.get("sensor.woonkamer_filter_cleaning_due_in").state == "720"
    assert hass.states.get("binary_sensor.woonkamer_clean_filter").state == "off"


async def test_filter_cleaned_follows_the_interval_the_device_reports(hass: HomeAssistant, fake, setup) -> None:
    fake.state["D05207"] = 360
    fake.state["D0520D"] = 0
    await setup()
    assert hass.states.get("binary_sensor.woonkamer_clean_filter").state == "on"
    await press(hass)
    assert fake.state["D0520D"] == 360
    await until(hass, lambda: hass.states.get("binary_sensor.woonkamer_clean_filter").state == "off")


async def test_filter_cleaned_is_refused_while_the_purifier_is_off(hass: HomeAssistant, fake, setup) -> None:
    fake.state["D0520D"] = 12
    await setup()
    fake.power_off()
    await until(hass, lambda: hass.states.get("fan.woonkamer").state == "off")
    sent = len(fake.controls)
    with pytest.raises(HomeAssistantError) as raised:
        await press(hass)
    assert raised.value.translation_key == "device_off" and len(fake.controls) == sent
    assert fake.state["D0520D"] == 12


async def test_filter_cleaned_needs_an_interval(hass: HomeAssistant, fake, setup) -> None:
    fake.state["D05207"] = 0
    await setup()
    sent = len(fake.controls)
    with pytest.raises(HomeAssistantError) as raised:
        await press(hass)
    assert raised.value.translation_key == "filter_interval_unknown" and len(fake.controls) == sent
