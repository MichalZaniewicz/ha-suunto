"""Config flow for the Suunto App (unofficial) integration.

Credentials handling: the password is used once (here and in reauth) to obtain a
session key, then discarded. Only the email and the revocable session key are
persisted to the config entry.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import SuuntoAppAuthError, SuuntoAppError, async_login
from .const import (
    CONF_EMAIL,
    CONF_FAST_SCAN_INTERVAL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_KEY,
    DEFAULT_FAST_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MIN_FAST_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD)
)
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
    }
)


class SuuntoAppConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the email/password config + reauth flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._reauth_email: str | None = None

    async def _login(self, email: str, password: str) -> dict[str, str]:
        """Run a login, returning the session info dict."""
        return await async_login(
            async_get_clientsession(self.hass), email, password
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials, log in once, store only email + session key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            try:
                info = await self._login(email, user_input[CONF_PASSWORD])
            except SuuntoAppAuthError:
                errors["base"] = "invalid_auth"
            except SuuntoAppError:
                errors["base"] = "cannot_connect"
            else:
                unique_id = info["user_key"] or info["username"] or email
                await self.async_set_unique_id(str(unique_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["username"] or email,
                    data={
                        CONF_EMAIL: email,
                        # Password intentionally NOT stored — only the session key.
                        CONF_SESSION_KEY: info["session_key"],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth when the stored session is no longer valid."""
        self._reauth_email = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again and refresh the session key."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        email = self._reauth_email or reauth_entry.data[CONF_EMAIL]

        if user_input is not None:
            try:
                info = await self._login(email, user_input[CONF_PASSWORD])
            except SuuntoAppAuthError:
                errors["base"] = "invalid_auth"
            except SuuntoAppError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_SESSION_KEY: info["session_key"],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"email": email},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> SuuntoAppOptionsFlow:
        """Return the options flow handler."""
        return SuuntoAppOptionsFlow()


class SuuntoAppOptionsFlow(OptionsFlow):
    """Handle the polling-interval option."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        fast_default = opts.get(
            CONF_FAST_SCAN_INTERVAL, DEFAULT_FAST_SCAN_INTERVAL_MINUTES
        )
        daily_default = opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FAST_SCAN_INTERVAL, default=fast_default
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_FAST_SCAN_INTERVAL_MINUTES,
                        max=120,
                        step=5,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SCAN_INTERVAL, default=daily_default
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_MINUTES,
                        max=1440,
                        step=5,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
