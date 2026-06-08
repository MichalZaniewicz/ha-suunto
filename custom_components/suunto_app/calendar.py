"""Calendar platform: past Suunto workouts as browsable events.

Each workout in the already-fetched 90-day list becomes a calendar event (no
extra requests), so the history can be browsed in a Calendar card. Events are
read-only and all in the past, so the entity has no "current" event.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SuuntoAppConfigEntry
from .const import DOMAIN


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
    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator: Any, entry: SuuntoAppConfigEntry) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_workouts_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Suunto",
            model="Suunto App (unofficial)",
        )

    def _events(self) -> list[CalendarEvent]:
        """Build a CalendarEvent per workout from the coordinator data."""
        events: list[CalendarEvent] = []
        for w in (self.coordinator.data or {}).get("workouts", []):
            start = w.get("start_time")
            if not isinstance(start, datetime):
                continue
            minutes = w.get("duration_minutes") or 0
            end = start + timedelta(minutes=minutes or 1)
            distance = w.get("distance_meters")
            km = f"{distance / 1000:.1f} km" if distance else None
            summary = " · ".join(
                p for p in (w.get("activity") or "Workout", km) if p
            )
            details = []
            if minutes:
                details.append(f"{minutes} min")
            if w.get("avg_hr_bpm"):
                details.append(
                    f"HR {w['avg_hr_bpm']}/{w.get('max_hr_bpm') or '?'} bpm"
                )
            if w.get("tss"):
                details.append(f"TSS {w['tss']}")
            events.append(
                CalendarEvent(
                    start=start,
                    end=end,
                    summary=summary,
                    description=" · ".join(details) or None,
                    uid=w.get("key"),
                )
            )
        return events

    @property
    def event(self) -> CalendarEvent | None:
        """No 'current' event — all workouts are in the past."""
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
