"""Sensors and warnings computed from the status."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.philips_pureprotect.airlink import session as session_module

from .conftest import state, until

LAST_STATUS = "sensor.woonkamer_last_status_received"
TIMER_ENDS = "sensor.woonkamer_timer_ends"
PM25 = "sensor.woonkamer_pm2_5"
READINGS = (PM25, "sensor.woonkamer_allergen_index", "sensor.woonkamer_temperature", "sensor.woonkamer_humidity")


async def test_measurements(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D03224", 198)
    await until(hass, lambda: state(hass, "sensor.woonkamer_temperature") == "19.8")
    fake.change("D03125", 55)
    fake.change("D03120", 7)
    await until(hass, lambda: state(hass, "sensor.woonkamer_allergen_index") == "7")
    assert state(hass, "sensor.woonkamer_humidity") == "55"
    unit = hass.states.get("sensor.woonkamer_pm2_5").attributes["unit_of_measurement"]
    assert unit == "μg/m³"


async def test_filter_life_is_never_zero_while_hours_are_left(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D0540E", 4800)
    await until(hass, lambda: state(hass, "sensor.woonkamer_filter_life_remaining") == "50")
    fake.change("D0540E", 3)
    await until(hass, lambda: state(hass, "sensor.woonkamer_filter_life_remaining") == "1")
    assert state(hass, "binary_sensor.woonkamer_replace_filter") == "off"
    fake.change("D0540E", 0)
    await until(hass, lambda: state(hass, "binary_sensor.woonkamer_replace_filter") == "on")
    assert state(hass, "sensor.woonkamer_filter_life_remaining") == "0"


async def test_warnings(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    fake.change("D0520D", 0)
    await until(hass, lambda: state(hass, "binary_sensor.woonkamer_clean_filter") == "on")
    assert state(hass, "binary_sensor.woonkamer_fault") == "off"
    fake.change("D03240", 49408)
    await until(hass, lambda: state(hass, "binary_sensor.woonkamer_fault") == "on")


async def test_timer_end_is_a_moment_that_does_not_creep(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    assert state(hass, "sensor.woonkamer_timer_ends") == "unknown"
    fake.change("D03211", 120)
    await until(hass, lambda: state(hass, "sensor.woonkamer_timer_ends") != "unknown")
    first = state(hass, "sensor.woonkamer_timer_ends")
    ends = dt_util.parse_datetime(first)
    assert ends is not None and abs(ends - (dt_util.utcnow() + timedelta(minutes=120))) < timedelta(seconds=10)

    # Other news from the device does not move the moment by the seconds that passed.
    fake.change("D03221", 30)
    await until(hass, lambda: state(hass, "sensor.woonkamer_pm2_5") == "30")
    assert state(hass, "sensor.woonkamer_timer_ends") == first
    # A timer that is set again does.
    fake.change("D03211", 60)
    await until(hass, lambda: state(hass, "sensor.woonkamer_timer_ends") != first)
    fake.change("D03211", 0)
    await until(hass, lambda: state(hass, "sensor.woonkamer_timer_ends") == "unknown")


async def test_last_status_is_not_rewritten_with_every_frame(hass: HomeAssistant, fake, setup) -> None:
    await setup()
    first = state(hass, "sensor.woonkamer_last_status_received")
    assert first not in ("unknown", "unavailable")
    for value in (10, 11, 12):
        fake.change("D03221", value)
        await until(hass, lambda value=value: state(hass, "sensor.woonkamer_pm2_5") == str(value))
    assert state(hass, "sensor.woonkamer_last_status_received") == first


# -- readings while the purifier is off -----------------------------------------------------------------------------


async def test_readings_are_unknown_while_the_purifier_is_off_and_does_not_measure(
    hass: HomeAssistant, fake, setup
) -> None:
    """Off, with "Sensors in standby" off, the purifier measures nothing and reports nothing.

    Measured (docs/metingen.md, 2 and 5): no status frame at all in standby. Kept at their last value, the
    readings would draw a flat line that was never measured, and "PM2.5 high: switch the purifier on"
    could never fire.
    """
    await setup()
    assert fake.state["D03134"] == 0  # "Sensors in standby" is off, as on the measured device
    assert state(hass, PM25) == "3"

    fake.power_off()
    await until(hass, lambda: state(hass, "fan.woonkamer") == "off")
    fake.change("D03221", 80)  # hours later somebody fries fish; the device is not measuring and tells nobody
    assert {entity_id: state(hass, entity_id) for entity_id in READINGS} == dict.fromkeys(READINGS, STATE_UNKNOWN)
    # What is not a reading stays: it does not change while the purifier is off.
    assert state(hass, "sensor.woonkamer_filter_life_remaining") == "100"
    assert state(hass, "switch.woonkamer_child_lock") == "off"

    fake.power_on()  # back on: the readings are there again with the first frame
    await until(hass, lambda: state(hass, PM25) == "80")
    assert state(hass, "sensor.woonkamer_temperature") == "21.2"


async def test_readings_stay_while_the_sensors_run_in_standby(hass: HomeAssistant, fake, setup) -> None:
    fake.state["D03134"] = 1  # the switch "Sensors in standby" is on
    await setup()
    fake.power_off()
    await until(hass, lambda: state(hass, "fan.woonkamer") == "off")
    assert state(hass, "switch.woonkamer_sensors_in_standby") == "on"
    assert state(hass, PM25) == "3" and state(hass, "sensor.woonkamer_temperature") == "21.2"
    # How often the device reports in this state is not measured yet (measurement 12 could not tell).
    # Whatever it does report is shown.
    fake.state["D03221"] = 44
    fake.push()
    await until(hass, lambda: state(hass, PM25) == "44")
    assert state(hass, "fan.woonkamer") == "off"


# -- a timestamp sensor does not follow every frame ---------------------------------------------------------------
#
# Measured: a frame every 3.3 s for eight hours (docs/metingen.md, 12). The two tests above that are named
# for this rule send their frames within one second, which is the resolution of a timestamp state; the
# tests below move the clock.


class _Clock:
    """Stands in for ``time`` inside the session: ``ahead`` moves its wall clock, not its timers."""

    def __init__(self) -> None:
        self.ahead = 0.0

    def time(self) -> float:
        return time.time() + self.ahead

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """Let a test decide how much later the next status frame arrives."""
    stand_in = _Clock()
    monkeypatch.setattr(session_module, "time", stand_in)
    return stand_in


async def test_last_status_moves_by_the_minute_and_not_with_every_frame(
    hass: HomeAssistant, fake, setup, clock: _Clock
) -> None:
    await setup()
    first = state(hass, LAST_STATUS)
    assert first not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
    # Fifteen frames, 3.3 s apart: fifty seconds of an active purifier.
    for frame in range(1, 16):
        clock.ahead = frame * 3.3
        fake.change("D03221", 10 + frame)
        await until(hass, lambda frame=frame: state(hass, PM25) == str(10 + frame))
        assert state(hass, LAST_STATUS) == first, f"rewritten for a frame {clock.ahead:.0f} s later"
    # Two minutes later it has to move, or it would not show how old the values are.
    clock.ahead = 120.0
    fake.change("D03221", 5)
    await until(hass, lambda: state(hass, LAST_STATUS) != first, "the sensor never moved")
    before, after = dt_util.parse_datetime(first), dt_util.parse_datetime(state(hass, LAST_STATUS))
    assert before is not None and after is not None
    assert timedelta(seconds=110) < after - before < timedelta(seconds=130)


async def test_timer_end_stays_put_while_the_minutes_count_down(
    hass: HomeAssistant, fake, setup, clock: _Clock
) -> None:
    await setup()
    fake.change("D03211", 120)
    await until(hass, lambda: state(hass, TIMER_ENDS) != STATE_UNKNOWN)
    first = state(hass, TIMER_ENDS)
    # Half a minute later other news arrives; the device still says 120 minutes.
    clock.ahead = 30.0
    fake.change("D03221", 30)
    await until(hass, lambda: state(hass, PM25) == "30")
    assert state(hass, TIMER_ENDS) == first, "the end crept along with the frame"
    # The device counts a minute down (measured: once per minute): the end is the same moment.
    clock.ahead = 60.0
    fake.state["D03211"] = 119
    fake.change("D03221", 31)
    await until(hass, lambda: state(hass, PM25) == "31")
    assert state(hass, TIMER_ENDS) == first, "the end moved although the timer just counted down"
    # A timer that is set again does move it.
    fake.change("D03211", 60)
    await until(hass, lambda: state(hass, TIMER_ENDS) not in (first, STATE_UNKNOWN))
