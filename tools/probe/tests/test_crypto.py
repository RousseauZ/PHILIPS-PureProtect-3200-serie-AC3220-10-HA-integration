"""Envelope tests, including a payload captured from a real device."""

import json
from pathlib import Path

import pytest

from pureprotect_probe import crypto

VECTOR = (Path(__file__).parent / "vectors" / "ac0850_status.txt").read_text().strip()


def test_decrypts_captured_device_payload() -> None:
    counter, plain = crypto.decrypt(VECTOR)
    assert counter == "F45D4729"
    reported = json.loads(plain)["state"]["reported"]
    assert reported["D01-05"] == "AC0850/11"


def test_reencrypting_the_captured_plaintext_gives_the_same_bytes() -> None:
    counter, plain = crypto.decrypt(VECTOR)
    assert crypto.encrypt(counter, plain) == VECTOR


def test_round_trip() -> None:
    envelope = crypto.encrypt("0000ABCD", '{"state":{"desired":{"D03102":1}}}')
    assert envelope[:8] == "0000ABCD"
    assert envelope == envelope.upper()
    assert (len(envelope) - 72) % 32 == 0
    assert crypto.decrypt(envelope) == ("0000ABCD", '{"state":{"desired":{"D03102":1}}}')


def test_next_counter_increments_and_wraps() -> None:
    assert crypto.next_counter("0000000F") == "00000010"
    assert crypto.next_counter("ffffffff") == "00000000"


@pytest.mark.parametrize("text", ["", "1234567", "123456789", "12345G78", "123456\x00\x00"])
def test_invalid_counters(text: str) -> None:
    assert not crypto.is_valid_counter(text)
    with pytest.raises(crypto.EnvelopeError):
        crypto.next_counter(text)


def test_tampering_is_detected() -> None:
    envelope = crypto.encrypt("00000001", "hello")
    broken = envelope[:10] + ("0" if envelope[10] != "0" else "1") + envelope[11:]
    with pytest.raises(crypto.EnvelopeError) as err:
        crypto.decrypt(broken)
    assert err.value.reason == "digest_mismatch"


def test_nul_bytes_with_a_valid_digest_are_reported_as_bad_ciphertext() -> None:
    import hashlib

    envelope = crypto.encrypt("00000001", "x" * 100)
    body = envelope[8:-64]
    body = body[:20] + "\x00\x00" + body[22:]
    digest = hashlib.sha256(("00000001" + body).encode()).hexdigest().upper()
    with pytest.raises(crypto.EnvelopeError) as err:
        crypto.decrypt("00000001" + body + digest)
    assert err.value.reason == "bad_ciphertext"


def test_short_input() -> None:
    with pytest.raises(crypto.EnvelopeError) as err:
        crypto.decrypt("00000001ABCD")
    assert err.value.reason == "too_short"
