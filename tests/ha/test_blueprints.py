"""The blueprints that stand in for the cloud functions of the Air+ app: a schedule and notifications."""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import async_fire_time_changed, async_mock_service

SOURCE = Path(__file__).resolve().parents[2] / "blueprints" / "automation" / "philips_pureprotect"
MODE = "select.woonkamer_stand"


async def automation(hass: HomeAssistant, blueprint: str, inputs: dict[str, Any]) -> None:
    """Install the blueprint as Home Assistant does on import, and make one automation from it."""
    target = Path(hass.config.path("blueprints", "automation", "philips_pureprotect"))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(SOURCE / blueprint, target / blueprint)
    config = {"automation": [{"use_blueprint": {"path": f"philips_pureprotect/{blueprint}", "input": inputs}}]}
    assert await async_setup_component(hass, "automation", config)
    await hass.async_block_till_done()
    assert hass.states.async_entity_ids("automation"), "the blueprint did not make an automation"


def test_every_blueprint_is_tested() -> None:
    assert sorted(path.name for path in SOURCE.glob("*.yaml")) == [
        "air_quality_alert.yaml",
        "filter_reminder.yaml",
        "schedule.yaml",
    ]


async def stop(hass: HomeAssistant) -> None:
    """Turn the automations off, which cancels the timers of their time triggers."""
    await hass.services.async_call("automation", "turn_off", {"entity_id": "all"}, blocking=True)
    await hass.async_block_till_done()


async def at(hass: HomeAssistant, freezer: FrozenDateTimeFactory, moment: Any) -> None:
    freezer.move_to(moment)
    async_fire_time_changed(hass, moment)
    await hass.async_block_till_done()


async def test_schedule_sets_the_mode_and_ends_it(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls: list[ServiceCall] = async_mock_service(hass, "select", "select_option")
    start = (dt_util.now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=2)
    weekday = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[start.weekday()]
    await automation(
        hass,
        "schedule.yaml",
        {
            "mode_entity": MODE,
            "days": [weekday],
            "start_time": f"{start:%H:%M:%S}",
            "start_mode": "sleep",
            "end_time": f"{end:%H:%M:%S}",
        },
    )
    await at(hass, freezer, start)
    assert [(call.data["entity_id"], call.data["option"]) for call in calls] == [([MODE], "sleep")]
    await at(hass, freezer, end)
    # The default at the end is off, which the select "Stand" has as an option.
    assert [call.data["option"] for call in calls] == ["sleep", "off"]
    await stop(hass)


async def test_schedule_keeps_to_its_days(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls: list[ServiceCall] = async_mock_service(hass, "select", "select_option")
    start = (dt_util.now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    other_day = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[(start.weekday() + 1) % 7]
    await automation(
        hass,
        "schedule.yaml",
        {"mode_entity": MODE, "days": [other_day], "start_time": f"{start:%H:%M:%S}", "end_time": "23:59:00"},
    )
    await at(hass, freezer, start)
    assert not calls
    await stop(hass)


@pytest.mark.parametrize(
    ("level", "steps", "fired"),
    [
        ("poor", ["good", "fair", "poor"], 1),
        ("poor", ["good", "fair", "fair"], 0),
        ("poor", ["good", "poor", "very_poor"], 1),  # worse still: not a second time
        ("fair", ["good", "fair"], 1),
        ("very_poor", ["good", "poor"], 0),
    ],
)
async def test_air_quality_alert_fires_on_the_way_into_the_level(
    hass: HomeAssistant, level: str, steps: list[str], fired: int
) -> None:
    calls: list[ServiceCall] = async_mock_service(hass, "test", "notify")
    entity = "sensor.woonkamer_luchtkwaliteit"
    hass.states.async_set(entity, steps[0])
    await automation(
        hass,
        "air_quality_alert.yaml",
        {
            "air_quality": entity,
            "level": level,
            "minutes": 0,
            "actions": [{"action": "test.notify", "data": {"message": "{{ trigger.to_state.state }}"}}],
        },
    )
    for step in steps[1:]:
        hass.states.async_set(entity, step)
        await hass.async_block_till_done()
    assert len(calls) == fired


async def test_air_quality_alert_waits_the_chosen_time(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls: list[ServiceCall] = async_mock_service(hass, "test", "notify")
    entity = "sensor.woonkamer_luchtkwaliteit"
    hass.states.async_set(entity, "good")
    await automation(
        hass,
        "air_quality_alert.yaml",
        {"air_quality": entity, "minutes": 10, "actions": [{"action": "test.notify"}]},
    )
    hass.states.async_set(entity, "poor")
    await hass.async_block_till_done()
    await at(hass, freezer, dt_util.utcnow() + timedelta(minutes=5))
    assert not calls
    await at(hass, freezer, dt_util.utcnow() + timedelta(minutes=6))
    assert len(calls) == 1


async def test_air_quality_alert_default_text(hass: HomeAssistant) -> None:
    calls: list[ServiceCall] = async_mock_service(hass, "persistent_notification", "create")
    entity = "sensor.woonkamer_luchtkwaliteit"
    hass.states.async_set(entity, "good")
    await automation(hass, "air_quality_alert.yaml", {"air_quality": entity, "minutes": 0})
    hass.states.async_set(entity, "very_poor")
    await hass.async_block_till_done()
    assert [call.data["message"] for call in calls] == ["De luchtkwaliteit is al 0 minuten zeer slecht."]


async def test_filter_reminder(hass: HomeAssistant) -> None:
    calls: list[ServiceCall] = async_mock_service(hass, "persistent_notification", "create")
    clean, replace = "binary_sensor.woonkamer_filter_reinigen", "binary_sensor.woonkamer_filter_vervangen"
    hass.states.async_set(clean, "off", {"friendly_name": "Woonkamer Filter reinigen"})
    hass.states.async_set(replace, "off", {"friendly_name": "Woonkamer Filter vervangen"})
    await automation(hass, "filter_reminder.yaml", {"warnings": [clean, replace]})
    hass.states.async_set(clean, "on", {"friendly_name": "Woonkamer Filter reinigen"})
    await hass.async_block_till_done()
    hass.states.async_set(clean, "unavailable")  # the purifier away for a while
    hass.states.async_set(clean, "on", {"friendly_name": "Woonkamer Filter reinigen"})
    await hass.async_block_till_done()
    assert [call.data["message"] for call in calls] == ["Woonkamer Filter reinigen: het filter heeft onderhoud nodig."]
