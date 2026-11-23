"""Find purifiers on the local network with the plaintext info resource.

One ``GET /sys/dev/info`` to a broadcast address is enough to find and
identify a purifier: the answer carries its ``device_id``, the same id as in
its encrypted status. Asking for it registers nothing and does not touch the
counter, so a search cannot disturb a session that already serves a device.

Measured on an AC3220/10 (docs/metingen.md, measurement 11): the broadcast
was answered in 2 of 5 rounds and multicast in none, and another device on
the network (a television) answers the same request without any ids. So a
search asks several rounds and keeps only answers that carry both ids.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
from collections.abc import Iterable
from typing import Any

from .coap import DEFAULT_PORT, GET, CoapError, Message, MType, build_request, code_class
from .models import Identity

_LOGGER = logging.getLogger(__package__)

INFO_PATH = "/sys/dev/info"


def parse_info(payload: bytes) -> Identity | None:
    """Return the identity in an info answer; None for anything that is not a purifier's."""
    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    device_id, product_id = data.get("device_id"), data.get("product_id")
    if not isinstance(device_id, str) or not device_id or not isinstance(product_id, str) or not product_id:
        return None

    def text(key: str) -> str:
        value = data.get(key)
        return value if isinstance(value, str) else ""

    return Identity(
        device_id=device_id, product_id=product_id, model_id=text("modelid"), type=text("type"), name=text("name")
    )


class _Collector(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.tokens: set[bytes] = set()
        self.found: dict[str, Identity] = {}

    def datagram_received(self, data: bytes, addr: Any) -> None:
        try:
            msg = Message.decode(data)
        except CoapError:
            return
        if msg.mtype not in (MType.NON, MType.ACK, MType.CON) or msg.token not in self.tokens:
            return
        if code_class(msg.code) != 2:
            return
        identity = parse_info(msg.payload)
        if identity is not None:
            self.found.setdefault(str(addr[0]), identity)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("search: %s", exc)


async def discover(
    targets: Iterable[str], *, port: int = DEFAULT_PORT, rounds: int = 4, round_wait: float = 1.5
) -> dict[str, Identity]:
    """Ask every target for its identity, several rounds; return {address: identity}.

    Targets are broadcast addresses, or single addresses. Every round sends
    one request to each target and listens ``round_wait`` seconds; the first
    answer of an address counts. An address that cannot be sent to is
    skipped. Never raises for the network: no answer means an empty result.
    """
    targets = list(dict.fromkeys(targets))
    if not targets:
        return {}
    loop = asyncio.get_running_loop()
    collector = _Collector()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: collector, local_addr=("0.0.0.0", 0), family=socket.AF_INET, allow_broadcast=True
        )
    except OSError as err:
        _LOGGER.debug("search: no socket: %s", err)
        return {}
    try:
        mid = int.from_bytes(os.urandom(2), "big")
        for _ in range(rounds):
            for target in targets:
                token = os.urandom(4)
                collector.tokens.add(token)
                mid = (mid + 1) & 0xFFFF
                with contextlib.suppress(OSError):
                    transport.sendto(build_request(MType.NON, GET, mid, token, INFO_PATH).encode(), (target, port))
            await asyncio.sleep(round_wait)
    finally:
        transport.close()
    return dict(collector.found)
