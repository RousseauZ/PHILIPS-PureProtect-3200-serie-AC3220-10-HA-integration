"""Finding a purifier: a search in the setup, DHCP, its MAC address, and a new address after a move."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

import pytest
from fake_purifier import FakePurifier, _AltSource
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.discovery_flow import DiscoveryKey
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant.common import MockConfigEntry

import custom_components.philips_pureprotect.coordinator as coordinator_module
from custom_components.philips_pureprotect import config_flow
from custom_components.philips_pureprotect import search as search_module
from custom_components.philips_pureprotect.airlink import SessionState
from custom_components.philips_pureprotect.const import CONF_MODEL, DOMAIN
from custom_components.philips_pureprotect.search import (
    read_mac as READ_MAC,  # the real one, before the fixtures replace it
)

from .conftest import options, until

MAC = "68:79:c4:12:34:56"
OTHER_ID = "99999999888811ef93334444555566bb"


async def search(hass: HomeAssistant) -> Any:
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    return await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": "search"})


def dhcp(ip: str = "127.0.0.1", mac: str = MAC) -> DhcpServiceInfo:
    return DhcpServiceInfo(ip=ip, hostname="mxchip-ac3220", macaddress=mac.replace(":", ""))


def purifier_entry(hass: HomeAssistant, unique_id: str, host: str, port: int, title: str = "Woonkamer") -> Any:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id=unique_id,
        data={CONF_HOST: host, CONF_PORT: port, CONF_MODEL: "AC3220/10"},
    )
    entry.add_to_hass(hass)
    return entry


def our_device(hass: HomeAssistant, entry: Any) -> dr.DeviceEntry:
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, entry.unique_id), entry.entry_id)
    assert device is not None
    return device


def dhcp_matches(hass: HomeAssistant, mac: str) -> set[str]:
    """Return the domains Home Assistant's DHCP watcher hands a MAC to through "registered_devices".

    As components/dhcp/__init__.py does it in 2026.11: every device with the MAC counts, by the domain of its
    config entry. (The component itself cannot be imported here: its packet sniffer is not installed.)
    """
    domains: set[str] = set()
    for device in dr.async_get(hass).async_get_devices(connections={(dr.CONNECTION_NETWORK_MAC, mac)}):
        entry = hass.config_entries.async_get_entry(device.config_entry_id)
        if entry is not None:
            domains.add(entry.domain)
    return domains


def neighbour_table(monkeypatch: pytest.MonkeyPatch, mac: str = MAC) -> list[str]:
    """Let the coordinator find a MAC in the neighbour table; returns the addresses it looked up."""
    asked: list[str] = []
    monkeypatch.setattr(coordinator_module, "read_mac", lambda host: asked.append(host) or mac)
    return asked


def quick_research(monkeypatch: pytest.MonkeyPatch) -> None:
    """Look for a lost purifier after 0.3 s instead of 120 s, checked every 0.1 s instead of 60 s."""
    monkeypatch.setattr(coordinator_module, "REDISCOVER_AFTER", 0.3)
    monkeypatch.setattr(coordinator_module, "REDISCOVER_CHECK", 0.1)


def count_searches(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Return the results of the searches the coordinators make, as they come."""
    results: list[dict[str, Any]] = []
    real = coordinator_module.async_search

    async def counted(hass: HomeAssistant, port: int) -> Any:
        found = await real(hass, port)
        results.append(found)
        return found

    monkeypatch.setattr(coordinator_module, "async_search", counted)
    return results


