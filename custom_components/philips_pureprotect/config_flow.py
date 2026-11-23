"""Set up a purifier by its address."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from .airlink import Identity, Session, SessionOptions
from .const import CONF_MODEL, DEFAULT_PORT, DOMAIN

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
    """Config flow: ask for the address and check that a purifier answers."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
                return self.async_create_entry(
                    title=identity.name or identity.model_id or "PureProtect",
                    data={CONF_HOST: host, CONF_MODEL: identity.model_id},
                )
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input), errors=errors
        )

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
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: host})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input or {CONF_HOST: entry.data[CONF_HOST]}),
            errors=errors,
        )
