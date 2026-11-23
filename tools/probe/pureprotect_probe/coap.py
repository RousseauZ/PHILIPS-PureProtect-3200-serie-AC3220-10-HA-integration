"""Minimal CoAP message codec (RFC 7252), limited to what the purifier needs.

Supported: the 4-byte header, tokens, options with extended delta/length,
and the payload marker. Not supported: DTLS and block-wise transfer (a
Block2 option is decoded so that it can be reported, never acted upon).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

VERSION = 1
PAYLOAD_MARKER = 0xFF
DEFAULT_PORT = 5683
ALL_COAP_NODES = "224.0.1.187"


class CoapError(ValueError):
    """Raised when a datagram is not a well-formed CoAP message."""


class MType(enum.IntEnum):
    """CoAP message types."""

    CON = 0
    NON = 1
    ACK = 2
    RST = 3


# Codes are (class << 5) | detail.
EMPTY = 0x00
GET = 0x01
POST = 0x02
CONTENT = 0x45  # 2.05
CHANGED = 0x44  # 2.04

OPT_URI_HOST = 3
OPT_OBSERVE = 6
OPT_URI_PATH = 11
OPT_CONTENT_FORMAT = 12
OPT_MAX_AGE = 14
OPT_BLOCK2 = 23
OPT_SIZE2 = 28


def code_class(code: int) -> int:
    """Return the class part of a code (0 request, 2 success, 4/5 error)."""
    return code >> 5


def code_text(code: int) -> str:
    """Format a code the way the RFC writes it, for example ``2.05``."""
    return f"{code >> 5}.{code & 0x1F:02d}"


def uint_bytes(value: int) -> bytes:
    """Encode an option value as a minimal-length big-endian unsigned integer."""
    if value < 0:
        raise CoapError("negative option value")
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def _split_ext(value: int) -> tuple[int, bytes]:
    """Return the 4-bit nibble and the extension bytes for a delta or length."""
    if value < 13:
        return value, b""
    if value < 269:
        return 13, bytes([value - 13])
    if value < 65805:
        return 14, (value - 269).to_bytes(2, "big")
    raise CoapError("option delta or length too large")


def _read_ext(nibble: int, data: bytes, pos: int) -> tuple[int, int]:
    """Resolve a nibble to its value, reading extension bytes when needed."""
    if nibble < 13:
        return nibble, pos
    if nibble == 13:
        if pos + 1 > len(data):
            raise CoapError("truncated option extension")
        return data[pos] + 13, pos + 1
    if nibble == 14:
        if pos + 2 > len(data):
            raise CoapError("truncated option extension")
        return int.from_bytes(data[pos : pos + 2], "big") + 269, pos + 2
    raise CoapError("reserved option nibble 15")


@dataclass(slots=True)
class Message:
    """One CoAP message."""

    mtype: MType
    code: int
    mid: int
    token: bytes = b""
    options: list[tuple[int, bytes]] = field(default_factory=list)
    payload: bytes = b""

    def option_values(self, number: int) -> list[bytes]:
        """Return every value of an option, in order."""
        return [value for num, value in self.options if num == number]

    def option_uint(self, number: int) -> int | None:
        """Return the first value of an option as an integer, or None."""
        values = self.option_values(number)
        if not values:
            return None
        return int.from_bytes(values[0], "big")

    @property
    def uri_path(self) -> str:
        """Return the request path, for example ``/sys/dev/status``."""
        parts = [v.decode("utf-8", "replace") for v in self.option_values(OPT_URI_PATH)]
        return "/" + "/".join(parts)

    @property
    def observe(self) -> int | None:
        """Return the Observe option value, or None when absent."""
        return self.option_uint(OPT_OBSERVE)

    @property
    def max_age(self) -> int | None:
        """Return the Max-Age option value, or None when absent."""
        return self.option_uint(OPT_MAX_AGE)

    @property
    def block2(self) -> tuple[int, bool, int] | None:
        """Return (block number, more flag, block size) or None when absent."""
        raw = self.option_uint(OPT_BLOCK2)
        if raw is None:
            return None
        return raw >> 4, bool(raw & 0x08), 1 << ((raw & 0x07) + 4)

    def encode(self) -> bytes:
        """Serialise the message to datagram bytes."""
        if len(self.token) > 8:
            raise CoapError("token longer than 8 bytes")
        if not 0 <= self.mid <= 0xFFFF:
            raise CoapError("message id out of range")
        out = bytearray(
            [
                (VERSION << 6) | (int(self.mtype) << 4) | len(self.token),
                self.code,
                self.mid >> 8,
                self.mid & 0xFF,
            ]
        )
        out += self.token
        previous = 0
        # sorted() is stable, so repeated options (Uri-Path) keep their order.
        for number, value in sorted(self.options, key=lambda item: item[0]):
            delta_nibble, delta_ext = _split_ext(number - previous)
            length_nibble, length_ext = _split_ext(len(value))
            previous = number
            out.append((delta_nibble << 4) | length_nibble)
            out += delta_ext
            out += length_ext
            out += value
        if self.payload:
            out.append(PAYLOAD_MARKER)
            out += self.payload
        return bytes(out)

    @classmethod
    def decode(cls, data: bytes) -> Message:
        """Parse datagram bytes; raises CoapError when malformed."""
        if len(data) < 4:
            raise CoapError("shorter than the 4-byte header")
        if data[0] >> 6 != VERSION:
            raise CoapError(f"unsupported version {data[0] >> 6}")
        token_length = data[0] & 0x0F
        if token_length > 8:
            raise CoapError("token length above 8")
        pos = 4 + token_length
        if pos > len(data):
            raise CoapError("truncated token")
        message = cls(
            mtype=MType((data[0] >> 4) & 0x03),
            code=data[1],
            mid=(data[2] << 8) | data[3],
            token=bytes(data[4:pos]),
        )
        number = 0
        while pos < len(data):
            first = data[pos]
            pos += 1
            if first == PAYLOAD_MARKER:
                message.payload = bytes(data[pos:])
                break
            delta, pos = _read_ext(first >> 4, data, pos)
            length, pos = _read_ext(first & 0x0F, data, pos)
            number += delta
            if pos + length > len(data):
                raise CoapError("truncated option value")
            message.options.append((number, bytes(data[pos : pos + length])))
            pos += length
        return message


def build_request(
    mtype: MType,
    code: int,
    mid: int,
    token: bytes,
    path: str,
    *,
    observe: int | None = None,
    payload: bytes = b"",
) -> Message:
    """Build a GET or POST for a path such as ``/sys/dev/sync``."""
    options: list[tuple[int, bytes]] = []
    if observe is not None:
        options.append((OPT_OBSERVE, uint_bytes(observe)))
    for part in path.strip("/").split("/"):
        options.append((OPT_URI_PATH, part.encode()))
    return Message(mtype, code, mid, token, options, payload)
