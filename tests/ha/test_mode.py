"""The select "Mode": every mode of the purifier, with the names of its buttons."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .conftest import until

MODE = "select.woonkamer_mode"


def state(hass: HomeAssistant) -> str:
    found = hass.states.get(MODE)
    assert found is not None
    return found.state


async def choose(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call("select", "select_option", {"entity_id": MODE, "option": option}, blocking=True)


async def test_every_mode_is_written_as_the_device_knows_it(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    found = hass.states.get(MODE)
    assert found is not None and found.attributes["options"] == [
        "off", "auto", "sleep", "medium", "turbo", "speed_1", "speed_2", "speed_3", "speed_4", "speed_5",
    ]  # fmt: skip
    for option, value in (
        ("sleep", 17), ("medium", 19), ("turbo", 18), ("speed_1", 1), ("speed_2", 2),
        ("speed_3", 3), ("speed_4", 4), ("speed_5", 5), ("auto", 0),
    ):  # fmt: skip
        await choose(hass, option)
        assert fake.controls[-1] == {"D0310C": value}, option
        assert state(hass) == option


async def test_medium_and_turbo_show_on_the_fan_as_their_speeds(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    await choose(hass, "turbo")
    assert hass.states.get("fan.woonkamer").attributes["percentage"] == 100
    await choose(hass, "medium")
    assert hass.states.get("fan.woonkamer").attributes["percentage"] == 60
    # And a speed set on the fan shows here by the device's name for it.
    await hass.services.async_call(
        "fan", "set_percentage", {"entity_id": "fan.woonkamer", "percentage": 40}, blocking=True
    )
    assert state(hass) == "speed_2"


async def test_off_and_back_on_in_a_mode(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    await choose(hass, "off")
    assert fake.controls[-1] == {"D03102": 0} and not fake.is_on
    assert state(hass) == "off" and hass.states.get("fan.woonkamer").state == "off"
    # One message: the device applies a mode that comes with the switch-on (measurement 14).
    await choose(hass, "turbo")
    assert fake.controls[-1] == {"D03102": 1, "D0310C": 18}
    assert fake.is_on and state(hass) == "turbo"


async def test_follows_the_buttons_on_the_device(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D0310C", 17)
    await until(hass, lambda: state(hass) == "sleep")
    fake.power_off()
    await until(hass, lambda: state(hass) == "off")


async def test_a_mode_switches_on_a_purifier_whose_status_is_from_before_a_restart(
    hass: HomeAssistant, fake, setup, slow_to_presume: None
) -> None:
    entry = await setup()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    fake.power_off(notify=False)
    await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    assert state(hass) == "auto" and not fake.is_on  # what was stored is all there is
    sent = len(fake.controls)
    await choose(hass, "sleep")
    assert fake.controls[sent:] == [{"D03102": 1, "D0310C": 17}]
    assert fake.is_on and state(hass) == "sleep"
