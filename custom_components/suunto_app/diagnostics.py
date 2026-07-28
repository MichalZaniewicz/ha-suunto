"""Diagnostics support for the Suunto App (unofficial) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SuuntoAppConfigEntry

# email/session_key live in entry.data; start_lat/start_lon are the decoded
# GPS start point on normalized workouts (any depth - async_redact_data walks
# nested dicts/lists). Raw sleep records carry only duration/isNap/HR/etc, no
# PII, so they need no redaction, but sit behind the same helper for safety if
# a field is ever added there.
TO_REDACT = {"email", "session_key", "start_lat", "start_lon"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SuuntoAppConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    daily = entry.runtime_data.daily
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "fast_coordinator_data": async_redact_data(entry.runtime_data.fast.data or {}, TO_REDACT),
        "daily_coordinator_data": async_redact_data(daily.data or {}, TO_REDACT),
        "last_sleep_raw": async_redact_data(daily.last_sleep_raw, TO_REDACT),
    }
