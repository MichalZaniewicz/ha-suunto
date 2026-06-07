"""Sensor platform for the Suunto App (unofficial) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import SuuntoAppConfigEntry
from .const import DOMAIN

UNIT_BPM = "bpm"
UNIT_KCAL = "kcal"
UNIT_STEPS = "steps"
UNIT_MS = "ms"
UNIT_WORKOUTS = "workouts"

# Decimal places to display per sensor (HA rounds state, history and tooltips).
# Without this, rounded floats show artifacts like -11.199999999999998.
_DISPLAY_PRECISION: dict[str, int] = {
    # whole numbers
    "current_hr": 0, "daily_steps": 0, "daily_energy": 0, "sleep_deep": 0,
    "sleep_avg_hr": 0, "sleep_min_hr": 0, "last_avg_hr": 0, "last_max_hr": 0,
    "last_distance": 0, "last_duration": 0, "last_pct_hrmax": 0, "last_cadence": 0,
    "last_ascent": 0, "last_ascent_rate": 0, "last_cal_per_km": 0, "resting_hr": 0,
    "stress_state": 0, "workouts_7d": 0, "workouts_30d": 0, "lifetime_workouts": 0,
    "lifetime_days": 0, "lifetime_energy": 0, "readiness": 0,
    # one decimal
    "sleep_duration": 1, "sleep_quality": 1, "sleep_spo2": 1, "sleep_hrv": 1,
    "recovery_balance": 1, "recovery_time": 1, "hrv_baseline": 1,
    "resting_hr_baseline": 1, "fitness_ctl": 1, "fatigue_atl": 1, "form_tsb": 1,
    "last_avg_speed": 1, "last_tss": 1, "last_stride": 1, "last_zone1": 1,
    "last_zone2": 1, "last_zone3": 1, "last_zone4": 1, "last_zone5": 1,
    "weekly_distance": 1, "weekly_time": 1, "lifetime_distance": 1, "lifetime_time": 1,
    # two decimals
    "acwr": 2, "last_avg_pace": 2,
}

# Which coordinator feeds a sensor: "fast" (live activity) or "daily" (history).
SOURCE_FAST = "fast"
SOURCE_DAILY = "daily"


def _section(section: str, field: str) -> Callable[[dict[str, Any]], Any]:
    """Build a value_fn that reads ``field`` from a coordinator data section."""
    return lambda data: (data.get(section) or {}).get(field)


@dataclass(frozen=True, kw_only=True)
class SuuntoAppSensorDescription(SensorEntityDescription):
    """Describes a Suunto App sensor and how to compute its value."""

    value_fn: Callable[[dict[str, Any]], Any]
    source: str = SOURCE_DAILY


SENSORS: tuple[SuuntoAppSensorDescription, ...] = (
    # --- Sleep ---
    SuuntoAppSensorDescription(
        key="sleep_duration",
        translation_key="sleep_duration",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sleep",
        value_fn=_section("sleep", "duration_hours"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_deep",
        translation_key="sleep_deep",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sleep",
        value_fn=_section("sleep", "deep_minutes"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_light",
        translation_key="sleep_light",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sleep",
        value_fn=_section("sleep", "light_minutes"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_rem",
        translation_key="sleep_rem",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sleep",
        value_fn=_section("sleep", "rem_minutes"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_avg_hr",
        translation_key="sleep_avg_hr",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        value_fn=_section("sleep", "avg_hr_bpm"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_min_hr",
        translation_key="sleep_min_hr",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart",
        value_fn=_section("sleep", "min_hr_bpm"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_quality",
        translation_key="sleep_quality",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-circle",
        value_fn=_section("sleep", "quality_pct"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_spo2",
        translation_key="sleep_spo2",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lungs",
        value_fn=_section("sleep", "spo2_pct"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_hrv",
        translation_key="sleep_hrv",
        native_unit_of_measurement=UNIT_MS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-flash",
        value_fn=_section("sleep", "avg_hrv_ms"),
    ),
    SuuntoAppSensorDescription(
        key="sleep_time",
        translation_key="sleep_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:bed-clock",
        value_fn=_section("sleep", "timestamp"),
    ),
    # --- Recovery ---
    SuuntoAppSensorDescription(
        key="recovery_balance",
        translation_key="recovery_balance",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-heart-variant",
        value_fn=_section("recovery", "balance_pct"),
    ),
    SuuntoAppSensorDescription(
        key="stress_state",
        translation_key="stress_state",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:head-flash-outline",
        value_fn=_section("recovery", "stress_state"),
    ),
    # --- Daily activity ---
    SuuntoAppSensorDescription(
        key="daily_steps",
        translation_key="daily_steps",
        native_unit_of_measurement=UNIT_STEPS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:walk",
        source=SOURCE_FAST,
        value_fn=_section("activity", "daily_steps"),
    ),
    SuuntoAppSensorDescription(
        key="daily_energy",
        translation_key="daily_energy",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:fire",
        source=SOURCE_FAST,
        value_fn=_section("activity", "daily_energy_kcal"),
    ),
    SuuntoAppSensorDescription(
        key="current_hr",
        translation_key="current_hr",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        source=SOURCE_FAST,
        value_fn=_section("activity", "current_hr_bpm"),
    ),
    # --- Last workout ---
    SuuntoAppSensorDescription(
        key="last_activity",
        translation_key="last_activity",
        icon="mdi:run",
        value_fn=_section("workout", "activity"),
    ),
    SuuntoAppSensorDescription(
        key="last_workout_start",
        translation_key="last_workout_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
        value_fn=_section("workout", "start_time"),
    ),
    SuuntoAppSensorDescription(
        key="last_distance",
        translation_key="last_distance",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_section("workout", "distance_meters"),
    ),
    SuuntoAppSensorDescription(
        key="last_duration",
        translation_key="last_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer",
        value_fn=_section("workout", "duration_minutes"),
    ),
    SuuntoAppSensorDescription(
        key="last_ascent",
        translation_key="last_ascent",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:slope-uphill",
        value_fn=_section("workout", "ascent_meters"),
    ),
    SuuntoAppSensorDescription(
        key="recovery_time",
        translation_key="recovery_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        value_fn=_section("workout", "recovery_time_hours"),
    ),
    SuuntoAppSensorDescription(
        key="last_avg_hr",
        translation_key="last_avg_hr",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        value_fn=_section("workout", "avg_hr_bpm"),
    ),
    SuuntoAppSensorDescription(
        key="last_max_hr",
        translation_key="last_max_hr",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-flash",
        value_fn=_section("workout", "max_hr_bpm"),
    ),
    SuuntoAppSensorDescription(
        key="last_avg_speed",
        translation_key="last_avg_speed",
        native_unit_of_measurement="km/h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        value_fn=_section("workout", "avg_speed_kmh"),
    ),
    SuuntoAppSensorDescription(
        key="last_avg_pace",
        translation_key="last_avg_pace",
        native_unit_of_measurement="min/km",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:run-fast",
        value_fn=_section("workout", "avg_pace_min_km"),
    ),
    SuuntoAppSensorDescription(
        key="last_cadence",
        translation_key="last_cadence",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:rotate-right",
        value_fn=_section("workout", "cadence"),
    ),
    SuuntoAppSensorDescription(
        key="last_tss",
        translation_key="last_tss",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=_section("workout", "tss"),
    ),
    SuuntoAppSensorDescription(
        key="last_zone1",
        translation_key="last_zone1",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-outline",
        value_fn=_section("workout", "zone1_min"),
    ),
    SuuntoAppSensorDescription(
        key="last_zone2",
        translation_key="last_zone2",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-outline",
        value_fn=_section("workout", "zone2_min"),
    ),
    SuuntoAppSensorDescription(
        key="last_zone3",
        translation_key="last_zone3",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-half-full",
        value_fn=_section("workout", "zone3_min"),
    ),
    SuuntoAppSensorDescription(
        key="last_zone4",
        translation_key="last_zone4",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart",
        value_fn=_section("workout", "zone4_min"),
    ),
    SuuntoAppSensorDescription(
        key="last_zone5",
        translation_key="last_zone5",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-flash",
        value_fn=_section("workout", "zone5_min"),
    ),
    # --- Lifetime stats ---
    SuuntoAppSensorDescription(
        key="lifetime_distance",
        translation_key="lifetime_distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:map-marker-distance",
        value_fn=_section("stats", "distance_km"),
    ),
    SuuntoAppSensorDescription(
        key="lifetime_time",
        translation_key="lifetime_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer",
        value_fn=_section("stats", "time_hours"),
    ),
    SuuntoAppSensorDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        native_unit_of_measurement=UNIT_KCAL,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:fire",
        value_fn=_section("stats", "energy_kcal"),
    ),
    SuuntoAppSensorDescription(
        key="lifetime_workouts",
        translation_key="lifetime_workouts",
        native_unit_of_measurement=UNIT_WORKOUTS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=_section("stats", "workouts"),
    ),
    SuuntoAppSensorDescription(
        key="lifetime_days",
        translation_key="lifetime_days",
        native_unit_of_measurement="d",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:calendar-check",
        value_fn=_section("stats", "active_days"),
    ),
    # --- Per-workout derived ---
    SuuntoAppSensorDescription(
        key="last_pct_hrmax",
        translation_key="last_pct_hrmax",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_fn=_section("workout", "pct_hrmax"),
    ),
    SuuntoAppSensorDescription(
        key="last_cal_per_km",
        translation_key="last_cal_per_km",
        native_unit_of_measurement="kcal/km",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=_section("workout", "cal_per_km"),
    ),
    SuuntoAppSensorDescription(
        key="last_ascent_rate",
        translation_key="last_ascent_rate",
        native_unit_of_measurement="m/h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:trending-up",
        value_fn=_section("workout", "ascent_rate_m_h"),
    ),
    SuuntoAppSensorDescription(
        key="last_stride",
        translation_key="last_stride",
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:shoe-print",
        value_fn=_section("workout", "stride_length_m"),
    ),
    # --- Training load ---
    SuuntoAppSensorDescription(
        key="fitness_ctl",
        translation_key="fitness_ctl",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arm-flex",
        value_fn=_section("load", "ctl"),
    ),
    SuuntoAppSensorDescription(
        key="fatigue_atl",
        translation_key="fatigue_atl",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging-low",
        value_fn=_section("load", "atl"),
    ),
    SuuntoAppSensorDescription(
        key="form_tsb",
        translation_key="form_tsb",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-bell-curve",
        value_fn=_section("load", "tsb"),
    ),
    SuuntoAppSensorDescription(
        key="acwr",
        translation_key="acwr",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:scale-balance",
        value_fn=_section("load", "acwr"),
    ),
    # --- Recovery baselines & readiness ---
    SuuntoAppSensorDescription(
        key="readiness",
        translation_key="readiness",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=_section("baseline", "readiness"),
    ),
    SuuntoAppSensorDescription(
        key="hrv_baseline",
        translation_key="hrv_baseline",
        native_unit_of_measurement=UNIT_MS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-flash",
        value_fn=_section("baseline", "hrv_baseline"),
    ),
    SuuntoAppSensorDescription(
        key="hrv_status",
        translation_key="hrv_status",
        device_class=SensorDeviceClass.ENUM,
        options=["low", "balanced", "high"],
        icon="mdi:heart-pulse",
        value_fn=_section("baseline", "hrv_status"),
    ),
    SuuntoAppSensorDescription(
        key="resting_hr",
        translation_key="resting_hr",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart",
        value_fn=_section("baseline", "resting_hr"),
    ),
    SuuntoAppSensorDescription(
        key="resting_hr_baseline",
        translation_key="resting_hr_baseline",
        native_unit_of_measurement=UNIT_BPM,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-outline",
        value_fn=_section("baseline", "resting_hr_baseline"),
    ),
    # --- Weekly volume ---
    SuuntoAppSensorDescription(
        key="weekly_distance",
        translation_key="weekly_distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=_section("weekly", "distance_km"),
    ),
    SuuntoAppSensorDescription(
        key="weekly_time",
        translation_key="weekly_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer",
        value_fn=_section("weekly", "time_hours"),
    ),
    # --- Counts ---
    SuuntoAppSensorDescription(
        key="workouts_7d",
        translation_key="workouts_7d",
        native_unit_of_measurement=UNIT_WORKOUTS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-week",
        value_fn=lambda d: d.get("count_7d"),
    ),
    SuuntoAppSensorDescription(
        key="workouts_30d",
        translation_key="workouts_30d",
        native_unit_of_measurement=UNIT_WORKOUTS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-month",
        value_fn=lambda d: d.get("count_30d"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuuntoAppConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Suunto App sensors from a config entry."""
    runtime = entry.runtime_data
    coordinators = {SOURCE_FAST: runtime.fast, SOURCE_DAILY: runtime.daily}
    async_add_entities(
        SuuntoAppSensor(coordinators[description.source], entry, description)
        for description in SENSORS
    )


class SuuntoAppSensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity
):
    """A single Suunto App metric."""

    entity_description: SuuntoAppSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry: SuuntoAppConfigEntry,
        description: SuuntoAppSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        if (precision := _DISPLAY_PRECISION.get(description.key)) is not None:
            self._attr_suggested_display_precision = precision
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Suunto",
            model="Suunto App (unofficial)",
        )

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
