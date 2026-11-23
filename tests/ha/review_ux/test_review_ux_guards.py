"""Review, lens "ux": rules of the Home Assistant layer that no test defended.

Every test in this file PASSES on the code as reviewed. Each one was written for a mutant
that the 41 tests of tests/ha let through: a copy of the integration with one rule broken,
on which the whole suite still passed. The mutant is named above each test. A test that
fails here after a change means that the owner would see the difference.

The tests that fail today are in test_review_ux.py.
"""

from __future__ import annotations

import json
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from homeassistant import loader
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator

import custom_components.philips_pureprotect as integration
import custom_components.philips_pureprotect.config_flow as config_flow_module
import custom_components.philips_pureprotect.coordinator as coordinator_module
from custom_components.philips_pureprotect.airlink import SessionState
from custom_components.philips_pureprotect.airlink import session as session_module
from custom_components.philips_pureprotect.const import DOMAIN
from custom_components.philips_pureprotect.select import SELECTS

from ..conftest import options, until

PACKAGE = Path(integration.__file__).parent
LANGUAGES = ("en", "nl")
OTHER_DEVICE = "99999999888811ef93334444555566bb"

LAST_STATUS = "sensor.woonkamer_last_status_received"
TIMER_ENDS = "sensor.woonkamer_timer_ends"
PM25 = "sensor.woonkamer_pm2_5"


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} does not exist"
    return found.state


def texts(language: str) -> dict[str, Any]:
    return json.loads((PACKAGE / "translations" / f"{language}.json").read_text(encoding="utf-8"))


