"""A purifier in standby cannot say that it is off: what Home Assistant shows and does then.

Measured (docs/metingen.md): in standby the purifier answers every probe and sends no status, also not in
answer to a registration; one that is on answers a registration from a new port within 0.2 to 1.9 s. The
session therefore takes a reachable purifier that sends nothing after its start to be in standby (after
10 s; 0.5 s in these tests), until a status says otherwise.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.philips_pureprotect.const import DOMAIN

from .conftest import FAST, measured_delays, options, restart_while_the_purifier_went_to_standby, state, until

FAN = "fan.woonkamer"
CHILD_LOCK = "switch.woonkamer_child_lock"
PM25 = "sensor.woonkamer_pm2_5"


async def switch_on_the_child_lock(hass: HomeAssistant) -> None:
    await hass.services.async_call("switch", "turn_on", {"entity_id": CHILD_LOCK}, blocking=True)


# -- after a restart ------------------------------------------------------------------------------------------------


async def test_after_a_restart_a_purifier_in_standby_is_shown_as_off(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any]
) -> None:
    measured_delays(fake)
    entry = await restart_while_the_purifier_went_to_standby(hass, fake, setup)
    session = entry.runtime_data.session

    await until(hass, lambda: session.presumed_standby, "the stored 'on' stays for as long as nobody touches it")

    assert session.available and not session.status_is_live
    assert state(hass, FAN) == "off"
    fan = hass.states.get(FAN)
    assert fan is not None and fan.attributes["percentage"] == 0 and fan.attributes["preset_mode"] is None
    assert state(hass, "sensor.woonkamer_fan_speed") == "0"
    # The settings are what they were when the purifier last reported; they do not change while it is off.
    assert state(hass, CHILD_LOCK) == "off" and state(hass, "select.woonkamer_light") == "ambient"
    # The readings are not: nothing is measured now.
    assert state(hass, PM25) == STATE_UNKNOWN and state(hass, "sensor.woonkamer_temperature") == STATE_UNKNOWN
    assert state(hass, "sensor.woonkamer_last_status_received") not in (STATE_UNKNOWN, STATE_UNAVAILABLE)

    # Switching on brings everything back.
    await hass.services.async_call("fan", "turn_on", {"entity_id": FAN}, blocking=True)
    assert fake.is_on and state(hass, FAN) == "on" and state(hass, PM25) == "3"
    assert not session.presumed_standby


async def test_a_setting_after_a_restart_in_standby_is_refused_as_off(hass: HomeAssistant, fake, setup) -> None:
    entry = await restart_while_the_purifier_went_to_standby(hass, fake, setup)
    await until(hass, lambda: entry.runtime_data.session.presumed_standby)
    sent = len(fake.controls)

    # README: "Weet Home Assistant dat het uit staat, dan stuurt het ze niet en meldt het dat je het
    # apparaat eerst moet aanzetten."
    with pytest.raises(HomeAssistantError) as raised:
        await switch_on_the_child_lock(hass)

    assert (raised.value.translation_key, fake.controls[sent:]) == ("device_off", [])


async def test_a_setting_right_after_a_restart_waits_until_it_is_known_whether_the_purifier_is_on(
    hass: HomeAssistant, fake, setup
) -> None:
    entry = await restart_while_the_purifier_went_to_standby(hass, fake, setup)
    session = entry.runtime_data.session
    sent = len(fake.controls)
    loop_time = hass.loop.time
    began = loop_time()

    # The stored status says on. Sent now, the setting would be answered "success", discarded, and
    # reported as not confirmed after the whole confirmation time.
    with pytest.raises(HomeAssistantError) as raised:
        await switch_on_the_child_lock(hass)

    assert (raised.value.translation_key, fake.controls[sent:]) == ("device_off", [])
    assert session.presumed_standby and loop_time() - began < 3 * FAST.standby_presume_after


async def test_a_purifier_that_is_on_is_never_shown_as_off_after_a_restart(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    measured_delays(fake)
    # The answer to the registration comes after 0.1 s here; a wide margin, as at the real timings.
    presume_after = 1.0
    monkeypatch.setattr(
        "custom_components.philips_pureprotect.coordinator.SESSION_OPTIONS",
        options(standby_presume_after=presume_after),
    )
    entry = await setup()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    shown: list[str] = []

    @callback
    def record(event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        assert new_state is not None
        shown.append(new_state.state)

    stop_recording = async_track_state_change_event(hass, FAN, record)
    await setup()
    session = entry.runtime_data.session
    # Well past the time after which standby would be presumed.
    await until(hass, lambda: session.diagnostics().seconds_since_last_frame > 1.5 * presume_after)
    stop_recording()

    assert not session.presumed_standby and session.diagnostics().standby_presumptions == 0
    assert state(hass, FAN) == "on" and "off" not in shown, shown


async def test_a_running_purifier_whose_answer_was_lost_is_shown_as_on_with_its_next_status(
    hass: HomeAssistant, fake, setup
) -> None:
    entry = await setup()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    fake.answer_registration = "on_change"  # as if the answers to the registrations were lost
    await setup(live=False)
    session = entry.runtime_data.session
    # The price of the rule: shown as off although it runs...
    await until(hass, lambda: session.presumed_standby)
    assert fake.is_on and state(hass, FAN) == "off" and state(hass, PM25) == STATE_UNKNOWN

    # ...until its next status, which a running purifier sends every few seconds (measurement 12).
    fake.change("D03221", 9)
    await until(hass, lambda: state(hass, FAN) == "on")
    assert state(hass, PM25) == "9" and not session.presumed_standby


async def test_the_presumed_standby_is_what_the_next_start_begins_with(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.SAVE_DELAY", 0.05)
    entry = await restart_while_the_purifier_went_to_standby(hass, fake, setup)
    key = f"{DOMAIN}.{entry.entry_id}"
    assert hass_storage[key]["data"]["status"]["D03102"] == 1
    await until(hass, lambda: entry.runtime_data.session.presumed_standby)
    # Power is one of the things that are written soon.
    await until(hass, lambda: hass_storage[key]["data"]["status"]["D03102"] == 0, "the file still says on")


# -- a purifier that was added while it was off ----------------------------------------------------------------------


async def test_a_purifier_that_was_added_while_off_is_shown_as_off(hass: HomeAssistant, fake, setup) -> None:
    fake.power_off(notify=False)
    entry = await setup(live=False)
    session = entry.runtime_data.session
    await until(hass, lambda: session.presumed_standby, "nothing was concluded from the silence")

    assert session.status is None
    assert state(hass, FAN) == "off"
    # README: "dan toont de ventilator na ongeveer tien seconden "uit" en zijn de overige waarden onbekend
    # tot je hem aanzet".
    assert state(hass, CHILD_LOCK) == STATE_UNKNOWN and state(hass, PM25) == STATE_UNKNOWN
    assert state(hass, "select.woonkamer_timer") == STATE_UNKNOWN

    await hass.services.async_call("fan", "turn_on", {"entity_id": FAN}, blocking=True)
    assert fake.is_on and state(hass, FAN) == "on"
    assert state(hass, CHILD_LOCK) == "off" and state(hass, PM25) == "3"


async def test_a_setting_on_a_purifier_that_was_added_while_off_says_to_switch_it_on(
    hass: HomeAssistant, fake, setup
) -> None:
    fake.power_off(notify=False)
    entry = await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    sent = len(fake.controls)

    # Asked at once, while nothing is known yet: the setting waits for the outcome and is not sent.
    with pytest.raises(HomeAssistantError) as raised:
        await switch_on_the_child_lock(hass)
    assert (raised.value.translation_key, fake.controls[sent:]) == ("device_off", [])
    # And again, now that it is known.
    with pytest.raises(HomeAssistantError) as raised:
        await switch_on_the_child_lock(hass)
    assert (raised.value.translation_key, fake.controls[sent:]) == ("device_off", [])


async def test_an_accepted_switch_off_is_shown_as_off_when_nothing_was_known(
    hass: HomeAssistant, fake, setup, slow_to_presume: None
) -> None:
    # The first seconds after adding a purifier that is off: it answers, it sends no status, the fan is "unknown".
    fake.power_off(notify=False)
    entry = await setup(live=False)
    session = entry.runtime_data.session
    await until(hass, lambda: session.available)
    assert state(hass, FAN) == STATE_UNKNOWN

    # Measured (measurement 5, rows 6 and 7): "success" to a switch-off means off, whatever the purifier
    # was, and in standby no frame follows.
    await hass.services.async_call("fan", "turn_off", {"entity_id": FAN}, blocking=True)
    await hass.async_block_till_done()

    assert session.diagnostics().switch_offs_assumed == 1 and session.status is None
    assert state(hass, FAN) == "off"
