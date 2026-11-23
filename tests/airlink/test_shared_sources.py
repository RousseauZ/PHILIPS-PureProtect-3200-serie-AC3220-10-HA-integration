"""The wire codec and the payload envelope are shared with the measurement tool.

They were verified against the real device through ``tools/probe``. The copies
in the integration must stay byte-identical, so that a fix made on one side
cannot be forgotten on the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tools" / "probe" / "pureprotect_probe"
AIRLINK = ROOT / "custom_components" / "philips_pureprotect" / "airlink"


@pytest.mark.parametrize("name", ["coap.py", "crypto.py"])
def test_copy_is_identical_to_the_probe(name: str) -> None:
    assert (AIRLINK / name).read_bytes() == (PROBE / name).read_bytes(), (
        f"airlink/{name} differs from tools/probe/pureprotect_probe/{name}; change both or neither"
    )


def test_package_does_not_import_home_assistant() -> None:
    for source in AIRLINK.glob("*.py"):
        text = source.read_text()
        assert "homeassistant" not in text, f"{source.name} mentions homeassistant"
        assert "aiocoap" not in text, f"{source.name} mentions aiocoap"
