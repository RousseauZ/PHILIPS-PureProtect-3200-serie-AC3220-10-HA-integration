"""Fixtures for the Home Assistant layer: a simulated purifier and a fast session.

These tests need Home Assistant 2026.11 or newer and ``pytest-homeassistant``.
Without them the directory is skipped, so that the protocol tests still run
on a plain Python.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import sys
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

import pytest

collect_ignore_glob: list[str] = []
try:
    import pytest_homeassistant  # noqa: F401
except ImportError:
    collect_ignore_glob = ["test_*.py"]

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "custom_components" / "philips_pureprotect" / "airlink"
if "airlink" not in sys.modules:
    # The simulated purifier speaks the protocol with the package as top-level ``airlink``.
    _spec = importlib.util.spec_from_file_location(
        "airlink", _PACKAGE / "__init__.py", submodule_search_locations=[str(_PACKAGE)]
    )
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["airlink"] = _module
    _spec.loader.exec_module(_module)
if str(_ROOT / "tests" / "airlink") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests" / "airlink"))

if not collect_ignore_glob:
    from fake_purifier import FakePurifier
    from homeassistant.const import CONF_HOST, CONF_PORT
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant.common import MockConfigEntry

    from custom_components.philips_pureprotect.airlink import SessionOptions
    from custom_components.philips_pureprotect.const import CONF_MODEL, DOMAIN

    # The production timings divided by a few hundred; the loopback answers within a millisecond.
    FAST = SessionOptions(
        probe_idle=0.2,
        probe_timeout=0.1,
        probe_retry=0.1,
        offline_min_misses=3,
        offline_min_silence=0.6,
        offline_backoff=(0.1, 0.1, 0.2),
        refresh_interval=0.3,
        refresh_min_gap=0.05,
        sync_timeout=0.25,
        control_timeout=0.25,
        write_attempts=3,
        write_budget=2.0,
        confirm_settle=0.1,
        confirm_timeout=0.4,
        confirm_retry_wait=0.3,
        info_timeout=0.25,
        info_attempts=2,
        request_status_timeout=0.3,
        socket_timeout=1.0,
        error_pause=0.05,
    )

    @pytest.fixture(autouse=True)
    def fast_session(monkeypatch: pytest.MonkeyPatch, socket_enabled: None, hass_storage: dict[str, Any]) -> None:
        """Run every session with test timings, allow its UDP socket to the loopback and keep storage in memory."""
        monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.SESSION_OPTIONS", FAST)
        monkeypatch.setattr("custom_components.philips_pureprotect.config_flow.IDENTIFY_OPTIONS", FAST)

    @pytest.fixture
    def default_port(monkeypatch: pytest.MonkeyPatch, fake: FakePurifier) -> int:
        """Make the simulated purifier's port the default one, as for a device added through the form."""
        monkeypatch.setattr("custom_components.philips_pureprotect.config_flow.DEFAULT_PORT", fake.port)
        monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.DEFAULT_PORT", fake.port)
        return fake.port

    @pytest.fixture
    async def fake(socket_enabled: None) -> AsyncGenerator[FakePurifier]:
        """Return a running simulated AC3220/10 on the loopback."""
        device = await FakePurifier.start()
        device.state["D03112"] = 0  # the display switch of newer firmware
        yield device
        device.close()

    @pytest.fixture
    def entry(hass: HomeAssistant, fake: FakePurifier) -> MockConfigEntry:
        """Return a config entry for the simulated purifier, added to Home Assistant."""
        config_entry = MockConfigEntry(
            domain=DOMAIN,
            title="Woonkamer",
            unique_id=fake.state["DeviceId"],
            data={CONF_HOST: "127.0.0.1", CONF_PORT: fake.port, CONF_MODEL: "AC3220/10"},
        )
        config_entry.add_to_hass(hass)
        return config_entry

    @pytest.fixture
    def setup(hass: HomeAssistant, entry: MockConfigEntry) -> Callable[[], Any]:
        """Return a coroutine function that sets the entry up and waits for the first status."""

        async def run(*, live: bool = True) -> MockConfigEntry:
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            if live:
                await until(hass, lambda: entry.runtime_data.session.status_is_live, "no status arrived")
            return entry

        return run


async def until(
    hass: Any, condition: Callable[[], Any], message: str = "condition not met", timeout: float = 5.0
) -> None:
    """Wait until a condition holds; the session runs outside Home Assistant's task tracking."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, message
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()


def options(**changes: Any) -> Any:
    """Return the fast options with some values replaced."""
    return dataclasses.replace(FAST, **changes)
