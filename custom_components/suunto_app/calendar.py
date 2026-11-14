"""Calendar platform: past Suunto workouts as browsable events.

Each workout in the already-fetched 90-day list becomes a calendar event (no
extra requests), so the history can be browsed in a Calendar card. Events are
read-only and all in the past, so the entity has no "current" event.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SuuntoAppConfigEntry, suunto_device_info
from .calendar_feed import workout_events


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuuntoAppConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the workouts calendar from a config entry."""
    async_add_entities([SuuntoWorkoutsCalendar(entry.runtime_data.daily, entry)])


class SuuntoWorkoutsCalendar(CoordinatorEntity, CalendarEntity):
    """A read-only calendar of past workouts."""

    _attr_has_entity_name = True
    _attr_translation_key = "workouts"

    def __init__(self, coordinator: Any, entry: SuuntoAppConfigEntry) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_workouts_calendar"
        self._attr_device_info = suunto_device_info(entry)
        # Built once per data update rather than per query - see _events().
        self._cached_events: list[CalendarEvent] | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Drop the cached events when fresh data arrives."""
        self._cached_events = None
        super()._handle_coordinator_update()

    def _events(self) -> list[CalendarEvent]:
        """Build a CalendarEvent per workout from the coordinator data.

        Cached until the next coordinator update: the whole 90-day list is
        rebuilt here, and a Calendar card asks for a range every time the user
        pages through months, which would otherwise redo the same few hundred
        events on each request.
        """
        if self._cached_events is not None:
            return self._cached_events
        events = workout_events((self.coordinator.data or {}).get("workouts", []))
        self._cached_events = events
        return events

    @property
    def event(self) -> CalendarEvent | None:
        """No 'current' event - all workouts are in the past."""
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return workouts overlapping the requested range."""
        return [
            e
            for e in self._events()
            if e.end > start_date and e.start < end_date
        ]
