"""Constants for the Philips PureProtect integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "philips_pureprotect"
LOGGER = logging.getLogger(__package__)

MANUFACTURER: Final = "Philips"
DEFAULT_PORT: Final = 5683
CONF_MODEL: Final = "model"

STORAGE_VERSION: Final = 1
# When the last status goes to disk (seconds). A running purifier reports
# every 3.3 s on average for hours (docs/metingen.md, measurement 12), so the
# file follows what a restart should bring back and not every frame: a change
# of power, mode, a setting, the keys or the firmware is written this soon...
SAVE_DELAY: Final = 10
# ...and anything else, such as the readings, at most this often.
SAVE_INTERVAL: Final = 15 * 60


class Key:
    """Keys of the status message, as measured on an AC3220/10 (docs/metingen.md)."""

    NAME = "D01S03"
    MODEL = "D01S05"
    FIRMWARE = "D01S12"
    WIFI_FIRMWARE = "WifiVersion"
    DEVICE_ID = "DeviceId"
    RSSI = "rssi"

    POWER = "D03102"
    CHILD_LOCK = "D03103"
    BRIGHTNESS = "D03105"  # 101 automatic, 123 bright, 115 low, 0 off
    MODE = "D0310C"  # 0 auto, 17 sleep, 19 medium, 18 turbo, 1-5 manual, -16 while off
    FAN_LEVEL = "D0310D"  # running speed: 1-4 and 18, 0 while off
    TIMER = "D03110"  # 0 off, 2-13 for 1-12 hours
    DISPLAY_OFF = "D03112"  # 0 display on, 1 display off
    ALLERGY_SLEEP = "D03115"
    ALLERGEN_INDEX = "D03120"
    HUMIDITY = "D03125"
    BEEP = "D03130"  # 100 on, 0 off
    STANDBY_SENSORS = "D03134"
    LIGHT_MODE = "D03135"  # 0 off, 1 air quality, 2 ambient light
    LIGHT_SCENE = "D03137"  # 1-4
    AUTO_PLUS = "D03180"
    TIMER_MINUTES_LEFT = "D03211"
    PM25 = "D03221"
    TEMPERATURE = "D03224"  # tenths of a degree Celsius
    ERROR_CODE = "D03240"

    FILTER_CLEAN_TOTAL = "D05207"
    FILTER_CLEAN_LEFT = "D0520D"  # hours
    FILTER_LIFE_TOTAL = "D05408"
    FILTER_LIFE_LEFT = "D0540E"  # hours


# What an AC3220/10 with firmware 0.2.3 reports. Used to create entities for a
# device that has not sent a status yet, which a purifier in standby never does
# by itself.
DEFAULT_KEYS: Final = frozenset(
    {
        Key.NAME, Key.MODEL, Key.FIRMWARE, Key.DEVICE_ID, Key.RSSI,
        Key.POWER, Key.CHILD_LOCK, Key.BRIGHTNESS, Key.MODE, Key.FAN_LEVEL, Key.TIMER, Key.DISPLAY_OFF,
        Key.ALLERGY_SLEEP, Key.ALLERGEN_INDEX, Key.HUMIDITY, Key.BEEP, Key.STANDBY_SENSORS, Key.LIGHT_MODE,
        Key.LIGHT_SCENE, Key.AUTO_PLUS, Key.TIMER_MINUTES_LEFT, Key.PM25, Key.TEMPERATURE, Key.ERROR_CODE,
        Key.FILTER_CLEAN_TOTAL, Key.FILTER_CLEAN_LEFT, Key.FILTER_LIFE_TOTAL, Key.FILTER_LIFE_LEFT,
    }
)  # fmt: skip

# A change of one of these is written to disk soon (SAVE_DELAY): the state
# and the settings an owner expects to find back after a restart. The
# readings, the running speed and the counters change by themselves all day
# and can wait (SAVE_INTERVAL).
SAVED_SOON: Final = (
    Key.NAME, Key.MODEL, Key.FIRMWARE, Key.WIFI_FIRMWARE,
    Key.POWER, Key.MODE, Key.CHILD_LOCK, Key.BRIGHTNESS, Key.TIMER, Key.DISPLAY_OFF, Key.ALLERGY_SLEEP,
    Key.BEEP, Key.STANDBY_SENSORS, Key.LIGHT_MODE, Key.LIGHT_SCENE, Key.AUTO_PLUS,
)  # fmt: skip

# Modes that are a choice of the device, not a fixed speed.
PRESET_MODES: Final = {"auto": 0, "sleep": 17}
# The five fixed speeds, written as a mode.
SPEEDS: Final = (1, 2, 3, 4, 5)
# Modes that stand for a fixed speed. Medium and turbo are buttons on the
# device; measured, they run at the speeds 3 and 5.
MODE_TO_SPEED: Final = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 19: 3, 18: 5}
# What the device reports as running speed (Key.FAN_LEVEL), as a step from 1
# to 5. Measured: speed 5 and turbo both report 18.
LEVEL_TO_SPEED: Final = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 18: 5}