def broadcast_reaches(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    """Let a search reach these loopback addresses, as a broadcast reaches every device of a network."""

    async def targets(hass: Any) -> list[str]:
        return list(addresses)

    monkeypatch.setattr(search_module, "async_search_targets", targets)


@pytest.fixture
async def at_two_addresses(socket_enabled: None) -> AsyncGenerator[tuple[FakePurifier, FakePurifier]]:
    """Return two simulated purifiers on one port: ours at 127.0.0.2 and another one at 127.0.0.1."""
    loop = asyncio.get_running_loop()
    ours = await FakePurifier.start("127.0.0.2")
    other = FakePurifier()
    other.state["DeviceId"] = OTHER_ID
    await loop.create_datagram_endpoint(lambda: other, local_addr=("127.0.0.1", ours.port))
    other._alt_transport, _ = await loop.create_datagram_endpoint(_AltSource, local_addr=("127.0.0.1", 0))
    yield ours, other
    ours.close()
    other.close()


# -- the search in the setup ---------------------------------------------------------------------


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
    entry = MockConfigEntry(domain=DOMAIN, unique_id=search_finds.state["DeviceId"], data={CONF_HOST: "127.0.0.1"})
    entry.add_to_hass(hass)
    result = await search(hass)
    # Something did answer, so not "no air purifier answered"; the owner can still enter another address.
    assert result["step_id"] == "manual" and result["errors"] == {"base": "no_new_devices"}
    assert entry.data[CONF_HOST] == "127.0.0.1"


async def test_search_follows_a_purifier_that_is_set_up_at_another_address(
    hass: HomeAssistant, search_finds, default_port: int
) -> None:
    """The owner's purifier got a new address and shows as unavailable; the search finds it there."""
    entry = purifier_entry(hass, search_finds.state["DeviceId"], "127.0.0.2", search_finds.port)  # nothing answers
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await search(hass)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "127.0.0.1"
    await until(
        hass,
        lambda: (
            entry.state is ConfigEntryState.LOADED
            and entry.runtime_data.host == "127.0.0.1"
            and entry.runtime_data.session.status_is_live
        ),
        "the entry was not reloaded at the new address",
    )


@pytest.mark.parametrize("way", ["search", "manual"])
async def test_adding_a_purifier_that_waits_as_discovered_works(
    hass: HomeAssistant, search_finds, default_port: int, way: str
) -> None:
    """DHCP found the purifier and its card waits; the owner adds it through the menu instead.

    Not "already in progress": creating the entry ends the waiting offer (Home Assistant aborts every flow with
    the same unique id).
    """
    discovered = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert discovered["type"] is FlowResultType.FORM and discovered["step_id"] == "discovery_confirm"
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    form = await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": way})
    assert form["type"] is FlowResultType.FORM and form["step_id"] == way
    answer = {"device": "127.0.0.1"} if way == "search" else {CONF_HOST: "127.0.0.1"}
    result = await hass.config_entries.flow.async_configure(form["flow_id"], answer)
    assert result["type"] is FlowResultType.CREATE_ENTRY, result.get("reason")
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


# -- DHCP ------------------------------------------------------------------------------------------


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


async def test_dhcp_moves_a_loaded_entry_and_reloads_it(hass: HomeAssistant, fake, default_port: int) -> None:
    entry = purifier_entry(hass, fake.state["DeviceId"], "127.0.0.2", fake.port)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "127.0.0.1"
    await until(
        hass,
        lambda: (
            entry.state is ConfigEntryState.LOADED
            and entry.runtime_data.host == "127.0.0.1"
            and entry.runtime_data.session.status_is_live
        ),
        "the entry was not reloaded at the new address",
    )


async def test_dhcp_sends_nothing_for_a_purifier_at_its_known_address(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=fake.state["DeviceId"], data={CONF_HOST: "127.0.0.1"})
    entry.add_to_hass(hass)
    key = DiscoveryKey(domain="dhcp", key=MAC.replace(":", ""), version=1)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP, "discovery_key": key}, data=dhcp()
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert not fake.requests
    # Tied to the entry, so that Home Assistant offers the purifier again once the entry is removed.
    assert entry.discovery_keys == {"dhcp": (key,)}


