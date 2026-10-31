"""Event platform: the integration's bus events as event entities.

The bus events (suunto_app_new_workout, suunto_app_woke_up,
suunto_app_ai_insight, suunto_app_ai_weekly_summary) stay as they were; these
entities mirror them, so an automation can be built from the UI ("Entity >
Workout > event fired") without typing an event type, and every one lands in
the logbook. The event data becomes the entity's attributes.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SuuntoAppConfigEntry, suunto_device_info
from .const import (
    DOMAIN,
    EVENT_AI_INSIGHT,
    EVENT_AI_WEEKLY,
    EVENT_NEW_WORKOUT,
    EVENT_WOKE_UP,
)

# translation_key -> {bus event: event type on the entity}
_EVENTS: dict[str, dict[str, str]] = {
    "workout": {EVENT_NEW_WORKOUT: "new_workout"},
    "woke_up": {EVENT_WOKE_UP: "woke_up"},
    "ai_report": {EVENT_AI_INSIGHT: "daily_insight", EVENT_AI_WEEKLY: "weekly_summary"},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuuntoAppConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the workout and woke-up entities; the AI one only while configured."""
    keys = ["workout", "woke_up"]
    if entry.runtime_data.ai is not None:
        keys.append("ai_report")
    else:
        registry = er.async_get(hass)
        if entity_id := registry.async_get_entity_id(
            "event", DOMAIN, f"{entry.entry_id}_event_ai_report"
        ):
            registry.async_remove(entity_id)
    async_add_entities(SuuntoEventEntity(entry, key) for key in keys)


class SuuntoEventEntity(EventEntity):
    """One of the integration's bus events, for this config entry."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # The AI texts are long and already kept on the AI sensors; a workout's
    # tags are a list. Live on the entity, not in the database.
    _unrecorded_attributes = frozenset(
        {"sections", "summary", "advice", "warning", "labels", "tags"}
    )

    def __init__(self, entry: SuuntoAppConfigEntry, key: str) -> None:
        """Initialize the entity."""
        self._entry_id = entry.entry_id
        self._types = _EVENTS[key]
        self._attr_translation_key = key
        self._attr_event_types = list(self._types.values())
        self._attr_unique_id = f"{entry.entry_id}_event_{key}"
        self._attr_device_info = suunto_device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Listen to this entry's bus events."""
        for event_type in self._types:
            self.async_on_remove(
                self.hass.bus.async_listen(event_type, self._on_event)
            )

    @callback
    def _on_event(self, event: Event) -> None:
        if event.data.get("entry_id") != self._entry_id:
            return
        data: dict[str, Any] = {
            key: value for key, value in event.data.items() if key != "entry_id"
        }
        self._trigger_event(self._types[event.event_type], data)
        self.async_write_ha_state()
