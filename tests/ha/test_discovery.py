"""Finding a purifier: a search in the setup, DHCP, its MAC address, and a new address after a move."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant.common import MockConfigEntry

from custom_components.philips_pureprotect import search as search_module
from custom_components.philips_pureprotect.const import CONF_MODEL, DOMAIN
from custom_components.philips_pureprotect.search import (
    read_mac as READ_MAC,  # the real one, before the fixtures replace it
)

from .conftest import until

MAC = "68:79:c4:12:34:56"


async def search(hass: HomeAssistant) -> Any:
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    return await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": "search"})


def dhcp(ip: str = "127.0.0.1") -> DhcpServiceInfo:
    return DhcpServiceInfo(ip=ip, hostname="mxchip-ac3220", macaddress=MAC.replace(":", ""))


async def test_search_offers_the_purifier_it_finds(hass: HomeAssistant, search_finds, default_port: int) -> None:
    result = await search(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "search"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": "127.0.0.1"})
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "Testkamer"
    assert result["data"] == {CONF_HOST: "127.0.0.1", CONF_MODEL: "AC3220/10"}
    assert result["result"].unique_id == search_finds.state["DeviceId"]


async def test_search_that_finds_nothing_leads_to_the_address_form(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    result = await search(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "manual"
    assert result["errors"] == {"base": "no_devices_found"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "127.0.0.1"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_search_leaves_out_a_purifier_that_is_set_up(
    hass: HomeAssistant, search_finds, default_port: int
) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=search_finds.state["DeviceId"], data={CONF_HOST: "192.0.2.7"}).add_to_hass(
        hass
    )
    result = await search(hass)
    assert result["step_id"] == "manual" and result["errors"] == {"base": "no_devices_found"}


async def test_dhcp_finds_a_new_purifier_and_asks_first(hass: HomeAssistant, fake, default_port: int) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {"name": "Testkamer", "model": "AC3220/10", "host": "127.0.0.1"}
    # Asking who it is registered nothing on the device.
    assert not fake.registrations and fake.syncs_received == 0
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["data"][CONF_HOST] == "127.0.0.1"


async def test_dhcp_follows_a_purifier_that_moved(hass: HomeAssistant, fake, default_port: int) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Woonkamer", unique_id=fake.state["DeviceId"], data={CONF_HOST: "192.0.2.7"}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "127.0.0.1"


async def test_dhcp_sends_nothing_for_a_purifier_at_its_known_address(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=fake.state["DeviceId"], data={CONF_HOST: "127.0.0.1"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert not fake.requests


@pytest.mark.parametrize(
    ("answer", "reason"),
    [(None, "cannot_connect"), (b'{"name":"[LG] webOS TV"}', "not_a_purifier")],
)
async def test_dhcp_lets_another_appliance_with_the_same_wifi_module_go(
    hass: HomeAssistant, fake, default_port: int, answer: bytes | None, reason: str
) -> None:
    if answer is None:
        fake.info_enabled = False
    else:
        fake._handle_info = lambda msg, sender: fake._respond(msg, sender, answer)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == reason


async def test_the_mac_address_is_noted_for_dhcp(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def neighbour_table(host: str) -> str:
        asked.append(host)
        return MAC

    monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.read_mac", neighbour_table)
    entry = await setup()
    registry = dr.async_get(hass)
    await until(
        hass,
        lambda: (
            (dr.CONNECTION_NETWORK_MAC, MAC)
            in registry.async_get_device_by_identifier((DOMAIN, fake.state["DeviceId"]), entry.entry_id).connections
        ),
        "the MAC address was not noted",
    )
    assert asked == ["127.0.0.1"]


async def test_a_mac_address_of_another_device_is_not_taken(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = MockConfigEntry(domain=DOMAIN, unique_id="another-device", data={CONF_HOST: "192.0.2.7"})
    other.add_to_hass(hass)
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={(DOMAIN, "another-device")},
        connections={(dr.CONNECTION_NETWORK_MAC, MAC)},
    )
    asked: list[str] = []
    monkeypatch.setattr(
        "custom_components.philips_pureprotect.coordinator.read_mac", lambda host: asked.append(host) or MAC
    )
    entry = await setup()
    await until(hass, lambda: bool(asked))
    device = registry.async_get_device_by_identifier((DOMAIN, fake.state["DeviceId"]), entry.entry_id)
    assert (dr.CONNECTION_NETWORK_MAC, MAC) not in device.connections


async def test_a_purifier_that_moved_is_found_again(
    hass: HomeAssistant, search_finds, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = search_finds
    monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.REDISCOVER_AFTER", 0.3)
    monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.REDISCOVER_CHECK", 0.2)
    # Set up at its old address, where nothing answers any more.
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Woonkamer",
        unique_id=fake.state["DeviceId"],
        data={CONF_HOST: "127.0.0.2", CONF_PORT: fake.port, CONF_MODEL: "AC3220/10"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await until(hass, lambda: entry.data[CONF_HOST] == "127.0.0.1", "the purifier was not looked for", timeout=10.0)
    await until(
        hass,
        lambda: getattr(entry, "runtime_data", None) is not None and entry.runtime_data.session.status_is_live,
        "the entry did not come back at the new address",
        timeout=10.0,
    )
    assert hass.states.get("fan.woonkamer").state == "on"


def test_the_neighbour_table_gives_only_a_complete_real_mac(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    table = tmp_path / "arp"
    table.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "10.10.10.113     0x1         0x2         68:79:C4:12:34:56     *        eth0\n"
        "10.10.10.68      0x1         0x0         00:00:00:00:00:00     *        eth0\n"
        "10.10.10.70      0x1         0x2         00:00:00:00:00:00     *        eth0\n"
    )
    monkeypatch.setattr(search_module, "ARP_TABLE", table)
    assert READ_MAC("10.10.10.113") == MAC
    assert READ_MAC("10.10.10.68") is None  # not complete
    assert READ_MAC("10.10.10.70") is None  # all zeros merged devices in another integration
    assert READ_MAC("10.10.10.1") is None
    assert READ_MAC("woonkamer.lan") is None  # a host name is not looked up
    monkeypatch.setattr(search_module, "ARP_TABLE", tmp_path / "missing")
    assert READ_MAC("10.10.10.113") is None
