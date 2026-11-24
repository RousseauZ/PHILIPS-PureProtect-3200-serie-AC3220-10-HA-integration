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
        standby_presume_after=0.5,
        socket_timeout=1.0,
        error_pause=0.05,
    )

    @pytest.fixture(autouse=True)
    def fast_session(monkeypatch: pytest.MonkeyPatch, socket_enabled: None, hass_storage: dict[str, Any]) -> None:
        """Run every session with test timings, allow its UDP socket to the loopback and keep storage in memory."""
        monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.SESSION_OPTIONS", FAST)
        monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.DEVICE_OFF_RETRY_DELAY", 0.05)
        monkeypatch.setattr("custom_components.philips_pureprotect.config_flow.IDENTIFY_OPTIONS", FAST)
        # No test reaches beyond the loopback: a search finds nothing unless a test points it at the simulator.
        monkeypatch.setattr("custom_components.philips_pureprotect.search.async_search_targets", _no_targets)
        monkeypatch.setattr("custom_components.philips_pureprotect.search.SEARCH_ROUNDS", 2)
        monkeypatch.setattr("custom_components.philips_pureprotect.search.SEARCH_WAIT", 0.1)
        # Nor does any test read the neighbour table of the machine it runs on. The coordinator holds its own reference.
        monkeypatch.setattr("custom_components.philips_pureprotect.search.read_mac", lambda host: None)
        monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.read_mac", lambda host: None)

    async def _no_targets(hass: Any) -> list[str]:
        return []

    @pytest.fixture
    def search_finds(monkeypatch: pytest.MonkeyPatch, fake: FakePurifier) -> FakePurifier:
        """Let a search reach the simulated purifier, as a broadcast would reach the real one."""

        async def loopback(hass: Any) -> list[str]:
            return ["127.0.0.1"]

        monkeypatch.setattr("custom_components.philips_pureprotect.search.async_search_targets", loopback)
        return fake

    @pytest.fixture
    def hass_config_dir(hass_tmp_config_dir: str) -> str:
        """Give every test a configuration directory of its own, so that none leaves files in the repository."""
        return hass_tmp_config_dir

    @pytest.fixture
    def slow_to_presume(monkeypatch: pytest.MonkeyPatch) -> None:
        """Show the first seconds after a start for as long as the test takes.

        A session takes a reachable purifier that sends no status to be in standby after a set time
        (10 s; 0.5 s in these tests). With this fixture that time does not come.
        """
        monkeypatch.setattr(
            "custom_components.philips_pureprotect.coordinator.SESSION_OPTIONS", options(standby_presume_after=60.0)
        )

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


def state(hass: Any, entity_id: str) -> str:
    """Return the state of an entity that has to exist."""
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} does not exist"
    return str(found.state)


def measured_delays(fake: Any) -> None:
    """Give the simulated purifier the measured delays, scaled like the test timings.

    The test timings are the real ones divided by about twelve. Measured (docs/metingen.md): a write is
    reported after 0.1 to 1.1 s, a new registration is answered after 0.2 to 1.9 s, and the running speed
    follows a change of mode 0.1 to 1 s later in a frame of its own.
    """
    fake.echo_delay = 0.05
    fake.registration_answer_delay = 0.1
    fake.speed_follows_after = 0.15


async def restart_while_the_purifier_went_to_standby(hass: Any, fake: Any, setup: Any) -> Any:
    """Stop the entry with the purifier on, switch the purifier off, and start the entry again.

    Measured (measurements 2 and 8): in standby the purifier answers the ping, the sync and the info
    request and sends no status at all, also not in answer to the registration of the new session. What
    was stored says "on".
    """
    entry = await setup()
    assert state(hass, "fan.woonkamer") == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    fake.power_off(notify=False)
    await setup(live=False)
    session = entry.runtime_data.session
    await until(hass, lambda: session.available, "the purifier in standby does not answer the probes")
    assert not session.status_is_live
    return entry
