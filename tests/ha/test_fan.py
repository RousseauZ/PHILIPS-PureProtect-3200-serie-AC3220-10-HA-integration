"""The fan: power, the modes auto and sleep, and five speeds."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import until

FAN = "fan.woonkamer"


def fan(hass: HomeAssistant) -> Any:
    found = hass.states.get(FAN)
    assert found is not None
    return found


async def call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call("fan", service, {"entity_id": FAN, **data}, blocking=True)


async def test_state_follows_mode_and_running_speed(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    assert fan(hass).state == "on"
    assert fan(hass).attributes["preset_mode"] == "auto" and fan(hass).attributes["preset_modes"] == ["auto", "sleep"]
    assert fan(hass).attributes["percentage"] == 20 and fan(hass).attributes["percentage_step"] == 20

    # Turbo and medium are buttons on the device; here they are 100 % and 60 %.
    fake.change("D0310C", 18)
    await until(hass, lambda: fan(hass).attributes["percentage"] == 100)
    assert fan(hass).attributes["preset_mode"] is None
    fake.change("D0310C", 19)
    await until(hass, lambda: fan(hass).attributes["percentage"] == 60)
    fake.change("D0310C", 17)
    await until(hass, lambda: fan(hass).attributes["preset_mode"] == "sleep")

    fake.power_off()
    await until(hass, lambda: fan(hass).state == "off")
    assert fan(hass).attributes["percentage"] == 0 and fan(hass).attributes["preset_mode"] is None


async def test_turn_off_and_on(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    await call(hass, "turn_off")
    assert not fake.is_on and fan(hass).state == "off"
    await call(hass, "turn_on")
    assert fake.is_on and fan(hass).state == "on"


async def test_speed_is_written_as_a_mode(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    for percentage, mode in ((100, 5), (60, 3), (50, 3), (1, 1), (20, 1), (81, 5)):
        await call(hass, "set_percentage", percentage=percentage)
        assert fake.state["D0310C"] == mode, percentage
    await call(hass, "set_percentage", percentage=0)
    assert not fake.is_on


async def test_preset_mode(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    await call(hass, "set_preset_mode", preset_mode="sleep")
    assert fake.state["D0310C"] == 17 and fan(hass).attributes["preset_mode"] == "sleep"
    await call(hass, "set_preset_mode", preset_mode="auto")
    assert fake.state["D0310C"] == 0


async def test_a_mode_or_speed_switches_a_purifier_on_first(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    await call(hass, "turn_off")
    controls_before = len(fake.controls)
    await call(hass, "turn_on", preset_mode="sleep")
    assert fake.is_on and fake.state["D0310C"] == 17
    # Two messages: the device discards a setting it gets while it is off.
    assert [set(values) for values in fake.controls[controls_before:]] == [{"D03102"}, {"D0310C"}]

    await call(hass, "turn_off")
    await call(hass, "set_percentage", percentage=80)
    assert fake.is_on and fake.state["D0310C"] == 4


async def test_a_refused_command_is_an_error_the_user_sees(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.refuse_control = True
    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_off")
    assert raised.value.translation_key == "refused" and raised.value.translation_domain == "philips_pureprotect"
    assert fake.is_on and fan(hass).state == "on"


async def test_a_command_to_a_silent_device_is_an_error(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.control_enabled = False
    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_off")
    assert raised.value.translation_key == "unreachable"
