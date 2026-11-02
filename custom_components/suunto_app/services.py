"""Read-only actions that return Suunto data to scripts and automations.

``suunto_app.get_workouts``, ``get_sleep`` and six more, one per tool of the
Assist tool set (llm_api.py) and built by the very same code, so an
automation and a conversation agent always see the same numbers. Called with
``response_variable``, e.g.::

    - action: suunto_app.get_workouts
      data: {days: 7, activity: Cycling}
      response_variable: rides
    - action: notify.mobile_app_phone
      data:
        message: "{{ rides.totals.distance_km }} km this week"

Everything comes from data the integration already holds: no action makes
a request to Suunto, and none changes anything. Dates and times are ISO 8601
in local time (Assist gets "2026-10-14 Wed" instead).
"""

from __future__ import annotations

from typing import Any

try:
    import probatio as vol
except ImportError:  # Home Assistant before 2026.10
    import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .llm_api import (
    InsightsTool,
    ReadinessTool,
    RecordsTool,
    SleepTool,
    TodayTool,
    TotalsTool,
    TrainingLoadTool,
    WorkoutsTool,
    _clean,
)

CONF_CONFIG_ENTRY_ID = "config_entry_id"

_INT = vol.All(vol.Coerce(int), vol.Range(min=1))

# action -> (the Assist tool that builds the answer, its extra fields)
_ACTIONS: dict[str, tuple[type, dict[Any, Any]]] = {
    "get_readiness": (ReadinessTool, {}),
    "get_sleep": (SleepTool, {vol.Optional("nights"): _INT}),
    "get_workouts": (
        WorkoutsTool,
        {
            vol.Optional("start_date"): vol.Coerce(str),
            vol.Optional("end_date"): vol.Coerce(str),
            vol.Optional("days"): _INT,
            vol.Optional("activity"): vol.Coerce(str),
            vol.Optional("limit"): _INT,
        },
    ),
    "get_training_load": (TrainingLoadTool, {vol.Optional("weeks"): _INT}),
    "get_today": (TodayTool, {}),
    "get_totals": (
        TotalsTool,
        {
            vol.Optional("period"): vol.In(
                ["last_7_days", "month", "year", "lifetime", "gear"]
            )
        },
    ),
    "get_records": (RecordsTool, {}),
    "get_insights": (InsightsTool, {}),
}


def _runtimes(hass: HomeAssistant, entry_id: str | None) -> list[tuple[str, Any]]:
    """(account name, runtime data) of the picked entry, or of every loaded one."""
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_entry",
                translation_placeholders={"entry_id": entry_id},
            )
        entries = [entry]
    else:
        entries = hass.config_entries.async_entries(DOMAIN)
    found = []
    for entry in entries:
        runtime = getattr(entry, "runtime_data", None)
        if (
            entry.state is ConfigEntryState.LOADED
            and runtime is not None
            and runtime.daily.data is not None
        ):
            found.append((entry.title, runtime))
    if not found:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_data")
    return found


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the read-only actions (once, from async_setup)."""
    for name, (tool_cls, fields) in _ACTIONS.items():
        tool = tool_cls()

        async def _handle(call: ServiceCall, tool: Any = tool) -> ServiceResponse:
            args = {k: v for k, v in call.data.items() if k != CONF_CONFIG_ENTRY_ID}
            now = dt_util.now()
            results = [
                {"account": account, **_clean(tool.build(runtime, now, args), iso=True)}
                for account, runtime in _runtimes(hass, call.data.get(CONF_CONFIG_ENTRY_ID))
            ]
            today = now.date().isoformat()
            if len(results) == 1:
                return {"today": today, **results[0]}
            return {"today": today, "accounts": results}

        hass.services.async_register(
            DOMAIN,
            name,
            _handle,
            schema=vol.Schema({vol.Optional(CONF_CONFIG_ENTRY_ID): str, **fields}),
            supports_response=SupportsResponse.ONLY,
        )
