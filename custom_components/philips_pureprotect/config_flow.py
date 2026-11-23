"""Set up a purifier by its address."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE, CONF_HOST
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig, SelectSelectorMode
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .airlink import Identity, Session, SessionOptions
from .const import CONF_MODEL, DEFAULT_PORT, DOMAIN
from .search import async_search

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
        """Search the network and offer the purifiers that are not set up yet."""
        if user_input is None:
            found = await async_search(self.hass, DEFAULT_PORT)
            configured = self._async_current_ids(include_ignore=False)
            self._found = {host: identity for host, identity in found.items() if identity.device_id not in configured}
            if not self._found:
                return self.async_show_form(step_id="manual", data_schema=SCHEMA, errors={"base": "no_devices_found"})
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
        await self.async_set_unique_id(identity.device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
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
                await self.async_set_unique_id(identity.device_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self._create(host, identity)
        return self.async_show_form(
            step_id="manual", data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input), errors=errors
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """A device with a MAC address of the purifiers' Wi-Fi module joined the network, or got a new address.

        The address of a purifier that is set up is updated. Anything else
        is asked for its identity with the info resource, which registers
        nothing and cannot disturb a running session; MXCHIP modules are in
        other brands' appliances too.
        """
        host = discovery_info.ip
        if any(entry.data.get(CONF_HOST) == host for entry in self._async_current_entries(include_ignore=False)):
            return self.async_abort(reason="already_configured")
        identity, error = await async_identify(host)
        if identity is None:
            return self.async_abort(reason=error or "cannot_connect")
        await self.async_set_unique_id(identity.device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
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
