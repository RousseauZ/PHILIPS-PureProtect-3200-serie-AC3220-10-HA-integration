"""Codec tests against hand-derived byte strings (RFC 7252 section 3)."""

import pytest

from pureprotect_probe.coap import (
    CONTENT,
    EMPTY,
    GET,
    OPT_MAX_AGE,
    OPT_OBSERVE,
    OPT_URI_PATH,
    CoapError,
    Message,
    MType,
    build_request,
    code_text,
    uint_bytes,
)

# NON GET /sys/dev/status, Observe: 0, MID 0x1234, token AABBCCDD.
# 0x54 = version 1, type NON (1), token length 4. 0x60 = option delta 6, length 0.
# 0x53 = delta 5 (11 - 6), length 3. 0x03 and 0x06 repeat Uri-Path with delta 0.
REGISTER = bytes.fromhex("54011234aabbccdd60" "53737973" "03646576" "06737461747573")


def test_encode_observe_registration() -> None:
    msg = build_request(MType.NON, GET, 0x1234, bytes.fromhex("aabbccdd"), "/sys/dev/status", observe=0)
    assert msg.encode() == REGISTER


def test_decode_observe_registration() -> None:
    msg = Message.decode(REGISTER)
    assert (msg.mtype, msg.code, msg.mid, msg.token) == (MType.NON, GET, 0x1234, bytes.fromhex("aabbccdd"))
    assert msg.uri_path == "/sys/dev/status"
    assert msg.observe == 0
    assert msg.payload == b""


def test_empty_messages() -> None:
    # CON ping: 0x40 = version 1, type CON, no token; code 0.00.
    assert Message(MType.CON, EMPTY, 0x0001).encode() == bytes.fromhex("40000001")
    # RST with the same message id: 0x70.
    reset = Message.decode(bytes.fromhex("70000001"))
    assert (reset.mtype, reset.code, reset.mid, reset.token) == (MType.RST, EMPTY, 1, b"")


def test_notification_with_payload() -> None:
    # 2.05 NON, Observe 0x0195 (2 bytes), Max-Age 60, payload "hi".
    # 0x62 = delta 6, length 2. 0x81 = delta 8 (14 - 6), length 1.
    raw = bytes.fromhex("5145abcd" "07" "620195" "813c" "ff" "6869")
    msg = Message.decode(raw)
    assert code_text(msg.code) == "2.05"
    assert msg.token == b"\x07"
    assert msg.observe == 0x0195
    assert msg.max_age == 60
    assert msg.payload == b"hi"
    assert msg.encode() == raw


def test_extended_delta_and_length() -> None:
    # Option 60 with a 300-byte value: delta 60 -> nibble 13 + (60 - 13),
    # length 300 -> nibble 14 + (300 - 269) as two bytes.
    value = bytes(range(256)) + bytes(44)
    msg = Message(MType.NON, CONTENT, 7, b"", [(60, value)])
    raw = msg.encode()
    assert raw[4:8] == bytes([0xDE, 60 - 13, 0x00, 300 - 269])
    assert Message.decode(raw).options == [(60, value)]


def test_option_order_is_stable() -> None:
    msg = Message(
        MType.NON,
        GET,
        1,
        b"",
        [(OPT_URI_PATH, b"a"), (OPT_MAX_AGE, uint_bytes(60)), (OPT_URI_PATH, b"b"), (OPT_OBSERVE, b"")],
    )
    decoded = Message.decode(msg.encode())
    assert [number for number, _ in decoded.options] == [OPT_OBSERVE, OPT_URI_PATH, OPT_URI_PATH, OPT_MAX_AGE]
    assert decoded.uri_path == "/a/b"


def test_block2_is_reported() -> None:
    # Block2 (23) value 0x1E = block 1, more flag set, size exponent 6 (1024 bytes).
    msg = Message.decode(Message(MType.NON, CONTENT, 1, b"", [(23, b"\x1e")]).encode())
    assert msg.block2 == (1, True, 1024)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x40\x01\x00",  # shorter than the header
        bytes.fromhex("80010001"),  # version 2
        bytes.fromhex("49010001"),  # token length 9
        bytes.fromhex("44010001aa"),  # token truncated
        bytes.fromhex("40010001f0"),  # reserved nibble 15
        bytes.fromhex("4001000113"),  # option value truncated
        bytes.fromhex("40010001d0"),  # extension byte missing
    ],
)
def test_malformed_datagrams_are_rejected(raw: bytes) -> None:
    with pytest.raises(CoapError):
        Message.decode(raw)


def test_uint_bytes_is_minimal() -> None:
    assert uint_bytes(0) == b""
    assert uint_bytes(60) == b"\x3c"
    assert uint_bytes(256) == b"\x01\x00"
