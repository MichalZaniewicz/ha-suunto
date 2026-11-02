"""Settings > System > Repairs > System information: the Suunto section.

What a bug report needs first: can Home Assistant reach both Sports Tracker
servers, is the account loaded (a lapsed session shows here), did the last
data updates work, and when did the watch last sync. Nothing personal: no
account name or e-mail, since this page is meant to be copied into issues.
With several accounts, the update lines describe the first loaded one.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import API_BASE, DOMAIN, TIMELINE_BASE


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register the system health info callback."""
    register.async_register_info(system_health_info)


def _update_status(coordinator: Any) -> Any:
    if coordinator.last_update_success:
        return "ok"
    error = coordinator.last_exception
    return {"type": "failed", "error": str(error) if error else "update failed"}


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return the info shown on the System information page."""
    entries = hass.config_entries.async_entries(DOMAIN)
    loaded = [e for e in entries if e.state is ConfigEntryState.LOADED]
    info: dict[str, Any] = {
        "api_reachable": system_health.async_check_can_reach_url(hass, API_BASE),
        "wellness_reachable": system_health.async_check_can_reach_url(
            hass, TIMELINE_BASE
        ),
        "accounts_loaded": f"{len(loaded)}/{len(entries)}",
    }
    not_loaded = [e for e in entries if e.state is not ConfigEntryState.LOADED]
    if not_loaded:
        info["account_state"] = {
            "type": "failed",
            "error": ", ".join(sorted({e.state.value for e in not_loaded})),
        }
    if not loaded:
        return info

    runtime = loaded[0].runtime_data
    daily = runtime.daily
    data = daily.data or {}
    last_sync = (data.get("sync") or {}).get("last_sync")
    info.update(
        {
            "daily_update": _update_status(daily),
            "activity_update": _update_status(runtime.fast),
            "watch_last_synced": (
                dt_util.as_local(last_sync).strftime("%Y-%m-%d %H:%M")
                if last_sync
                else "-"
            ),
            "workouts_in_window": len(data.get("workouts") or []),
            "ai_configured": runtime.ai is not None,
        }
    )
    return info
