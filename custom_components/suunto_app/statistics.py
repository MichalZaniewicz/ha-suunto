"""Hourly long-term statistics for the fast-changing Suunto metrics.

The 24/7 streams (HR/steps/energy every 10 min, recovery every 30 min) and the
dense workout HR samples are all *backdated* sub-hourly data. Home Assistant's
only supported way to ingest backdated data is long-term statistics, which are
hourly. So we bucket the samples into hourly statistics and import them
idempotently every cycle over a rolling window — a late watch->app sync then
fills past hours retroactively, and because statistics are persisted, history
accumulates over time even though each fetch only sees a couple of days.

Stat ids are external (``suunto_app:hr`` etc.), separate from the live sensors:
- HR / recovery balance / stress  -> mean+min+max
- steps / energy                  -> sum (cumulative; HA shows the per-hour delta)

The pure bucketing helpers below have no Home Assistant dependency (the recorder
imports happen inside the async push), so they can be unit-tested standalone.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import fmean
from typing import Any

_LOGGER = logging.getLogger(__name__)

# (suffix, display name, unit) for the mean-type metrics.
_MEAN_METRICS = (
    ("hr", "Suunto HR (hourly)", "bpm"),
    ("recovery_balance", "Suunto recovery balance (hourly)", "%"),
    ("stress", "Suunto stress state (hourly)", None),
)
# (suffix, display name, unit) for the sum-type metrics.
_SUM_METRICS = (
    ("steps", "Suunto steps (hourly)", "steps"),
    ("energy", "Suunto energy (hourly)", "kcal"),
)


def floor_hour(value: datetime) -> datetime:
    """Truncate a datetime to the start of its UTC hour (statistics are UTC)."""
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def hourly_mean(
    samples: list[tuple[datetime, float]],
) -> dict[datetime, tuple[float, float, float]]:
    """Bucket (timestamp, value) into per-hour (mean, min, max)."""
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for ts, value in samples:
        buckets[floor_hour(ts)].append(value)
    return {
        hour: (fmean(values), min(values), max(values))
        for hour, values in buckets.items()
        if values
    }


def hourly_sum(samples: list[tuple[datetime, float]]) -> dict[datetime, float]:
    """Bucket (timestamp, value) into a per-hour total."""
    buckets: dict[datetime, float] = defaultdict(float)
    for ts, value in samples:
        buckets[floor_hour(ts)] += value
    return dict(buckets)


async def async_update_statistics(
    hass: Any,
    *,
    hr: list[tuple[datetime, float]],
    steps: list[tuple[datetime, float]],
    energy: list[tuple[datetime, float]],
    balance: list[tuple[datetime, float]],
    stress: list[tuple[datetime, float]],
) -> None:
    """Compute hourly buckets and import them as external statistics.

    Idempotent: re-importing a window replaces the overlapping rows, so late
    syncs backfill cleanly. Raises nothing the caller must handle here — the
    coordinator wraps this so a statistics hiccup never breaks the data update.
    """
    # Imported lazily so the pure helpers above stay HA-free / testable.
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
        statistics_during_period,
    )

    from .const import DOMAIN

    mean_samples = {"hr": hr, "recovery_balance": balance, "stress": stress}
    for suffix, name, unit in _MEAN_METRICS:
        buckets = hourly_mean(mean_samples[suffix])
        if not buckets:
            continue
        metadata = StatisticMetaData(
            has_mean=True,
            has_sum=False,
            name=name,
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:{suffix}",
            unit_of_measurement=unit,
        )
        data = [
            StatisticData(start=hour, mean=mean, min=low, max=high)
            for hour, (mean, low, high) in sorted(buckets.items())
        ]
        async_add_external_statistics(hass, metadata, data)
        _LOGGER.debug("Imported %d hourly rows for %s:%s", len(data), DOMAIN, suffix)

    sum_samples = {"steps": steps, "energy": energy}
    for suffix, name, unit in _SUM_METRICS:
        buckets = hourly_sum(sum_samples[suffix])
        if not buckets:
            continue
        ordered = sorted(buckets.items())
        statistic_id = f"{DOMAIN}:{suffix}"
        window_start = ordered[0][0]

        # Continue the cumulative total from whatever is already stored just
        # before the window, so the per-hour deltas stay correct across reruns.
        base = 0.0
        prev_hour = window_start - timedelta(hours=1)
        rows = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            prev_hour,
            window_start,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        series = rows.get(statistic_id) if rows else None
        if series and series[-1].get("sum") is not None:
            base = float(series[-1]["sum"])

        running = base
        data = []
        for hour, total in ordered:
            running += total
            data.append(StatisticData(start=hour, state=total, sum=running))
        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=name,
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=unit,
        )
        async_add_external_statistics(hass, metadata, data)
        _LOGGER.debug("Imported %d hourly rows for %s:%s", len(data), DOMAIN, suffix)
