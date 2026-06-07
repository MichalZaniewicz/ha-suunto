"""Derived training/recovery metrics computed from Suunto data.

Pure functions (no Home Assistant or network dependencies) so they can be unit
tested directly. All inputs are plain Python values extracted by the coordinator.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

# Exponential-decay time constants (days) for the impulse-response model.
CTL_TIME_CONSTANT = 42  # Chronic Training Load == "Fitness"
ATL_TIME_CONSTANT = 7  # Acute Training Load == "Fatigue"

DEFAULT_SLEEP_TARGET_HOURS = 8.0


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def training_load(
    daily_tss: dict[date, float], today: date, window_days: int = 90
) -> dict[str, float | None]:
    """Compute CTL (fitness), ATL (fatigue) and TSB (form) from a daily TSS map.

    CTL/ATL are exponentially weighted moving averages of daily TSS. TSB (form)
    is yesterday's CTL minus yesterday's ATL — positive means fresh, negative
    means fatigued. Values are seeded from 0 at the start of the window, so the
    first weeks are an underestimate; with a 90-day window they stabilise.
    """
    if not daily_tss:
        return {"ctl": None, "atl": None, "tsb": None}

    # Seed CTL/ATL with the window's mean daily TSS (a steady-state prior) rather
    # than 0, so a long-standing constant load isn't underestimated during the
    # model's ramp-up.
    total = sum(daily_tss.get(today - timedelta(days=i), 0.0) for i in range(window_days + 1))
    seed = total / (window_days + 1)

    ctl = atl = seed
    ctl_prev = atl_prev = seed
    day = today - timedelta(days=window_days)
    while day <= today:
        tss = daily_tss.get(day, 0.0)
        ctl_prev, atl_prev = ctl, atl
        ctl += (tss - ctl) / CTL_TIME_CONSTANT
        atl += (tss - atl) / ATL_TIME_CONSTANT
        day += timedelta(days=1)

    return {
        "ctl": round(ctl, 1),
        "atl": round(atl, 1),
        "tsb": round(ctl_prev - atl_prev, 1),
    }


def acwr(daily_tss: dict[date, float], today: date) -> float | None:
    """Acute:chronic workload ratio = (7-day load) / (mean weekly 28-day load).

    The commonly cited "sweet spot" is roughly 0.8–1.3; well above ~1.5 is
    associated with elevated injury risk.
    """
    acute = sum(daily_tss.get(today - timedelta(days=i), 0.0) for i in range(7))
    chronic_total = sum(
        daily_tss.get(today - timedelta(days=i), 0.0) for i in range(28)
    )
    chronic = chronic_total / 4.0
    if chronic <= 0:
        return None
    return round(acute / chronic, 2)


def baseline_stats(values: list[float]) -> tuple[float | None, float | None]:
    """Return (mean, population standard deviation) of the values, or (None, None)."""
    clean = [v for v in values if v is not None]
    if not clean:
        return None, None
    mean = sum(clean) / len(clean)
    if len(clean) < 2:
        return round(mean, 1), None
    var = sum((v - mean) ** 2 for v in clean) / len(clean)
    return round(mean, 1), round(math.sqrt(var), 1)


def hrv_status(
    latest: float | None, mean: float | None, sd: float | None
) -> str | None:
    """Classify the latest HRV against its baseline as low/balanced/high."""
    if latest is None or mean is None:
        return None
    if sd:
        if latest < mean - sd:
            return "low"
        if latest > mean + sd:
            return "high"
    return "balanced"


def readiness(
    *,
    latest_hrv: float | None,
    baseline_hrv: float | None,
    latest_rhr: float | None,
    baseline_rhr: float | None,
    sleep_hours: float | None,
    balance_pct: float | None,
    sleep_target_hours: float = DEFAULT_SLEEP_TARGET_HOURS,
) -> int | None:
    """A 0–100 readiness score blending sleep, HRV, resting HR and recovery balance.

    This is a heuristic (the component weights are our choice, not an official
    Suunto metric): HRV above baseline, resting HR below baseline, more sleep and
    a higher recovery balance all push the score up.
    """
    parts: list[tuple[float, float]] = []  # (score, weight)

    if sleep_hours is not None:
        parts.append((_clamp(sleep_hours / sleep_target_hours * 100), 0.25))
    if latest_hrv and baseline_hrv:
        parts.append((_clamp(50 + (latest_hrv - baseline_hrv) / baseline_hrv * 100), 0.30))
    if latest_rhr and baseline_rhr:
        parts.append((_clamp(50 + (baseline_rhr - latest_rhr) / baseline_rhr * 100), 0.20))
    if balance_pct is not None:
        parts.append((_clamp(balance_pct), 0.25))

    if not parts:
        return None
    total_weight = sum(w for _, w in parts)
    return round(sum(score * w for score, w in parts) / total_weight)
