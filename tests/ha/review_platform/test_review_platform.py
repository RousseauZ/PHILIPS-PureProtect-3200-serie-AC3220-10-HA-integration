"""Review, lens "platform": where the Home Assistant layer does not do what Home Assistant 2026.11 expects.

Every test here fails on the code as reviewed and names the defect it proves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.logger.helpers import get_integration_loggers
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

import custom_components.philips_pureprotect as integration
from custom_components.philips_pureprotect.const import DOMAIN

from ..conftest import until

FAN = "fan.woonkamer"


def fan(hass: HomeAssistant) -> Any:
    found = hass.states.get(FAN)
    assert found is not None
    return found


async def call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call("fan", service, {"entity_id": FAN, **data}, blocking=True)


async def restart_with_the_purifier_gone_to_standby(hass: HomeAssistant, fake: Any, setup: Any) -> Any:
    """Stop the entry while the purifier runs and start it again after it was switched off on the device."""
    entry = await setup()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    fake.power_off(notify=False)
    await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    # The stored status is all Home Assistant has: it still says "on".
    assert fan(hass).state == "on" and not fake.is_on
    return entry


# -- 1. fan.turn_on trusts a status that is known to go stale ----------------------------------------------------


async def test_turn_on_switches_on_a_purifier_that_went_to_standby_while_home_assistant_was_down(
    hass: HomeAssistant, fake, setup
) -> None:
    """A purifier in standby reports nothing, so after a restart the stored "on" is all there is.

    fan.turn_on must still switch it on. It sends nothing, because the entity reads its own stale state.
    """
    await restart_with_the_purifier_gone_to_standby(hass, fake, setup)
    sent = len(fake.controls)
    await call(hass, "turn_on")
    assert fake.controls[sent:], "fan.turn_on sent nothing to the purifier"
    assert fake.is_on


async def test_a_mode_switches_on_a_purifier_that_went_to_standby_while_home_assistant_was_down(
    hass: HomeAssistant, fake, setup
) -> None:
    """The same state: a mode is sent without the power key, the device discards it and the call fails."""
    await restart_with_the_purifier_gone_to_standby(hass, fake, setup)
    await call(hass, "set_preset_mode", preset_mode="sleep")
    assert fake.is_on and fake.state["D0310C"] == 17


async def test_turn_on_switches_on_after_the_frame_of_the_switch_off_was_lost(hass: HomeAssistant, fake, setup) -> None:
    """Status frames are not confirmed on the wire; when the one that says "off" is lost, standby hides it for good."""
    await setup()
    fake.drop_next_notifications = 1
    fake.power_off()
    await asyncio.sleep(0.5)
    await hass.async_block_till_done()
    assert fan(hass).state == "on" and not fake.is_on  # the starting point: Home Assistant missed it
    await call(hass, "turn_on")
    assert fake.is_on


# -- 2. percentage and preset mode are reported together ---------------------------------------------------------


async def test_a_scene_made_in_auto_leaves_the_purifier_in_auto(hass: HomeAssistant, fake, setup) -> None:
    """Home Assistant restores a fan from its attributes and takes percentage and preset mode as exclusive.

    The fan reports the running speed as percentage while it is in auto. A scene stored in auto therefore
    carries a percentage, and activating it later sends that percentage: the purifier leaves auto.
    """
    assert await async_setup_component(hass, "scene", {})
    entry = await setup()
    assert fan(hass).attributes["preset_mode"] == "auto"
    await hass.services.async_call("scene", "create", {"scene_id": "night", "snapshot_entities": [FAN]}, blocking=True)

    fake.change("D0310D", 2)  # in auto the purifier picks another speed by itself
    await until(hass, lambda: entry.runtime_data.value("D0310D") == 2)
    assert fan(hass).attributes["preset_mode"] == "auto"

    sent = len(fake.controls)
    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.night"}, blocking=True)
    assert fake.state["D0310C"] == 0, f"the scene took the purifier out of auto: {fake.controls[sent:]}"


async def test_a_scene_made_at_a_fixed_speed_brings_that_speed_back(hass: HomeAssistant, fake, setup) -> None:
    """The other direction: auto happens to run at the speed the scene stored, so nothing is restored."""
    assert await async_setup_component(hass, "scene", {})
    entry = await setup()
    await call(hass, "set_percentage", percentage=60)
    await until(hass, lambda: fan(hass).attributes["percentage"] == 60)
    await hass.services.async_call("scene", "create", {"scene_id": "speed3", "snapshot_entities": [FAN]}, blocking=True)

    await call(hass, "set_preset_mode", preset_mode="auto")
    await until(hass, lambda: entry.runtime_data.value("D0310D") == 1)  # the speed that auto starts with
    fake.change("D0310D", 3)  # later auto runs at speed 3
    await until(hass, lambda: entry.runtime_data.value("D0310D") == 3)
    assert fake.state["D0310C"] == 0 and fan(hass).attributes["preset_mode"] == "auto"

    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.speed3"}, blocking=True)
    assert fake.state["D0310C"] == 3, "the scene left the purifier in auto"


# -- 3. the percentage lags behind a confirmed speed --------------------------------------------------------------


async def test_the_percentage_shows_a_confirmed_speed_at_once(hass: HomeAssistant, fake, setup) -> None:
    """Measured: the running speed follows a mode change 0.1 to 1 s later, in a frame of its own.

    The write is confirmed by the frame with the new mode. Until the next frame the entity still shows the
    old percentage, so the slider in the frontend jumps back after every change.
    """
    fake.speed_follows_after = 0.5
    await setup()
    assert fake.state["D0310D"] == 1  # the speed it runs at before the change
    await call(hass, "set_percentage", percentage=100)
    assert fake.state["D0310C"] == 5
    assert fan(hass).attributes["percentage"] == 100


async def test_two_quick_steps_up_are_two_steps(hass: HomeAssistant, fake, setup) -> None:
    """fan.increase_speed computes from the entity's percentage; with the stale one the second step is lost."""
    fake.speed_follows_after = 0.5
    await setup()
    await call(hass, "set_percentage", percentage=20)
    await until(hass, lambda: fan(hass).attributes["preset_mode"] is None and fan(hass).attributes["percentage"] == 20)
    await call(hass, "increase_speed")
    await call(hass, "increase_speed")
    assert fake.state["D0310C"] == 3


