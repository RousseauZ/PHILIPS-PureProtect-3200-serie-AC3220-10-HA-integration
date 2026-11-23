"""Review, lens "device": the Home Assistant layer against the measured AC3220/10.

Every test in this file fails on the code as it was reviewed. Each one makes
the simulated purifier behave the way docs/metingen.md says the real one does
and then states what the owner should see. The numbers in the names are the
numbers of the issues in the review report.

The fast test timings are the production timings divided by about 12
(confirm_timeout 5 s is 0.4 s here), so the measured delays are scaled the same
way: the echo of a write (measured 0.1 to 1.1 s) is 0.05 s, the answer to a new
registration (0.2 to 1.9 s) is 0.1 s, and the fan speed that follows a mode
change in a frame of its own (0.1 to 1 s later) is 0.15 s.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from custom_components.philips_pureprotect.const import DOMAIN

from ..conftest import FAST, until

FAN = "fan.woonkamer"
CHILD_LOCK = "switch.woonkamer_child_lock"
POWER = "D03102"
MODE = "D0310C"
FAN_LEVEL = "D0310D"


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} does not exist"
    return found.state


def fan_attribute(hass: HomeAssistant, name: str) -> Any:
    found = hass.states.get(FAN)
    assert found is not None
    return found.attributes.get(name)


async def fan_call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call("fan", service, {"entity_id": FAN, **data}, blocking=True)


def measured_delays(fake: Any) -> None:
    """Give the simulated purifier the measured delays, scaled to the test timings."""
    fake.echo_delay = 0.05
    fake.registration_answer_delay = 0.1
    fake.speed_follows_after = 0.15


async def restart_while_the_purifier_went_to_standby(hass: HomeAssistant, fake: Any, setup: Any, entry: Any) -> None:
    """Stop Home Assistant with the purifier on, switch the purifier off, start Home Assistant again.

    Measured (measurements 2 and 8): in standby the purifier answers the ping,
    the sync and the info request, and sends no status at all, also not in
    answer to the registration of the new session. The stored status says "on".
    """
    await setup()
    assert state(hass, FAN) == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    fake.power_off(notify=False)
    await setup(live=False)
    session = entry.runtime_data.session
    await until(hass, lambda: session.available, "the purifier in standby does not answer the probes")
    assert not session.status_is_live and session.status[POWER] == 1  # the starting point: a stale "on"


# -- issue 1: fan.turn_on sends nothing when the last known status says "on" ------------------------


async def test_1_turn_on_after_a_restart_reaches_a_purifier_that_went_to_standby(
    hass: HomeAssistant, fake, setup, entry
) -> None:
    await restart_while_the_purifier_went_to_standby(hass, fake, setup, entry)
    sent = len(fake.controls)

    await fan_call(hass, "turn_on")

    assert fake.controls[sent:], "fan.turn_on sent nothing: it trusted a status from before the restart"
    await until(hass, lambda: fake.is_on, "the purifier is still off after fan.turn_on", timeout=2.0)
    assert state(hass, FAN) == "on"


async def test_1_a_mode_after_a_restart_switches_a_purifier_in_standby_on_first(
    hass: HomeAssistant, fake, setup, entry
) -> None:
    await restart_while_the_purifier_went_to_standby(hass, fake, setup, entry)

    # fan.py: "Set auto or sleep; switches on when needed."
    try:
        await fan_call(hass, "set_preset_mode", preset_mode="sleep")
    except HomeAssistantError as err:
        pytest.fail(
            f"the mode was written to a purifier in standby, which discards it: {err.translation_key} ({err}); "
            f"the purifier is {'on' if fake.is_on else 'still off'}"
        )
    assert fake.is_on and fake.state[MODE] == 17


async def test_1_turn_on_reaches_a_purifier_whose_switch_off_was_never_reported(
    hass: HomeAssistant, fake, setup
) -> None:
    await setup()
    # Someone presses the button on the purifier and the one frame that says so is lost. Status frames are
    # 1942 bytes, fragmented and unacknowledged (measurement 1), and in standby nothing follows.
    fake.drop_next_notifications = 1
    fake.power_off()
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert not fake.is_on and state(hass, FAN) == "on"  # Home Assistant cannot know

    await fan_call(hass, "turn_on")

    await until(hass, lambda: fake.is_on, "fan.turn_on sent nothing and the purifier stays off", timeout=2.0)


async def test_1_turn_on_right_after_turn_off_is_not_dropped(hass: HomeAssistant, fake, setup) -> None:
    measured_delays(fake)
    await setup()

    # Two automations, or a double tap: the purifier has accepted the switch-off and its report (measured:
    # about 0.1 s after a switch-off, up to 1.1 s after other writes) is still on its way when the
    # switch-on is asked for.
    sent = len(fake.controls)
    switch_off = asyncio.create_task(fan_call(hass, "turn_off"))
    while len(fake.controls) == sent:
        await asyncio.sleep(0.001)
    assert not fake.is_on and state(hass, FAN) == "on"
    await fan_call(hass, "turn_on")
    await switch_off

    await until(
        hass,
        lambda: fake.is_on and state(hass, FAN) == "on",
        "the last command was fan.turn_on, yet the purifier ended up off: the switch-on was never sent",
        timeout=2.0,
    )


# -- issue 2: after a restart the fan shows the stored "on" for as long as the purifier is in standby ----


async def test_2_fan_does_not_keep_showing_on_after_a_restart_with_the_purifier_in_standby(
    hass: HomeAssistant, fake, setup, entry
) -> None:
    measured_delays(fake)
    await restart_while_the_purifier_went_to_standby(hass, fake, setup, entry)

    # Measured over eight runs (docs/metingen.md, "Eerste statusbericht na een nieuw abonnement"): a purifier
    # that is on answers a registration from a new port within 0.2 to 1.9 s, six times out of six; one in
    # standby never does. A restart registers from a new port. This purifier answers the probes and has left
    # the registration unanswered for ten times the time the session allows for that answer: it is off.
    await asyncio.sleep(10 * FAST.request_status_timeout)
    await hass.async_block_till_done()

    assert entry.runtime_data.session.available and not entry.runtime_data.session.status_is_live
    assert state(hass, FAN) != "on", (
        "the fan still shows the 'on' of before the restart (with speed "
        f"{fan_attribute(hass, 'percentage')} % and mode {fan_attribute(hass, 'preset_mode')}) while the purifier "
        "is in standby, and will do so until someone touches the purifier"
    )


async def test_2_a_setting_after_a_restart_in_standby_is_refused_as_off(
    hass: HomeAssistant, fake, setup, entry
) -> None:
    measured_delays(fake)
    await restart_while_the_purifier_went_to_standby(hass, fake, setup, entry)
    await asyncio.sleep(10 * FAST.request_status_timeout)
    await hass.async_block_till_done()
    sent = len(fake.controls)

    # README: "Het apparaat negeert instellingen zolang het uit staat. Home Assistant stuurt ze dan niet en
    # meldt dat je het apparaat eerst moet aanzetten."
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call("switch", "turn_on", {"entity_id": CHILD_LOCK}, blocking=True)

    assert (raised.value.translation_key, fake.controls[sent:]) == ("device_off", []), (
        "the setting was sent to a purifier in standby and failed after the full confirmation wait "
        "(11 s at the production timings) with a message that does not say the purifier is off"
    )


# -- issue 3: a percentage is reported in auto and sleep, which Home Assistant's scenes cannot handle ----


async def test_3_restoring_a_scene_keeps_the_purifier_in_auto(hass: HomeAssistant, fake, setup, entry) -> None:
    await setup()
    assert await async_setup_component(hass, "scene", {})
    await hass.async_block_till_done()
    assert fake.state[MODE] == 0 and fan_attribute(hass, "preset_mode") == "auto"

    # The owner stores the state of the purifier: auto, which happens to run at speed 1 at that moment.
    await hass.services.async_call(
        "scene", "create", {"scene_id": "evening", "snapshot_entities": [FAN]}, blocking=True
    )
    # Later the air is worse and the purifier, still in auto, runs faster (measurement 6: the running speed
    # D0310D changes by itself while the mode D0310C stays 0).
    fake.change(FAN_LEVEL, 2)
    await until(hass, lambda: entry.runtime_data.value(FAN_LEVEL) == 2)
    sent = len(fake.controls)

    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.evening"}, blocking=True)
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()

    assert fake.state[MODE] == 0, (
        f"restoring a scene that says 'auto' took the purifier out of auto: it was sent {fake.controls[sent:]} "
        f"and now stays at that fixed speed (the fan shows mode {fan_attribute(hass, 'preset_mode')})"
    )


# -- issue 4: "Light: off" fails on a device that ignores the brightness, although the light goes off ----


async def test_4_light_off_succeeds_on_a_device_that_does_not_take_a_brightness(
    hass: HomeAssistant, fake, setup
) -> None:
    # What the simulated purifier does unless told otherwise, and what the nearest relative was seen to do
    # (docs/onderzoek.md, appendix A: D03105 is read-only on an AC4220/12, where D03135 does work). Whether
    # the AC3220 takes a brightness from the network is not measured yet.
    fake.readonly_keys = {"D03105"}
    await setup()
    assert state(hass, "select.woonkamer_light") == "ambient"

    try:
        await hass.services.async_call(
            "select", "select_option", {"entity_id": "select.woonkamer_light", "option": "off"}, blocking=True
        )
    except HomeAssistantError as err:
        pytest.fail(
            f"'Light: off' was reported as failed ({err.translation_key}) although the lamp function is "
            f"{fake.state['D03135']} now and the entity shows '{state(hass, 'select.woonkamer_light')}'"
        )
    assert fake.state["D03135"] == 0 and state(hass, "select.woonkamer_light") == "off"


# -- issue 5: a scene that switches on and changes a setting depends on the order of its entities ----


async def test_5_a_scene_can_switch_on_and_change_a_setting_in_any_order(hass: HomeAssistant, fake, setup) -> None:
    measured_delays(fake)
    await setup()
    assert await async_setup_component(hass, "scene", {})
    await hass.async_block_till_done()
    await fan_call(hass, "turn_off")
    assert state(hass, FAN) == "off" and state(hass, CHILD_LOCK) == "off"
    # Home Assistant loads the code that applies a scene to a domain on first use, which takes a moment
    # and shuffles the order once. A scene that changes nothing gets that out of the way.
    await hass.services.async_call("scene", "apply", {"entities": {CHILD_LOCK: "off", FAN: "off"}}, blocking=True)
    sent = len(fake.controls)

    # The same scene with the fan listed first works: the session holds the setting back until the
    # switch-on is confirmed. Home Assistant applies the domains of a scene at the same time, in the order
    # in which they first appear.
    try:
        await hass.services.async_call("scene", "apply", {"entities": {CHILD_LOCK: "on", FAN: "on"}}, blocking=True)
    except HomeAssistantError as err:
        await asyncio.sleep(0.3)
        pytest.fail(
            f"the scene failed on the setting while it was switching the purifier on: {err} "
            f"(sent: {fake.controls[sent:]})"
        )
    await until(hass, lambda: fake.is_on and fake.state["D03103"] == 1, "the scene was not applied", timeout=2.0)


# -- issue 6: after a speed change the fan shows the previous speed until the fan has spun up ----


async def test_6_the_new_speed_is_shown_as_soon_as_the_command_is_confirmed(hass: HomeAssistant, fake, setup) -> None:
    measured_delays(fake)  # the mode is reported first, the running speed 0.1 to 1 s later (measurement 6)
    fake.state[MODE] = 1  # fixed speed 1, running at speed 1
    await setup()
    assert fan_attribute(hass, "percentage") == 20 and fan_attribute(hass, "preset_mode") is None

    await fan_call(hass, "set_percentage", percentage=100)

    assert fake.state[MODE] == 5
    assert fan_attribute(hass, "percentage") == 100, (
        f"the command for 100 % was confirmed and the fan shows {fan_attribute(hass, 'percentage')} %: "
        "the speed from before the command"
    )


# -- issue 7: the stored status is only written after a minute of silence ----


async def test_7_the_status_is_saved_while_the_purifier_keeps_reporting(
    hass: HomeAssistant, fake, setup, entry, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # const.py: "The last status is written to disk at most this often (seconds)."
    monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.SAVE_DELAY", 0.3)
    await setup()
    key = f"{DOMAIN}.{entry.entry_id}"
    hass_storage.pop(key, None)

    # Measurement 12: a frame every 3.3 s on average, for eight hours. Here: a frame every 0.05 s for seven
    # times the save delay.
    for index in range(42):
        fake.change("D03221", 10 + index % 2)
        await asyncio.sleep(0.05)
        if key in hass_storage:
            break

    assert key in hass_storage, (
        "nothing was written while frames kept coming: every frame postpones the save by the full delay, so a "
        "purifier that reports every few seconds is only saved when Home Assistant stops cleanly"
    )


# -- issue 8: a switch-off that the purifier accepted leaves the fan "unknown" ----


async def test_8_an_accepted_switch_off_is_shown_as_off_when_nothing_was_known(
    hass: HomeAssistant, fake, setup, entry
) -> None:
    # Added while the purifier is in standby: it answers, it sends no status, the fan is "unknown".
    fake.power_off(notify=False)
    await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    assert state(hass, FAN) == "unknown"

    # Measured (measurement 5, rows 6 and 7): "success" to a switch-off means off, whatever the purifier
    # was, and in standby no frame follows. The session takes the answer for it after its full wait
    # (8 s at the production timings) and the call succeeds.
    await fan_call(hass, "turn_off")
    await hass.async_block_till_done()

    assert entry.runtime_data.session.diagnostics().switch_offs_assumed == 1
    assert state(hass, FAN) == "off", (
        f"the purifier accepted the switch-off, the call succeeded, and the fan still shows '{state(hass, FAN)}'"
    )


# -- issue 9: the stored status stays behind when the purifier is removed ----


async def test_9_removing_the_purifier_removes_its_stored_status(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any]
) -> None:
    entry = await setup()
    key = f"{DOMAIN}.{entry.entry_id}"

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage, (
        f"the file .storage/{key} with the last status (name and device id included) is left behind for good"
    )
