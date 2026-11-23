"""The integration's own pictogram, which Home Assistant shows in its lists and on the device page."""

from __future__ import annotations

import struct
from pathlib import Path

from homeassistant import loader
from homeassistant.core import HomeAssistant

BRAND = Path(__file__).resolve().parents[2] / "custom_components" / "philips_pureprotect" / "brand"


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", header[16:24])


def test_every_icon_is_there_in_its_size() -> None:
    sizes = {name: png_size(BRAND / name) for name in ("icon.png", "icon@2x.png", "dark_icon.png", "dark_icon@2x.png")}
    assert sizes == {
        "icon.png": (256, 256),
        "icon@2x.png": (512, 512),
        "dark_icon.png": (256, 256),
        "dark_icon@2x.png": (512, 512),
    }
    # Home Assistant takes only these names from the folder (homeassistant/components/brands/const.py).
    assert {path.name for path in BRAND.iterdir()} <= {
        "icon.png", "icon@2x.png", "dark_icon.png", "dark_icon@2x.png",
        "logo.png", "logo@2x.png", "dark_logo.png", "dark_logo@2x.png",
    }  # fmt: skip


async def test_home_assistant_sees_the_pictogram(hass: HomeAssistant) -> None:
    integration = await loader.async_get_integration(hass, "philips_pureprotect")
    assert integration.has_branding
