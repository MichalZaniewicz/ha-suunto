"""Config flow for the Suunto App (unofficial) integration.

Credentials handling: the password is used once (here and in reauth) to obtain a
session key, then discarded. Only the email and the revocable session key are
persisted to the config entry.
"""

from __future__ import annotations

import logging
import uuid
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
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import SuuntoAppAuthError, SuuntoAppError, async_login
from .const import (
    CONF_EMAIL,
    CONF_FAST_SCAN_INTERVAL,
    CONF_FUEL_CONSUMPTION,
    CONF_FUEL_PRICE,
    CONF_GEAR,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_KEY,
    DEFAULT_FAST_SCAN_INTERVAL_MINUTES,
    DEFAULT_FUEL_CONSUMPTION,
    DEFAULT_FUEL_PRICE,
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
                        # Password intentionally NOT stored - only the session key.
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
    """Options: polling intervals, commute fuel figures, and tracked gear."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        menu = ["settings", "gear_add"]
        if self.config_entry.options.get(CONF_GEAR):
            menu += ["gear_service", "gear_remove"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    def _save(self, **changes: Any) -> ConfigFlowResult:
        """Store the options with ``changes`` applied, keeping everything else."""
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    def _gear(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_GEAR) or [])

    def _lifetime_by_activity(self) -> list[dict[str, Any]]:
        """Per-sport lifetime totals from the last daily update (may be empty)."""
        runtime = getattr(self.config_entry, "runtime_data", None)
        data = runtime.daily.data if runtime else None
        return ((data or {}).get("stats") or {}).get("by_activity") or []

    def _gear_selector(self) -> SelectSelector:
        return SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=g["id"], label=g.get("name") or g["id"])
                    for g in self._gear()
                ],
                mode=SelectSelectorMode.LIST,
            )
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Polling intervals and the fuel figures behind the commute savings."""
        if user_input is not None:
            return self._save(**user_input)

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
                vol.Required(
                    CONF_FUEL_CONSUMPTION,
                    default=opts.get(CONF_FUEL_CONSUMPTION, DEFAULT_FUEL_CONSUMPTION),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=30,
                        step=0.1,
                        unit_of_measurement="l/100 km",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_FUEL_PRICE,
                    default=opts.get(CONF_FUEL_PRICE, DEFAULT_FUEL_PRICE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=100, step=0.01, mode=NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_gear_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start tracking a piece of gear by one sport's distance."""
        activities = [
            a for a in self._lifetime_by_activity() if a.get("activity_id") is not None
        ]
        if not activities:
            # No lifetime stats yet (fresh install, or the last update failed),
            # so there is no baseline to count from.
            return self.async_abort(reason="no_activities")

        if user_input is not None:
            activity_id = int(user_input["activity"])
            baseline = next(
                (
                    a.get("distance_km") or 0.0
                    for a in activities
                    if a["activity_id"] == activity_id
                ),
                0.0,
            )
            gear = self._gear()
            gear.append(
                {
                    "id": uuid.uuid4().hex[:8],
                    "name": user_input["name"].strip() or "Gear",
                    "activity_id": activity_id,
                    # Lifetime distance of that sport right now: everything
                    # ridden from here on counts toward this gear.
                    "baseline_km": baseline,
                    "start_km": user_input["start_km"],
                    "interval_km": user_input["interval_km"],
                }
            )
            return self._save(**{CONF_GEAR: gear})

        schema = vol.Schema(
            {
                vol.Required("name"): TextSelector(),
                vol.Required(
                    "activity", default=str(activities[0]["activity_id"])
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=str(a["activity_id"]),
                                label=str(a.get("activity") or a["activity_id"]),
                            )
                            for a in activities
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required("start_km", default=0): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=200000,
                        step=1,
                        unit_of_measurement="km",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("interval_km", default=3000): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=200000,
                        step=1,
                        unit_of_measurement="km",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="gear_add", data_schema=schema)

    async def async_step_gear_service(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reset a piece of gear to 0 km after replacing or servicing it."""
        if user_input is not None:
            lifetime = {
                a.get("activity_id"): a.get("distance_km") or 0.0
                for a in self._lifetime_by_activity()
            }
            gear = self._gear()
            for item in gear:
                if item["id"] == user_input["gear"]:
                    item["start_km"] = 0
                    item["baseline_km"] = lifetime.get(
                        item.get("activity_id"), item.get("baseline_km", 0.0)
                    )
            return self._save(**{CONF_GEAR: gear})
        return self.async_show_form(
            step_id="gear_service",
            data_schema=vol.Schema({vol.Required("gear"): self._gear_selector()}),
        )

    async def async_step_gear_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Stop tracking a piece of gear."""
        if user_input is not None:
            return self._save(
                **{CONF_GEAR: [g for g in self._gear() if g["id"] != user_input["gear"]]}
            )
        return self.async_show_form(
            step_id="gear_remove",
            data_schema=vol.Schema({vol.Required("gear"): self._gear_selector()}),
        )
