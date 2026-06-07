"""Data update coordinator for the Suunto App (unofficial) integration."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import metrics
from . import statistics as suunto_stats
from .api import SportsTrackerClient, SuuntoAppAuthError, SuuntoAppError
from .const import (
    ACTIVITY_LOOKBACK_DAYS,
    FOOT_ACTIVITY_IDS,
    RECOVERY_LOOKBACK_DAYS,
    SLEEP_LOOKBACK_DAYS,
    WORKOUT_CACHE_GRACE_HOURS,
    WORKOUTS_LOOKBACK_DAYS,
    activity_name,
)

_LOGGER = logging.getLogger(__name__)


def _hz_to_bpm(value: Any) -> int | None:
    """Convert a heart rate in Hz (beats/second) to integer bpm."""
    num = _as_float(value)
    if num is None or num <= 0:
        return None
    return round(num * 60)


def _frac_to_pct(value: Any) -> float | None:
    """Convert a 0..1 fraction to a 0..100 percentage."""
    num = _as_float(value)
    if num is None or num <= 0:
        return None
    return round(num * 100, 1)


def _sec_to_hours(value: Any) -> float | None:
    num = _as_float(value)
    return round(num / 3600, 2) if num else None


def _sec_to_min(value: Any) -> int | None:
    num = _as_float(value)
    return round(num / 60) if num else None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    num = _as_float(value)
    return round(num) if num is not None else None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    return dt_util.parse_datetime(str(value))


def _latest(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the record with the newest parseable timestamp."""
    best: dict[str, Any] | None = None
    best_ts: datetime | None = None
    for rec in records:
        ts = _parse_ts(rec.get("timestamp"))
        if ts is None:
            continue
        if best_ts is None or ts > best_ts:
            best, best_ts = rec, ts
    return best


def _sum_present(items: list[float | None]) -> float | None:
    """Sum values, returning None when none are present (vs 0 for a real zero)."""
    present = [v for v in items if v is not None]
    return sum(present) if present else None


def _weighted_avg(pairs: list[tuple[float | None, float]]) -> float | None:
    """Duration-weighted average of (value, weight), ignoring missing/zero values."""
    num = den = 0.0
    for value, weight in pairs:
        if value is None or value <= 0 or weight <= 0:
            continue
        num += value * weight
        den += weight
    return num / den if den else None


def _group_sleep_nights(
    records: list[dict[str, Any]],
) -> dict[Any, list[tuple[datetime, dict[str, Any]]]]:
    """Group sleep segments into nights via a noon-to-noon key.

    Suunto returns a night in fragments (one per wake interruption); a noon-to-
    noon key makes an evening start and its post-midnight continuation land in
    the same night, so they can be summed (the app shows the sum).
    """
    segments = [r for r in records if not (r.get("entryData") or {}).get("isNap")]
    segments = segments or records
    groups: dict[Any, list[tuple[datetime, dict[str, Any]]]] = {}
    for rec in segments:
        ts = _parse_ts(rec.get("timestamp"))
        if ts is None:
            continue
        night_key = (dt_util.as_local(ts) - timedelta(hours=12)).date()
        groups.setdefault(night_key, []).append((ts, rec.get("entryData") or {}))
    return groups


def _aggregate_night(
    night: list[tuple[datetime, dict[str, Any]]],
) -> dict[str, Any]:
    """Sum/duration-weight one night's segments into a single summary."""
    night = sorted(night, key=lambda x: x[0])
    eds = [ed for _, ed in night]
    weights = [(_as_float(ed.get("duration")) or 0.0) for ed in eds]
    return {
        "timestamp": night[0][0],
        "duration_hours": _sec_to_hours(
            _sum_present([_as_float(ed.get("duration")) for ed in eds])
        ),
        "deep_minutes": _min_from_sum(eds, "deepSleepDuration"),
        "light_minutes": _min_from_sum(eds, "lightSleepDuration"),
        "rem_minutes": _min_from_sum(eds, "remSleepDuration"),
        "avg_hr_bpm": _hz_to_bpm(
            _weighted_avg([(_as_float(ed.get("hrAvg")), w) for ed, w in zip(eds, weights)])
        ),
        "min_hr_bpm": _hz_to_bpm(
            min(
                (v for ed in eds if (v := _as_float(ed.get("hrMin"))) and v > 0),
                default=None,
            )
        ),
        "quality_pct": _frac_to_pct(
            _weighted_avg([(_as_float(ed.get("quality")), w) for ed, w in zip(eds, weights)])
        ),
        "spo2_pct": _frac_to_pct(
            max((_as_float(ed.get("maxSpo2")) or 0 for ed in eds), default=0)
        ),
        "avg_hrv_ms": _round_avg(
            _weighted_avg([(_as_float(ed.get("avgHrv")), w) for ed, w in zip(eds, weights)])
        ),
        "segments": len(night),
    }


