"""Loading, unloading, availability and the entities of a purifier."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from homeassistant import loader
from homeassistant.components.logger.helpers import get_integration_loggers
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.typing import WebSocketGenerator

import custom_components.philips_pureprotect as integration
import custom_components.philips_pureprotect.config_flow as config_flow_module
import custom_components.philips_pureprotect.coordinator as coordinator_module
from custom_components.philips_pureprotect.airlink import SessionState
from custom_components.philips_pureprotect.const import CONF_MODEL, DOMAIN

from .conftest import FAST, options, state, until

OTHER_DEVICE = "99999999888811ef93334444555566bb"

# The timings the integration runs with outside the tests. conftest.py replaces both sets with fast ones
# for every test; they are read here when this file is imported, before that fixture runs.
PRODUCTION_SESSION = coordinator_module.SESSION_OPTIONS
PRODUCTION_IDENTIFY = config_flow_module.IDENTIFY_OPTIONS
PRODUCTION_RETRY_DELAY = coordinator_module.DEVICE_OFF_RETRY_DELAY  # read before any fixture shortens it


async def test_setup_creates_the_entities_of_the_device(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    assert entry.state is ConfigEntryState.LOADED
    states = {found.entity_id: found.state for found in hass.states.async_all()}
    assert states == {
        "fan.woonkamer": "on",
        "binary_sensor.woonkamer_replace_filter": "off",
        "binary_sensor.woonkamer_clean_filter": "off",
        "binary_sensor.woonkamer_fault": "off",
        "select.woonkamer_light": "ambient",
        "select.woonkamer_light_brightness": "auto",
        "select.woonkamer_ambient_light_scene": "scene_4",
        "select.woonkamer_timer": "off",
        "sensor.woonkamer_last_status_received": states["sensor.woonkamer_last_status_received"],
        "sensor.woonkamer_pm2_5": "3",
        "sensor.woonkamer_allergen_index": "1",
        "sensor.woonkamer_temperature": "21.2",
        "sensor.woonkamer_humidity": "47",
        "sensor.woonkamer_filter_life_remaining": "100",
        "sensor.woonkamer_filter_cleaning_due_in": "720",
        "sensor.woonkamer_fan_speed": "1",
        "sensor.woonkamer_timer_ends": STATE_UNKNOWN,
        "switch.woonkamer_child_lock": "off",
        "switch.woonkamer_beep": "on",
        "switch.woonkamer_auto_plus": "off",
        "switch.woonkamer_allergy_sleep": "off",
        "switch.woonkamer_sensors_in_standby": "off",
        "switch.woonkamer_display": "on",
    }
    # Diagnostic values that few people need exist, but are switched off.
    registry = er.async_get(hass)
    for entity_id in ("sensor.woonkamer_signal_strength", "sensor.woonkamer_error_code"):
        registered = registry.async_get(entity_id)
        assert registered is not None and registered.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, fake.state["DeviceId"]), entry.entry_id)
    assert device is not None
    assert (device.manufacturer, device.model, device.sw_version, device.name) == (
        "Philips",
        "AC3220/10",
        "0.2.3",
        "Woonkamer",
    )


async def test_unload_stops_the_session(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    session = entry.runtime_data.session
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not session.available and state(hass, "fan.woonkamer") == STATE_UNAVAILABLE


async def test_a_change_on_the_device_reaches_the_entities(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D03221", 42)
    await until(hass, lambda: state(hass, "sensor.woonkamer_pm2_5") == "42")
    fake.change("D03103", 1)
    await until(hass, lambda: state(hass, "switch.woonkamer_child_lock") == "on")


async def test_setup_does_not_wait_for_a_device_that_is_away(hass: HomeAssistant, fake, setup) -> None:
    fake.silent = True
    entry = await setup(live=False)
    assert entry.state is ConfigEntryState.LOADED
    # Nothing is known and nothing answers: the entities of the model exist, unavailable.
    assert state(hass, "fan.woonkamer") == STATE_UNAVAILABLE
    assert state(hass, "sensor.woonkamer_pm2_5") == STATE_UNAVAILABLE
    fake.silent = False
    await until(hass, lambda: state(hass, "fan.woonkamer") == "on")
    assert state(hass, "sensor.woonkamer_pm2_5") == "3"


async def test_a_device_in_standby_is_available_with_unknown_values(
    hass: HomeAssistant, fake, setup, slow_to_presume: None
) -> None:
    fake.power_off(notify=False)
    entry = await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    # It answers, but a purifier in standby sends no status until something changes. These are the
    # first seconds; what follows them is in test_standby.py.
    assert state(hass, "fan.woonkamer") == STATE_UNKNOWN
    assert state(hass, "switch.woonkamer_child_lock") == STATE_UNKNOWN
    fake.power_on()
    await until(hass, lambda: state(hass, "fan.woonkamer") == "on")
    assert state(hass, "switch.woonkamer_child_lock") == "off"


async def test_the_last_status_survives_a_restart(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any], slow_to_presume: None
) -> None:
    entry = await setup()
    fake.change("D03221", 17)
    await until(hass, lambda: state(hass, "sensor.woonkamer_pm2_5") == "17")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["status"]["D03221"] == 17

    # While Home Assistant was down the purifier went to standby: it answers, but sends nothing.
    fake.power_off(notify=False)
    await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    assert not entry.runtime_data.session.status_is_live
    # The first seconds after the start: what was stored is shown as it was. What becomes of it when
    # the purifier stays silent is in test_standby.py.
    assert state(hass, "sensor.woonkamer_pm2_5") == "17"
    assert state(hass, "sensor.woonkamer_last_status_received") not in (STATE_UNKNOWN, STATE_UNAVAILABLE)


async def test_an_entity_appears_when_the_device_starts_to_report_its_key(hass: HomeAssistant, fake, setup) -> None:
    del fake.state["D03112"]
    entry = await setup()
    # Created at first on the assumption of the model, and removed when the
    # first status showed that this device has no such key.
    assert hass.states.get("switch.woonkamer_display") is None
    assert er.async_get(hass).async_get("switch.woonkamer_display") is None
    assert not entry.runtime_data.keys_assumed
    assert hass.states.get("switch.woonkamer_child_lock") is not None
    fake.change("D03112", 1)
    await until(hass, lambda: hass.states.get("switch.woonkamer_display") is not None)
    assert state(hass, "switch.woonkamer_display") == "off"


async def test_entities_go_unavailable_only_when_the_device_is_gone(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    session = entry.runtime_data.session
    fake.silent = True
    await until(hass, lambda: not session.available, "the session never went offline")
    assert state(hass, "fan.woonkamer") == STATE_UNAVAILABLE
    fake.silent = False
    await until(hass, lambda: state(hass, "fan.woonkamer") == "on", "the session never came back")


async def test_another_device_at_the_address_raises_a_repair_issue(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    issues = ir.async_get(hass)
    issue_id = f"wrong_device_{entry.entry_id}"
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    ours = fake.state["DeviceId"]
    fake.state["DeviceId"] = OTHER_DEVICE
    fake.change("D03221", 99)
    await until(hass, lambda: issues.async_get_issue(DOMAIN, issue_id) is not None, "no repair issue")
    assert state(hass, "fan.woonkamer") == STATE_UNAVAILABLE
    assert state(hass, "sensor.woonkamer_pm2_5") == STATE_UNAVAILABLE  # the other device's 99 is not shown

    fake.state["DeviceId"] = ours
    fake.change("D03221", 5)
    await until(hass, lambda: issues.async_get_issue(DOMAIN, issue_id) is None, "the repair issue stayed")
    assert state(hass, "sensor.woonkamer_pm2_5") == "5"


async def test_entities_stay_available_while_the_purifier_only_misses_checks(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A missed check is not unavailability: that is the fault of the existing integrations and the reason
    # this one exists. Long enough between the first miss and "offline" to look around.
    monkeypatch.setattr(coordinator_module, "SESSION_OPTIONS", options(offline_min_silence=2.0))
    entry = await setup()
    session = entry.runtime_data.session
    fake.silent = True
    await until(hass, lambda: session.state is SessionState.SUSPECT, "no check was missed")
    assert state(hass, "fan.woonkamer") == "on" and state(hass, "sensor.woonkamer_pm2_5") == "3"
    # More misses do not change that, as long as the silence is shorter than the limit.
    missed = session.diagnostics().probes_missed
    await until(hass, lambda: session.diagnostics().probes_missed >= missed + 2)
    assert session.state is SessionState.SUSPECT
    assert state(hass, "fan.woonkamer") == "on" and state(hass, "switch.woonkamer_child_lock") == "off"
    # Only the limit makes them unavailable, and an answer brings them back with their values.
    await until(hass, lambda: session.state is SessionState.OFFLINE, "the session never went offline")
    assert state(hass, "fan.woonkamer") == STATE_UNAVAILABLE
    fake.silent = False
    await until(hass, lambda: state(hass, "fan.woonkamer") == "on", "the purifier never came back")


def test_the_timings_outside_the_tests_are_the_promised_ones() -> None:
    # README: unavailable only after "ruim drie minuten" without an answer to any check.
    assert PRODUCTION_SESSION.offline_min_silence >= 180 and PRODUCTION_SESSION.offline_min_misses >= 3
    # Measured: a write is reported after 0.1 to 1.1 s (docs/metingen.md, 3 and 5); the wait has to be well above that.
    assert PRODUCTION_SESSION.confirm_timeout >= 2
    # Measured: a new registration is answered after up to 1.9 s. Standby is presumed only well after
    # that, and after the second registration of a start had its chance too.
    assert PRODUCTION_SESSION.standby_presume_after >= PRODUCTION_SESSION.refresh_min_gap + 2 * 1.9
    # A setting that waits for that outcome has to get it within its own time limit.
    assert PRODUCTION_SESSION.standby_presume_after <= PRODUCTION_SESSION.write_budget
    # Measured: the info resource answers after up to 1.3 s and is lost now and then (1, 11 and 12),
    # so the form has to wait that long and ask more than once.
    assert PRODUCTION_IDENTIFY.info_timeout >= 1.3 and PRODUCTION_IDENTIFY.info_attempts >= 3
    # A scene that names a setting before the fan gets a second chance, and soon.
    assert 0 < PRODUCTION_RETRY_DELAY <= 1


async def test_the_manifest_puts_the_integration_in_the_list_to_add(hass: HomeAssistant) -> None:
    found = await loader.async_get_integration(hass, DOMAIN)
    assert found.config_flow is True  # without it the integration is not in "Integratie toevoegen"
    assert found.name == "Philips PureProtect"  # the name README tells the owner to choose
    assert found.version is not None  # Home Assistant refuses a custom integration without one
    assert (found.integration_type, found.iot_class) == ("device", "local_push")
    assert found.requirements == []  # nothing to download: it starts without internet
    hacs = json.loads((Path(integration.__file__).parents[2] / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["homeassistant"] == "2026.11.0"  # README: "Vereist: Home Assistant 2026.11 of nieuwer"


async def test_debug_logging_of_the_integration_covers_the_session_layer(hass: HomeAssistant, fake, setup) -> None:
    """The button "Enable debug logging" sets the level of the package logger and of the manifest's "loggers".

    The session and the transport are where losing and finding the device is logged. They log under the
    name of their package, which is a child of the integration's, so the button reaches them.
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
    assert f"{package}.airlink" in used, "the session layer logs under another name"
    missed = {name for name in used if not any(name == root or name.startswith(f"{root}.") for root in covered)}
    assert not missed, f"loggers that the debug switch of the integration does not reach: {sorted(missed)}"