async def test_dhcp_keeps_a_host_name_that_leads_to_the_address_it_saw(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    """DHCP sees the purifier at 127.0.0.1, where the host name in the entry leads: the owner's name stays."""
    entry = purifier_entry(hass, fake.state["DeviceId"], "localhost", fake.port)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "localhost"
    assert not fake.requests


async def test_dhcp_follows_a_purifier_to_an_address_that_another_entry_still_names(
    hass: HomeAssistant, fake, default_port: int
) -> None:
    """Two purifiers swapped addresses: ours is now at 127.0.0.1, the address the other entry names.

    The session of that other entry reports that another device answers there, so DHCP asks who it is.
    """
    ours = purifier_entry(hass, fake.state["DeviceId"], "192.0.2.7", fake.port)
    other = purifier_entry(hass, OTHER_ID, "127.0.0.1", fake.port, title="Slaapkamer")
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()
    await until(hass, lambda: other.runtime_data.session.identity_mismatch, "the other entry did not notice")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert ours.data[CONF_HOST] == "127.0.0.1"
    assert other.data[CONF_HOST] == "127.0.0.1"  # its own session goes on looking for it


async def test_a_discovered_purifier_that_moves_before_it_is_confirmed_is_added_at_its_new_address(
    hass: HomeAssistant, fake, default_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DHCP offers the purifier, which gets another address before the owner confirms: the offer shows the new one.

    The simulator answers for both addresses; they are loopback ones, so that the entry sends nothing beyond this
    computer.
    """
    real_identify = config_flow.async_identify

    async def identify_anywhere(host: str) -> Any:
        return await real_identify("127.0.0.1")

    monkeypatch.setattr(config_flow, "async_identify", identify_anywhere)
    first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp("127.0.0.20"))
    assert first["type"] is FlowResultType.FORM and first["step_id"] == "discovery_confirm"
    second = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp("127.0.0.21"))
    assert second["type"] is FlowResultType.FORM
    waiting = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["flow_id"] for flow in waiting] == [second["flow_id"]]
    result = await hass.config_entries.flow.async_configure(second["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["data"][CONF_HOST] == "127.0.0.21"
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_an_offer_the_owner_opened_is_left_alone(
    hass: HomeAssistant, fake, default_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_identify = config_flow.async_identify

    async def identify_anywhere(host: str) -> Any:
        return await real_identify("127.0.0.1")

    monkeypatch.setattr(config_flow, "async_identify", identify_anywhere)
    first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp("127.0.0.20"))
    # Opening the card in the frontend reads the flow, which counts as working on it.
    await hass.config_entries.flow.async_configure(first["flow_id"])
    second = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp("127.0.0.21"))
    assert second["type"] is FlowResultType.ABORT and second["reason"] == "already_in_progress"
    assert [flow["flow_id"] for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)] == [
        first["flow_id"]
    ]


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


# -- the MAC address -------------------------------------------------------------------------------


async def test_the_mac_address_is_noted_for_dhcp(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = neighbour_table(monkeypatch)
    entry = await setup()
    await until(
        hass, lambda: (dr.CONNECTION_NETWORK_MAC, MAC) in our_device(hass, entry).connections, "the MAC was not noted"
    )
    assert asked == ["127.0.0.1"]
    assert DOMAIN in dhcp_matches(hass, MAC)


async def test_the_mac_address_is_noted_on_the_first_start(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The purifier answers before its device exists, as when the platforms take long to load; its MAC is noted."""
    forward = hass.config_entries.async_forward_entry_setups

    async def platforms_after_the_first_answer(config_entry: Any, platforms: Any) -> None:
        await until(hass, lambda: config_entry.runtime_data.session.status_is_live, "no status")
        await asyncio.sleep(0.1)  # time for a lookup that would find no device
        await forward(config_entry, platforms)

    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", platforms_after_the_first_answer)
    asked = neighbour_table(monkeypatch)
    entry = await setup()
    await until(
        hass, lambda: (dr.CONNECTION_NETWORK_MAC, MAC) in our_device(hass, entry).connections, "the MAC was not noted"
    )
    assert asked == ["127.0.0.1"]


async def test_the_mac_address_is_noted_although_a_router_integration_tracks_the_purifier(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In 2026.11 devices of different config entries may share a MAC; a router's device tracker has one per client."""
    router = MockConfigEntry(domain="fritz", title="FRITZ!Box 7590")
    router.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=router.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, MAC)}, name="mxchip"
    )
    neighbour_table(monkeypatch)
    entry = await setup()
    await until(
        hass, lambda: (dr.CONNECTION_NETWORK_MAC, MAC) in our_device(hass, entry).connections, "the MAC was not noted"
    )
    assert dhcp_matches(hass, MAC) == {"fritz", DOMAIN}


