"""Payload envelope of the Philips purifier protocol.

Wire format, all upper-case ASCII hex::

    [counter: 8 chars][ciphertext: n * 32 chars][sha256 digest: 64 chars]

Key and IV are the two halves of ``upper(hex(md5("JiangPan" + counter)))``,
used as ASCII bytes. The cipher is AES-128-CBC with PKCS7 padding. The
digest is a plain SHA-256 over ``counter + ciphertext`` without any secret,
so this is obfuscation and not security.
"""

from __future__ import annotations

import hashlib
import re

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SECRET = "JiangPan"
COUNTER_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
_DIGEST_LEN = 64
_BLOCK_HEX = 32


class EnvelopeError(ValueError):
    """Raised when an envelope cannot be decoded; ``reason`` is a short tag."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_valid_counter(text: str) -> bool:
    """Return True when the text is exactly eight hex characters."""
    return bool(COUNTER_RE.match(text))


def next_counter(counter: str) -> str:
    """Return the counter plus one, wrapping at 32 bits."""
    if not is_valid_counter(counter):
        raise EnvelopeError("bad_counter")
    return f"{(int(counter, 16) + 1) % 0x1_0000_0000:08X}"


def _cipher(counter: str) -> Cipher:
    digest = hashlib.md5((SECRET + counter).encode()).hexdigest().upper()  # noqa: S324
    key = digest[:16].encode()
    iv = digest[16:].encode()
    return Cipher(algorithms.AES(key), modes.CBC(iv))


def encrypt(counter: str, plaintext: str) -> str:
    """Encrypt plaintext with the given counter and return the envelope."""
    if not is_valid_counter(counter):
        raise EnvelopeError("bad_counter")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = _cipher(counter).encryptor()
    ciphertext = (encryptor.update(padded) + encryptor.finalize()).hex().upper()
    digest = hashlib.sha256((counter + ciphertext).encode()).hexdigest().upper()
    return counter + ciphertext + digest


def decrypt(envelope: str) -> tuple[str, str]:
    """Decode an envelope and return (counter, plaintext)."""
    if len(envelope) < 8 + _BLOCK_HEX + _DIGEST_LEN:
        raise EnvelopeError("too_short")
    counter = envelope[:8]
    ciphertext = envelope[8:-_DIGEST_LEN]
    digest = envelope[-_DIGEST_LEN:]
    if not is_valid_counter(counter):
        raise EnvelopeError("bad_counter")
    expected = hashlib.sha256((counter + ciphertext).encode()).hexdigest().upper()
    if digest != expected:
        raise EnvelopeError("digest_mismatch")
    if len(ciphertext) % _BLOCK_HEX or not _HEX_RE.match(ciphertext):
        raise EnvelopeError("bad_ciphertext")
    decryptor = _cipher(counter).decryptor()
    padded = decryptor.update(bytes.fromhex(ciphertext)) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    try:
        plain = unpadder.update(padded) + unpadder.finalize()
    except ValueError as err:
        raise EnvelopeError("bad_padding") from err
    try:
        return counter, plain.decode()
    except UnicodeDecodeError as err:
        raise EnvelopeError("bad_utf8") from err
