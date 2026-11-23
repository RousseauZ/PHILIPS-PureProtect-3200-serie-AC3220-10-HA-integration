"""Review, lens "ux": what the owner sees in Home Assistant.

Three tests here fail on the code as reviewed, and each names the defect it proves:

    test_1_readings_are_not_shown_as_current_while_the_purifier_does_not_measure
    test_2_a_setting_on_a_purifier_that_was_added_while_off_says_to_switch_it_on
    test_3_the_integration_ships_its_icon

test_1_readings_stay_while_the_sensors_run_in_standby passes today: it is the other half of
issue 1 and bounds its fix.

The tests that pass today and defend rules that no test noticed when they were broken are in
test_review_ux_guards.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant import loader
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.philips_pureprotect.const import DOMAIN

from ..conftest import until

MEASUREMENTS = (
    "sensor.woonkamer_pm2_5",
    "sensor.woonkamer_allergen_index",
    "sensor.woonkamer_temperature",
    "sensor.woonkamer_humidity",
)


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} does not exist"
    return found.state


# -- issue 1: a purifier that is off shows the readings of the moment it was switched off, as if current ----


async def test_1_readings_are_not_shown_as_current_while_the_purifier_does_not_measure(
    hass: HomeAssistant, fake, setup
) -> None:
    """Off, with "Sensors in standby" off, the purifier measures nothing and reports nothing.

    Measured (docs/metingen.md, 2 and 5): no status frame at all in standby. Home Assistant
    then keeps PM2.5, allergen index, temperature and humidity at the value of the moment of
    switching off, for hours, as a number like any other. The graph is a flat line that was
    never measured, and the automation every owner writes first ("PM2.5 above 25: switch the
    purifier on") can never fire, because the number cannot change while the purifier is off.
    """
    await setup()
    assert fake.state["D03134"] == 0  # "Sensors in standby" is off, as on the measured device
    assert state(hass, "sensor.woonkamer_pm2_5") == "3"

    fake.power_off()
    await until(hass, lambda: state(hass, "fan.woonkamer") == "off")
    # Hours later somebody is frying fish. The device is not measuring and tells nobody.
    fake.change("D03221", 80)

    shown = {entity_id: state(hass, entity_id) for entity_id in MEASUREMENTS}
    stale = {entity_id: value for entity_id, value in shown.items() if value not in (STATE_UNKNOWN, STATE_UNAVAILABLE)}
    assert not stale, f"shown as current readings while nothing is measured: {stale}"

    # Back on: the readings are there again with the first frame.
    fake.power_on()
    await until(hass, lambda: state(hass, "sensor.woonkamer_pm2_5") == "80")


async def test_1_readings_stay_while_the_sensors_run_in_standby(hass: HomeAssistant, fake, setup) -> None:
    """The other half, which holds today: with "Sensors in standby" on, the purifier goes on measuring."""
    fake.state["D03134"] = 1
    await setup()
    fake.power_off()
    await until(hass, lambda: state(hass, "fan.woonkamer") == "off")
    assert state(hass, "switch.woonkamer_sensors_in_standby") == "on"
    assert state(hass, "sensor.woonkamer_pm2_5") == "3" and state(hass, "sensor.woonkamer_temperature") == "21.2"


# -- issue 2: a setting on a purifier that was added while it was off ends in "never reported the change" ----


async def test_2_a_setting_on_a_purifier_that_was_added_while_off_says_to_switch_it_on(
    hass: HomeAssistant, fake, setup
) -> None:
    """README: "Staat de luchtreiniger tijdens het toevoegen uit, dan zijn de waarden onbekend tot je hem aanzet."

    And: "Het apparaat negeert instellingen zolang het uit staat. Home Assistant stuurt ze dan
    niet en meldt dat je het apparaat eerst moet aanzetten."

    In exactly the first state the second promise is not kept. Nothing is known yet, so the
    setting is sent (twice), the purifier answers "success" and discards it, and after the whole
    confirmation time (11 s with the production timings) the owner reads "accepted the command
    but never reported the change", which does not mention that the purifier is off.
    """
    fake.power_off(notify=False)
    entry = await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    assert state(hass, "switch.woonkamer_child_lock") == STATE_UNKNOWN

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.woonkamer_child_lock"}, blocking=True)
    # A reachable purifier that has not sent its status after all this time is in standby
    # (measured: one that is on answers a registration within 2 s).
    assert raised.value.translation_key == "device_off", str(raised.value)


# -- issue 3: the integration has no icon of its own ----


async def test_3_the_integration_ships_its_icon(hass: HomeAssistant) -> None:
    """docs/onderzoek.md 6.7: brand images live in a folder brand/ of the integration; "brand/icon.png meeleveren".

    Home Assistant 2026.11 serves the icon of a custom integration from that folder
    (homeassistant/components/brands: `if not integration.has_branding: return None`). Without
    it the list of integrations, the form and the device page show the placeholder.
    """
    found = await loader.async_get_integration(hass, DOMAIN)
    assert found.has_branding, "custom_components/philips_pureprotect/brand/ does not exist"
    assert (Path(found.file_path) / "brand" / "icon.png").is_file()
