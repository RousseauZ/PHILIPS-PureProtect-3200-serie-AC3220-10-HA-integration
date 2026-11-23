"""The diagnostics download."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
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