# -- 4. removing the entry leaves its file behind ----------------------------------------------------------------


async def test_removing_the_entry_removes_the_stored_status(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any]
) -> None:
    """The last status is kept in .storage under the entry id; nothing removes it when the entry is deleted."""
    entry = await setup()
    key = f"{DOMAIN}.{entry.entry_id}"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert key in hass_storage  # written when the entry was unloaded

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


# -- 5. "Enable debug logging" does not reach the session layer ---------------------------------------------------


async def test_debug_logging_of_the_integration_covers_the_session_layer(hass: HomeAssistant, fake, setup) -> None:
    """The button on the integration page sets the level of the package logger and of the manifest's "loggers".

    The session and the transport log under another name that the manifest does not list, so the lines about
    losing and finding the device never show up in the log the owner is asked to send.
    """
    await setup()
    covered = await get_integration_loggers(hass, DOMAIN)
    package = "custom_components.philips_pureprotect"
    used = {
        value.name
        for name, module in list(sys.modules.items())
        if name == package or name.startswith(f"{package}.")
        for value in vars(module).values()
        if isinstance(value, logging.Logger)
    }
    assert used, "no logger found in the package"
    missed = {name for name in used if not any(name == root or name.startswith(f"{root}.") for root in covered)}
    assert not missed, f"loggers that the debug switch of the integration does not reach: {sorted(missed)}"


# -- 6. the status is not saved while the purifier keeps reporting ------------------------------------------------


async def test_the_status_is_saved_while_the_purifier_keeps_reporting(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Store.async_delay_save restarts its delay on every call, and it is called for every frame.

    Measured: an active purifier sends a frame every 3.3 s for hours. With a delay of 60 s nothing is ever
    written until the purifier falls silent or Home Assistant stops cleanly.
    """
    delay = 0.3
    monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.SAVE_DELAY", delay)
    entry = await setup()
    key = f"{DOMAIN}.{entry.entry_id}"
    loop = asyncio.get_running_loop()
    started = loop.time()
    value = 10
    while loop.time() - started < 5 * delay:  # frames three times as often as the delay, for five delays
        value += 1
        fake.change("D03221", value)
        await asyncio.sleep(delay / 3)
    await hass.async_block_till_done()
    assert key in hass_storage, "nothing was saved in five times the save delay"


# -- 7. homeassistant.update_entity ends in NotImplementedError ---------------------------------------------------


async def test_update_entity_does_not_end_in_an_error(
    hass: HomeAssistant, fake, setup, caplog: pytest.LogCaptureFixture
) -> None:
    """A coordinator without interval still gets refresh requests, from the service homeassistant.update_entity."""
    assert await async_setup_component(hass, "homeassistant", {})
    entry = await setup()
    await hass.services.async_call("homeassistant", "update_entity", {"entity_id": [FAN]}, blocking=True)
    await hass.async_block_till_done()
    assert "Update method not implemented" not in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert entry.runtime_data.last_update_success


# -- 8. a text of the integration that Home Assistant never shows -------------------------------------------------


@pytest.mark.parametrize("language", ["en", "nl"])
async def test_the_text_for_a_changed_address_is_the_one_that_is_shown(
    hass: HomeAssistant, fake, default_port: int, language: str
) -> None:
    """Without a reason, async_update_reload_and_abort takes the text from Home Assistant's own translations."""
    texts = json.loads((Path(integration.__file__).parent / "translations" / f"{language}.json").read_text("utf-8"))
    entry = MockConfigEntry(
        domain=DOMAIN, title="Woonkamer", unique_id=fake.state["DeviceId"], data={CONF_HOST: "192.0.2.7"}
    )
    entry.add_to_hass(hass)
    flow = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_HOST: "127.0.0.1"})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    own_text = texts["config"]["abort"].get(result["reason"])
    shown_from = result.get("translation_domain") or DOMAIN
    assert own_text is None or shown_from == DOMAIN, (
        f"{own_text!r} is in {language}.json, but the text shown comes from the domain {shown_from!r}"
    )
