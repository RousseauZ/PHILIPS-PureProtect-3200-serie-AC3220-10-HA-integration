"""Finding purifiers on the network, and their MAC address."""

from __future__ import annotations

import ipaddress
from pathlib import Path

from homeassistant.components import network
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import format_mac

from .airlink import Identity, discover
from .const import LOGGER

# A broadcast was answered in 2 of 5 rounds (docs/metingen.md, measurement
# 11), so a search asks several times: about six seconds in all.
SEARCH_ROUNDS = 4
SEARCH_WAIT = 1.5
ARP_TABLE = Path("/proc/net/arp")
_NO_MAC = {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}


async def async_search_targets(hass: HomeAssistant) -> list[str]:
    """Return the broadcast addresses of the networks Home Assistant is in."""
    return sorted(str(address) for address in await network.async_get_ipv4_broadcast_addresses(hass))


async def async_search(hass: HomeAssistant, port: int) -> dict[str, Identity]:
    """Ask the network who is a purifier; returns {address: identity}."""
    targets = await async_search_targets(hass)
    found = await discover(targets, port=port, rounds=SEARCH_ROUNDS, round_wait=SEARCH_WAIT)
    LOGGER.debug("Search in %s found %s", targets, {address: identity.device_id for address, identity in found.items()})
    return found


def read_mac(host: str) -> str | None:
    """Return the MAC address the operating system knows for an IPv4 address.

    Reads the neighbour table of Linux, which Home Assistant OS and the
    container install share with the host. Incomplete entries and the
    all-zero and broadcast addresses are not a device's MAC (they merged
    devices in another integration). Blocking: run it in the executor.
    """
    try:
        address = str(ipaddress.IPv4Address(host))
        lines = ARP_TABLE.read_text(encoding="ascii", errors="replace").splitlines()[1:]
    except (ValueError, OSError):
        return None
    for line in lines:
        fields = line.split()
        if len(fields) < 4 or fields[0] != address:
            continue
        flags, mac = fields[2], fields[3].lower()
        try:
            complete = int(flags, 16) & 0x2
        except ValueError:
            continue
        if complete and mac not in _NO_MAC:
            return format_mac(mac)
    return None
