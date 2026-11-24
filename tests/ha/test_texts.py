"""The texts: every message reaches the owner through a translation key, in English and in Dutch.

A missing text shows as a raw key, a misspelt placeholder as a literal "{host}". Nothing else in the suite
reads translations/*.json or icons.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant.common import MockConfigEntry

import custom_components.philips_pureprotect as integration
from custom_components.philips_pureprotect.const import DOMAIN
from custom_components.philips_pureprotect.select import MODE_OPTIONS, SELECTS

from .conftest import until

PACKAGE = Path(integration.__file__).parent
LANGUAGES = ("en", "nl")
OTHER_DEVICE = "99999999888811ef93334444555566bb"


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


async def submit(hass: HomeAssistant, flow: Any, host: str) -> Any:
    return await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_HOST: host})


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
            assert placeholders(entry["message"]) == {"name"}, f"{language}: {key}"


def test_an_error_that_follows_a_wait_says_what_to_do_next() -> None:
    # After up to eleven seconds of waiting the owner should not be left with "it did not work".
    hints = {
        "device_off": {"en": "Switch it on", "nl": "Zet hem eerst aan"},
        "refused": {"en": "try again", "nl": "probeer het opnieuw"},
        "not_confirmed": {"en": "switch it on first", "nl": "zet hem dan eerst aan"},
        "unreachable": {"en": "Check that", "nl": "Controleer of"},
    }
    for key, per_language in hints.items():
        for language, hint in per_language.items():
            assert hint in texts(language)["exceptions"][key]["message"], f"{language}: {key}"
    for language in LANGUAGES:
        for key, text in texts(language)["config"]["error"].items():
            assert "address" in text or "adres" in text, f"{language}: {key}"


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
        assert set(selects) == {description.translation_key for description in SELECTS} | {"mode"}, language
        assert set(selects["mode"]["state"]) == set(MODE_OPTIONS), language
        for description in SELECTS:
            assert description.translation_key is not None
            assert set(selects[description.translation_key]["state"]) == set(description.choices), (
                f"{language}: {description.key}"
            )
            # What travels along with a choice is named by a choice that exists.
            assert set(description.companions) <= set(description.choices), description.key


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


async def test_entity_names_in_dutch(
    hass: HomeAssistant, fake, setup, entity_registry_enabled_by_default: None
) -> None:
    hass.config.language = "nl"
    await setup()
    names = {found.entity_id: found.name for found in hass.states.async_all()}
    assert names["fan.woonkamer"] == "Woonkamer"
    assert names["sensor.woonkamer_ventilatorsnelheid"] == "Woonkamer Ventilatorsnelheid"
    assert names["binary_sensor.woonkamer_storing"] == "Woonkamer Storing"  # README: "Waarschuwingen: ..., storing"
    assert names["switch.woonkamer_sensoren_in_stand_by"] == "Woonkamer Sensoren in stand-by"
    assert names["sensor.woonkamer_laatste_status_ontvangen"] == "Woonkamer Laatste status ontvangen"


async def test_the_repair_issue_has_its_text_and_names_purifier_and_address(hass: HomeAssistant, fake, setup) -> None:
    entry = await setup()
    issues = ir.async_get(hass)
    issue_id = f"wrong_device_{entry.entry_id}"
    fake.state["DeviceId"] = OTHER_DEVICE
    fake.change("D03221", 99)
    await until(hass, lambda: issues.async_get_issue(DOMAIN, issue_id) is not None, "no repair issue")
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {"name": "Woonkamer", "host": "127.0.0.1"}
    # There is no repair flow, so no button for one.
    assert issue.is_fixable is False and issue.severity is ir.IssueSeverity.ERROR
    for language in LANGUAGES:
        text = texts(language)["issues"][issue.translation_key]
        assert placeholders(text["title"]) == {"name"}, language
        assert placeholders(text["description"]) == {"name", "host"}, language
        assert "Woonkamer" in text["title"].format(**issue.translation_placeholders)


async def test_every_outcome_of_the_form_has_a_text(hass: HomeAssistant, fake, default_port: int) -> None:
    errors: set[str] = set()
    aborts: set[str] = set()

    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    flow = await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": "manual"})
    fake.silent = True
    errors.add((await submit(hass, flow, "127.0.0.1"))["errors"]["base"])
    fake.silent = False
    answer_as_purifier = fake._handle_info
    fake._handle_info = lambda msg, sender: fake._respond(msg, sender, b'{"name":"Television"}')
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
