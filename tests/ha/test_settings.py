"""Switches and selects: what they show and what they send."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from .conftest import measured_delays, state, until


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


@pytest.mark.parametrize(
    "order", [("switch.woonkamer_child_lock", "fan.woonkamer"), ("fan.woonkamer", "switch.woonkamer_child_lock")]
)
async def test_a_scene_can_switch_on_and_change_a_setting_in_any_order(
    hass: HomeAssistant, fake, setup, order: tuple[str, str]
) -> None:
    measured_delays(fake)
    await setup()
    assert await async_setup_component(hass, "scene", {})
    await hass.async_block_till_done()
    await hass.services.async_call("fan", "turn_off", {"entity_id": "fan.woonkamer"}, blocking=True)
    assert state(hass, "fan.woonkamer") == "off" and state(hass, "switch.woonkamer_child_lock") == "off"
    # Home Assistant loads the code that applies a scene to a domain on first use, which takes a moment
    # and shuffles the order once. A scene that changes nothing gets that out of the way.
    nothing = {"switch.woonkamer_child_lock": "off", "fan.woonkamer": "off"}
    await hass.services.async_call("scene", "apply", {"entities": nothing}, blocking=True)
    sent = len(fake.controls)

    # Home Assistant applies the domains of a scene at the same time, in the order in which they first
    # appear. With the setting first it finds the purifier off; a moment later the switch-on is under way.
    await hass.services.async_call("scene", "apply", {"entities": dict.fromkeys(order, "on")}, blocking=True)

    await until(hass, lambda: fake.is_on and fake.state["D03103"] == 1, "the scene was not applied", timeout=2.0)
    assert fake.controls[sent:] == [{"D03102": 1}, {"D03103": 1}]
    assert state(hass, "switch.woonkamer_child_lock") == "on"


async def test_what_the_light_selects_send(hass: HomeAssistant, fake, setup) -> None:
    # Whether the AC3220 takes brightness and scene from the network is still to be
    # measured; this test is about what is sent, on a device that takes them.
    fake.readonly_keys = set()
    await setup()
    last: Any = lambda: fake.controls[-1]

    # Off is the lamp function alone, so that it is confirmed on a key that related models do take.
    await select(hass, "light", "off")
    assert last() == {"D03135": 0}
    assert state(hass, "select.woonkamer_light") == "off"
    assert state(hass, "select.woonkamer_light_brightness") == "auto"  # left as it was

    # Back on is the lamp function alone as well, while there is a brightness.
    await select(hass, "light", "air_quality")
    assert last() == {"D03135": 1}
    await select(hass, "light", "ambient")
    assert last() == {"D03135": 2}

    await select(hass, "light_brightness", "low")
    assert last() == {"D03105": 115} and state(hass, "select.woonkamer_light_brightness") == "low"

    # The Air+ app switches the light off with brightness 0 as well (measurements 6 and 7).
    fake.change("D03105", 0)
    fake.change("D03135", 0)
    await until(hass, lambda: state(hass, "select.woonkamer_light") == "off")
    # Brightness 0 has no name of its own: the light is off.
    assert state(hass, "select.woonkamer_light_brightness") == "unknown"
    # Coming back from that needs a brightness again, or the light would stay dark.
    await select(hass, "light", "air_quality")
    assert last() == {"D03135": 1, "D03105": 101}
    assert state(hass, "select.woonkamer_light_brightness") == "auto"

    # A scene is chosen the way the app does: with the ambient light on, at automatic brightness.
    await select(hass, "light_brightness", "low")
    await select(hass, "ambient_light_scene", "scene_2")
    assert last() == {"D03137": 2, "D03105": 101, "D03135": 2}
    assert state(hass, "select.woonkamer_ambient_light_scene") == "scene_2"
    assert state(hass, "select.woonkamer_light_brightness") == "auto"
    assert state(hass, "select.woonkamer_light") == "ambient"


async def test_light_off_succeeds_on_a_device_that_does_not_take_a_brightness(hass: HomeAssistant, fake, setup) -> None:
    # What the nearest relative was seen to do (docs/onderzoek.md, appendix A: D03105 is read-only on an
    # AC4220/12, where D03135 does work): a brightness is answered "success" and discarded.
    fake.readonly_keys = {"D03105"}
    await setup()
    assert state(hass, "select.woonkamer_light") == "ambient"

    await select(hass, "light", "off")

    assert fake.state["D03135"] == 0 and state(hass, "select.woonkamer_light") == "off"
    await select(hass, "light", "air_quality")
    assert fake.state["D03135"] == 1 and state(hass, "select.woonkamer_light") == "air_quality"


async def test_every_choice_is_written_as_the_value_of_the_device(hass: HomeAssistant, fake, setup) -> None:
    fake.readonly_keys = set()  # a device that takes brightness and scene from the network
    await setup()
    expected = {
        "light": ("D03135", {"off": 0, "air_quality": 1, "ambient": 2}),
        "light_brightness": ("D03105", {"auto": 101, "low": 115, "bright": 123}),
        "ambient_light_scene": ("D03137", {"scene_1": 1, "scene_2": 2, "scene_3": 3, "scene_4": 4}),
        "timer": ("D03110", {"off": 0} | {f"hours_{hours}": hours + 1 for hours in range(1, 13)}),
    }
    for name, (key, choices) in expected.items():
        entity_id = f"select.woonkamer_{name}"
        assert hass.states.get(entity_id).attributes["options"] == list(choices)
        for option, value in choices.items():
            await select(hass, name, option)
            assert fake.state[key] == value, f"{name}: {option}"
            assert state(hass, entity_id) == option


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