async def test_the_debug_button_of_the_integration_switches_the_session_layer_to_debug(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, fake, setup
) -> None:
    """What "Enable debug logging" on the integration page sends, and what it does to the session's logger."""
    names = ("custom_components.philips_pureprotect", "homeassistant.components.philips_pureprotect")
    levels = {name: logging.getLogger(name).level for name in names}
    logger_class = logging.getLoggerClass()  # Home Assistant's logger component replaces it for good
    session_logger = logging.getLogger("custom_components.philips_pureprotect.airlink")
    try:
        assert await async_setup_component(hass, "logger", {})
        await setup()
        client = await hass_ws_client(hass)
        for number, (level, debug) in enumerate((("INFO", False), ("DEBUG", True)), start=1):
            await client.send_json(
                {
                    "id": number,
                    "type": "logger/integration_log_level",
                    "integration": DOMAIN,
                    "level": level,
                    "persistence": "none",
                }
            )
            assert (await client.receive_json())["success"]
            assert session_logger.isEnabledFor(logging.DEBUG) is debug, level
    finally:
        logging.setLoggerClass(logger_class)
        for name, level in levels.items():  # the levels of loggers outlive a test
            logger = logging.getLogger(name)
            getattr(logger, "orig_setLevel", logger.setLevel)(level)