async def test_a_mac_address_of_another_purifier_is_not_taken(
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
    asked = neighbour_table(monkeypatch)
    entry = await setup()
    await until(hass, lambda: bool(asked))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (dr.CONNECTION_NETWORK_MAC, MAC) not in our_device(hass, entry).connections


async def test_the_mac_address_of_another_purifier_at_the_address_is_not_noted(
    hass: HomeAssistant, fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The address in the entry now belongs to another purifier, which answers the ping long before it is identified.

    Measured: a ping is answered after about 0.1 s, the info request after 0.5 to 1.3 s and a new registration after
    0.2 to 2.1 s; here 0.3 s and 0.2 s.
    """
    loop = asyncio.get_running_loop()
    answer_info = fake._handle_info
    fake._handle_info = lambda msg, sender: fake._timers.append(loop.call_later(0.3, answer_info, msg, sender))
    fake.registration_answer_delay = 0.2
    asked = neighbour_table(monkeypatch)  # the MAC of the purifier that answers
    entry = purifier_entry(hass, OTHER_ID, "127.0.0.1", fake.port, title="Slaapkamer")
    # The device is in the registry from the runs before this start.
    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, OTHER_ID)})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await until(hass, lambda: entry.runtime_data.session.identity_mismatch, "the other purifier was not noticed")
    await asyncio.sleep(0.2)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not asked
    assert (dr.CONNECTION_NETWORK_MAC, MAC) not in our_device(hass, entry).connections


async def test_a_mac_address_that_is_not_in_the_table_is_looked_up_less_often(
    hass: HomeAssistant, fake, setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As in a container that does not share the host's network: the table never lists the purifier."""
    monkeypatch.setattr(coordinator_module, "MAC_RETRY", 0.05)
    monkeypatch.setattr(coordinator_module, "MAC_RETRY_MAX", 0.2)
    monkeypatch.setattr(coordinator_module, "REDISCOVER_CHECK", 0.01)
    times: list[float] = []
    monkeypatch.setattr(coordinator_module, "read_mac", lambda host: times.append(time.monotonic()))  # finds nothing
    entry = await setup()
    await until(hass, lambda: len(times) >= 4, "not looked up four times")
    gaps = [later - earlier for earlier, later in itertools.pairwise(times)]
    # Waits of 0.1, 0.2 and 0.2 s (doubled, up to the maximum); only lower bounds, a slow machine is later.
    assert gaps[0] >= 0.08 and gaps[1] >= 0.17 and gaps[2] >= 0.17, gaps
    assert (dr.CONNECTION_NETWORK_MAC, MAC) not in our_device(hass, entry).connections


async def test_the_default_fixtures_keep_the_real_neighbour_table_out(
    hass: HomeAssistant, fake, entry, setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A table that lists the simulator's address stands in for the one of the machine the tests run on."""
    table = tmp_path / "arp"
    table.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "127.0.0.1        0x1         0x2         68:79:c4:12:34:56     *        lo\n"
    )
    monkeypatch.setattr(search_module, "ARP_TABLE", table)
    # The device is in the registry from the runs before this start, so a lookup could note what it reads.
    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.unique_id)})
    await setup()
    await asyncio.sleep(0.3)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (dr.CONNECTION_NETWORK_MAC, MAC) not in our_device(hass, entry).connections


