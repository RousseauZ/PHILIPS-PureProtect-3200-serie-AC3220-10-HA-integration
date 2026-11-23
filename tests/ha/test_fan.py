"""The fan: power, the modes auto and sleep, and five speeds."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from .conftest import measured_delays, restart_while_the_purifier_went_to_standby, state, until

FAN = "fan.woonkamer"
FAN_SPEED = "sensor.woonkamer_fan_speed"


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
    # In auto and sleep there is no percentage: Home Assistant takes percentage and preset mode as
    # excluding each other. What the fan really does is in a sensor of its own.
    assert fan(hass).attributes["percentage"] is None and fan(hass).attributes["percentage_step"] == 20
    assert state(hass, FAN_SPEED) == "1"

    # Turbo and medium are buttons on the device; here they are 100 % and 60 %.
    fake.change("D0310C", 18)
    await until(hass, lambda: fan(hass).attributes["percentage"] == 100)
    assert fan(hass).attributes["preset_mode"] is None
    fake.change("D0310C", 19)
    await until(hass, lambda: fan(hass).attributes["percentage"] == 60)
    fake.change("D0310C", 17)
    await until(hass, lambda: fan(hass).attributes["preset_mode"] == "sleep")
    assert fan(hass).attributes["percentage"] is None

    fake.power_off()
    await until(hass, lambda: fan(hass).state == "off")
    assert fan(hass).attributes["percentage"] == 0 and fan(hass).attributes["preset_mode"] is None


async def test_the_running_speed_is_a_sensor_of_its_own(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    # In auto the purifier picks its speed itself (measurement 6); the fan entity shows no percentage then.
    for level, step in ((2, "2"), (4, "4"), (18, "5")):  # the device calls its highest speed 18
        fake.change("D0310D", level)
        await until(hass, lambda step=step: state(hass, FAN_SPEED) == step)
        assert fan(hass).attributes["preset_mode"] == "auto" and fan(hass).attributes["percentage"] is None
    fake.change("D0310D", 7)  # a value nobody has seen
    await until(hass, lambda: state(hass, FAN_SPEED) == "unknown")
    fake.power_off()
    await until(hass, lambda: state(hass, FAN_SPEED) == "0")


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


async def test_a_mode_goes_out_alone_to_a_purifier_that_reported_itself_on(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    sent = len(fake.controls)
    await call(hass, "set_preset_mode", preset_mode="sleep")
    await call(hass, "set_percentage", percentage=40)
    # A status of this session shows it on: no need to switch on what is on.
    assert fake.controls[sent:] == [{"D0310C": 17}, {"D0310C": 2}]


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


# -- "on" in Home Assistant is not proof that the purifier is on ---------------------------------------------------
#
# A purifier in standby reports nothing. A status from before a restart, or one whose switch-off frame was
# lost, therefore goes on saying "on" (found by the reviews of 23 November 2026).


async def test_turn_on_is_sent_to_a_purifier_that_went_to_standby_during_a_restart(
    hass: HomeAssistant, fake, setup, slow_to_presume: None
) -> None:
    await restart_while_the_purifier_went_to_standby(hass, fake, setup)
    assert fan(hass).state == "on" and not fake.is_on  # the first seconds: what was stored is all there is
    sent = len(fake.controls)

    await call(hass, "turn_on")

    assert fake.controls[sent:] == [{"D03102": 1}], "fan.turn_on trusted a status from before the restart"
    assert fake.is_on and fan(hass).state == "on"


async def test_a_mode_switches_a_purifier_on_that_went_to_standby_during_a_restart(
    hass: HomeAssistant, fake, setup, slow_to_presume: None
) -> None:
    await restart_while_the_purifier_went_to_standby(hass, fake, setup)
    assert fan(hass).state == "on" and not fake.is_on
    sent = len(fake.controls)

    # Without the power key the mode would be answered "success" and discarded.
    await call(hass, "set_preset_mode", preset_mode="sleep")

    assert fake.controls[sent:] == [{"D03102": 1}, {"D0310C": 17}]
    assert fake.is_on and fake.state["D0310C"] == 17 and fan(hass).attributes["preset_mode"] == "sleep"


async def test_turn_on_is_sent_after_the_frame_of_a_switch_off_was_lost(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    # Someone presses the button on the purifier and the one frame that says so is lost: status frames
    # are 1942 bytes, fragmented and unacknowledged (measurement 1), and in standby nothing follows.
    fake.drop_next_notifications = 1
    fake.power_off()
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert not fake.is_on and fan(hass).state == "on"  # Home Assistant cannot know

    await call(hass, "turn_on")

    assert fake.is_on and fan(hass).state == "on"


async def test_turn_on_right_after_turn_off_is_not_dropped(hass: HomeAssistant, fake, setup) -> None:
    measured_delays(fake)
    await setup()
    # Two automations, or a double tap: the purifier has accepted the switch-off and its report is still
    # on its way when the switch-on is asked for.
    sent = len(fake.controls)
    switch_off = asyncio.create_task(call(hass, "turn_off"))
    while len(fake.controls) == sent:
        await asyncio.sleep(0.001)
    assert not fake.is_on and fan(hass).state == "on"
    await call(hass, "turn_on")
    await switch_off

    await until(hass, lambda: fake.is_on and fan(hass).state == "on", "the purifier ended up off", timeout=2.0)


# -- percentage and preset mode exclude each other -----------------------------------------------------------------


async def test_a_scene_made_in_auto_leaves_the_purifier_in_auto(hass: HomeAssistant, fake, setup) -> None:
    assert await async_setup_component(hass, "scene", {})
    entry = await setup()
    assert fan(hass).attributes["preset_mode"] == "auto"
    await hass.services.async_call("scene", "create", {"scene_id": "night", "snapshot_entities": [FAN]}, blocking=True)

    fake.change("D0310D", 2)  # later the air is worse and auto runs faster (measurement 6)
    await until(hass, lambda: entry.runtime_data.value("D0310D") == 2)
    sent = len(fake.controls)

    # Home Assistant restores a fan from its attributes; with a percentage stored next to "auto" it
    # would send that percentage, as a fixed speed.
    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.night"}, blocking=True)
    await hass.async_block_till_done()
    assert fake.state["D0310C"] == 0, f"the scene took the purifier out of auto: {fake.controls[sent:]}"
    assert fan(hass).attributes["preset_mode"] == "auto"


async def test_a_scene_made_at_a_fixed_speed_brings_that_speed_back(hass: HomeAssistant, fake, setup) -> None:
    assert await async_setup_component(hass, "scene", {})
    entry = await setup()
    await call(hass, "set_percentage", percentage=60)
    await until(hass, lambda: fan(hass).attributes["percentage"] == 60)
    await hass.services.async_call("scene", "create", {"scene_id": "speed3", "snapshot_entities": [FAN]}, blocking=True)

    await call(hass, "set_preset_mode", preset_mode="auto")
    await until(hass, lambda: entry.runtime_data.value("D0310D") == 1)  # the speed auto starts with
    fake.change("D0310D", 3)  # later auto happens to run at the speed the scene stored
    await until(hass, lambda: entry.runtime_data.value("D0310D") == 3)
    assert fake.state["D0310C"] == 0 and fan(hass).attributes["preset_mode"] == "auto"

    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.speed3"}, blocking=True)
    assert fake.state["D0310C"] == 3, "the scene left the purifier in auto"


async def test_a_confirmed_speed_is_shown_at_once(hass: HomeAssistant, fake, setup) -> None:
    # The mode is reported first and confirms the command; the running speed follows in a frame of its
    # own (measurement 6). Read from the running speed, the slider would spring back after every change.
    measured_delays(fake)
    fake.speed_follows_after = 0.5  # the slow end of what was measured, so that there is time to look
    fake.state["D0310C"] = 1  # fixed speed 1, running at speed 1
    await setup()
    assert fan(hass).attributes["percentage"] == 20 and fan(hass).attributes["preset_mode"] is None

    await call(hass, "set_percentage", percentage=100)

    assert fake.state["D0310C"] == 5 and fake.state["D0310D"] == 1  # the fan has not spun up yet
    assert fan(hass).attributes["percentage"] == 100
    await until(hass, lambda: state(hass, FAN_SPEED) == "5")
    assert fan(hass).attributes["percentage"] == 100


async def test_two_quick_steps_up_are_two_steps(hass: HomeAssistant, fake, setup) -> None:
    # fan.increase_speed computes from the percentage of the entity.
    fake.speed_follows_after = 0.5
    fake.state["D0310C"] = 1
    await setup()
    assert fan(hass).attributes["percentage"] == 20
    await call(hass, "increase_speed")
    await call(hass, "increase_speed")
    assert fake.state["D0310C"] == 3


async def test_a_mode_without_a_known_speed_falls_back_on_the_running_speed(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.state["D0310C"] = 33  # a mode this integration has no speed for
    fake.change("D0310D", 4)
    await until(hass, lambda: fan(hass).attributes["percentage"] == 80)
    assert fan(hass).attributes["preset_mode"] is None
