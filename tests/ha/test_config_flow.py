"""Adding a purifier by address, and changing its address."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant.common import MockConfigEntry

import custom_components.philips_pureprotect as integration
from custom_components.philips_pureprotect.config_flow import async_identify
from custom_components.philips_pureprotect.const import CONF_MODEL, DOMAIN

from .conftest import until


async def start(hass: HomeAssistant) -> Any:
    """Open the form for an address, the way the owner does: Add integration, then Enter the address."""
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert menu["type"] is FlowResultType.MENU and menu["step_id"] == "user"
    assert menu["menu_options"] == ["search", "manual"]
    result = await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": "manual"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "manual" and not result["errors"]
    return result


async def submit(hass: HomeAssistant, flow: Any, host: str) -> Any:
    return await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_HOST: host})


def suggested(form: Any) -> dict[str, Any]:
    """Return what a form shows in its fields before the user types."""
    return {str(key): (key.description or {}).get("suggested_value") for key in form["data_schema"].schema}


async def test_add_by_address(hass: HomeAssistant, fake, default_port: int) -> None:
    result = await submit(hass, await start(hass), " 127.0.0.1 ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Testkamer"
    assert result["data"] == {CONF_HOST: "127.0.0.1", CONF_MODEL: "AC3220/10"}
    entry = result["result"]
    assert entry.unique_id == fake.state["DeviceId"]
    # Identifying registered nothing on the device; the session that follows does.
    await until(hass, lambda: entry.runtime_data.session.status_is_live)
    assert hass.states.get("fan.testkamer").state == "on"


async def test_identifying_does_not_disturb_the_device(hass: HomeAssistant, fake, default_port: int) -> None:
    identity, error = await async_identify("127.0.0.1")
    assert error is None and identity is not None and identity.device_id == fake.state["DeviceId"]
    # Only the info resource was asked: no registration, no sync and no command,
    # so a session that already serves this purifier would not notice.
    assert {path for _, path in fake.requests} == {"/sys/dev/info"}
    assert not fake.registrations and not fake.controls and fake.syncs_received == 0


async def test_nothing_answers(hass: HomeAssistant, fake, default_port: int) -> None:
    flow = await start(hass)
    fake.silent = True
    result = await submit(hass, flow, "127.0.0.1")
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "cannot_connect"}
    # The form can be sent again once the purifier is back.
    fake.silent = False
    result = await submit(hass, flow, "127.0.0.1")
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_an_info_answer_is_often_lost_and_asked_again(hass: HomeAssistant, fake, default_port: int) -> None:
    fake.drop_next_infos = 1
    result = await submit(hass, await start(hass), "127.0.0.1")
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_something_else_answers(hass: HomeAssistant, fake, default_port: int) -> None:
    # Measured: a television on the same network answers on this port, without ids.
    fake._handle_info = lambda msg, sender: fake._respond(msg, sender, b'{"name":"[LG] webOS TV","swversion":"1.0"}')
    result = await submit(hass, await start(hass), "127.0.0.1")
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "not_a_purifier"}


async def test_a_purifier_that_is_set_up_already_only_gets_its_address_updated(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    existing = MockConfigEntry(domain=DOMAIN, unique_id=fake.state["DeviceId"], data={CONF_HOST: "192.0.2.7"})
    existing.add_to_hass(hass)
    result = await submit(hass, await start(hass), "127.0.0.1")
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert existing.data[CONF_HOST] == "127.0.0.1"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reconfigure_changes_the_address(hass: HomeAssistant, fake, default_port: int) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Woonkamer", unique_id=fake.state["DeviceId"], data={CONF_HOST: "192.0.2.7"}
    )
    entry.add_to_hass(hass)
    flow = await entry.start_reconfigure_flow(hass)
    assert flow["type"] is FlowResultType.FORM and flow["step_id"] == "reconfigure"
    result = await submit(hass, flow, "127.0.0.1")
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "127.0.0.1"
    await hass.async_block_till_done()
    await until(hass, lambda: entry.runtime_data.session.status_is_live)


async def test_reconfigure_refuses_another_purifier(hass: HomeAssistant, fake, default_port: int) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Slaapkamer", unique_id="another-device", data={CONF_HOST: "192.0.2.7"}
    )
    entry.add_to_hass(hass)
    result = await submit(hass, await entry.start_reconfigure_flow(hass), "127.0.0.1")
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == "192.0.2.7"


async def test_the_form_keeps_the_address_that_did_not_answer(hass: HomeAssistant, fake, default_port: int) -> None:
    flow = await start(hass)
    fake.silent = True
    result = await submit(hass, flow, "127.0.0.1")
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "cannot_connect"}
    assert suggested(result) == {CONF_HOST: "127.0.0.1"}  # a typing error can be corrected, not retyped


async def test_a_purifier_without_a_name_is_called_after_its_model(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    fake.state["D01S03"] = ""
    result = await submit(hass, await start(hass), "127.0.0.1")
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "AC3220/10"
    await hass.async_block_till_done()


async def test_reconfigure_shows_the_current_address_and_says_what_went_wrong(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    # This is the form the repair issue sends the owner to.
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
    assert suggested(result) == {CONF_HOST: " 127.0.0.1 "}
    assert entry.data[CONF_HOST] == "192.0.2.7"

    fake.silent = False
    result = await submit(hass, flow, " 127.0.0.1 ")
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_HOST] == "127.0.0.1"  # without the spaces
    await hass.async_block_till_done()
    await until(hass, lambda: entry.runtime_data.session.status_is_live)


@pytest.mark.parametrize(
    ("language", "text"), [("en", "The address has been changed."), ("nl", "Het adres is gewijzigd.")]
)
async def test_the_text_for_a_changed_address_is_the_one_of_this_integration(
    hass: HomeAssistant, fake, default_port: int, language: str, text: str
) -> None:
    """Without a reason of its own, Home Assistant would show its general text for a reconfiguration."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Woonkamer", unique_id=fake.state["DeviceId"], data={CONF_HOST: "192.0.2.7"}
    )
    entry.add_to_hass(hass)
    result = await submit(hass, await entry.start_reconfigure_flow(hass), "127.0.0.1")
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    # No other domain to take the text from: it is the one in the files of this integration.
    assert (result.get("translation_domain") or DOMAIN) == DOMAIN
    translations = Path(integration.__file__).parent / "translations" / f"{language}.json"
    assert json.loads(translations.read_text("utf-8"))["config"]["abort"][result["reason"]] == text