def test_the_neighbour_table_gives_only_a_complete_real_mac(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    table = tmp_path / "arp"
    table.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "10.10.10.113     0x1         0x2         68:79:C4:12:34:56     *        eth0\n"
        "10.10.10.68      0x1         0x0         00:00:00:00:00:00     *        eth0\n"
        "10.10.10.70      0x1         0x2         00:00:00:00:00:00     *        eth0\n"
        "10.10.10.80      0x1         0x2         02:aa:bb:cc:dd:ee     *        eth0\n"
        "10.10.10.81      0x1         0x2         02:AA:BB:CC:DD:EE     *        eth0\n"
        "10.10.10.90      0x1         0x0         68:79:c4:12:34:56     *        eth0\n"
    )
    monkeypatch.setattr(search_module, "ARP_TABLE", table)
    assert READ_MAC("10.10.10.113") == MAC  # an incomplete entry with the same MAC does not count
    assert READ_MAC("10.10.10.68") is None  # not complete
    assert READ_MAC("10.10.10.70") is None  # all zeros merged devices in another integration
    assert READ_MAC("10.10.10.80") is None  # one MAC for two addresses: a repeater answering for both
    assert READ_MAC("10.10.10.1") is None
    assert READ_MAC("woonkamer.lan") is None  # a host name is not looked up
    monkeypatch.setattr(search_module, "ARP_TABLE", tmp_path / "missing")
    assert READ_MAC("10.10.10.113") is None


# -- a new address after a move --------------------------------------------------------------------


