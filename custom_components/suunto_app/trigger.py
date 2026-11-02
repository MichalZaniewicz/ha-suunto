"""Triggers for the automation editor: "Suunto: new workout" and friends.

Home Assistant lists these under the integration in the trigger picker, with
their own fields (sport, minimum distance, sleep shorter than...), so nobody
has to know the bus event names or write a template to filter them. Each one
listens to the bus event the integration already fires (const.EVENT_*),
which stays as it was for existing automations.

The trigger variables carry the event data twice: as ``trigger.data`` and,
like the plain event trigger, as ``trigger.event.data``, so templates written
for one work with the other.

Needs Home Assistant 2025.12 or newer (integration-provided triggers); on an
older version the picker simply does not show them.
"""

from __future__ import annotations

from typing import Any

try:
    import probatio as vol
except ImportError:  # Home Assistant before 2026.10
    import voluptuous as vol

from homeassistant.const import CONF_OPTIONS
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.trigger import Trigger, TriggerConfig
from homeassistant.helpers.typing import ConfigType

from .const import (
    COMMUTE_TAG,
    EVENT_AI_INSIGHT,
    EVENT_AI_WEEKLY,
    EVENT_NEW_WORKOUT,
    EVENT_WOKE_UP,
)

CONF_CONFIG_ENTRY = "config_entry"

_ENTRY = {vol.Optional(CONF_CONFIG_ENTRY): str}
_NUMBER = vol.All(vol.Coerce(float), vol.Range(min=0))


def _options_schema(fields: dict[Any, Any]) -> Any:
    return vol.Schema(
        {vol.Optional(CONF_OPTIONS, default={}): vol.Schema({**_ENTRY, **fields})}
    )


def _activity_matches(wanted: list[str], activity: Any) -> bool:
    """Empty list = any sport; otherwise the exact label, case-insensitive."""
    if not wanted:
        return True
    label = str(activity or "").casefold()
    return any(label == str(item).casefold().strip() for item in wanted)


def workout_matches(options: dict[str, Any], data: dict[str, Any]) -> bool:
    """Whether a new-workout event passes the trigger's filters (pure)."""
    if not _activity_matches(options.get("activity") or [], data.get("activity")):
        return False
    min_km = options.get("min_distance_km")
    if min_km and (data.get("distance_meters") or 0) < min_km * 1000:
        return False
    min_minutes = options.get("min_duration_minutes")
    if min_minutes and (data.get("duration_minutes") or 0) < min_minutes:
        return False
    commute = options.get("commute", "any")
    is_commute = COMMUTE_TAG in (data.get("tags") or [])
    if (commute == "only" and not is_commute) or (commute == "exclude" and is_commute):
        return False
    if options.get("with_achievement") and not data.get("achievement_count"):
        return False
    return True


def woke_up_matches(options: dict[str, Any], data: dict[str, Any]) -> bool:
    """Whether a woke-up event passes the trigger's filters (pure).

    A night without a known length never passes a length filter.
    """
    hours = data.get("sleep_hours")
    below = options.get("sleep_below_hours")
    above = options.get("sleep_above_hours")
    if (below is not None or above is not None) and hours is None:
        return False
    if below is not None and not hours < below:
        return False
    if above is not None and not hours > above:
        return False
    readiness_below = options.get("readiness_below")
    if readiness_below is not None:
        readiness = data.get("readiness")
        if readiness is None or not readiness < readiness_below:
            return False
    return True


def ai_report_matches(options: dict[str, Any], event_type: str) -> bool:
    report = options.get("report", "any")
    if report == "daily":
        return event_type == EVENT_AI_INSIGHT
    if report == "weekly":
        return event_type == EVENT_AI_WEEKLY
    return True


class _SuuntoEventTrigger(Trigger):
    """Fires on one or more of the integration's bus events that pass a filter."""

    _EVENTS: tuple[str, ...] = ()
    _SCHEMA: Any = _options_schema({})
    _DESCRIPTION = "Suunto event"

    @classmethod
    async def async_validate_config(
        cls, hass: HomeAssistant, config: ConfigType
    ) -> ConfigType:
        """Validate the trigger's options."""
        return cls._SCHEMA(config)

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        """Initialize the trigger."""
        super().__init__(hass, config)
        self._options: dict[str, Any] = dict(config.options or {})

    def _matches(self, event: Event) -> bool:
        raise NotImplementedError

    async def async_attach_runner(
        self, run_action: Any, did_not_trigger: Any = None
    ) -> CALLBACK_TYPE:
        """Listen to the bus events; ``did_not_trigger`` exists from 2026.8."""
        entry_id = self._options.get(CONF_CONFIG_ENTRY)

        @callback
        def _on_event(event: Event) -> None:
            if entry_id and event.data.get("entry_id") != entry_id:
                return
            if not self._matches(event):
                return
            data = dict(event.data)
            run_action(
                {"event": event, "data": data, "event_type": event.event_type},
                self._DESCRIPTION,
                event.context,
            )

        unsubs = [self._hass.bus.async_listen(name, _on_event) for name in self._EVENTS]

        @callback
        def _unsubscribe() -> None:
            for unsub in unsubs:
                unsub()

        return _unsubscribe


class NewWorkoutTrigger(_SuuntoEventTrigger):
    """A new workout has reached Home Assistant (after the watch synced)."""

    _EVENTS = (EVENT_NEW_WORKOUT,)
    _DESCRIPTION = "Suunto new workout"
    _SCHEMA = _options_schema(
        {
            vol.Optional("activity", default=[]): vol.All(
                lambda value: value if isinstance(value, list) else [value], [str]
            ),
            vol.Optional("min_distance_km"): _NUMBER,
            vol.Optional("min_duration_minutes"): _NUMBER,
            vol.Optional("commute", default="any"): vol.In(["any", "only", "exclude"]),
            vol.Optional("with_achievement", default=False): bool,
        }
    )

    def _matches(self, event: Event) -> bool:
        return workout_matches(self._options, event.data)


class WokeUpTrigger(_SuuntoEventTrigger):
    """Last night's sleep has synced in."""

    _EVENTS = (EVENT_WOKE_UP,)
    _DESCRIPTION = "Suunto woke up"
    _SCHEMA = _options_schema(
        {
            vol.Optional("sleep_below_hours"): _NUMBER,
            vol.Optional("sleep_above_hours"): _NUMBER,
            vol.Optional("readiness_below"): vol.All(
                vol.Coerce(float), vol.Range(min=0, max=100)
            ),
        }
    )

    def _matches(self, event: Event) -> bool:
        return woke_up_matches(self._options, event.data)


class AiReportTrigger(_SuuntoEventTrigger):
    """The daily AI insight or the weekly AI summary is ready."""

    _EVENTS = (EVENT_AI_INSIGHT, EVENT_AI_WEEKLY)
    _DESCRIPTION = "Suunto AI report"
    _SCHEMA = _options_schema(
        {vol.Optional("report", default="any"): vol.In(["any", "daily", "weekly"])}
    )

    def _matches(self, event: Event) -> bool:
        return ai_report_matches(self._options, event.event_type)


TRIGGERS: dict[str, type[Trigger]] = {
    "new_workout": NewWorkoutTrigger,
    "woke_up": WokeUpTrigger,
    "ai_report": AiReportTrigger,
}


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Return the triggers this integration provides."""
    return TRIGGERS
