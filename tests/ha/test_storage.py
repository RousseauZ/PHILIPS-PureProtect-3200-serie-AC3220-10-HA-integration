"""The last status on disk: when it is written, what a damaged file costs, and where it goes on removal.

Measured: a running purifier sends a status frame every 3.3 s on average, for hours (docs/metingen.md,
measurement 12: 8859 frames in eight hours). The file follows what an owner wants back after a restart, not
every frame.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from custom_components.philips_pureprotect import const
from custom_components.philips_pureprotect.const import DOMAIN

from .conftest import state, until

COORDINATOR = "custom_components.philips_pureprotect.coordinator"
PM25 = "sensor.woonkamer_pm2_5"


def stored(entry: MockConfigEntry, data: Any, *, version: int = 1) -> dict[str, Any]:
    """Return the file Home Assistant keeps for an entry, with the given content."""
    return {"version": version, "minor_version": 1, "key": f"{DOMAIN}.{entry.entry_id}", "data": data}


class Writes:
    """Counts how often the file of an entry is written; every write puts a new object in the storage."""

    def __init__(self, storage: dict[str, Any], key: str) -> None:
        self._storage, self._key = storage, key
        self._seen: Any = storage.get(key)
        self.count = 0

    def look(self) -> int:
        current = self._storage.get(self._key)
        if current is not self._seen:
            self._seen = current
            self.count += 1
        return self.count

    def status(self) -> dict[str, Any]:
        return self._storage[self._key]["data"]["status"]


def test_the_file_is_not_written_every_minute() -> None:
    # What runs outside the tests: soon after a change that matters, otherwise four times an hour at most.
    assert 0 < const.SAVE_DELAY <= 30 and const.SAVE_INTERVAL >= 10 * 60
    # Power, mode and the settings are among what is written soon; the readings are not.
    assert {"D03102", "D0310C", "D03103", "D03110", "D03135", "D01S12"} <= set(const.SAVED_SOON)
    assert not {"D03221", "D03224", "D03125", "D03120", "D0310D", "D03211", "Runtime", "rssi"} & set(const.SAVED_SOON)


async def test_readings_alone_are_saved_once_in_a_long_while(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(f"{COORDINATOR}.SAVE_DELAY", 0.05)
    monkeypatch.setattr(f"{COORDINATOR}.SAVE_INTERVAL", 0.5)
    entry = await setup()
    key = f"{DOMAIN}.{entry.entry_id}"
    # The first status of a purifier is new in every respect: it is written soon.
    await until(hass, lambda: key in hass_storage, "the first status was not saved")
    writes = Writes(hass_storage, key)

    # A frame every 0.05 s for four intervals: an active purifier, scaled.
    loop = asyncio.get_running_loop()
    started = loop.time()
    value = 10
    while loop.time() - started < 2.0:
        value += 1
        fake.change("D03221", value)
        await asyncio.sleep(0.05)
        writes.look()
    frames = value - 10
    # Written while the frames keep coming: a later frame does not postpone the write...
    assert writes.count >= 2, f"{writes.count} writes for {frames} frames in four intervals"
    # ...and not for every frame, or every few: once per interval.
    assert writes.count <= 5, f"{writes.count} writes for {frames} frames in four intervals"

    # After the last frame one more write brings the file up to date, and then it is quiet.
    await until(hass, lambda: writes.status()["D03221"] == value, "the last status never reached the file")
    await hass.async_block_till_done()
    writes.look()
    settled = writes.count
    await asyncio.sleep(1.2)
    assert writes.look() == settled, "written again although nothing new arrived"


async def test_a_change_that_matters_is_saved_soon(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(f"{COORDINATOR}.SAVE_DELAY", 0.05)
    monkeypatch.setattr(f"{COORDINATOR}.SAVE_INTERVAL", 60.0)
    entry = await setup()
    key = f"{DOMAIN}.{entry.entry_id}"
    await until(hass, lambda: key in hass_storage, "the first status was not saved")
    writes = Writes(hass_storage, key)

    fake.change("D03221", 55)
    await until(hass, lambda: state(hass, PM25) == "55")
    await asyncio.sleep(0.3)
    assert writes.look() == 0 and writes.status()["D03221"] == 3, "a reading was written at once"

    # A setting changed on the purifier, the mode, switching off: each is in the file within the short delay.
    for change, shown in (
        (lambda: fake.change("D03103", 1), ("D03103", 1)),
        (lambda: fake.change("D0310C", 17), ("D0310C", 17)),
        (lambda: fake.change("D01S12", "0.2.4"), ("D01S12", "0.2.4")),
        (fake.power_off, ("D03102", 0)),
    ):
        change()
        await until(hass, lambda shown=shown: writes.status()[shown[0]] == shown[1], f"{shown} was not saved soon")
    assert writes.status()["D03221"] == 55  # and what waited went along


async def test_new_keys_are_saved_soon(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(f"{COORDINATOR}.SAVE_DELAY", 0.05)
    monkeypatch.setattr(f"{COORDINATOR}.SAVE_INTERVAL", 60.0)
    del fake.state["D03112"]
    entry = await setup()
    key = f"{DOMAIN}.{entry.entry_id}"
    await until(hass, lambda: key in hass_storage)
    assert "D03112" not in hass_storage[key]["data"]["keys"]
    fake.change("D03112", 1)  # the firmware was updated and reports a key it did not have
    await until(hass, lambda: "D03112" in hass_storage[key]["data"]["keys"], "the new key was not saved soon")


async def test_the_status_is_saved_and_the_session_closed_when_home_assistant_stops(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any]
) -> None:
    entry = await setup()
    session = entry.runtime_data.session
    fake.change("D03221", 17)
    await until(hass, lambda: state(hass, PM25) == "17")
    # Home Assistant does not unload entries when it stops.
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["status"]["D03221"] == 17
    assert not session.available  # stopped: its socket is closed and nothing is sent any more


async def test_removing_the_purifier_removes_its_stored_status(
    hass: HomeAssistant, fake, setup, hass_storage: dict[str, Any]
) -> None:
    entry = await setup()
    key = f"{DOMAIN}.{entry.entry_id}"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert key in hass_storage  # written when the entry was unloaded, with the name and the device id in it

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage, f"the file .storage/{key} is left behind for good"
    # And nothing writes it back afterwards.
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_removing_a_purifier_that_never_loaded_removes_its_stored_status(
    hass: HomeAssistant, fake, entry, hass_storage: dict[str, Any]
) -> None:
    key = f"{DOMAIN}.{entry.entry_id}"
    hass_storage[key] = stored(entry, {"status": {"D03102": 1}, "received_at": 1795000000.0, "keys": ["D03102"]})
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


# -- the file is a cache: the purifier sends its status again ------------------------------------------------------


async def test_a_stored_status_of_a_newer_version_does_not_stop_the_setup(
    hass: HomeAssistant, fake, entry, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """After going back to an older version of the integration the file has a newer storage version.

    Home Assistant's Store refuses such a file with an exception. The file only holds the last status; an
    entry that fails to set up over it would stay that way until the owner deletes a file by hand.
    """
    key = f"{DOMAIN}.{entry.entry_id}"
    hass_storage[key] = stored(
        entry, {"status": {"D03102": 1}, "received_at": 1795000000.0, "keys": ["D03102"]}, version=2
    )
    assert await hass.config_entries.async_setup(entry.entry_id), "a stored status it cannot read stopped the setup"
    assert entry.state is ConfigEntryState.LOADED
    await until(hass, lambda: entry.runtime_data.session.status_is_live, "no status arrived")
    assert state(hass, "fan.woonkamer") == "on"
    # Said once, in words, without a traceback.
    warnings = [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and record.name != "homeassistant.loader"
    ]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING and warnings[0].exc_info is None
    assert "stored status of Woonkamer" in warnings[0].getMessage()
    # The next write replaces the file with one this version reads.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass_storage[key]["version"] == 1 and hass_storage[key]["data"]["status"]["D03221"] == 3


@pytest.mark.parametrize("content", [[1, 2, 3], "text", {"status": "on", "keys": 7, "received_at": "then"}, {}])
async def test_a_stored_status_of_the_wrong_shape_is_left_out(
    hass: HomeAssistant, fake, entry, setup, hass_storage: dict[str, Any], content: Any
) -> None:
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored(entry, content)
    await setup()
    assert state(hass, "fan.woonkamer") == "on" and state(hass, PM25) == "3"


@pytest.mark.parametrize("received_at", [1795000000000.0, 1e18, -1e18])
async def test_an_impossible_time_in_the_stored_status_does_not_cost_entities(
    hass: HomeAssistant, fake, entry, setup, hass_storage: dict[str, Any], slow_to_presume: None, received_at: float
) -> None:
    """A time of receipt that is no valid moment, such as milliseconds instead of seconds.

    The two timestamp sensors compute their first value while they are added. A conversion that raises
    there costs the entity until the next restart.
    """
    fake.power_off(notify=False)  # so that the stored status is what the sensors start with, and stay with
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored(
        entry,
        {"status": {**fake.state, "D03102": 1, "D03211": 30}, "received_at": received_at, "keys": sorted(fake.state)},
    )
    await setup(live=False)
    assert entry.state is ConfigEntryState.LOADED
    await until(hass, lambda: entry.runtime_data.session.available)
    assert state(hass, PM25) == "3"
    # Both exist; the time that cannot be is left out.
    assert state(hass, "sensor.woonkamer_last_status_received") == STATE_UNKNOWN
    assert state(hass, "sensor.woonkamer_timer_ends") == STATE_UNKNOWN

    fake.state["D03211"] = 30
    fake.power_on()
    await until(hass, lambda: state(hass, "sensor.woonkamer_last_status_received") != STATE_UNKNOWN)
    assert state(hass, "sensor.woonkamer_last_status_received") != STATE_UNAVAILABLE