async def test_a_purifier_that_moved_is_found_again(
    hass: HomeAssistant, search_finds, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = search_finds
    quick_research(monkeypatch)
    entry = purifier_entry(hass, fake.state["DeviceId"], "127.0.0.2", fake.port)  # nothing answers there any more
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


async def test_a_purifier_whose_old_address_another_purifier_took_is_looked_for(
    hass: HomeAssistant, at_two_addresses, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another purifier answers at the address in the entry, so the session is not OFFLINE; ours is looked for."""
    ours, _ = at_two_addresses
    quick_research(monkeypatch)
    broadcast_reaches(monkeypatch, "127.0.0.1", "127.0.0.2")
    entry = purifier_entry(hass, ours.state["DeviceId"], "127.0.0.1", ours.port)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await until(hass, lambda: entry.runtime_data.session.identity_mismatch, "the other purifier was not noticed")
    await until(hass, lambda: entry.data[CONF_HOST] == "127.0.0.2", "the purifier was not looked for")
    await until(
        hass,
        lambda: entry.state is ConfigEntryState.LOADED and entry.runtime_data.session.status_is_live,
        "the entry did not come back at the new address",
    )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_re_search_keeps_a_host_name_that_still_leads_to_the_purifier(
    hass: HomeAssistant, search_finds, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The purifier was away and is back where its name leads, but the offline session has not probed it yet.

    The search finds it at 127.0.0.1, where "localhost" leads: no new address, no reload.
    """
    fake = search_finds
    quick_research(monkeypatch)
    # Searches made while the purifier is still away find nothing and double the wait; under load that
    # can be several before it is back. Capped here, so that the next search comes soon.
    monkeypatch.setattr(coordinator_module, "REDISCOVER_MAX", 0.6)
    # And each search listens long enough for an answer when the machine is busy.
    monkeypatch.setattr("custom_components.philips_pureprotect.search.SEARCH_WAIT", 0.5)
    searches = count_searches(monkeypatch)
    monkeypatch.setattr(coordinator_module, "SESSION_OPTIONS", options(offline_backoff=(30.0,), refresh_interval=30.0))
    entry = purifier_entry(hass, fake.state["DeviceId"], "localhost", fake.port)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await until(hass, lambda: coordinator.session.status_is_live, "no status arrived")
    old_port = fake.registrations[-1][0][1]
    fake.silent = True
    await until(hass, lambda: coordinator.session.state is SessionState.OFFLINE, "the purifier did not go offline")
    # Going offline, the session opened a new socket and registered from it; that was lost too. Waiting for a
    # registration from the new port, not for any registration: one sent while the session still had doubts
    # comes from the old port, and the new one, answered once the purifier is back, would end the test's premise.
    await until(
        hass,
        lambda: any(sender[1] != old_port for sender, _ in fake.registrations),
        "no registration from a new socket",
    )
    fake.silent = False  # back; the session probes again only after 30 s
    await until(hass, lambda: any(found for found in searches), "the search did not find it", timeout=15.0)
    await hass.async_block_till_done()
    assert coordinator.session.state is SessionState.OFFLINE  # so the search did judge the address
    assert entry.data[CONF_HOST] == "localhost"
    assert entry.runtime_data is coordinator, "the entry was reloaded"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_host_name_that_leads_to_the_purifier_again_is_looked_up_afresh(
    hass: HomeAssistant, at_two_addresses, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The name led to the address another purifier has now, and leads to ours again: the entry is reloaded.

    The session looks a name up again by itself while nothing answers, not while another device does.
    """
    ours, _ = at_two_addresses
    quick_research(monkeypatch)
    broadcast_reaches(monkeypatch, "127.0.0.1", "127.0.0.2")
    entry = purifier_entry(hass, ours.state["DeviceId"], "localhost", ours.port)  # the session goes to 127.0.0.1
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    first = entry.runtime_data
    await until(hass, lambda: first.session.identity_mismatch, "the other purifier was not noticed")

    async def name_leads_to_ours_now(hass: HomeAssistant, host: str) -> set[str]:
        return {"127.0.0.2"}

    monkeypatch.setattr(coordinator_module, "async_addresses", name_leads_to_ours_now)
    await until(hass, lambda: entry.runtime_data is not first, "the entry was not reloaded")
    assert entry.data[CONF_HOST] == "localhost"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_purifier_that_is_not_found_is_looked_for_less_often(
    hass: HomeAssistant, fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coordinator_module, "REDISCOVER_AFTER", 0.1)
    monkeypatch.setattr(coordinator_module, "REDISCOVER_MAX", 0.4)
    monkeypatch.setattr(coordinator_module, "REDISCOVER_CHECK", 0.02)
    times: list[float] = []
    real = coordinator_module.async_search

    async def timed(hass: HomeAssistant, port: int) -> Any:
        times.append(time.monotonic())
        return await real(hass, port)

    monkeypatch.setattr(coordinator_module, "async_search", timed)
    entry = purifier_entry(hass, fake.state["DeviceId"], "127.0.0.2", fake.port)  # nothing answers, nothing found
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await until(hass, lambda: len(times) >= 4, "not searched four times")
    gaps = [later - earlier for earlier, later in itertools.pairwise(times)]
    # Waits of 0.2, 0.4 and 0.4 s (doubled, up to the maximum); only lower bounds, a slow machine is later.
    assert gaps[0] >= 0.18 and gaps[1] >= 0.38 and gaps[2] >= 0.38, gaps
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_search_stops_when_its_entry_is_removed(
    hass: HomeAssistant, search_finds, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = search_finds
    quick_research(monkeypatch)
    monkeypatch.setattr(search_module, "SEARCH_ROUNDS", 4)
    monkeypatch.setattr(search_module, "SEARCH_WAIT", 0.3)
    entry = purifier_entry(hass, fake.state["DeviceId"], "127.0.0.2", fake.port)  # nothing answers there
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    infos: Callable[[], int] = lambda: fake.requests.count(("NON", "/sys/dev/info"))
    await until(hass, lambda: coordinator._searching and infos() > 0, "no search started")
    await hass.config_entries.async_remove(entry.entry_id)
    sent = infos()
    await asyncio.sleep(1.5)  # longer than the rounds that were left
    assert infos() == sent, "the search went on after its entry was removed"
    assert not coordinator._searching
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


async def test_search_offers_only_the_ac3220(hass: HomeAssistant, search_finds, default_port: int) -> None:
    search_finds.state["D01S05"] = "AC2220/10"  # another Philips purifier with the same Wi-Fi module
    result = await search(hass)
    assert result["step_id"] == "manual" and result["errors"] == {"base": "no_devices_found"}


async def test_dhcp_lets_another_philips_model_go(hass: HomeAssistant, fake, default_port: int) -> None:
    fake.state["D01S05"] = "AC2220/10"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=dhcp())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "unsupported_model"
    assert result["description_placeholders"] == {"model": "AC2220/10"}


async def test_another_model_can_still_be_added_by_its_address(hass: HomeAssistant, fake, default_port: int) -> None:
    fake.state["D01S05"] = "AC2220/10"
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    form = await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": "manual"})
    result = await hass.config_entries.flow.async_configure(form["flow_id"], {CONF_HOST: "127.0.0.1"})
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["data"][CONF_MODEL] == "AC2220/10"
