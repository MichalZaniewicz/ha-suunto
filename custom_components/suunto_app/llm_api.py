"""Suunto data as a tool set for Home Assistant's conversation agents.

Registers one LLM API ("Suunto") that a conversation agent (Assist with
Gemini, OpenAI, Anthropic, Ollama...) can turn on next to "Assist" in its
settings. The model then answers training questions - "how did I sleep?",
"can I train hard today?", "how far did I ride this month?", "what is my
best 5K?" - by calling these tools instead of reading a hundred sensors.

Every tool is read-only and answers from the data the coordinators already
hold, so a question never adds a request to Suunto.

Compatibility: Home Assistant's `llm` helper changed over time - tool
parameters moved from voluptuous to probatio schemas, tools gained
`ToolResult`/`ToolAnnotations`/`integration`, and `async_register_api`
only returns an unregister callback since 2025. Each difference is
detected at runtime instead of pinning one Home Assistant version.
"""

from __future__ import annotations

import importlib
import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util

from .const import (
    COMMUTE_TAG,
    DOMAIN,
    FOOT_ACTIVITY_IDS,
    SLEEP_LOOKBACK_DAYS,
    STANDARD_DISTANCES_M,
    WORKOUTS_LOOKBACK_DAYS,
)

_LOGGER = logging.getLogger(__name__)

LLM_API_ID = DOMAIN
LLM_API_NAME = "Suunto"
_DATA_UNREGISTER = f"{DOMAIN}_llm_api_unregister"

MAX_WORKOUTS = 50
_DEFAULT_WORKOUTS = 20
_DEFAULT_WORKOUT_DAYS = 7
_DEFAULT_SLEEP_NIGHTS = 7
_DEFAULT_WEEKS = 4
MAX_WEEKS = 12
MAX_LAPS = 40

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ---------------------------------------------------------------------------
# Version-tolerant building blocks
# ---------------------------------------------------------------------------


def _schema(fields: dict[str, tuple[type, str]]) -> Any:
    """An all-optional parameter schema in whatever schema library this
    Home Assistant's `llm.Tool.parameters` uses (voluptuous, or probatio
    on newer versions). Validators stay plain `str`/`int`, which both
    libraries understand and turn into OpenAPI types; ranges are clamped
    in the tools themselves."""
    schema_cls = type(llm.Tool.parameters)
    library = importlib.import_module(schema_cls.__module__.split(".")[0])
    return schema_cls(
        {
            library.Optional(name, description=description): validator
            for name, (validator, description) in fields.items()
        }
    )


def _result(data: dict[str, Any], *, error: bool = False) -> Any:
    tool_result = getattr(llm, "ToolResult", None)
    if tool_result is None:
        return data
    return tool_result(data=data, error=error)


_ACCOUNT_FIELD = (
    str,
    "The Suunto account name. Only needed when more than one account is set up; "
    "leave it out to get every account.",
)


# ---------------------------------------------------------------------------
# Small helpers (pure, no Home Assistant state)
# ---------------------------------------------------------------------------


def _dated(day: date | None) -> str | None:
    """"2026-10-14 Wed": the weekday spelled out next to every date.

    Found live in the Librus integration: given bare dates, the model works
    weekdays out by itself and gets them wrong."""
    return f"{day.isoformat()} {_WEEKDAYS[day.weekday()]}" if day else None


def _when(moment: datetime | None) -> str | None:
    """A timestamp in local time with its weekday: "2026-10-14 Wed 07:12"."""
    if moment is None:
        return None
    local = dt_util.as_local(moment)
    return f"{_dated(local.date())} {local.strftime('%H:%M')}"


