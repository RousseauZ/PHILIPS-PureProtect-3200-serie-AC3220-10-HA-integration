"""Connects one airlink session to Home Assistant."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
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
    STORAGE_VERSION,
    Key,
)

type PureProtectConfigEntry = ConfigEntry[PureProtectCoordinator]

# The timings of the session; the tests replace them with fast ones.
SESSION_OPTIONS = SessionOptions()


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
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._issue_shown = False
        self._registered_versions: tuple[Any, Any] = (None, None)
        self.data = {}

    async def async_start(self) -> None:
        """Load the saved status and start the session; never waits for the device."""
        entry = self.config_entry
        stored = await self._store.async_load()
        restored = RestoredState.from_dict(stored) if isinstance(stored, Mapping) else None
        self.session = Session(
            self.host,
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
            options=SESSION_OPTIONS,
            expected_device_id=self.device_id,
            restored=restored,
        )
        self.data = self.session.status or {}
        self.keys = self.session.snapshot().keys
        if not self.keys:
            self.keys, self.keys_assumed = DEFAULT_KEYS, True
        entry.async_on_unload(self.session.add_listener(self._handle_session_update))
        await self.session.start()

    async def async_stop(self) -> None:
        """Stop the session and save what it knows."""
        await self.session.stop()
        if self.session.status is not None:
            await self._store.async_save(self._data_to_save())

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

    @callback
    def _handle_session_update(self) -> None:
        """Take over a new status or a new session state."""
        status = self.session.status or {}
        if not self.keys.issuperset(status):
            self.keys = frozenset(status) if self.keys_assumed else self.keys | frozenset(status)
            self.keys_assumed = False
        self._update_issue()
        self.async_set_updated_data(status)
        self._update_device()
        if self.session.status is not None:
            self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    @callback
    def _update_device(self) -> None:
        """Bring model and firmware in the device registry up to date with the status."""
        versions = (self.data.get(Key.MODEL), self.data.get(Key.FIRMWARE))
        if versions == self._registered_versions or not all(isinstance(text, str) for text in versions):
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier((DOMAIN, self.device_id), self.config_entry.entry_id)
        if device is None:
            return  # no entity was added yet; they take these values along
        self._registered_versions = versions
        registry.async_update_device(device.id, model=versions[0], sw_version=versions[1])

    def _data_to_save(self) -> dict[str, Any]:
        return self.session.snapshot().as_dict()

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

    async def async_write(self, values: Mapping[str, int]) -> None:
        """Send values to the purifier and wait until it reports them."""
        if self.session.identity_mismatch:
            raise self._error("wrong_device")
        try:
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

    def _error(self, key: str) -> HomeAssistantError:
        return HomeAssistantError(
            translation_domain=DOMAIN, translation_key=key, translation_placeholders={"name": self.config_entry.title}
        )
