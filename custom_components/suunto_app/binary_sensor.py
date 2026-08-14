"""Binary sensor platform for the Suunto App (unofficial) integration.

Two states that are naturally yes/no and awkward to template from the numeric
sensors: whether Suunto still counts you as recovering, and whether a workout
has been logged today. Both read the daily coordinator's existing payload, so
neither costs a request.

Both flip on a clock, not only on a fetch: the daily coordinator polls hourly, so
without a timer "recovering" would stay on for up to an hour after the countdown
ended, and "workout today" would linger past midnight. Each entity therefore
schedules a state write for the moment its answer changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from . import SuuntoAppConfigEntry, suunto_device_info


def _recovered_at(data: dict[str, Any]) -> datetime | None:
    """When the last workout's recovery countdown ends (UTC), if known."""
    return ((data.get("workout") or {}).get("recovered_at")) or None


def _is_recovering(data: dict[str, Any]) -> bool | None:
    """True while Suunto's recovery countdown is still running."""
    if not data.get("workout"):
        return None  # no workout in the window - nothing to say
    recovered = _recovered_at(data)
    return bool(recovered and recovered > dt_util.utcnow())


def _recovering_next_change(data: dict[str, Any]) -> datetime | None:
    """The countdown's end, so the entity turns itself off on time."""
    recovered = _recovered_at(data)
    return recovered if recovered and recovered > dt_util.utcnow() else None


def _workout_today(data: dict[str, Any]) -> bool | None:
    """True when the newest workout started today (local time)."""
    start = (data.get("workout") or {}).get("start_time")
    if start is None:
        return None
    return dt_util.as_local(start).date() == dt_util.now().date()


def _next_local_midnight(data: dict[str, Any]) -> datetime | None:
    """Next local midnight - when "today" stops meaning the same day."""
    return dt_util.start_of_local_day(dt_util.now() + timedelta(days=1))


def _unusual_recovery(data: dict[str, Any]) -> bool | None:
    """True when resting HR is elevated and HRV suppressed at the same time.

    Computed by the daily coordinator (metrics.unusual_recovery) from the
    sleep-night HRV/RHR baselines, the same series the hrv_status/readiness
    sensors already read - no extra fetch. Only changes when new sleep data
    arrives, so unlike the two entities above this needs no self-scheduled
    timer.
    """
    return (data.get("baseline") or {}).get("unusual_recovery")


@dataclass(frozen=True, kw_only=True)
class SuuntoAppBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Suunto App binary sensor and how to compute its state."""

    is_on_fn: Callable[[dict[str, Any]], bool | None]
    # When the state will next change on its own, independent of a fetch.
    next_change_fn: Callable[[dict[str, Any]], datetime | None] | None = None


BINARY_SENSORS: tuple[SuuntoAppBinarySensorDescription, ...] = (
    SuuntoAppBinarySensorDescription(
        key="is_recovering",
        translation_key="is_recovering",
        icon="mdi:bed-clock",
        is_on_fn=_is_recovering,
        next_change_fn=_recovering_next_change,
    ),
    SuuntoAppBinarySensorDescription(
        key="workout_today",
        translation_key="workout_today",
        icon="mdi:calendar-check",
        is_on_fn=_workout_today,
        next_change_fn=_next_local_midnight,
    ),
    SuuntoAppBinarySensorDescription(
        key="unusual_recovery",
        translation_key="unusual_recovery",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:shield-alert-outline",
        is_on_fn=_unusual_recovery,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuuntoAppConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Suunto App binary sensors from a config entry."""
    async_add_entities(
        SuuntoAppBinarySensor(entry.runtime_data.daily, entry, description)
        for description in BINARY_SENSORS
    )


class SuuntoAppBinarySensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], BinarySensorEntity
):
    """A single yes/no Suunto App state."""

    entity_description: SuuntoAppBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry: SuuntoAppConfigEntry,
        description: SuuntoAppBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = suunto_device_info(entry)
        self._unsub_timer: CALLBACK_TYPE | None = None

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_added_to_hass(self) -> None:
        """Register with the coordinator and arm the self-refresh timer."""
        await super().async_added_to_hass()
        self._schedule_next_change()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Re-arm the timer on fresh data (a new workout moves the deadline)."""
        self._schedule_next_change()
        super()._handle_coordinator_update()

    @callback
    def _schedule_next_change(self) -> None:
        """Schedule a state write for the moment this answer changes."""
        self._cancel_timer()
        if self.entity_description.next_change_fn is None:
            return
        if self.coordinator.data is None:
            return
        when = self.entity_description.next_change_fn(self.coordinator.data)
        if when is None:
            return
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, self._async_timer_fired, dt_util.as_utc(when)
        )

    @callback
    def _async_timer_fired(self, _now: datetime) -> None:
        """Write the flipped state, then arm the next transition."""
        self._unsub_timer = None
        self.async_write_ha_state()
        # "Workout today" needs a fresh timer every midnight; "recovering" simply
        # finds no future deadline and stops rearming.
        self._schedule_next_change()

    @callback
    def _cancel_timer(self) -> None:
        """Drop any pending timer."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    async def async_will_remove_from_hass(self) -> None:
        """Stop the timer when the entity goes away."""
        self._cancel_timer()
        await super().async_will_remove_from_hass()
