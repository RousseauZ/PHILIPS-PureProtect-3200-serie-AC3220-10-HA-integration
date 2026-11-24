"""Connects one airlink session to Home Assistant."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .airlink import (
    AirlinkError,
    DeviceOffError,
    NotConfirmedError,
    RefusedError,
    RestoredState,
    Session,
    SessionOptions,
    SessionState,
    UnreachableError,
)
from .const import (
    CONF_MODEL,
    DEFAULT_KEYS,
    DEFAULT_PORT,
    DOMAIN,
    LOGGER,
    MANUFACTURER,
    SAVE_DELAY,
    SAVE_INTERVAL,
    SAVED_SOON,
    STORAGE_VERSION,
    Key,
)
from .search import async_addresses, async_search, is_address, read_mac

type PureProtectConfigEntry = ConfigEntry[PureProtectCoordinator]

# The timings of the session; the tests replace them with fast ones.
SESSION_OPTIONS = SessionOptions()
# A setting that is refused because the purifier is off is tried once more
# after this many seconds; see PureProtectCoordinator.async_write.
DEVICE_OFF_RETRY_DELAY = 0.5
# A purifier that is lost at its address (OFFLINE, or another device answers
# there) for this many seconds is looked for on the network, in case it got
# another address. OFFLINE itself takes three minutes of silence, so this is
# about five minutes after its last answer. Every search that does not find
# it doubles the wait, up to REDISCOVER_MAX. Checked every REDISCOVER_CHECK.
REDISCOVER_AFTER = 120.0
REDISCOVER_MAX = 3600.0
REDISCOVER_CHECK = 60.0
# A MAC address that was not in the neighbour table is looked up again after
# this many seconds, twice as long after every further miss, up to MAC_RETRY_MAX.
MAC_RETRY = 60.0
MAC_RETRY_MAX = 3600.0


def status_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Return the file that keeps the last status of one purifier."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}", atomic_writes=True)


def moment(timestamp: float | None) -> datetime | None:
    """Return a time of receipt as a moment; None when it is none."""
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, UTC)
    except (OverflowError, OSError, ValueError):
        return None  # a number from a damaged file


class PureProtectCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Passes the status of a purifier on to its entities and sends their commands.

    There is no polling interval: the session pushes every status frame and
    is the only judge of reachability (docs/onderzoek.md, 6.2).
    """

    config_entry: PureProtectConfigEntry

    def __init__(self, hass: HomeAssistant, entry: PureProtectConfigEntry) -> None:
        """Prepare the coordinator; nothing is sent before ``async_start``."""
        super().__init__(hass, LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}", update_interval=None)
        assert entry.unique_id is not None
        self.device_id: str = entry.unique_id
        self.host: str = entry.data[CONF_HOST]
        self.session: Session
        self.keys: frozenset[str] = frozenset()
        # True while the keys are the ones of the model, not ones the device reported.
        self.keys_assumed = False
        self._store = status_store(hass, entry.entry_id)
        # When the pending write of the status is due (loop time); None without one.
        self._save_due: float | None = None
        # What the file holds: the values of _kept() and the time of its status.
        self._saved_kept: tuple[Any, ...] | None = None
        self._saved_frame_at: float | None = None
        self._issue_shown = False
        self._registered_versions: tuple[Any, Any] = (None, None)
        # Since when the purifier is lost at its address (monotonic); None while it is not.
        self._lost_since: float | None = None
        self._search_wait = REDISCOVER_AFTER
        self._searching = False
        self._mac_known = False
        self._mac_tried: float | None = None
        self._mac_wait = MAC_RETRY
        self._mac_reading = False
        self.data = {}

    async def async_start(self) -> None:
        """Load the saved status and start the session; never waits for the device."""
        entry = self.config_entry
        stored: Any = None
        try:
            stored = await self._store.async_load()
        except Exception as err:  # noqa: BLE001 - the file is a cache: the purifier sends its status again
            LOGGER.warning("The stored status of %s cannot be read and is left out: %s", entry.title, err)
        restored = RestoredState.from_dict(stored) if isinstance(stored, Mapping) else None
        if restored is not None and moment(restored.received_at) is None:
            restored = dataclasses.replace(restored, received_at=None)
        self.session = Session(
            self.host,
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
            options=SESSION_OPTIONS,
            expected_device_id=self.device_id,
            restored=restored,
        )
        self.data = self._shown_status()
        self.keys = self.session.snapshot().keys
        if not self.keys:
            self.keys, self.keys_assumed = DEFAULT_KEYS, True
        if self.session.status is not None:
            self._saved_kept, self._saved_frame_at = self._kept(), self.session.last_frame_at
        entry.async_on_unload(self.session.add_listener(self._handle_session_update))
        entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._async_tick, timedelta(seconds=REDISCOVER_CHECK), cancel_on_shutdown=True
            )
        )
        await self.session.start()

    async def async_stop(self) -> None:
        """Stop the session and save what it knows."""
        await self.session.stop()
        if self.session.status is not None:
            await self._store.async_save(self._data_to_save())

    async def _async_update_data(self) -> dict[str, Any]:
        """Answer a request to refresh, such as homeassistant.update_entity, with what is known.

        Nothing is asked of the purifier: it reports every change by itself,
        and in standby it would not answer.
        """
        return self._shown_status()

    @property
    def available(self) -> bool:
        """Return True while the configured purifier answers."""
        return self.session.available and not self.session.identity_mismatch

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device registry entry of the purifier."""
        status = self.data
        entry = self.config_entry
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            manufacturer=MANUFACTURER,
            model=status.get(Key.MODEL) or entry.data.get(CONF_MODEL),
            name=entry.title,
            sw_version=status.get(Key.FIRMWARE),
        )

    def value(self, key: str) -> int | None:
        """Return the integer the device reports for a key, if it does."""
        value = self.data.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _shown_status(self) -> dict[str, Any]:
        """Return the status for the entities.

        A purifier that never sent a status and is presumed to be in standby
        is shown as off, with everything else unknown.
        """
        status = self.session.status
        if status is not None:
            return status
        return {Key.POWER: 0} if self.session.presumed_standby else {}

    @callback
    def _handle_session_update(self) -> None:
        """Take over a new status or a new session state."""
        status = self.session.status or {}
        if not self.keys.issuperset(status):
            self.keys = frozenset(status) if self.keys_assumed else self.keys | frozenset(status)
            self.keys_assumed = False
        self._update_issue()
        self.async_set_updated_data(self._shown_status())
        self._update_device()
        self._schedule_save()
        self._note_lost()
        self.async_learn_mac()

    # -- finding the purifier again ------------------------------------------

    def _is_ours(self, device_id: str) -> bool:
        return device_id.casefold() == self.device_id.casefold()

    @property
    def _lost(self) -> bool:
        """Return True while the purifier is not where the entry says: nothing answers, or another device does."""
        return self.session.state is SessionState.OFFLINE or self.session.identity_mismatch

    @callback
    def _note_lost(self) -> None:
        if not self._lost:
            self._lost_since = None
            self._search_wait = REDISCOVER_AFTER
        elif self._lost_since is None:
            self._lost_since = time.monotonic()

    @property
    def _identity_confirmed(self) -> bool:
        """Return True while the purifier at the address is known to be this one.

        By a status frame (the session drops frames of another device) or by
        the info resource. The first ping answer comes before either.
        """
        session = self.session
        if session.identity_mismatch or session.state not in (SessionState.LIVE, SessionState.REACHABLE):
            return False
        identity = session.identity
        return session.status_is_live or (identity is not None and self._is_ours(identity.device_id))

    @callback
    def async_learn_mac(self) -> None:
        """Note the purifier's MAC address in the device registry, once.

        With it Home Assistant's DHCP watcher recognises the purifier when it
        gets another address, also when it was added by hand (manifest:
        ``registered_devices``). The operating system learned the MAC from
        the exchanges with the device. Tried again after every session
        update and every REDISCOVER_CHECK, at most once per MAC_RETRY (more
        seldom after misses); the setup calls it once the entities, and with
        them the device, exist.
        """
        if self._mac_known or self._mac_reading or not self._identity_confirmed:
            return
        now = time.monotonic()
        if self._mac_tried is not None and now - self._mac_tried < self._mac_wait:
            return
        if self._device() is None:
            return  # no entity was added yet; the setup asks again once they are
        self._mac_tried = now
        self._mac_reading = True
        self.config_entry.async_create_background_task(self.hass, self._async_learn_mac(), f"{DOMAIN} MAC {self.host}")

    def _device(self) -> dr.DeviceEntry | None:
        registry = dr.async_get(self.hass)
        return registry.async_get_device_by_identifier((DOMAIN, self.device_id), self.config_entry.entry_id)

    async def _async_learn_mac(self) -> None:
        try:
            # A host name is looked up the way the session looks it up.
            addresses = await async_addresses(self.hass, self.host)
            mac = None
            if len(addresses) == 1:
                mac = await self.hass.async_add_executor_job(read_mac, next(iter(addresses)))
        finally:
            self._mac_reading = False
        if mac is None:
            # Not in the table: Home Assistant may not share the host's network, or the name leads to several
            # addresses. Not worth a lookup every minute for ever.
            self._mac_wait = min(self._mac_wait * 2, MAC_RETRY_MAX)
            return
        device = self._device()
        if device is None or not self._identity_confirmed:
            return  # also when another device turned up at the address meanwhile
        connection = (CONNECTION_NETWORK_MAC, mac)
        if connection in device.connections:
            self._mac_known = True
            return
        registry = dr.async_get(self.hass)
        for other in registry.async_get_devices(connections={connection}):
            owner = self.hass.config_entries.async_get_entry(other.config_entry_id)
            if other.id != device.id and owner is not None and owner.domain == DOMAIN:
                # Two purifiers with one MAC is a wrong reading, not a fact to record. A device of another
                # integration with this MAC is normal: a router's device tracker has one for every client.
                LOGGER.debug("%s: MAC %s already belongs to another purifier; not recorded", self.host, mac)
                return
        kept = {item for item in device.connections if item[0] != CONNECTION_NETWORK_MAC}
        registry.async_update_device(device.id, new_connections=kept | {connection})
        self._mac_known = True

    @callback
    def _async_tick(self, _now: datetime) -> None:
        """Every REDISCOVER_CHECK: try the MAC address again, and look for a purifier that is lost.

        Also when it never answered at all since the start: a purifier that
        moved while Home Assistant was down is never reachable at the stored
        address. The search is a task of the entry, so unloading stops it.
        """
        self.async_learn_mac()
        self._note_lost()
        if self._lost_since is None or self._searching or time.monotonic() - self._lost_since < self._search_wait:
            return
        self._searching = True
        self.config_entry.async_create_background_task(
            self.hass, self._async_look_for_it(), f"{DOMAIN} search for {self.config_entry.title}"
        )

    async def _async_look_for_it(self) -> None:
        """Search the network; move the entry when the purifier answers at another address."""
        entry = self.config_entry
        try:
            found = await async_search(self.hass, entry.data.get(CONF_PORT, DEFAULT_PORT))
            answers = sorted(host for host, identity in found.items() if self._is_ours(identity.device_id))
            current = await async_addresses(self.hass, self.host) if answers else set()
        finally:
            self._searching = False
        if self._lost_since is not None:
            # The next search after a longer while: a purifier that is unplugged is not looked for every few
            # minutes for ever.
            self._lost_since = time.monotonic()
            self._search_wait = min(self._search_wait * 2, REDISCOVER_MAX)
        if not answers or not self._lost:
            return  # not found, or it answered again at its address while the search ran
        if here := [host for host in answers if host in current]:
            if self.session.identity_mismatch and not is_address(self.host):
                # The name leads to the purifier now. The session looks a name up again by itself while nothing
                # answers, but not while another device answers at the address it looked up before.
                LOGGER.info("%s answers where %s leads now, %s; reloading", entry.title, self.host, here[0])
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return
        host = answers[0]
        LOGGER.info("%s answers at a new address, %s instead of %s", entry.title, host, self.host)
        self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_HOST: host})
        self.hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def _update_device(self) -> None:
        """Bring model and firmware in the device registry up to date with the status."""
        versions = (self.data.get(Key.MODEL), self.data.get(Key.FIRMWARE))
        if versions == self._registered_versions or not all(isinstance(text, str) for text in versions):
            return
        device = self._device()
        if device is None:
            return  # no entity was added yet; they take these values along
        self._registered_versions = versions
        dr.async_get(self.hass).async_update_device(device.id, model=versions[0], sw_version=versions[1])

    # -- the stored status -------------------------------------------------

    def _kept(self) -> tuple[Any, ...]:
        """Return what a restart should bring back as it is now: the keys, the state and the settings."""
        status = self.session.status or {}
        return (self.keys, *(status.get(key) for key in SAVED_SOON))

    @callback
    def _schedule_save(self) -> None:
        """Have the status written: soon after a change that matters, otherwise once in a long while.

        One write is pending at most, and a later status never postpones it.
        Without a new status since the last write nothing is written at all,
        so a purifier in standby costs no disk writes.
        """
        if self.session.status is None:
            return
        if self._kept() != self._saved_kept:
            delay: float = SAVE_DELAY
        elif self.session.last_frame_at != self._saved_frame_at:
            delay = SAVE_INTERVAL
        else:
            return
        due = self.hass.loop.time() + delay
        if self._save_due is not None and self._save_due <= due:
            return
        self._save_due = due
        # An earlier moment replaces the pending one; this is never called with a later one.
        self._store.async_delay_save(self._data_to_save, delay)

    def _data_to_save(self) -> dict[str, Any]:
        """Return the status for the file; called at the moment it is written."""
        self._save_due = None
        self._saved_kept, self._saved_frame_at = self._kept(), self.session.last_frame_at
        return self.session.snapshot().as_dict()

    # -- another device at the address -------------------------------------

    @callback
    def _update_issue(self) -> None:
        """Show a repair issue while another device answers at the address."""
        mismatch = self.session.identity_mismatch
        if mismatch == self._issue_shown:
            return
        self._issue_shown = mismatch
        issue_id = f"wrong_device_{self.config_entry.entry_id}"
        if mismatch:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="wrong_device",
                translation_placeholders={"name": self.config_entry.title, "host": self.host},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @callback
    def async_clear_issue(self) -> None:
        """Remove the repair issue of this purifier."""
        ir.async_delete_issue(self.hass, DOMAIN, f"wrong_device_{self.config_entry.entry_id}")

    # -- commands ----------------------------------------------------------

    async def async_write(self, values: Mapping[str, int]) -> None:
        """Send values to the purifier and wait until it reports them."""
        if self.session.identity_mismatch:
            raise self._error("wrong_device")
        try:
            try:
                await self.session.write(values)
            except DeviceOffError:
                # A scene applies its entities at the same time, and may name
                # a setting before the fan that switches the purifier on. A
                # moment later that switch-on is under way, and the session
                # holds the setting back until it is confirmed. A purifier
                # that really is off is reported that moment later.
                await asyncio.sleep(DEVICE_OFF_RETRY_DELAY)
                await self.session.write(values)
        except DeviceOffError as err:
            raise self._error("device_off") from err
        except RefusedError as err:
            raise self._error("refused") from err
        except NotConfirmedError as err:
            raise self._error("not_confirmed") from err
        except UnreachableError as err:
            raise self._error("unreachable") from err
        except AirlinkError as err:
            raise self._error("unreachable") from err

    def error(self, key: str) -> HomeAssistantError:
        """Return the translated error ``key`` for this purifier."""
        return self._error(key)

    def _error(self, key: str) -> HomeAssistantError:
        return HomeAssistantError(
            translation_domain=DOMAIN, translation_key=key, translation_placeholders={"name": self.config_entry.title}
        )