def _normalize_sleep(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the latest night's aggregated sleep summary."""
    groups = _group_sleep_nights(records)
    if not groups:
        return None
    return _aggregate_night(groups[max(groups)])


def _sleep_series(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-night HRV / resting-HR / duration series (oldest first) for baselines."""
    groups = _group_sleep_nights(records)
    series: list[dict[str, Any]] = []
    for key in sorted(groups):
        agg = _aggregate_night(groups[key])
        series.append(
            {
                "date": key,
                "hrv": agg["avg_hrv_ms"],
                "rhr": agg["min_hr_bpm"],
                "duration_h": agg["duration_hours"],
            }
        )
    return series


def _min_from_sum(eds: list[dict[str, Any]], field: str) -> int | None:
    """Sum a per-segment seconds field across a night and convert to minutes."""
    total = _sum_present([_as_float(ed.get(field)) for ed in eds])
    return _sec_to_min(total)


def _round_avg(value: float | None) -> float | None:
    return round(value, 1) if value else None


def _normalize_recovery(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the latest recovery record (fields: balance, stressState)."""
    record = _latest(records)
    if not record:
        return None
    ed = record.get("entryData") or {}
    return {
        "timestamp": _parse_ts(record.get("timestamp")),
        # Confirmed live fields: balance (0..1 fraction) and stressState (enum int).
        "balance_pct": _frac_to_pct(ed.get("balance")),
        "stress_state": _as_int(ed.get("stressState")),
    }


def _normalize_activity(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Sum today's per-10-min steps/energy and take the most recent heart rate."""
    if not records:
        return None
    today = dt_util.now().date()
    steps = 0.0
    energy = 0.0
    saw_today = False
    for rec in records:
        ts = _parse_ts(rec.get("timestamp"))
        if ts is None or dt_util.as_local(ts).date() != today:
            continue
        saw_today = True
        ed = rec.get("entryData") or {}
        # Confirmed live per-interval fields: stepCount + energyConsumption.
        steps += _as_float(ed.get("stepCount")) or 0.0
        energy += _as_float(ed.get("energyConsumption")) or 0.0

    latest = _latest(records)
    latest_ed = (latest or {}).get("entryData") or {}
    current_hr = _hz_to_bpm(latest_ed.get("hr"))

    # energyConsumption appears to be in calories; /1000 -> kcal (best-effort).
    return {
        "daily_steps": _as_int(steps) if saw_today else None,
        "daily_energy_kcal": _as_int(energy / 1000) if saw_today else None,
        "current_hr_bpm": current_hr,
    }


def _centi_to_min(value: Any) -> float | None:
    """Convert centiseconds (timeInZone unit) to minutes.

    A present zero stays 0.0 (you spent 0 min in that HR zone) — only a truly
    absent value is None, so unused zones show "0 min" instead of "unknown".
    """
    num = _as_float(value)
    return round(num / 6000, 1) if num is not None else None


def _normalize_workout(workout: dict[str, Any]) -> dict[str, Any]:
    activity_id = _as_int(workout.get("activityId"))
    start = workout.get("startTime")
    start_dt = (
        datetime.fromtimestamp(int(start) / 1000, tz=timezone.utc) if start else None
    )
    hrdata = workout.get("hrdata") or {}
    cadence = workout.get("cadence") or {}
    tss = workout.get("tss") or {}
    avg_speed = _as_float(workout.get("avgSpeed"))  # m/s
    avg_hr = _as_float(hrdata.get("workoutAvgHR"))
    user_max_hr = _as_float(hrdata.get("userMaxHR"))
    distance = _as_float(workout.get("totalDistance"))
    energy = _as_float(workout.get("energyConsumption"))
    total_time = _as_float(workout.get("totalTime"))
    ascent = _as_float(workout.get("totalAscent"))
    cad_avg = _as_float(cadence.get("avg"))
    return {
        "key": workout.get("key"),
        "activity_id": activity_id,
        "activity": activity_name(activity_id),
        "start_time": start_dt,
        "duration_minutes": _sec_to_min(workout.get("totalTime")),
        "distance_meters": _as_int(workout.get("totalDistance")),
        "ascent_meters": _as_int(workout.get("totalAscent")),
        "step_count": _as_int(workout.get("stepCount")),
        "recovery_time_hours": (
            round(total_recovery / 3600, 1)
            if (total_recovery := _as_float(workout.get("recoveryTime"))) is not None
            else None
        ),
        # Heart rate (already in bpm).
        "avg_hr_bpm": _as_int(hrdata.get("workoutAvgHR")),
        "max_hr_bpm": _as_int(hrdata.get("workoutMaxHR")),
        # Speed (m/s -> km/h) and pace (already decimal min/km).
        "avg_speed_kmh": round(avg_speed * 3.6, 1) if avg_speed else None,
        "avg_pace_min_km": _as_float(workout.get("avgPace")) or None,
        # Cadence: object {avg, max}; expose the average (rpm/spm).
        "cadence": _as_int(cadence.get("avg")),
        # Training Stress Score.
        "tss": (
            round(_as_float(tss.get("trainingStressScore")), 1)
            if tss.get("trainingStressScore")
            else None
        ),
        # Time in each HR zone (centiseconds -> minutes).
        "zone1_min": _centi_to_min(workout.get("timeInZone1")),
        "zone2_min": _centi_to_min(workout.get("timeInZone2")),
        "zone3_min": _centi_to_min(workout.get("timeInZone3")),
        "zone4_min": _centi_to_min(workout.get("timeInZone4")),
        "zone5_min": _centi_to_min(workout.get("timeInZone5")),
        # --- Derived ---
        "pct_hrmax": (
            round(avg_hr / user_max_hr * 100)
            if avg_hr and user_max_hr
            else None
        ),
        "cal_per_km": (
            round(energy / (distance / 1000)) if energy and distance else None
        ),
        "ascent_rate_m_h": (
            round(ascent / (total_time / 3600)) if ascent and total_time else None
        ),
        # Stride length (distance per cadence cycle) — only meaningful for
        # foot-based activities; for cycling etc. cadence is pedal RPM, not steps.
        "stride_length_m": (
            round(avg_speed / (cad_avg / 60), 2)
            if avg_speed and cad_avg and activity_id in FOOT_ACTIVITY_IDS
            else None
        ),
    }


def _normalize_stats(stats: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten the lifetime workout-stats payload."""
    if not stats:
        return None
    distance = _as_float(stats.get("totalDistanceSum"))
    time_s = _as_float(stats.get("totalTimeSum"))
    return {
        "distance_km": round(distance / 1000, 1) if distance else None,
        "time_hours": round(time_s / 3600, 1) if time_s else None,
        "energy_kcal": _as_int(stats.get("totalEnergyConsumptionSum")),
        "workouts": _as_int(stats.get("totalNumberOfWorkoutsSum")),
        "active_days": _as_int(stats.get("totalDays")),
    }


def _since_ms(now: datetime, days: int) -> int:
    """Epoch-milliseconds cutoff ``days`` before ``now``."""
    return int((now - timedelta(days=days)).timestamp() * 1000)


class SuuntoActivityCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fast coordinator: live-ish activity (current HR, daily steps/energy)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SportsTrackerClient,
        scan_interval: timedelta,
    ) -> None:
        """Initialize the live coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Suunto live",
            update_interval=scan_interval,
            config_entry=entry,
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch only the 24/7 activity stream (cheap, changes minute-to-minute)."""
        since = _since_ms(dt_util.utcnow(), ACTIVITY_LOOKBACK_DAYS)
        try:
            activity = await self._client.async_get_wellness("activity", since)
        except SuuntoAppAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SuuntoAppError as err:
            raise UpdateFailed(str(err)) from err
        return {"activity": _normalize_activity(activity)}


class SuuntoDailyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Slow coordinator: sleep, recovery, workouts, stats + derived metrics."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SportsTrackerClient,
        scan_interval: timedelta,
    ) -> None:
        """Initialize the history coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Suunto daily",
            update_interval=scan_interval,
            config_entry=entry,
        )
        self._client = client
        # key -> (workout, last_seen): smooths the API's eventually-consistent
        # workouts list so a transiently-missing workout doesn't drop sensors.
        self._workout_cache: dict[str, tuple[dict[str, Any], datetime]] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch history streams + workouts and build the daily-metrics payload."""
        now = dt_util.utcnow()

        # Fetch the independent endpoints concurrently. return_exceptions keeps a
        # single flaky stream from blanking everything: a failed stream falls
        # back to empty while the others still update.
        labels = ("sleep", "recovery", "workouts")
        results = await asyncio.gather(
            self._client.async_get_wellness("sleep", _since_ms(now, SLEEP_LOOKBACK_DAYS)),
            self._client.async_get_wellness(
                "recovery", _since_ms(now, RECOVERY_LOOKBACK_DAYS)
            ),
            self._client.async_get_workouts(_since_ms(now, WORKOUTS_LOOKBACK_DAYS)),
            return_exceptions=True,
        )

        data: dict[str, list] = {}
        errors = 0
        for label, result in zip(labels, results):
            if isinstance(result, SuuntoAppAuthError):
                raise ConfigEntryAuthFailed(str(result)) from result
            if isinstance(result, SuuntoAppError):
                _LOGGER.warning("Suunto '%s' fetch failed: %s", label, result)
                data[label] = []
                errors += 1
            elif isinstance(result, BaseException):
                raise result  # unexpected error — don't swallow it
            else:
                data[label] = result

        # Only fail when every endpoint errored (empty-but-successful is valid).
        if errors == len(labels):
            raise UpdateFailed("All Suunto endpoints failed this cycle")

        sleep, recovery, workouts = data["sleep"], data["recovery"], data["workouts"]

        # Smooth the eventually-consistent workouts list: re-add any workout that
        # was present recently but is transiently missing this cycle, so every
        # workout-derived sensor stays stable through an upstream hiccup.
        workouts = self._merge_workouts(workouts, now)

        # Lifetime stats — username comes from a workout record so a cached
        # session (no fresh login) still works.
        stats: dict[str, Any] = {}
        username = workouts[0].get("username") if workouts else None
        if username:
            try:
                stats = await self._client.async_get_stats(username)
            except SuuntoAppError as err:
                _LOGGER.debug("Stats fetch failed (non-fatal): %s", err)

        # Counts are filtered explicitly: the fetch window is 90 days (needed for
        # the training-load model), so len(workouts) is NOT a 30-day count.
        now_ms = int(now.timestamp() * 1000)
        week_ago = now_ms - 7 * 86_400_000
        month_ago = now_ms - 30 * 86_400_000
        recent = [w for w in workouts if (w.get("startTime") or 0) >= week_ago]
        count_7d = len(recent)
        count_30d = sum(1 for w in workouts if (w.get("startTime") or 0) >= month_ago)

        sleep_norm = _normalize_sleep(sleep)
        recovery_norm = _normalize_recovery(recovery)

        # --- Training load (CTL/ATL/TSB + ACWR) from per-workout TSS history ---
        today = dt_util.now().date()
        daily_tss: dict[Any, float] = defaultdict(float)
        for w in workouts:
            score = _as_float((w.get("tss") or {}).get("trainingStressScore"))
            start = w.get("startTime")
            if score and start:
                day = dt_util.as_local(
                    datetime.fromtimestamp(int(start) / 1000, tz=timezone.utc)
                ).date()
                daily_tss[day] += score
        load = metrics.training_load(daily_tss, today)
        load["acwr"] = metrics.acwr(daily_tss, today)

        # --- HRV / resting-HR baselines + readiness from the sleep series ---
        nights = _sleep_series(sleep)
        hrv_mean, hrv_sd = metrics.baseline_stats([n["hrv"] for n in nights])
        rhr_mean, _ = metrics.baseline_stats([n["rhr"] for n in nights])
        latest_hrv = sleep_norm["avg_hrv_ms"] if sleep_norm else None
        latest_rhr = sleep_norm["min_hr_bpm"] if sleep_norm else None
        baseline = {
            "hrv_baseline": hrv_mean,
            "hrv_status": metrics.hrv_status(latest_hrv, hrv_mean, hrv_sd),
            "resting_hr": latest_rhr,
            "resting_hr_baseline": rhr_mean,
            "readiness": metrics.readiness(
                latest_hrv=latest_hrv,
                baseline_hrv=hrv_mean,
                latest_rhr=latest_rhr,
                baseline_rhr=rhr_mean,
                sleep_hours=sleep_norm["duration_hours"] if sleep_norm else None,
                balance_pct=recovery_norm["balance_pct"] if recovery_norm else None,
            ),
        }

        # --- Weekly volume ---
        weekly = {
            "distance_km": round(
                sum(_as_float(w.get("totalDistance")) or 0 for w in recent) / 1000, 1
            ),
            "time_hours": round(
                sum(_as_float(w.get("totalTime")) or 0 for w in recent) / 3600, 1
            ),
        }

        # Hourly long-term statistics for the fast-changing metrics. Auxiliary:
        # an import hiccup must never blank the normal data update (but a real
        # auth failure still surfaces for the reauth flow).
        try:
            await self._async_update_statistics(workouts, recovery)
        except SuuntoAppAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception:  # noqa: BLE001 - statistics are best-effort
            _LOGGER.exception("Hourly statistics import failed (non-fatal)")

        return {
            "sleep": sleep_norm,
            "recovery": recovery_norm,
            "workout": _normalize_workout(workouts[0]) if workouts else None,
            "stats": _normalize_stats(stats),
            "load": load,
            "baseline": baseline,
            "weekly": weekly,
            "count_7d": count_7d,
            "count_30d": count_30d,
        }

    def _merge_workouts(
        self, fresh: list[dict[str, Any]], now: datetime
    ) -> list[dict[str, Any]]:
        """Union the fresh workouts with recently-seen ones (keyed by ``key``).

        Refreshes the cache from this cycle's fetch, then re-adds any cached
        workout that is missing now but was seen within the grace window and is
        still inside the fetch window. Expired entries are dropped, so a
        genuinely deleted workout disappears once it has been absent past grace.
        """
        cutoff = now - timedelta(hours=WORKOUT_CACHE_GRACE_HOURS)
        window_start_ms = _since_ms(now, WORKOUTS_LOOKBACK_DAYS)

        fresh_keys: set[str] = set()
        for workout in fresh:
            key = workout.get("key")
            if key:
                fresh_keys.add(key)
                self._workout_cache[key] = (workout, now)

        merged = list(fresh)
        for key, (workout, seen) in list(self._workout_cache.items()):
            if seen < cutoff:
                del self._workout_cache[key]
                continue
            if key in fresh_keys:
                continue
            if (workout.get("startTime") or 0) >= window_start_ms:
                merged.append(workout)
                _LOGGER.debug("Re-added transiently-missing workout %s", key)

        merged.sort(key=lambda w: w.get("startTime") or 0, reverse=True)
        return merged

    async def _async_update_statistics(
        self, workouts: list[dict[str, Any]], recovery: list[dict[str, Any]]
    ) -> None:
        """Build hourly statistic samples from activity/recovery/workouts.

        HR merges the 10-min 24/7 stream with the ~25 s workout heartrates (more
        samples just sharpen the hourly mean/min/max). Steps/energy come from the
        24/7 stream ONLY — the workout totals are already counted there, so
        adding them would double-count the sum.
        """
        now = dt_util.utcnow()
        since_ms = _since_ms(now, ACTIVITY_LOOKBACK_DAYS)
        activity = await self._client.async_get_wellness("activity", since_ms)

        hr: list[tuple[datetime, float]] = []
        steps: list[tuple[datetime, float]] = []
        energy: list[tuple[datetime, float]] = []
        for rec in activity:
            ts = _parse_ts(rec.get("timestamp"))
            if ts is None:
                continue
            ed = rec.get("entryData") or {}
            hz = _as_float(ed.get("hr"))
            if hz and hz > 0:
                hr.append((ts, hz * 60))  # Hz -> bpm
            step_count = _as_float(ed.get("stepCount"))
            if step_count is not None:
                steps.append((ts, step_count))
            cal = _as_float(ed.get("energyConsumption"))
            if cal is not None:
                energy.append((ts, cal / 1000))  # cal -> kcal

        balance: list[tuple[datetime, float]] = []
        stress: list[tuple[datetime, float]] = []
        for rec in recovery:
            ts = _parse_ts(rec.get("timestamp"))
            if ts is None:
                continue
            ed = rec.get("entryData") or {}
            bal = _as_float(ed.get("balance"))
            if bal is not None:
                balance.append((ts, bal * 100))  # 0..1 -> %
            stress_state = _as_float(ed.get("stressState"))
            if stress_state is not None:
                stress.append((ts, stress_state))

        # Dense workout HR samples for workouts overlapping the activity window.
        recent_keys = [
            key
            for w in workouts
            if (w.get("startTime") or 0) >= since_ms and (key := w.get("key"))
        ]
        if recent_keys:
            results = await asyncio.gather(
                *(self._client.async_get_workout_data(k) for k in recent_keys),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, SuuntoAppAuthError):
                    raise result
                if isinstance(result, BaseException):
                    _LOGGER.debug("Workout data fetch failed (skipped): %s", result)
                    continue
                for point in result.get("heartrates") or []:
                    epoch_ms = point.get("d")
                    bpm = _as_float(point.get("hr"))
                    if epoch_ms and bpm and bpm > 0:
                        when = datetime.fromtimestamp(
                            int(epoch_ms) / 1000, tz=timezone.utc
                        )
                        hr.append((when, bpm))

        await suunto_stats.async_update_statistics(
            self.hass,
            hr=hr,
            steps=steps,
            energy=energy,
            balance=balance,
            stress=stress,
        )
