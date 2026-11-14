"""Diagnostics support for the Suunto App (unofficial) integration.

Settings > Devices & services > Suunto App > (three dots) > Download
diagnostics. Meant to be attached to a GitHub issue, so everything personal
is redacted: the e-mail, the session key, the calendar link's secret, the GPS
start points, body data and your own notes for the AI. What is left says what
broke: versions, settings, how each coordinator and each data stream is
doing (health.py), the open Repairs notices, the stored history and the AI
runners, plus the data the sensors are built from.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration

from . import SuuntoAppConfigEntry
from .const import CONF_AI_CONTEXT, CONF_CALENDAR_FEED_TOKEN, DOMAIN

# email/session_key and the calendar link's token live in entry.data; your
# own AI notes in the options; start_lat/start_lon are the decoded GPS start
# point on normalized workouts (any depth - async_redact_data walks nested
# dicts/lists); body data comes from the profile.
TO_REDACT = {
    "email",
    "session_key",
    CONF_CALENDAR_FEED_TOKEN,
    CONF_AI_CONTEXT,
    "start_lat",
    "start_lon",
    "weight_kg",
    "height_cm",
    "age",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _coordinator(coordinator: Any) -> dict[str, Any]:
    interval = coordinator.update_interval
    error = coordinator.last_exception
    return {
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": interval.total_seconds() if interval else None,
        "last_exception": f"{type(error).__name__}: {error}" if error else None,
    }


def _runner(runner: Any) -> dict[str, Any] | None:
    """The AI insight / weekly summary runner, without the AI's text."""
    if runner is None:
        return None
    result = runner.result or {}
    return {
        "ai_task_entity": runner.ai_task_entity,
        "enabled": runner.enabled,
        "running": runner.running,
        "last_error": runner.last_error,
        "attempts": list(getattr(runner, "_attempts", ()) or ()),
        "last_result": {
            key: result.get(key)
            for key in ("for_date", "week_start", "generated_at", "status", "manual")
            if key in result
        },
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SuuntoAppConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    daily = runtime.daily
    integration = await async_get_integration(hass, DOMAIN)
    issues = [
        {
            "issue_id": issue.issue_id.replace(entry.entry_id, "<entry>"),
            "translation_key": issue.translation_key,
            "severity": issue.severity,
            "ignored": issue.dismissed_version is not None,
        }
        for issue in ir.async_get(hass).issues.values()
        if issue.domain == DOMAIN and entry.entry_id in issue.issue_id and issue.active
    ]
    return {
        "versions": {
            "integration": str(integration.version),
            "home_assistant": HA_VERSION,
        },
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "coordinators": {
            "daily": _coordinator(daily),
            "live": _coordinator(runtime.fast),
        },
        "stream_health": daily.health.snapshot(),
        "open_repair_issues": issues,
        "history_store": {
            "deep_scan_at": _iso(getattr(daily, "_seeded_at", None)),
            "known_workout_keys": len(getattr(daily, "_known_workout_keys", None) or ()),
            "held_events": len(getattr(daily, "_held_events", None) or ()),
            "sport_palette": getattr(daily, "_sport_palette", {}),
        },
        "ai": {"daily": _runner(runtime.ai), "weekly": _runner(runtime.weekly)},
        "fast_coordinator_data": async_redact_data(runtime.fast.data or {}, TO_REDACT),
        "daily_coordinator_data": async_redact_data(daily.data or {}, TO_REDACT),
        "last_sleep_raw": async_redact_data(daily.last_sleep_raw, TO_REDACT),
    }
