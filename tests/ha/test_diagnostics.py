"""The diagnostics download."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator

from .conftest import until


async def test_diagnostics_hold_the_counters_and_no_identifiers(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, fake, setup
) -> None:
    entry = await setup()
    await hass.services.async_call("fan", "turn_off", {"entity_id": "fan.woonkamer"}, blocking=True)
    await until(hass, lambda: hass.states.get("fan.woonkamer").state == "off")
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert data["session"]["state"] == "live" and data["session"]["commands_sent"] == 1
    assert data["session"]["frames_received"] >= 2 and data["session"]["identity_mismatch"] is False
    assert data["keys_assumed"] is False and "D03102" in data["keys"]
    assert data["status"]["D03102"] == 0 and data["status"]["D01S05"] == "AC3220/10"

    text = str(data)
    for secret in (fake.state["DeviceId"], fake.state["ProductId"], "Testkamer", "127.0.0.1"):
        assert secret not in text, secret


async def test_diagnostics_hide_the_name_of_the_entry_and_the_product_code(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, fake, setup
) -> None:
    # The title of the entry is the name the owner gave the purifier in the Air+ app.
    fake.state["D01S0D"] = "688001001384"
    entry = await setup()
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = json.dumps(data)
    assert data["status"]["D03102"] == 1  # the status is there
    assert data["entry_state"] == "loaded"
    assert data["session"]["presumed_standby"] is False and data["session"]["standby_presumptions"] == 0
    for secret in (entry.title, "688001001384"):
        assert secret not in text, secret


async def test_diagnostics_can_be_downloaded_for_an_entry_whose_setup_failed(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, fake, entry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The download is offered for every entry, and a report is wanted most for one that does not load."""

    async def fail(self: Any) -> None:
        raise RuntimeError("the setup fails, whatever the reason")

    monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.PureProtectCoordinator.async_start", fail)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert await async_setup_component(hass, "diagnostics", {})
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(f"/api/diagnostics/config_entry/{entry.entry_id}")
    assert response.status == HTTPStatus.OK, "no diagnostics for an entry that is not loaded"
    data = (await response.json())["data"]
    assert data["entry_state"] == "setup_error" and "session" not in data
    assert data["entry"]["domain"] == "philips_pureprotect"
    for secret in (entry.title, "127.0.0.1", fake.state["DeviceId"]):
        assert secret not in json.dumps(data), secret
