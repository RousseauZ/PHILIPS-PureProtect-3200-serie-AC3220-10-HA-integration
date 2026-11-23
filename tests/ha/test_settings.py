"""Switches and selects: what they show and what they send."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import until


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} does not exist"
    return found.state


async def switch(hass: HomeAssistant, name: str, on: bool) -> None:
    service = "turn_on" if on else "turn_off"
    await hass.services.async_call("switch", service, {"entity_id": f"switch.woonkamer_{name}"}, blocking=True)


async def select(hass: HomeAssistant, name: str, option: str) -> None:
    await hass.services.async_call(
        "select", "select_option", {"entity_id": f"select.woonkamer_{name}", "option": option}, blocking=True
    )


@pytest.mark.parametrize(
    ("name", "key", "on_value", "off_value"),
    [
        ("child_lock", "D03103", 1, 0),
        ("beep", "D03130", 100, 0),
        ("auto_plus", "D03180", 1, 0),
        ("allergy_sleep", "D03115", 1, 0),
        ("sensors_in_standby", "D03134", 1, 0),
        ("display", "D03112", 0, 1),  # the device stores "display off"
    ],
)
async def test_switch_writes_and_shows_its_key(
    hass: HomeAssistant, fake, setup, name: str, key: str, on_value: int, off_value: int
) -> None:
    await setup()
    await switch(hass, name, False)
    assert fake.state[key] == off_value and state(hass, f"switch.woonkamer_{name}") == "off"
    await switch(hass, name, True)
    assert fake.state[key] == on_value and state(hass, f"switch.woonkamer_{name}") == "on"


async def test_a_setting_is_refused_while_the_purifier_is_off(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.power_off()
    await until(hass, lambda: state(hass, "fan.woonkamer") == "off")
    sent = len(fake.controls)
    with pytest.raises(HomeAssistantError) as raised:
        await switch(hass, "child_lock", True)
    # The device would answer "success" and discard it; nothing is sent, and the user is told why.
    assert raised.value.translation_key == "device_off" and len(fake.controls) == sent
    assert state(hass, "switch.woonkamer_child_lock") == "off"


async def test_light_is_written_the_way_the_app_does(hass: HomeAssistant, fake, setup) -> None:
    # Whether the AC3220 takes brightness and scene from the network is still to be
    # measured; this test is about what is sent, on a device that takes them.
    fake.readonly_keys = set()
    await setup()
    last: Any = lambda: fake.controls[-1]

    await select(hass, "light", "off")
    assert last() == {"D03105": 0, "D03135": 0}
    assert state(hass, "select.woonkamer_light") == "off"
    # Brightness 0 has no name of its own: the light is off.
    assert state(hass, "select.woonkamer_light_brightness") == "unknown"

    # Back on needs a brightness again.
    await select(hass, "light", "air_quality")
    assert last() == {"D03135": 1, "D03105": 101}
    await select(hass, "light", "ambient")
    assert last() == {"D03135": 2}

    await select(hass, "light_brightness", "low")
    assert last() == {"D03105": 115} and state(hass, "select.woonkamer_light_brightness") == "low"

    await select(hass, "ambient_light_scene", "scene_2")
    assert last() == {"D03137": 2, "D03105": 101, "D03135": 2}
    assert state(hass, "select.woonkamer_ambient_light_scene") == "scene_2"
    assert state(hass, "select.woonkamer_light_brightness") == "auto"


async def test_timer_counts_from_two(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    await select(hass, "timer", "hours_1")
    assert fake.state["D03110"] == 2
    await select(hass, "timer", "hours_12")
    assert fake.state["D03110"] == 13 and state(hass, "select.woonkamer_timer") == "hours_12"
    await select(hass, "timer", "off")
    assert fake.state["D03110"] == 0


async def test_a_value_without_a_name_reads_as_unknown(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D03135", 7)
    await until(hass, lambda: state(hass, "select.woonkamer_light") == "unknown")


async def test_a_setting_the_device_ignores_is_reported_as_not_confirmed(hass: HomeAssistant, fake, setup) -> None:
    # Related models acknowledge a new brightness and keep the old one.
    fake.readonly_keys = {"D03105"}
    await setup()
    with pytest.raises(HomeAssistantError) as raised:
        await select(hass, "light_brightness", "low")
    assert raised.value.translation_key == "not_confirmed"
    assert state(hass, "select.woonkamer_light_brightness") == "auto"
