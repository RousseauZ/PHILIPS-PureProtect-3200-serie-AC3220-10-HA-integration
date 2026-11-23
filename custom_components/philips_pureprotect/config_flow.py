"""Set up a purifier by its address."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.config_entries import (
    SOURCE_DHCP,
    SOURCE_IGNORE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_DEVICE, CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig, SelectSelectorMode
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .airlink import Identity, Session, SessionOptions
from .const import CONF_MODEL, DEFAULT_PORT, DOMAIN, LOGGER
from .coordinator import PureProtectCoordinator
from .search import async_addresses, async_search

# The info resource of an AC3220/10 answers after about half a second and
# quite often not at all (docs/metingen.md), so it is asked a few times.
IDENTIFY_OPTIONS = SessionOptions(info_attempts=6, info_timeout=2.0)

SCHEMA = probatio.Schema({probatio.Required(CONF_HOST): str})


async def async_identify(host: str) -> tuple[Identity | None, str | None]:
    """Ask who answers at the address; returns the identity or an error key.

    This reads the plaintext info resource only. It registers nothing and
    does not touch the counter, so it cannot disturb a session that already
    serves the device.
    """
    session = Session(host, port=DEFAULT_PORT, options=IDENTIFY_OPTIONS)
    try:
        identity = await session.identify()
        answered = session.diagnostics().datagrams_received > 0
    finally:
        await session.stop()
    if identity is not None:
        return identity, None
    return None, "not_a_purifier" if answered else "cannot_connect"


class PureProtectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow: find a purifier in the network, or ask for its address."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing found."""
        self._found: dict[str, Identity] = {}
        self._discovered: tuple[str, Identity] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the owner choose: search the network, or enter the address."""
        return self.async_show_menu(step_id="user", menu_options=["search", "manual"])

    async def async_step_search(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Search the network and offer the purifiers that are not set up yet.

        A purifier that is set up and answers at another address gets that
        address, as with DHCP.
        """
        if user_input is None:
            found = await async_search(self.hass, DEFAULT_PORT)
            self._found = {}
            moved = False
            for host, identity in found.items():
                entry = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, identity.device_id)
                if entry is None or entry.source == SOURCE_IGNORE:
                    self._found[host] = identity
                elif host not in await async_addresses(self.hass, entry.data.get(CONF_HOST, "")):
                    LOGGER.info(
                        "%s answers at a new address, %s instead of %s", entry.title, host, entry.data.get(CONF_HOST)
                    )
                    self._async_move(entry, host)
                    moved = True
            if not self._found:
                if moved:
                    return self.async_abort(reason="already_configured")
                error = "no_new_devices" if found else "no_devices_found"
                return self.async_show_form(step_id="manual", data_schema=SCHEMA, errors={"base": error})
            options = [
                SelectOptionDict(value=host, label=f"{_title(identity)} · {identity.model_id or '?'} · {host}")
                for host, identity in sorted(self._found.items())
            ]
            return self.async_show_form(
                step_id="search",
                data_schema=probatio.Schema(
                    {
                        probatio.Required(CONF_DEVICE): SelectSelector(
                            SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                        )
                    }
                ),
            )
        host = user_input[CONF_DEVICE]
        identity = self._found[host]
        # Not refused while DHCP offers the same purifier: creating the entry ends that offer.
        await self.async_set_unique_id(identity.device_id, raise_on_progress=False)
        await self._async_abort_if_set_up(host)
        return self._create(host, identity)

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add a purifier by address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            identity, error = await async_identify(host)
            if identity is None:
                errors["base"] = error or "cannot_connect"
            else:
                # Not refused while DHCP offers the same purifier: creating the entry ends that offer.
                await self.async_set_unique_id(identity.device_id, raise_on_progress=False)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self._create(host, identity)
        return self.async_show_form(
            step_id="manual", data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input), errors=errors
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """A device with a MAC address of the purifiers' Wi-Fi module joined the network, or got a new address.

        Nothing is sent to the address of a purifier that is set up, unless
        its session says that another device answers there: then the
        purifiers may have swapped addresses. Anything else is asked for its
        identity with the info resource, which registers nothing and cannot
        disturb a running session; MXCHIP modules are in other brands'
        appliances too. The address of a purifier that is set up is updated.
        """
        host = discovery_info.ip
        for entry in self._async_current_entries(include_ignore=False):
            if host in await async_addresses(self.hass, entry.data.get(CONF_HOST, "")) and not _elsewhere(entry):
                # With the unique id Home Assistant ties this discovery to the entry, and offers the purifier
                # again when the entry is removed.
                await self.async_set_unique_id(entry.unique_id, raise_on_progress=False)
                return self.async_abort(reason="already_configured")
        identity, error = await async_identify(host)
        if identity is None:
            return self.async_abort(reason=error or "cannot_connect")
        # An offer of this purifier that waits untouched shows an address it may have left: this one replaces it.
        for flow in self._async_in_progress(
            include_uninitialized=True, match_context={"unique_id": identity.device_id}
        ):
            if flow["context"].get("source") == SOURCE_DHCP and not flow["context"].get("dismiss_protected"):
                self.hass.config_entries.flow.async_abort(flow["flow_id"])
        await self.async_set_unique_id(identity.device_id)
        await self._async_abort_if_set_up(host)
        self._discovered = (host, identity)
        self.context["title_placeholders"] = {"name": _title(identity)}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask before adding a purifier that was found by itself."""
        assert self._discovered is not None
        host, identity = self._discovered
        if user_input is not None:
            return self._create(host, identity)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": _title(identity), "model": identity.model_id or "?", "host": host},
        )

    def _create(self, host: str, identity: Identity) -> ConfigFlowResult:
        return self.async_create_entry(title=_title(identity), data={CONF_HOST: host, CONF_MODEL: identity.model_id})

    async def _async_abort_if_set_up(self, host: str) -> None:
        """Abort when the purifier of this flow is set up; it gets the address it was found at.

        Not when the address in its entry is a host name that leads there:
        the owner chose the name.
        """
        entry = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, self.unique_id or "")
        if entry is not None and host in await async_addresses(self.hass, entry.data.get(CONF_HOST, "")):
            self._abort_if_unique_id_configured()
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

    @callback
    def _async_move(self, entry: ConfigEntry, host: str) -> None:
        """Give an entry the address its purifier was found at, and reload it, as _abort_if_unique_id_configured does."""
        if self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_HOST: host}) and entry.state in (
            ConfigEntryState.LOADED,
            ConfigEntryState.SETUP_RETRY,
        ):
            self.hass.config_entries.async_schedule_reload(entry.entry_id)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the address of a purifier, after checking that it is the same one."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            identity, error = await async_identify(host)
            if identity is None:
                errors["base"] = error or "cannot_connect"
            else:
                await self.async_set_unique_id(identity.device_id)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host}, reason="reconfigure_successful"
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input or {CONF_HOST: entry.data[CONF_HOST]}),
            errors=errors,
        )


def _title(identity: Identity) -> str:
    return identity.name or identity.model_id or "PureProtect"


def _elsewhere(entry: ConfigEntry) -> bool:
    """Return True when the session of an entry says that another device answers at its address."""
    coordinator = getattr(entry, "runtime_data", None)
    return (
        entry.state is ConfigEntryState.LOADED
        and isinstance(coordinator, PureProtectCoordinator)
        and coordinator.session.identity_mismatch
    )
