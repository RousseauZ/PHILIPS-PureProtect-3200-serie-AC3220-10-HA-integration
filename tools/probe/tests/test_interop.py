"""Cross-checks against independent implementations.

These tests run only when the packages are installed
(``pip install -r requirements-dev.txt``). They guard against a mistake that
the codec, the client and the simulator would otherwise share.
"""

import os
import warnings

import pytest

from pureprotect_probe import coap, crypto


def test_codec_agrees_with_aiocoap() -> None:
    aiocoap = pytest.importorskip("aiocoap")
    from aiocoap.numbers.codes import Code

    warnings.simplefilter("ignore", DeprecationWarning)
    kinds = {aiocoap.NON: coap.MType.NON, aiocoap.CON: coap.MType.CON, aiocoap.ACK: coap.MType.ACK}
    for kind, expected in kinds.items():
        for token_length in (0, 1, 2, 4, 8):
            for observe in (None, 0, 1, 255, 256, 65536):
                for payload in (b"", b"x", os.urandom(300), os.urandom(2100)):
                    theirs = aiocoap.Message(mtype=kind, code=Code.CONTENT, mid=4321, token=os.urandom(token_length), payload=payload)
                    theirs.opt.uri_path = ("sys", "dev", "status")
                    theirs.opt.max_age = 60
                    if observe is not None:
                        theirs.opt.observe = observe
                    raw = theirs.encode()
                    ours = coap.Message.decode(raw)
                    assert (ours.mtype, ours.mid, ours.token, ours.payload) == (expected, 4321, theirs.token, payload)
                    assert (ours.uri_path, ours.observe, ours.max_age) == ("/sys/dev/status", observe, 60)
                    assert ours.encode() == raw
    for path, observe, payload in (("/sys/dev/sync", None, b"AD48E910"), ("/sys/dev/status", 0, b""), ("/sys/dev/status", 1, b"")):
        ours = coap.build_request(coap.MType.NON, coap.POST if payload else coap.GET, 0xBEEF, os.urandom(4), path, observe=observe, payload=payload)
        theirs = aiocoap.Message.decode(ours.encode())
        assert "/" + "/".join(theirs.opt.uri_path) == path
        assert (theirs.opt.observe, theirs.payload, theirs.mid, theirs.token) == (observe, payload, 0xBEEF, ours.token)
    ping = aiocoap.Message.decode(coap.Message(coap.MType.CON, coap.EMPTY, 7).encode())
    assert ping.mtype == aiocoap.CON and ping.code == Code.EMPTY


def test_envelope_agrees_with_the_reference_client() -> None:
    encryption = pytest.importorskip("aioairctrl.coap.encryption")
    for counter in ("00000000", "0000FFFF", "FFFFFFFE", "FFFFFFFF", "7FFFFFFF"):
        for text in ("", "x", '{"state":{"desired":{"D03102":1}}}', "é" * 50, "A" * 16, "B" * 2000):
            reference = encryption.EncryptionContext()
            reference.set_client_key(counter)
            envelope = reference.encrypt(text)  # the reference increments the counter first
            following = crypto.next_counter(counter)
            assert envelope[:8] == following
            assert crypto.encrypt(following, text) == envelope
            assert crypto.decrypt(envelope) == (following, text)
            assert encryption.EncryptionContext().decrypt(crypto.encrypt(following, text)) == text