def _clean(value: Any) -> Any:
    """JSON-ready copy: dates and times readable, floats rounded, and every
    unknown value dropped so the model is not told about fields with no data."""
    if isinstance(value, datetime):
        return _when(value)
    if isinstance(value, date):
        return _dated(value)
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        out = {key: _clean(item) for key, item in value.items()}
        return {key: item for key, item in out.items() if item not in (None, "", [], {})}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def _day_arg(args: dict[str, Any], key: str) -> date | None:
    value = str(args.get(key) or "").strip()
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _int_arg(args: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _local_day(moment: datetime | None) -> date | None:
    return dt_util.as_local(moment).date() if moment else None


def _km(meters: Any) -> float | None:
    return round(meters / 1000, 2) if meters else None


def _clock(seconds: float | None) -> str | None:
    """1534.2 -> "25:34", 4000 -> "1:06:40"."""
    if seconds is None:
        return None
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _tag_label(tag: str) -> str:
    """COMMUTE -> "Commute", IMPACT_LONG_AEROBIC_BASE -> "Long aerobic base"."""
    return tag.removeprefix("IMPACT_").replace("_", " ").capitalize()


def _pct(value: Any, goal: Any) -> int | None:
    return round(value / goal * 100) if value is not None and goal else None


# ---------------------------------------------------------------------------
# What each tool returns (pure: data dicts in, JSON-ready dict out)
# ---------------------------------------------------------------------------


def workout_summary(
    workout: dict[str, Any], decoupling: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One normalized workout (coordinator._normalize_workout) for the model."""
    foot = workout.get("activity_id") in FOOT_ACTIVITY_IDS
    tags = workout.get("tags") or []
    zones = {
        f"zone{n}": workout.get(f"zone{n}_min")
        for n in range(6)
        if workout.get(f"zone{n}_min")
    }
    return {
        "start": workout.get("start_time"),
        "activity": workout.get("activity"),
        "duration_min": workout.get("duration_minutes"),
        "distance_km": _km(workout.get("distance_meters")),
        "avg_speed_kmh": workout.get("avg_speed_kmh"),
        # Cycling's avg pace is not a pace anyone quotes.
        "avg_pace_min_km": workout.get("avg_pace_min_km") if foot else None,
        "avg_hr": workout.get("avg_hr_bpm") or None,
        "max_hr": workout.get("max_hr_bpm") or None,
        "avg_hr_pct_of_max": workout.get("pct_hrmax"),
        "hr_zone_minutes": zones,
        "tss": workout.get("tss"),
        "pte": workout.get("pte"),
        "epoc": workout.get("epoc"),
        "feeling_1_5": workout.get("feeling"),
        "kcal": workout.get("energy_kcal"),
        "ascent_m": workout.get("ascent_meters"),
        "descent_m": workout.get("descent_meters"),
        "max_altitude_m": workout.get("max_altitude_meters"),
        "steps": workout.get("step_count"),
        "cadence_spm": workout.get("cadence_spm"),
        "stride_length_m": workout.get("stride_length_m"),
        "recovery_time_h": workout.get("recovery_time_hours"),
        "commute": True if COMMUTE_TAG in tags else None,
        "suunto_tags": [_tag_label(tag) for tag in tags if tag != COMMUTE_TAG],
        "weather": {
            "temp_c": workout.get("weather_temp_c"),
            "condition": workout.get("weather_condition"),
            "wind_kmh": workout.get("weather_wind_kmh"),
            "humidity_pct": workout.get("weather_humidity_pct"),
        },
        "route_achievements": len(workout.get("achievements") or []) or None,
        "route_ranking": workout.get("route_ranking"),
        "aerobic_decoupling_pct": (decoupling or {}).get("decoupling_pct"),
        "manually_added": workout.get("is_manually_added") or None,
    }


def workouts_result(daily: dict[str, Any], today: date, args: dict[str, Any]) -> dict[str, Any]:
    window_start = today - timedelta(days=WORKOUTS_LOOKBACK_DAYS)
    end = _day_arg(args, "end_date") or today
    start = _day_arg(args, "start_date")
    if start is None:
        days = _int_arg(args, "days", _DEFAULT_WORKOUT_DAYS, 1, WORKOUTS_LOOKBACK_DAYS)
        start = end - timedelta(days=days - 1)
    if start > end:
        start, end = end, start
    wanted = str(args.get("activity") or "").casefold().strip()
    limit = _int_arg(args, "limit", _DEFAULT_WORKOUTS, 1, MAX_WORKOUTS)

    workouts = daily.get("workouts") or []
    matching = [
        w
        for w in workouts
        if (day := _local_day(w.get("start_time"))) is not None
        and start <= day <= end
        and (not wanted or wanted in str(w.get("activity") or "").casefold())
    ]
    decoupling = {
        d.get("start_time"): d
        for d in ((daily.get("decoupling") or {}).get("history") or [])
    }
    last = daily.get("workout") or {}
    items = []
    for w in matching[:limit]:
        item = workout_summary(w, decoupling.get(w.get("start_time")))
        # Lap splits are only fetched for the newest workout.
        if last.get("laps") and w.get("key") == last.get("key"):
            item["laps"] = last["laps"][:MAX_LAPS]
        items.append(item)

    out: dict[str, Any] = {
        "from": start,
        "to": end,
        "totals": {
            "workouts": len(matching),
            "distance_km": round(sum(w.get("distance_meters") or 0 for w in matching) / 1000, 1),
            "time_hours": round(sum(w.get("duration_minutes") or 0 for w in matching) / 60, 1),
            "kcal": sum(w.get("energy_kcal") or 0 for w in matching),
            "tss": round(sum(w.get("tss") or 0 for w in matching), 1),
            "ascent_m": sum(w.get("ascent_meters") or 0 for w in matching),
        },
        "workouts": items,
    }
    if len(matching) > len(items):
        out["note"] = f"Only the newest {len(items)} of {len(matching)} workouts are listed."
    if start < window_start:
        out["data_starts"] = window_start
        out["note_window"] = (
            f"Single workouts are only known for the last {WORKOUTS_LOOKBACK_DAYS} days; "
            "use suunto_get_totals or suunto_get_records for longer periods."
        )
    if wanted and not matching:
        out["activities_in_data"] = sorted(
            {w.get("activity") for w in workouts if w.get("activity")}
        )
    return out


def sleep_result(
    daily: dict[str, Any], fast: dict[str, Any], args: dict[str, Any]
) -> dict[str, Any]:
    sleep = daily.get("sleep") or {}
    baseline = daily.get("baseline") or {}
    nap = daily.get("nap") or {}
    count = _int_arg(args, "nights", _DEFAULT_SLEEP_NIGHTS, 1, SLEEP_LOOKBACK_DAYS)
    history = (daily.get("sleep_history") or [])[-count:]
    nights = [
        {
            "night_of": n.get("date"),
            "hours": n.get("duration_h"),
            "hrv_ms": n.get("hrv"),
            "resting_hr": n.get("rhr"),
        }
        for n in reversed(history)
    ]
    hours = [n["duration_h"] for n in history if n.get("duration_h")]
    hrv = [n["hrv"] for n in history if n.get("hrv")]
    rhr = [n["rhr"] for n in history if n.get("rhr")]
    goal = (fast.get("goals") or {}).get("sleep_hours")
    return {
        "last_night": {
            "night_of": sleep.get("night"),
            "fell_asleep": sleep.get("timestamp"),
            "woke_up": sleep.get("wake_time"),
            "hours": sleep.get("duration_hours"),
            "deep_min": sleep.get("deep_minutes"),
            "light_min": sleep.get("light_minutes"),
            "rem_min": sleep.get("rem_minutes"),
            "quality_pct": sleep.get("quality_pct"),
            "avg_hr": sleep.get("avg_hr_bpm"),
            "resting_hr": sleep.get("min_hr_bpm"),
            "hrv_ms": sleep.get("avg_hrv_ms"),
            "max_spo2_pct": sleep.get("spo2_pct"),
            "fragments": sleep.get("segments"),
            "not_synced_yet": True if sleep.get("stale") else None,
            "still_in_progress": True if sleep and not sleep.get("finished") else None,
        },
        "nap": {
            "day": nap.get("date"),
            "minutes": nap.get("duration_minutes"),
            "naps": nap.get("segments"),
        },
        "averages": {
            "nights": len(history),
            "hours": round(sum(hours) / len(hours), 2) if hours else None,
            "hrv_ms": round(sum(hrv) / len(hrv), 1) if hrv else None,
            "resting_hr": round(sum(rhr) / len(rhr), 1) if rhr else None,
            "nights_meeting_goal": sum(1 for h in hours if h >= goal) if goal else None,
        },
        "sleep_goal_hours": goal,
        "baselines": {
            "hrv_ms": baseline.get("hrv_baseline"),
            "hrv_status": baseline.get("hrv_status"),
            "resting_hr": baseline.get("resting_hr_baseline"),
        },
        "regularity": daily.get("sleep_regularity"),
        "social_jetlag": daily.get("social_jetlag"),
        "nights": nights,
    }


def readiness_result(daily: dict[str, Any], now: datetime) -> dict[str, Any]:
    baseline = daily.get("baseline") or {}
    load = daily.get("load") or {}
    recovery = daily.get("recovery") or {}
    sleep = daily.get("sleep") or {}
    last = daily.get("workout") or {}
    recovered_at = last.get("recovered_at")
    recovering = bool(recovered_at and recovered_at > now) if last else None
    return {
        "readiness_0_100": baseline.get("readiness"),
        "training_suggestion": load.get("suggestion"),
        "brief": daily.get("brief"),
        "hrv": {
            "last_night_ms": sleep.get("avg_hrv_ms"),
            "baseline_ms": baseline.get("hrv_baseline"),
            "status": baseline.get("hrv_status"),
        },
        "resting_hr": {
            "last_night": baseline.get("resting_hr"),
            "baseline": baseline.get("resting_hr_baseline"),
        },
        "unusual_recovery": baseline.get("unusual_recovery"),
        "sleep_hours": sleep.get("duration_hours"),
        "sleep_not_synced_yet": True if baseline.get("sleep_stale") else None,
        "recovery_balance_pct": recovery.get("balance_pct"),
        "recovery_measured": recovery.get("timestamp"),
        "form_tsb": load.get("tsb"),
        "acwr": load.get("acwr"),
        "last_workout": {
            "start": last.get("start_time"),
            "activity": last.get("activity"),
            "days_since": last.get("days_since"),
            "recovery_time_h": last.get("recovery_time_hours"),
            "recovered_at": recovered_at,
            "still_recovering": recovering,
            "hours_left": (
                round((recovered_at - now).total_seconds() / 3600, 1) if recovering else None
            ),
        },
    }


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def training_load_result(
    daily: dict[str, Any], fast: dict[str, Any], today: date, args: dict[str, Any]
) -> dict[str, Any]:
    load = daily.get("load") or {}
    forecast = daily.get("forecast") or {}
    weeks = _int_arg(args, "weeks", _DEFAULT_WEEKS, 1, MAX_WEEKS)
    first_week = _week_start(today) - timedelta(weeks=weeks - 1)
    by_week: dict[date, dict[str, Any]] = {
        first_week + timedelta(weeks=n): {
            "workouts": 0, "distance_km": 0.0, "time_hours": 0.0, "tss": 0.0
        }
        for n in range(weeks)
    }
    for w in daily.get("workouts") or []:
        day = _local_day(w.get("start_time"))
        if day is None or (bucket := by_week.get(_week_start(day))) is None:
            continue
        bucket["workouts"] += 1
        bucket["distance_km"] += (w.get("distance_meters") or 0) / 1000
        bucket["time_hours"] += (w.get("duration_minutes") or 0) / 60
        bucket["tss"] += w.get("tss") or 0
    week_rows = [
        {
            "week_from": start,
            "workouts": row["workouts"],
            "distance_km": round(row["distance_km"], 1),
            "time_hours": round(row["time_hours"], 1),
            "tss": round(row["tss"]),
            "in_progress": True if start == _week_start(today) else None,
        }
        for start, row in sorted(by_week.items(), reverse=True)
    ]
    goal = (fast.get("goals") or {}).get("weekly_training_hours")
    weekly = daily.get("weekly") or {}
    return {
        "fitness_ctl": load.get("ctl"),
        "fatigue_atl": load.get("atl"),
        "form_tsb": load.get("tsb"),
        "acwr": load.get("acwr"),
        "training_suggestion": load.get("suggestion"),
        "if_resting": {
            "tomorrow_tsb": forecast.get("tomorrow_tsb"),
            "peak_tsb": forecast.get("peak_tsb"),
            "peak_date": forecast.get("peak_date"),
            "days_to_peak": forecast.get("days_to_peak"),
        },
        "maintenance_tss_per_week": forecast.get("maintenance_tss_week"),
        "last_7_days": {
            **weekly,
            "workouts": daily.get("count_7d"),
            "training_goal_hours": goal,
            "goal_pct": _pct(weekly.get("time_hours"), goal),
        },
        "workouts_30d": daily.get("count_30d"),
        "current_streak_days": daily.get("current_streak"),
        "days_since_last_workout": (daily.get("workout") or {}).get("days_since"),
        "weeks": week_rows,
    }


def today_result(
    daily: dict[str, Any], fast: dict[str, Any], today: date
) -> dict[str, Any]:
    activity = fast.get("activity") or {}
    goals = fast.get("goals") or {}
    profile = fast.get("profile") or {}
    todays = [
        workout_summary(w)
        for w in daily.get("workouts") or []
        if _local_day(w.get("start_time")) == today
    ]
    return {
        "steps": activity.get("daily_steps"),
        "steps_goal": goals.get("daily_steps"),
        "steps_goal_pct": _pct(activity.get("daily_steps"), goals.get("daily_steps")),
        "active_kcal": activity.get("daily_energy_kcal"),
        "active_kcal_goal": goals.get("daily_energy_kcal"),
        "active_kcal_goal_pct": _pct(
            activity.get("daily_energy_kcal"), goals.get("daily_energy_kcal")
        ),
        "total_kcal_so_far": activity.get("daily_total_energy_kcal"),
        "bmr_kcal_per_day": profile.get("bmr_kcal"),
        "heart_rate": activity.get("current_hr_bpm"),
        "heart_rate_measured": activity.get("current_hr_at"),
        "yesterday": {
            "steps": activity.get("yesterday_steps"),
            "active_kcal": activity.get("yesterday_energy_kcal"),
        },
        "profile": {
            "weight_kg": profile.get("weight_kg"),
            "height_cm": profile.get("height_cm"),
            "age": profile.get("age"),
        },
        "workouts_today": todays,
    }


def totals_result(daily: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    period = str(args.get("period") or "").casefold().strip()
    commute = daily.get("commute") or {}
    stats = daily.get("stats") or {}
    sections = {
        "last_7_days": lambda: {
            **(daily.get("weekly") or {}),
            "workouts": daily.get("count_7d"),
        },
        "month": lambda: {
            **(daily.get("month_totals") or {}),
            "commutes": commute.get("month"),
        },
        "year": lambda: (
            {**daily["year_totals"], "commutes": commute.get("year")}
            if daily.get("year_totals")
            else {"note": "The year totals are not loaded yet (history scan pending)."}
        ),
        "lifetime": lambda: {
            key: value for key, value in stats.items() if key != "by_activity"
        }
        | {"by_activity": [
            {k: v for k, v in item.items() if k != "activity_id"}
            for item in stats.get("by_activity") or []
        ]},
        "gear": lambda: list((daily.get("gear") or {}).values()),
    }
    aliases = {"week": "last_7_days", "7d": "last_7_days", "all": "lifetime", "total": "lifetime"}
    period = aliases.get(period, period)
    if period in sections:
        return {period: sections[period]()}
    return {name: build() for name, build in sections.items()}


_RECORD_UNITS = {
    "fastest_pace": ("pace_min_km", lambda v: v),
    "biggest_climb": ("ascent_m", lambda v: v),
    "longest_workout": ("duration_min", lambda v: v),
    "farthest_workout": ("distance_km", lambda v: _km(v)),
    "hardest_workout": ("tss", lambda v: v),
}


def _records(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if not snapshot:
        return None
    out: dict[str, Any] = {"longest_streak_days": snapshot.get("longest_streak_days")}
    for field, (unit, convert) in _RECORD_UNITS.items():
        entry = snapshot.get(field)
        if entry:
            out[field] = {
                unit: convert(entry.get("value")),
                "activity": entry.get("activity"),
                "date": _local_day(entry.get("start_time")),
            }
    return out


def records_result(daily: dict[str, Any]) -> dict[str, Any]:
    efforts = {}
    for label, entry in (daily.get("best_efforts") or {}).items():
        seconds = entry.get("value")
        meters = STANDARD_DISTANCES_M.get(label)
        efforts[label] = {
            "time": _clock(seconds),
            "pace_min_km": round(seconds / 60 / (meters / 1000), 2) if seconds and meters else None,
            "activity": entry.get("activity"),
            "date": _local_day(entry.get("start_time")),
        }
    fitness = daily.get("fitness") or {}
    return {
        "all_time": _records(daily.get("records")),
        "this_year": _records(daily.get("records_year")),
        "this_month": _records(daily.get("records_month")),
        "best_efforts": efforts,
        "best_efforts_note": (
            "Fastest continuous run/walk efforts from GPS, tracked since this "
            "integration was installed, not from the whole history."
        ),
        "vo2max": {
            "vo2max": fitness.get("vo2max"),
            "estimated_vo2max": fitness.get("estimated_vo2max"),
            "fitness_age": fitness.get("fitness_age"),
            "measured": fitness.get("measured_at"),
            "from_activity": fitness.get("activity"),
        },
    }


def insights_result(daily: dict[str, Any], ai_result: dict[str, Any] | None) -> dict[str, Any]:
    insights = daily.get("insights") or {}
    decoupling = daily.get("decoupling") or {}
    ai = ai_result or {}
    return {
        "brief": daily.get("brief"),
        "personal_patterns": [
            {
                "finding": item.get("text"),
                "condition": item.get("condition"),
                "metric": item.get("metric"),
                "with": item.get("with"),
                "without": item.get("without"),
                "diff_pct": item.get("diff_pct"),
                "nights": (item.get("n_with") or 0) + (item.get("n_without") or 0),
                "good_for_you": item.get("favorable"),
            }
            for item in insights.get("insights") or []
        ],
        "patterns_based_on": {
            "nights": insights.get("nights"),
            "training_days": insights.get("training_days"),
        },
        "aerobic_decoupling": [
            {
                "start": d.get("start_time"),
                "activity": d.get("activity"),
                "decoupling_pct": d.get("decoupling_pct"),
                "first_half_hr": d.get("first_half_hr"),
                "second_half_hr": d.get("second_half_hr"),
            }
            for d in decoupling.get("history") or []
        ],
        "sleep_regularity": daily.get("sleep_regularity"),
        "social_jetlag": daily.get("social_jetlag"),
        "ai_daily_insight": {
            "for_date": ai.get("for_date"),
            "headline": ai.get("headline"),
            "status": ai.get("status"),
            "sections": {
                key: section.get("text")
                for key, section in (ai.get("sections") or {}).items()
                if isinstance(section, dict)
            },
            "advice": ai.get("advice"),
            "warning": ai.get("warning"),
        },
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _accounts(hass: HomeAssistant) -> list[tuple[str, Any]]:
    """(account name, runtime data) for every loaded entry with data."""
    found = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None or runtime.daily.data is None:
            continue
        found.append((entry.title, runtime))
    return found


class _SuuntoTool(llm.Tool):
    """Read-only, idempotent, no side effects outside Home Assistant."""

    integration = DOMAIN

    def __init__(self) -> None:
        annotations = getattr(llm, "ToolAnnotations", None)
        if annotations is not None:
            self.annotations = annotations(
                read_only=True, destructive=False, idempotent=True, open_world=False
            )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> Any:
        args = tool_input.tool_args or {}
        accounts = _accounts(hass)
        if not accounts:
            return _result({"error": "No Suunto data is available yet."}, error=True)
        wanted = str(args.get("account") or "").casefold().strip()
        if wanted:
            picked = [a for a in accounts if wanted in a[0].casefold()]
            if not picked:
                return _result(
                    {
                        "error": f"No Suunto account matching {wanted!r}.",
                        "accounts": [name for name, _ in accounts],
                    },
                    error=True,
                )
            accounts = picked
        now = dt_util.now()
        results = []
        for name, runtime in accounts:
            body = self.build(runtime, now, args)
            results.append({"account": name, **_clean(body)})
        if len(results) == 1:
            return _result({"today": _dated(now.date()), **results[0]})
        return _result({"today": _dated(now.date()), "accounts": results})

    def build(self, runtime: Any, now: datetime, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class WorkoutsTool(_SuuntoTool):
    name = "suunto_get_workouts"
    description = (
        "Workouts in a date range, newest first, with totals for the range: activity, "
        "duration, distance, speed or pace, heart rate and time in HR zones, TSS, peak "
        "training effect, calories, ascent, weather, Suunto's own tags (commute, long "
        "aerobic base...), and lap splits for the newest workout. Covers the last "
        f"{WORKOUTS_LOOKBACK_DAYS} days. Use it for 'what did I do this week', 'how was "
        "my last run', 'how many rides in September'."
    )
    parameters = _schema(
        {
            "start_date": (str, "First day, YYYY-MM-DD. Leave out to count `days` back."),
            "end_date": (str, "Last day, YYYY-MM-DD. Defaults to today."),
            "days": (int, f"Days back from end_date when start_date is not given, 1-{WORKOUTS_LOOKBACK_DAYS}. Defaults to {_DEFAULT_WORKOUT_DAYS}."),
            "activity": (str, "Only this sport, by its English Suunto name or part of it: Running, Cycling, Walking, Hiking, Trekking, Gym, Swimming..."),
            "limit": (int, f"How many workouts to list, 1-{MAX_WORKOUTS}. Defaults to {_DEFAULT_WORKOUTS}; the totals always cover the whole range."),
            "account": _ACCOUNT_FIELD,
        }
    )

    def build(self, runtime, now, args):
        return workouts_result(runtime.daily.data, now.date(), args)


class SleepTool(_SuuntoTool):
    name = "suunto_get_sleep"
    description = (
        "Sleep: last night in detail (when you fell asleep and woke up, hours, deep, "
        "light and REM minutes, quality, heart rate, HRV, SpO2), naps, the averages and "
        "night-by-night list for recent nights, the sleep goal, HRV and resting-HR "
        "baselines, sleep regularity and social jetlag. A night is named after the "
        "evening it started on. Use it for 'how did I sleep', 'average sleep this week'."
    )
    parameters = _schema(
        {
            "nights": (int, f"How many recent nights to list and average, 1-{SLEEP_LOOKBACK_DAYS}. Defaults to {_DEFAULT_SLEEP_NIGHTS}."),
            "account": _ACCOUNT_FIELD,
        }
    )

    def build(self, runtime, now, args):
        return sleep_result(runtime.daily.data, runtime.fast.data or {}, args)


class ReadinessTool(_SuuntoTool):
    name = "suunto_get_readiness"
    description = (
        "Readiness for today: readiness score 0-100, the training suggestion (rest, "
        "easy, moderate, hard), last night's HRV and resting heart rate against the "
        "baselines, the unusual-recovery flag, recovery balance, form (TSB), ACWR, and "
        "whether the recovery time of the last workout is still running. Use it for "
        "'can I train hard today', 'am I recovered', 'should I rest'."
    )
    parameters = _schema({"account": _ACCOUNT_FIELD})

    def build(self, runtime, now, args):
        return readiness_result(runtime.daily.data, now)


class TrainingLoadTool(_SuuntoTool):
    name = "suunto_get_training_load"
    description = (
        "Training load and form: fitness (CTL), fatigue (ATL), form (TSB), ACWR, what "
        "form would do with full rest, the last 7 days against the weekly training "
        "goal, the current streak, and a week-by-week table (Monday to Sunday) of "
        "workouts, distance, hours and TSS. Use it for 'what is my form', 'am I "
        "overtraining', 'compare my last weeks'."
    )
    parameters = _schema(
        {
            "weeks": (int, f"How many calendar weeks in the table, 1-{MAX_WEEKS}, the current week first. Defaults to {_DEFAULT_WEEKS}."),
            "account": _ACCOUNT_FIELD,
        }
    )

    def build(self, runtime, now, args):
        return training_load_result(runtime.daily.data, runtime.fast.data or {}, now.date(), args)


class TodayTool(_SuuntoTool):
    name = "suunto_get_today"
    description = (
        "Today so far: steps and active calories against the daily goals, total "
        "calories including the basal rate, the latest heart rate, yesterday's "
        "complete steps and calories, and today's workouts. Use it for 'how many steps "
        "do I have', 'did I hit my goal'."
    )
    parameters = _schema({"account": _ACCOUNT_FIELD})

    def build(self, runtime, now, args):
        return today_result(runtime.daily.data, runtime.fast.data or {}, now.date())


class TotalsTool(_SuuntoTool):
    name = "suunto_get_totals"
    description = (
        "Totals: last 7 days, this calendar month, this calendar year and lifetime "
        "(lifetime also per sport): workouts, distance, hours, calories, active days, "
        "the main sport, commutes with the fuel and money they saved, and the distance "
        "on each tracked piece of gear. Use it for 'how far did I ride this year', "
        "'how many km on my bike', 'how much did commuting save'."
    )
    parameters = _schema(
        {
            "period": (str, "Only one part: last_7_days, month, year, lifetime or gear. Leave out for all of them."),
            "account": _ACCOUNT_FIELD,
        }
    )

    def build(self, runtime, now, args):
        return totals_result(runtime.daily.data, args)


class RecordsTool(_SuuntoTool):
    name = "suunto_get_records"
    description = (
        "Personal records all-time, this year and this month (fastest pace, biggest "
        "climb, longest, farthest and hardest workout, longest streak), best efforts "
        "for 1K, 5K, 10K, half marathon and marathon, and VO2max and fitness age. Use "
        "it for 'what is my best 5K', 'my longest ride', 'what is my VO2max'."
    )
    parameters = _schema({"account": _ACCOUNT_FIELD})

    def build(self, runtime, now, args):
        return records_result(runtime.daily.data)


class InsightsTool(_SuuntoTool):
    name = "suunto_get_insights"
    description = (
        "What the data says about this athlete: personal patterns (for example how "
        "late workouts or training days change sleep, HRV or resting HR), aerobic "
        "decoupling of recent long workouts, sleep regularity, social jetlag, the "
        "one-line daily brief and today's AI daily insight if one was generated. Use it "
        "for 'what helps me sleep better', 'what works for me', 'any advice for today'."
    )
    parameters = _schema({"account": _ACCOUNT_FIELD})

    def build(self, runtime, now, args):
        ai = runtime.ai.result if getattr(runtime, "ai", None) is not None else None
        return insights_result(runtime.daily.data, ai)


TOOLS: tuple[type[_SuuntoTool], ...] = (
    ReadinessTool,
    SleepTool,
    WorkoutsTool,
    TrainingLoadTool,
    TodayTool,
    TotalsTool,
    RecordsTool,
    InsightsTool,
)


# ---------------------------------------------------------------------------
# The API and its registration
# ---------------------------------------------------------------------------


class SuuntoLLMAPI(llm.API):
    """The tool set a conversation agent turns on as "Suunto"."""

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        accounts = _accounts(self.hass)
        who = ", ".join(name for name, _ in accounts) or "no data loaded yet"
        prompt = (
            "Suunto is the user's sports watch. Use the suunto_* tools to answer questions "
            "about workouts, sleep, recovery, readiness, training load, daily activity, "
            f"totals and records for the Suunto account: {who}. Today is "
            f"{_dated(dt_util.now().date())}. Every date in tool results comes with its "
            "weekday; trust those weekdays instead of working them out. Readiness, the "
            "training suggestion and unusual recovery are heuristics, not official Suunto "
            "metrics, and nothing here is medical advice. The tools only read data "
            "already synced from the watch; nothing is changed or sent. Answer in the "
            "user's language, briefly, with the numbers that matter."
        )
        return llm.APIInstance(
            api=self,
            api_prompt=prompt,
            llm_context=llm_context,
            tools=[tool() for tool in TOOLS],
        )


@callback
def async_setup_llm_api(hass: HomeAssistant) -> None:
    """Register the API once per Home Assistant run (it looks up loaded
    entries on every call, so later entries need nothing more)."""
    if _DATA_UNREGISTER in hass.data:
        return
    try:
        unregister = llm.async_register_api(
            hass, SuuntoLLMAPI(hass=hass, id=LLM_API_ID, name=LLM_API_NAME)
        )
    except Exception as err:  # noqa: BLE001 - never block the integration over this
        _LOGGER.warning("Could not register the Suunto LLM API: %s", err)
        return
    # Home Assistant before 2025 returns None and cannot unregister; the
    # API then stays registered until restart and simply finds no data.
    hass.data[_DATA_UNREGISTER] = unregister


@callback
def async_unload_llm_api(hass: HomeAssistant) -> None:
    """Remove the API with the last entry, where Home Assistant allows it."""
    unregister = hass.data.get(_DATA_UNREGISTER)
    if callable(unregister):
        unregister()
        hass.data.pop(_DATA_UNREGISTER)