async def test_the_session_logs_losing_and_finding_the_device_under_the_integration(
    hass: HomeAssistant, fake, setup, caplog: pytest.LogCaptureFixture
) -> None:
    entry = await setup()
    session = entry.runtime_data.session
    with caplog.at_level(logging.DEBUG, logger="custom_components.philips_pureprotect"):
        fake.silent = True
        await until(hass, lambda: not session.available, "the session never went offline")
        fake.silent = False
        await until(hass, lambda: session.available, "the session never came back")
    ours = [record for record in caplog.records if record.name == "custom_components.philips_pureprotect.airlink"]
    # One line at loss and one at recovery, at a level that is in the log without any switch.
    told = [(record.levelno, record.getMessage()) for record in ours if "answer" in record.getMessage()]
    assert told == [
        (logging.INFO, "127.0.0.1: the device does not answer"),
        (logging.INFO, "127.0.0.1: the device answers again"),
    ]
    # With the debug switch on, the changes of state are there as well.
    assert any(record.levelno == logging.DEBUG and "-> offline" in record.getMessage() for record in ours)


async def test_update_entity_does_not_end_in_an_error(
    hass: HomeAssistant, fake, setup, caplog: pytest.LogCaptureFixture
) -> None:
    """A coordinator without interval still gets refresh requests, from the service homeassistant.update_entity."""
    assert await async_setup_component(hass, "homeassistant", {})
    entry = await setup()
    await hass.services.async_call(
        "homeassistant", "update_entity", {"entity_id": ["fan.woonkamer", "sensor.woonkamer_pm2_5"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert "Update method not implemented" not in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert entry.runtime_data.last_update_success
    assert state(hass, "fan.woonkamer") == "on" and state(hass, "sensor.woonkamer_pm2_5") == "3"
    # Nothing is asked of the purifier for it: it reports every change by itself.
    assert not fake.controls and fake.syncs_received == 0


async def test_unload_after_home_assistant_stopped_logs_no_error(
    hass: HomeAssistant, fake, setup, caplog: pytest.LogCaptureFixture
) -> None:
    """The stop listener is a one-time listener; once it has fired there is nothing left to remove."""
    entry = await setup()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert not entry.runtime_data.session.available  # the stop handler stopped the session

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert not errors, errors


async def test_an_unloaded_entry_no_longer_listens_for_the_stop_of_home_assistant(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any]
) -> None:
    entry = await setup()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    key = f"{DOMAIN}.{entry.entry_id}"
    del hass_storage[key]  # written at unload
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert key not in hass_storage, "the stop listener of an unloaded entry still fired"


async def test_unloading_the_purifier_removes_its_repair_issue(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    issues = ir.async_get(hass)
    issue_id = f"wrong_device_{entry.entry_id}"
    fake.state["DeviceId"] = OTHER_DEVICE
    fake.change("D03221", 99)
    await until(hass, lambda: issues.async_get_issue(DOMAIN, issue_id) is not None, "no repair issue")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_an_entry_at_the_wrong_address_leaves_the_stream_to_the_purifier_that_lives_there(
    hass: HomeAssistant, fake, setup
) -> None:
    """Two purifiers; the address stored for the bedroom one now belongs to the living room one.

    The purifier serves one observer per source address and the newest registration wins
    (docs/metingen.md, measurement 9). An entry that knows it is at the wrong address must not go on
    registering there, or the entry that owns the purifier loses its status stream again and again.
    """
    await setup()  # the living room purifier, at its own address
    # Start the bedroom entry right behind a periodic registration of the living room session.
    registrations = len(fake.registrations)
    await until(hass, lambda: len(fake.registrations) > registrations, "no periodic registration")
    bedroom = MockConfigEntry(
        domain=DOMAIN,
        title="Slaapkamer",
        unique_id=OTHER_DEVICE,
        data={CONF_HOST: "127.0.0.1", CONF_PORT: fake.port, CONF_MODEL: "AC3220/10"},
    )
    bedroom.add_to_hass(hass)
    assert await hass.config_entries.async_setup(bedroom.entry_id)
    issues = ir.async_get(hass)
    await until(
        hass,
        lambda: issues.async_get_issue(DOMAIN, f"wrong_device_{bedroom.entry_id}") is not None,
        "the bedroom entry never noticed that another purifier answers",
    )
    assert state(hass, "fan.slaapkamer") == STATE_UNAVAILABLE
    # The first registration of the bedroom entry cannot be helped: it did not know yet. Give the
    # living room session two refresh intervals to take its stream back.
    await asyncio.sleep(2 * FAST.refresh_interval)
    bedroom_session = bedroom.runtime_data.session
    before = bedroom_session.diagnostics()

    # From here on, for three more refresh intervals, every change must reach the living room entry.
    for value in range(40, 52):
        fake.change("D03221", value)
        await until(
            hass,
            lambda value=value: state(hass, "sensor.woonkamer_pm2_5") == str(value),
            f"PM2.5 {value} did not reach the living room entry: the bedroom entry holds the status stream",
            timeout=FAST.refresh_interval / 3,
        )
        await asyncio.sleep(FAST.refresh_interval / 4)
    after = bedroom_session.diagnostics()
    # The bedroom entry registered nothing in all that time, so not one frame went its way.
    assert after.registrations_sent == before.registrations_sent
    assert after.frames_dropped == before.frames_dropped, "the bedroom entry took frames of the other purifier"
    assert fake.syncs_received == 0, "and it leaves the counter of that purifier alone"
    assert after.probes_sent > before.probes_sent or after.datagrams_sent > before.datagrams_sent  # still watching


async def test_the_device_shows_its_model_before_the_first_status(hass: HomeAssistant, fake, setup) -> None:
    fake.power_off(notify=False)
    entry = await setup(live=False)
    await until(hass, lambda: entry.runtime_data.session.available)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, fake.state["DeviceId"]), entry.entry_id)
    assert device is not None and (device.name, device.model, device.sw_version) == ("Woonkamer", "AC3220/10", None)


async def test_new_firmware_of_the_purifier_shows_on_the_device_page(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    registry = dr.async_get(hass)

    def firmware() -> str | None:
        device = registry.async_get_device_by_identifier((DOMAIN, fake.state["DeviceId"]), entry.entry_id)
        assert device is not None
        return device.sw_version

    await until(hass, lambda: firmware() == "0.2.3")
    fake.change("D01S12", "0.2.4")
    await until(hass, lambda: firmware() == "0.2.4", "the device page kept the old firmware")