def flat(tree: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Return the leaves of a translation file under their dotted path."""
    leaves: dict[str, Any] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            leaves.update(flat(value, f"{prefix}{key}."))
        else:
            leaves[f"{prefix}{key}"] = value
    return leaves


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w*)\}", text))


def suggested(form: Any) -> dict[str, Any]:
    """Return what a form shows in its fields before the user types."""
    return {str(key): (key.description or {}).get("suggested_value") for key in form["data_schema"].schema}


async def submit(hass: HomeAssistant, flow: Any, host: str) -> Any:
    return await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_HOST: host})


async def raise_another_device(hass: HomeAssistant, fake: Any, entry: Any) -> Any:
    """Let another device answer at the address and return the repair issue that follows."""
    issues = ir.async_get(hass)
    issue_id = f"wrong_device_{entry.entry_id}"
    fake.state["DeviceId"] = OTHER_DEVICE
    fake.change("D03221", 99)
    await until(hass, lambda: issues.async_get_issue(DOMAIN, issue_id) is not None, "no repair issue")
    return issues.async_get_issue(DOMAIN, issue_id)


# == 0. A missed check is not unavailability ==============================================================
#
# Mutant "coord_unavailable_at_the_first_missed_probe": PureProtectCoordinator.available true only in
# the states "live" and "reachable", so that everything goes unavailable at the first check the purifier
# does not answer. That is the fault of the existing integrations and the reason this one exists, and
# README promises the opposite ("pas niet beschikbaar als het apparaat ruim drie minuten op geen enkele
# controle antwoordt"). tests/ha passed on it: test_entities_go_unavailable_only_when_the_device_is_gone
# says "only" and looks at the end only.


async def test_entities_stay_available_while_the_purifier_only_misses_checks(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Long enough between the first miss and "offline" to look around.
    monkeypatch.setattr(
        "custom_components.philips_pureprotect.coordinator.SESSION_OPTIONS", options(offline_min_silence=2.0)
    )
    entry = await setup()
    session = entry.runtime_data.session
    fake.silent = True
    await until(hass, lambda: session.state is SessionState.SUSPECT, "no check was missed")
    assert state(hass, "fan.woonkamer") == "on" and state(hass, PM25) == "3"
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


# Mutants "coord_production_gives_up_after_ten_seconds" and "flow_production_asks_once": the timings
# the integration runs with outside the tests. conftest.py replaces both sets with fast ones for every
# test, so nothing looked at the real ones. They are read here when this file is imported, before
# that fixture runs.
PRODUCTION_SESSION = coordinator_module.SESSION_OPTIONS
PRODUCTION_IDENTIFY = config_flow_module.IDENTIFY_OPTIONS


def test_the_timings_outside_the_tests_are_the_promised_ones() -> None:
    # README: unavailable only after "ruim drie minuten" without an answer to any check.
    assert PRODUCTION_SESSION.offline_min_silence >= 180 and PRODUCTION_SESSION.offline_min_misses >= 3
    # Measured: a write is reported after 0.1 to 1.1 s (docs/metingen.md, 3 and 5); the wait has to be well above that.
    assert PRODUCTION_SESSION.confirm_timeout >= 2
    # Measured: the info resource answers after up to 1.3 s and is lost now and then (1, 11 and 12),
    # so the form has to wait that long and ask more than once.
    assert PRODUCTION_IDENTIFY.info_timeout >= 1.3 and PRODUCTION_IDENTIFY.info_attempts >= 3


# == 1. A timestamp sensor does not follow every frame ==================================================
#
# Mutant "sensor_timestamp_follows_every_frame": `if True:` instead of the 60-second step in
# _SteadyTimestampSensor._refresh. tests/ha/test_sensors.py has two tests named for this rule
# (test_timer_end_is_a_moment_that_does_not_creep, test_last_status_is_not_rewritten_with_every_frame)
# and both pass on the mutant: their frames arrive within the same second, and the state of a
# timestamp sensor has a resolution of one second. Measured: a frame every 3.3 s for eight hours
# (docs/metingen.md, 12), so on the mutant two sensors write a new state 26 000 times a day.


class _Clock:
    """Stands in for ``time`` inside the session: ``ahead`` moves its wall clock, not its timers."""

    def __init__(self) -> None:
        self.ahead = 0.0

    def time(self) -> float:
        return time.time() + self.ahead

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """Let a test decide how much later the next status frame arrives."""
    stand_in = _Clock()
    monkeypatch.setattr(session_module, "time", stand_in)
    return stand_in


async def test_last_status_moves_by_the_minute_and_not_with_every_frame(
    hass: HomeAssistant, fake, setup, clock: _Clock
) -> None:
    await setup()
    first = state(hass, LAST_STATUS)
    assert first not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
    # Fifteen frames, 3.3 s apart: fifty seconds of an active purifier.
    for frame in range(1, 16):
        clock.ahead = frame * 3.3
        fake.change("D03221", 10 + frame)
        await until(hass, lambda frame=frame: state(hass, PM25) == str(10 + frame))
        assert state(hass, LAST_STATUS) == first, f"rewritten for a frame {clock.ahead:.0f} s later"
    # Two minutes later it has to move, or it would not show how old the values are.
    clock.ahead = 120.0
    fake.change("D03221", 5)
    await until(hass, lambda: state(hass, LAST_STATUS) != first, "the sensor never moved")
    before, after = dt_util.parse_datetime(first), dt_util.parse_datetime(state(hass, LAST_STATUS))
    assert before is not None and after is not None
    assert timedelta(seconds=110) < after - before < timedelta(seconds=130)


async def test_timer_end_stays_put_while_the_minutes_count_down(
    hass: HomeAssistant, fake, setup, clock: _Clock
) -> None:
    await setup()
    fake.change("D03211", 120)
    await until(hass, lambda: state(hass, TIMER_ENDS) != STATE_UNKNOWN)
    first = state(hass, TIMER_ENDS)
    # Half a minute later other news arrives; the device still says 120 minutes.
    clock.ahead = 30.0
    fake.change("D03221", 30)
    await until(hass, lambda: state(hass, PM25) == "30")
    assert state(hass, TIMER_ENDS) == first, "the end crept along with the frame"
    # The device counts a minute down (measured: once per minute): the end is the same moment.
    clock.ahead = 60.0
    fake.state["D03211"] = 119
    fake.change("D03221", 31)
    await until(hass, lambda: state(hass, PM25) == "31")
    assert state(hass, TIMER_ENDS) == first, "the end moved although the timer just counted down"
    # A timer that is set again does move it.
    fake.change("D03211", 60)
    await until(hass, lambda: state(hass, TIMER_ENDS) not in (first, STATE_UNKNOWN))


# == 2. The texts ==========================================================================================
#
# No test read translations/*.json or icons.json. Mutants that passed: a Dutch text removed
# ("text_nl_exception_missing", "text_nl_option_missing", "text_nl_entity_name_missing",
# "text_nl_preset_missing"), a placeholder misspelt ("text_nl_placeholder_typo", "text_nl_issue_placeholder"),
# a key renamed so that the code asks for a text that is not there ("text_en_exception_renamed",
# "text_en_option_missing", "text_en_issue_missing", "text_en_flow_error_missing", "text_en_abort_missing"),
# the placeholders left out in the code ("coord_error_without_placeholders",
# "coord_issue_without_placeholders", "coord_issue_unknown_translation_key") and two in icons.json
# ("icons_unknown_entity", "icons_not_an_icon").


def test_both_languages_have_the_same_texts() -> None:
    english, dutch = flat(texts("en")), flat(texts("nl"))
    assert sorted(english) == sorted(dutch)
    empty = [key for key, text in (english | dutch).items() if not isinstance(text, str) or not text.strip()]
    assert not empty


def test_placeholders_are_the_same_in_both_languages() -> None:
    english, dutch = flat(texts("en")), flat(texts("nl"))
    different = {
        key: (english[key], dutch[key]) for key in english if placeholders(english[key]) != placeholders(dutch[key])
    }
    assert not different


def test_every_error_the_coordinator_raises_has_a_text() -> None:
    source = (PACKAGE / "coordinator.py").read_text(encoding="utf-8")
    # Read from the source, so that a new error cannot be forgotten; adapt the pattern when the way of raising changes.
    raised = set(re.findall(r'self\._error\("(\w+)"\)', source))
    assert raised >= {"device_off", "refused", "not_confirmed", "unreachable"}
    for language in LANGUAGES:
        messages = texts(language)["exceptions"]
        assert raised <= set(messages), language
        for key, entry in messages.items():
            assert placeholders(entry["message"]) <= {"name"}, f"{language}: {key}"


async def test_an_error_names_the_purifier(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.refuse_control = True
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call("fan", "turn_off", {"entity_id": "fan.woonkamer"}, blocking=True)
    error = raised.value
    assert error.translation_domain == DOMAIN and error.translation_placeholders == {"name": "Woonkamer"}
    # What the log and an automation trace show (always English).
    assert str(error).startswith("Woonkamer ") and "{" not in str(error)
    # What the frontend fills in, in the language of the user.
    for language in LANGUAGES:
        message = texts(language)["exceptions"][error.translation_key]["message"]
        assert "Woonkamer" in message.format(**error.translation_placeholders)


def test_every_choice_of_a_select_has_a_text() -> None:
    for language in LANGUAGES:
        selects = texts(language)["entity"]["select"]
        assert set(selects) == {description.translation_key for description in SELECTS}, language
        for description in SELECTS:
            assert description.translation_key is not None
            assert set(selects[description.translation_key]["state"]) == set(description.choices), (
                f"{language}: {description.key}"
            )


async def test_every_entity_has_a_name_and_every_name_an_entity(
    hass: HomeAssistant, fake, setup, entity_registry_enabled_by_default: None
) -> None:
    entry = await setup()
    registered = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    translated = {(found.domain, found.translation_key) for found in registered if found.translation_key}
    # Named after the device (the fan) or after their device class.
    for found in registered:
        if not found.translation_key:
            assert found.original_device_class, f"{found.entity_id} has no name at all"
    for language in LANGUAGES:
        entities = texts(language)["entity"]
        assert {(domain, key) for domain, keys in entities.items() for key in keys} == translated, language
        for domain, key in translated - {("fan", "purifier")}:
            assert entities[domain][key]["name"].strip(), f"{language}: {domain}.{key}"
        presets = entities["fan"]["purifier"]["state_attributes"]["preset_mode"]["state"]
        assert set(presets) == set(hass.states.get("fan.woonkamer").attributes["preset_modes"]), language

    icons = json.loads((PACKAGE / "icons.json").read_text(encoding="utf-8"))["entity"]
    assert {(domain, key) for domain, keys in icons.items() for key in keys} <= translated
    wrong = {path: icon for path, icon in flat(icons).items() if not re.fullmatch(r"mdi:[a-z0-9-]+", icon)}
    assert not wrong


async def test_the_repair_issue_has_its_text_and_names_purifier_and_address(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    issue = await raise_another_device(hass, fake, entry)
    assert issue.translation_placeholders == {"name": "Woonkamer", "host": "127.0.0.1"}
    # Mutant "coord_issue_fixable_without_a_fix": there is no repair flow, so no button for one.
    assert issue.is_fixable is False and issue.severity is ir.IssueSeverity.ERROR
    for language in LANGUAGES:
        text = texts(language)["issues"][issue.translation_key]
        assert placeholders(text["title"]) == {"name"}, language
        assert placeholders(text["description"]) == {"name", "host"}, language
        assert "Woonkamer" in text["title"].format(**issue.translation_placeholders)


async def test_every_outcome_of_the_form_has_a_text(hass: HomeAssistant, fake, default_port: int) -> None:
    errors: set[str] = set()
    aborts: set[str] = set()

    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    fake.silent = True
    errors.add((await submit(hass, flow, "127.0.0.1"))["errors"]["base"])
    fake.silent = False
    answer_as_purifier = fake._handle_info
    fake._handle_info = lambda msg, sender: fake._respond(msg, sender, b'{"name":"[LG] webOS TV"}')
    errors.add((await submit(hass, flow, "127.0.0.1"))["errors"]["base"])
    fake._handle_info = answer_as_purifier

    other = MockConfigEntry(
        domain=DOMAIN, title="Slaapkamer", unique_id="another-device", data={CONF_HOST: "192.0.2.7"}
    )
    other.add_to_hass(hass)
    aborts.add((await submit(hass, await other.start_reconfigure_flow(hass), "127.0.0.1"))["reason"])
    await hass.config_entries.async_remove(other.entry_id)

    same = MockConfigEntry(
        domain=DOMAIN, title="Woonkamer", unique_id=fake.state["DeviceId"], data={CONF_HOST: "192.0.2.7"}
    )
    same.add_to_hass(hass)
    aborts.add((await submit(hass, flow, "127.0.0.1"))["reason"])
    await hass.async_block_till_done()
    aborts.add((await submit(hass, await same.start_reconfigure_flow(hass), "127.0.0.1"))["reason"])
    await hass.async_block_till_done()

    assert errors == {"cannot_connect", "not_a_purifier"}
    assert len(aborts) == 3
    for language in LANGUAGES:
        config = texts(language)["config"]
        assert errors <= set(config["error"]), language
        assert aborts <= set(config["abort"]), language


# == 3. Unique ids ==========================================================================================
#
# Mutants "entity_unique_id_changes" (another separator) and "entity_unique_id_from_entry" (the id of
# the config entry instead of the device). With either, an update of the integration gives the owner
# a second set of entities and leaves the old ones, with their history and automations, behind as
# "no longer provided". Nothing in tests/ha looked at a unique id.

UNIQUE_IDS = {
    "fan.woonkamer": "fan",
    "binary_sensor.woonkamer_replace_filter": "filter_replace",
    "binary_sensor.woonkamer_clean_filter": "filter_clean",
    "binary_sensor.woonkamer_problem": "problem",
    "select.woonkamer_light": "light_mode",
    "select.woonkamer_light_brightness": "light_brightness",
    "select.woonkamer_ambient_light_scene": "light_scene",
    "select.woonkamer_timer": "timer",
    "sensor.woonkamer_pm2_5": "pm25",
    "sensor.woonkamer_allergen_index": "allergen_index",
    "sensor.woonkamer_temperature": "temperature",
    "sensor.woonkamer_humidity": "humidity",
    "sensor.woonkamer_filter_life_remaining": "filter_life",
    "sensor.woonkamer_filter_cleaning_due_in": "filter_cleaning",
    "sensor.woonkamer_signal_strength": "signal_strength",
    "sensor.woonkamer_error_code": "error_code",
    "sensor.woonkamer_fan_level": "fan_level",
    "sensor.woonkamer_last_status_received": "last_status",
    "sensor.woonkamer_timer_ends": "timer_end",
    "switch.woonkamer_child_lock": "child_lock",
    "switch.woonkamer_beep": "beep",
    "switch.woonkamer_auto_plus": "auto_plus",
    "switch.woonkamer_allergy_sleep": "allergy_sleep",
    "switch.woonkamer_sensors_in_standby": "standby_sensors",
    "switch.woonkamer_display": "display",
}


async def test_unique_ids_are_the_device_id_and_a_name_that_never_changes(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    registered = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    device_id = fake.state["DeviceId"]
    assert {found.entity_id: found.unique_id for found in registered} == {
        entity_id: f"{device_id}_{name}" for entity_id, name in UNIQUE_IDS.items()
    }


# == 4. What Home Assistant is told about each entity ======================================================
#
# Mutants: "sensor_pm25_no_statistics" and "sensor_allergen_no_statistics" (no state class: the
# long-term graphs stop), "sensor_humidity_no_unit", "sensor_filter_cleaning_in_minutes" (720 hours
# shown as 720 min), "binary_no_device_class" (Problem/OK becomes On/Off), and the five that move
# entities between the sections of the device page: "switch_not_configuration",
# "select_not_configuration", "sensor_filter_life_not_diagnostic", "sensor_last_status_not_diagnostic",
# "binary_not_diagnostic". tests/ha checked the unit of PM2.5 and nothing else.

# entity: (device class, state class, unit, section of the device page)
DESCRIBED = {
    "fan.woonkamer": (None, None, None, None),
    "sensor.woonkamer_pm2_5": ("pm25", "measurement", "μg/m³", None),
    "sensor.woonkamer_allergen_index": (None, "measurement", None, None),
    "sensor.woonkamer_temperature": ("temperature", "measurement", "°C", None),
    "sensor.woonkamer_humidity": ("humidity", "measurement", "%", None),
    "sensor.woonkamer_timer_ends": ("timestamp", None, None, None),
    "sensor.woonkamer_filter_life_remaining": (None, None, "%", "diagnostic"),
    "sensor.woonkamer_filter_cleaning_due_in": ("duration", None, "h", "diagnostic"),
    "sensor.woonkamer_last_status_received": ("timestamp", None, None, "diagnostic"),
    "sensor.woonkamer_signal_strength": ("signal_strength", "measurement", "dBm", "diagnostic"),
    "sensor.woonkamer_error_code": (None, None, None, "diagnostic"),
    "sensor.woonkamer_fan_level": (None, None, None, "diagnostic"),
    "binary_sensor.woonkamer_replace_filter": ("problem", None, None, "diagnostic"),
    "binary_sensor.woonkamer_clean_filter": ("problem", None, None, "diagnostic"),
    "binary_sensor.woonkamer_problem": ("problem", None, None, "diagnostic"),
    "switch.woonkamer_child_lock": (None, None, None, "config"),
    "switch.woonkamer_beep": (None, None, None, "config"),
    "switch.woonkamer_auto_plus": (None, None, None, "config"),
    "switch.woonkamer_allergy_sleep": (None, None, None, "config"),
    "switch.woonkamer_sensors_in_standby": (None, None, None, "config"),
    "switch.woonkamer_display": (None, None, None, "config"),
    "select.woonkamer_light": (None, None, None, "config"),
    "select.woonkamer_light_brightness": (None, None, None, "config"),
    "select.woonkamer_ambient_light_scene": (None, None, None, "config"),
    "select.woonkamer_timer": (None, None, None, "config"),
}


async def test_what_home_assistant_is_told_about_each_entity(
    hass: HomeAssistant, fake, setup, entity_registry_enabled_by_default: None
) -> None:
    entry = await setup()
    assert set(DESCRIBED) == set(UNIQUE_IDS)
    found: dict[str, tuple[Any, ...]] = {}
    for registered in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        attributes = hass.states.get(registered.entity_id).attributes
        category = registered.entity_category
        found[registered.entity_id] = (
            attributes.get("device_class"),
            attributes.get("state_class"),
            attributes.get("unit_of_measurement"),
            None if category is None else category.value,
        )
    assert found == DESCRIBED


# == 5. Home Assistant stops ================================================================================
#
# Mutant "init_no_save_when_home_assistant_stops": the listener for the stop of Home Assistant removed.
# README: "Na een herstart van Home Assistant tonen de entiteiten de laatst ontvangen waarden." The one
# test of that (test_the_last_status_survives_a_restart) unloads the entry, which Home Assistant does
# not do when it stops.


async def test_the_status_is_saved_and_the_session_closed_when_home_assistant_stops(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any]
) -> None:
    entry = await setup()
    session = entry.runtime_data.session
    fake.change("D03221", 17)
    await until(hass, lambda: state(hass, PM25) == "17")
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["status"]["D03221"] == 17
    assert not session.available  # stopped: its socket is closed and nothing is sent any more


# Mutant "init_unload_leaves_the_repair_issue".
async def test_unloading_the_purifier_removes_its_repair_issue(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    issue = await raise_another_device(hass, fake, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue.issue_id) is None


# == 6. The form =============================================================================================
#
# Mutants "flow_user_form_forgets_input", "flow_reconfigure_form_empty", "flow_reconfigure_error_not_shown",
# "flow_reconfigure_host_not_stripped" and "flow_title_empty_without_a_name". The error paths of
# "Reconfigure" were not run at all, and that is the form the repair issue sends the owner to.


async def test_the_form_keeps_the_address_that_did_not_answer(hass: HomeAssistant, fake, default_port: int) -> None:
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    fake.silent = True
    result = await submit(hass, flow, "127.0.0.1")
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "cannot_connect"}
    assert suggested(result) == {CONF_HOST: "127.0.0.1"}  # a typing error can be corrected, not retyped


async def test_reconfigure_shows_the_current_address_and_says_what_went_wrong(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Woonkamer", unique_id=fake.state["DeviceId"], data={CONF_HOST: "192.0.2.7"}
    )
    entry.add_to_hass(hass)
    flow = await entry.start_reconfigure_flow(hass)
    assert suggested(flow) == {CONF_HOST: "192.0.2.7"}

    fake.silent = True
    result = await submit(hass, flow, " 127.0.0.1 ")
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_HOST] == "192.0.2.7"

    fake.silent = False
    result = await submit(hass, flow, " 127.0.0.1 ")
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_HOST] == "127.0.0.1"  # without the spaces
    await hass.async_block_till_done()
    await until(hass, lambda: entry.runtime_data.session.status_is_live)


async def test_a_purifier_without_a_name_is_called_after_its_model(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    fake.state["D01S03"] = ""
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await submit(hass, flow, "127.0.0.1")
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "AC3220/10"
    await hass.async_block_till_done()


# Mutant "manifest_no_config_flow": without `"config_flow": true` the integration is not in the list of
# "Integratie toevoegen" (README, step 5), so it cannot be installed at all. The tests start the flow
# by its domain and never noticed.
async def test_the_manifest_puts_the_integration_in_the_list_to_add(hass: HomeAssistant) -> None:
    found = await loader.async_get_integration(hass, DOMAIN)
    assert found.config_flow is True
    assert found.name == "Philips PureProtect"  # the name README tells the owner to choose
    assert found.version is not None  # Home Assistant refuses a custom integration without one
    assert (found.integration_type, found.iot_class) == ("device", "local_push")
    assert found.requirements == []  # nothing to download: it starts without internet
    hacs = json.loads((PACKAGE.parents[1] / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["homeassistant"] == "2026.11.0"  # README: "Vereist: Home Assistant 2026.11 of nieuwer"


# == 7. Diagnostics ==========================================================================================
#
# Mutants "diag_title_not_redacted" and "diag_product_code_not_redacted". The title of the entry is the
# name the owner gave the purifier in the Air+ app; the existing test gives the entry another title
# than the device, and looks for the name of the device only.


async def test_diagnostics_hide_the_name_of_the_entry_and_the_product_code(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, fake, setup
) -> None:
    fake.state["D01S0D"] = "688001001384"
    entry = await setup()
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = json.dumps(data)
    assert data["status"]["D03102"] == 1  # the status is there
    for secret in (entry.title, "688001001384"):
        assert secret not in text, secret


# == 8. The device page ======================================================================================
#
# Mutants "coord_model_only_from_status" (a purifier that was added while off has no model until it
# is switched on) and "coord_firmware_updated_once_only" (a firmware update of the purifier never
# shows).


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


# == 9. What is sent =========================================================================================
#
# Mutants "select_bright_value" (bright written as 124) and "select_scene_value" (scene 3 as 5): the
# tests chose "low" and "scene 2" only.


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
            await hass.services.async_call(
                "select", "select_option", {"entity_id": entity_id, "option": option}, blocking=True
            )
            assert fake.state[key] == value, f"{name}: {option}"
            assert state(hass, entity_id) == option
