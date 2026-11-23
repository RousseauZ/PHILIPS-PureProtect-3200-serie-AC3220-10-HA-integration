"""Finding purifiers on the network, their addresses and their MAC address."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
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
# How long a host name may take to resolve (seconds).
RESOLVE_TIMEOUT = 5.0


async def async_search_targets(hass: HomeAssistant) -> list[str]:
    """Return the broadcast addresses of the networks Home Assistant is in."""
    return sorted(str(address) for address in await network.async_get_ipv4_broadcast_addresses(hass))


async def async_search(hass: HomeAssistant, port: int) -> dict[str, Identity]:
    """Ask the network who is a purifier; returns {address: identity}."""
    targets = await async_search_targets(hass)
    found = await discover(targets, port=port, rounds=SEARCH_ROUNDS, round_wait=SEARCH_WAIT)
    LOGGER.debug("Search in %s found %s", targets, {address: identity.device_id for address, identity in found.items()})
    return found


def is_address(host: str) -> bool:
    """Return True for an IPv4 address, False for a host name."""
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return True


async def async_addresses(hass: HomeAssistant, host: str) -> set[str]:
    """Return the IPv4 addresses a configured host stands for now.

    An address stands for itself; a host name for what it resolves to at
    this moment, the way the session looks it up. Empty for a name that
    cannot be resolved.
    """
    if not host:
        return set()
    if is_address(host):
        return {str(ipaddress.IPv4Address(host))}
    try:
        async with asyncio.timeout(RESOLVE_TIMEOUT):
            infos = await hass.loop.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_DGRAM)
    except (OSError, TimeoutError, UnicodeError) as err:
        LOGGER.debug("Cannot resolve %s: %r", host, err)
        return set()
    return {str(info[4][0]) for info in infos}


def read_mac(host: str) -> str | None:
    """Return the MAC address the operating system knows for an IPv4 address.

    Reads the neighbour table of Linux, which Home Assistant OS and the
    container install share with the host. Incomplete entries and the
    all-zero and broadcast addresses are not a device's MAC (they merged
    devices in another integration). Neither is a MAC the table lists for
    several addresses: that is a Wi-Fi repeater or a proxy answering for the
    devices behind it. Blocking: run it in the executor.
    """
    try:
        address = str(ipaddress.IPv4Address(host))
        lines = ARP_TABLE.read_text(encoding="ascii", errors="replace").splitlines()[1:]
    except (ValueError, OSError):
        return None
    complete: dict[str, str] = {}  # address: MAC
    for line in lines:
        fields = line.split()
        if len(fields) < 4:
            continue
        try:
            flags = int(fields[2], 16)
        except ValueError:
            continue
        mac = fields[3].lower()
        if flags & 0x2 and mac not in _NO_MAC:
            complete[fields[0]] = mac
    found = complete.get(address)
    if found is None:
        return None
    if any(other != address and known == found for other, known in complete.items()):
        LOGGER.debug("%s: MAC %s is listed for several addresses; not taken", address, found)
        return None
    return format_mac(found)
