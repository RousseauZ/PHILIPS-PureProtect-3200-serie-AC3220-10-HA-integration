"""Review, lens "lifecycle": setup, teardown, concurrency and failure paths of the Home Assistant layer.

Every test here fails on the code as reviewed and names the defect it proves.
"""

from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.philips_pureprotect.const import CONF_MODEL, DOMAIN

from ..conftest import FAST, until

BEDROOM_DEVICE = "99999999888811ef93334444555566bb"


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} does not exist"
    return found.state


def stored(entry: MockConfigEntry, data: Any, *, version: int = 1) -> dict[str, Any]:
    """Return the file Home Assistant keeps for an entry, with the given content."""
    return {"version": version, "minor_version": 1, "key": f"{DOMAIN}.{entry.entry_id}", "data": data}


# -- 1. an entry that knows it talks to the wrong purifier keeps taking that purifier's status stream ----------


async def test_an_entry_at_the_wrong_address_leaves_the_stream_to_the_purifier_that_lives_there(
    hass: HomeAssistant, fake, setup
) -> None:
    """Two purifiers; the address stored for the bedroom one now belongs to the living room one.

    The bedroom entry notices: repair issue, entities unavailable, commands blocked. Its session
    keeps running all the same and registers for status at that address every refresh interval
    (70 s in production). The purifier serves one observer per source address and the newest
    registration wins (docs/metingen.md, measurement 9), so the living room entry loses its stream
    to an entry that throws every frame away, until its own next refresh takes it back.
    docs/onderzoek.md 6.5: never open a second session to a purifier that is already set up.
    """
    await setup()  # the living room purifier, at its own address
    # Start the bedroom entry right behind a periodic registration of the living room session.
    registrations = len(fake.registrations)
    await until(hass, lambda: len(fake.registrations) > registrations, "no periodic registration")
    bedroom = MockConfigEntry(
        domain=DOMAIN,
        title="Slaapkamer",
        unique_id=BEDROOM_DEVICE,
        data={CONF_HOST: "127.0.0.1", CONF_PORT: fake.port, CONF_MODEL: "AC3220/10"},
    )
    bedroom.add_to_hass(hass)
    assert await hass.config_entries.async_setup(bedroom.entry_id)
    issues = ir.async_get(hass)
    await until(
        hass,
        lambda: issues.async_get_issue(DOMAIN, f"wrong_device_{bedroom.entry_id}") is not None,
        "the bedroom entry never noticed that another purifier answers",
    )
    # The first registration of the bedroom entry cannot be helped: it did not know yet. Give the
    # living room session two refresh intervals to take its stream back.
    await asyncio.sleep(2 * FAST.refresh_interval)

    # From here on, for three more refresh intervals, every change must reach the living room entry at once.
    for value in range(40, 52):
        fake.change("D03221", value)
        await until(
            hass,
            lambda value=value: state(hass, "sensor.woonkamer_pm2_5") == str(value),
            f"PM2.5 {value} did not reach the living room entry: the bedroom entry holds the status stream",
            timeout=FAST.refresh_interval / 3,
        )
        await asyncio.sleep(FAST.refresh_interval / 4)


# -- 2. the stored status is a cache, but a file the integration cannot read stops the whole integration ------


async def test_a_stored_status_of_a_newer_version_does_not_stop_the_setup(
    hass: HomeAssistant, fake, entry, hass_storage: dict[str, Any]
) -> None:
    """After going back to an older version of the integration the file has a newer storage version.

    Home Assistant's Store refuses such a file with an exception. Nothing catches it, so the entry ends
    in "setup failed" for good: the owner has to find and delete a file in .storage by hand. The file
    only holds the last status, which the purifier sends again.
    """
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored(
        entry, {"status": {"D03102": 1}, "received_at": 1795000000.0, "keys": ["D03102"]}, version=2
    )
    assert await hass.config_entries.async_setup(entry.entry_id), "a stored status it cannot read stopped the setup"
    assert entry.state is ConfigEntryState.LOADED
    await until(hass, lambda: entry.runtime_data.session.status_is_live, "no status arrived")
    assert state(hass, "fan.woonkamer") == "on"


async def test_an_impossible_time_in_the_stored_status_does_not_cost_entities(
    hass: HomeAssistant, fake, entry, setup, hass_storage: dict[str, Any]
) -> None:
    """A time of receipt that is no valid moment (here: milliseconds instead of seconds).

    The two timestamp sensors compute their first value while they are added. The conversion raises,
    Home Assistant gives up on the entity, and "Last status received" and "Timer ends" do not exist
    until the next restart, also long after the purifier has sent a fresh status.
    """
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored(
        entry,
        {"status": {**fake.state, "D03211": 30}, "received_at": 1795000000000.0, "keys": sorted(fake.state)},
    )
    await setup()
    assert entry.state is ConfigEntryState.LOADED
    assert state(hass, "sensor.woonkamer_pm2_5") == "3"
    assert hass.states.get("sensor.woonkamer_last_status_received") is not None, "the sensor was never added"
    assert hass.states.get("sensor.woonkamer_timer_ends") is not None, "the sensor was never added"


# -- 3. the diagnostics download only works while the entry is loaded -----------------------------------------


async def test_diagnostics_can_be_downloaded_for_an_entry_whose_setup_failed(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, fake, entry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The download is there to find out why a purifier misbehaves, and is offered for every entry.

    It reads entry.runtime_data, which only exists while the entry is loaded. For an entry whose
    setup failed, which is when a report is needed most, the owner gets "500 Internal Server Error"
    instead of a file.
    """

    async def fail(self: Any) -> None:
        raise RuntimeError("the setup fails, whatever the reason")

    monkeypatch.setattr("custom_components.philips_pureprotect.coordinator.PureProtectCoordinator.async_start", fail)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert await async_setup_component(hass, "diagnostics", {})
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(f"/api/diagnostics/config_entry/{entry.entry_id}")
    assert response.status == HTTPStatus.OK, "no diagnostics for an entry that is not loaded"


# -- 4. unloading after Home Assistant began to stop logs an error with a traceback ---------------------------


async def test_unload_after_home_assistant_stopped_logs_no_error(
    hass: HomeAssistant, fake, setup, caplog: pytest.LogCaptureFixture
) -> None:
    """The stop listener is a one-time listener and its remover is handed to the entry for unload.

    Once the stop event has fired the listener is gone, and the remover that the unload still calls
    makes Home Assistant log "Unable to remove unknown job listener" with a traceback.
    """
    entry = await setup()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert not entry.runtime_data.session.available  # the stop handler stopped the session

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert not errors, errors
