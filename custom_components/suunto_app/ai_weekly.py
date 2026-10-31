"""Once-a-week AI summary of the training week, through Home Assistant's AI Task.

The weekly counterpart of ai_insight.py, through the same ``ai_task`` entity
and with the same answer shape (headline, status, four sections, advice,
warning), so the same card and report blueprint can show either. It looks at
the seven days ending on the chosen weekday: every workout, volume against
the week before and the 4-week average, the nights, readiness and the daily
steps and active calories (read back from the long-term statistics this
integration already imports). Nothing extra is fetched from Suunto.

When it runs:
- on the chosen weekday at the chosen hour (default Sunday 19:00);
- after a restart, if that moment passed less than CATCH_UP_HOURS ago and
  this week's summary is missing;
- on demand, from the "Generate weekly AI summary" button (the week ending
  today).
A failed automatic run is retried on the next daily coordinator update, at
most MAX_ATTEMPTS times per week. The result is kept in a Store.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .ai_insight import (
    SECTION_STATUSES,
    STATUSES,
    _LANGUAGE_NAMES,
    _compact,
    _round,
    async_generate_data,
    explain_error,
    labels_for,
    parse_result,
    patterns_context,
    resolve_language,
)
from .const import DOMAIN, EVENT_AI_WEEKLY, WEEKDAYS
from .coordinator import SuuntoDailyCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
MAX_ATTEMPTS = 3
# A missed run (Home Assistant was off at the hour) is made up for this long
# afterwards; later, the next week's summary is the next one.
CATCH_UP_HOURS = 24

SECTIONS: dict[str, str] = {
    "training": "Training: every workout of the week by sport, the volume (workouts, hours,"
    " distance, ascent, TSS) against last week and the 4-week average, the intensity"
    " (PTE, heart rate), the load at the end of the week (CTL/ATL/TSB/ACWR), new best"
    " efforts, and the weekly training goal.",
    "sleep": "Sleep: the week's nights (duration, HRV, resting heart rate) against last week"
    " and the baselines, the shortest and longest night, consistency (sleep regularity,"
    " social jetlag) and the sleep goal.",
    "recovery": "Health and recovery: readiness day by day, the HRV and resting heart rate"
    " trend over the week, unusual_recovery, how recovery followed the hard days.",
    "activity": "Daily activity: steps and active calories day by day against the daily goals,"
    " the most and least active day, the current streak.",
}


def _structure() -> dict[str, dict[str, Any]]:
    """Schema of the answer, in the format the ai_task.generate_data action takes."""
    fields: dict[str, dict[str, Any]] = {
        "headline": {
            "description": "One sentence, at most 120 characters: the key message of the week.",
            "required": True,
            "selector": {"text": {}},
        },
        "status": {
            "description": "Overall call for the week; rest = the coming week should be easy.",
            "required": True,
            "selector": {"select": {"options": list(STATUSES)}},
        },
    }
    for key, covers in SECTIONS.items():
        fields[key] = {
            "description": (
                "120-180 words in exactly two paragraphs separated by a blank line:"
                f" first what the week shows, then what it means and why. {covers}"
                " Empty string if there is no data for it."
            ),
            "required": True,
            "selector": {"text": {"multiline": True}},
        }
        fields[f"{key}_status"] = {
            "description": f"How the {key} section looks this week.",
            "required": True,
            "selector": {"select": {"options": list(SECTION_STATUSES)}},
        }
    fields["advice"] = {
        "description": "2-4 short, concrete points for the coming week.",
        "required": True,
        "selector": {"text": {"multiple": True}},
    }
    fields["warning"] = {
        "description": "Only if something needs attention; otherwise an empty string.",
        "required": False,
        "selector": {"text": {}},
    }
    return fields


STRUCTURE = _structure()

_INSTRUCTIONS = """You are an endurance coach and a sleep and recovery analyst.
Below is a JSON snapshot of one athlete's week from a Suunto watch: {week_start} to {week_end}.
Write a thorough review of the week, split into sections, and what to do in the coming week.

Rules:
- Write every field in {language}.
- Base every statement on the numbers given. Never invent data; ignore what is missing.
- Every date carries its weekday; use those weekdays, do not work them out yourself.
- Compare the week with last_week and the 4-week average, not with population norms.
- Judge HRV and resting heart rate against the athlete's own baselines.
- Be specific: name the numbers and the days that support a point.
- Keep each section to its own topic; do not repeat a point in two sections.
- LENGTH IS A HARD REQUIREMENT: every section (training, sleep, recovery, activity) is
  120-180 words in exactly two paragraphs, separated by a blank line.
  Paragraph 1: what the week shows, with the numbers and the trend.
  Paragraph 2: what it means - cause and effect, how it ties to the other sections, and
  what to change or keep next week.
- Use plain hyphens; never long dashes.
- Write numbers the way {language} does (for example a decimal comma where that is the norm).
- advice: for the coming week, concrete (which days, how hard, how long).
- warning: only for something that genuinely needs attention (for example HRV suppressed
  together with an elevated resting heart rate for several nights, ACWR above 1.5, or a
  sharp jump in volume); otherwise leave it empty.
- You are not a doctor: no diagnoses, no medical advice.

Field notes: tsb = form (positive is fresh, negative is fatigued), ctl = fitness,
atl = fatigue, acwr = acute:chronic workload ratio (about 0.8-1.3 is the safe zone),
readiness = 0-100 heuristic score, pte = Suunto peak training effect (1-5),
tss = training stress score, suggestion = a rule-based hint from TSB and ACWR,
days[].steps and days[].active_kcal include workouts; the last day may be partial when
the week ends today (days[].partial), do not judge goals on it.
goals = targets the athlete set in the Suunto app (daily_energy_kcal is active calories,
weekly_training_hours the weekly training time), best_efforts_this_week = new personal
bests set this week, forecast = what form would do under full rest.
patterns.personal_correlations with metric efficiency = metres per heartbeat in one sport.
{extra}
Data:
{data}"""

# The report title and the advice heading for the weekly version, per
# language; the rest of the labels come from the daily insight's.
_TITLES: dict[str, tuple[str, str]] = {
    "en": ("AI weekly summary", "Next week"),
    "pl": ("Podsumowanie tygodnia AI", "Na kolejny tydzień"),
    "de": ("KI-Wochenrückblick", "Nächste Woche"),
    "fr": ("Bilan IA de la semaine", "Semaine prochaine"),
    "es": ("Resumen semanal con IA", "Próxima semana"),
    "it": ("Riepilogo settimanale IA", "Prossima settimana"),
    "nl": ("AI-weekoverzicht", "Volgende week"),
    "pt": ("Resumo semanal com IA", "Próxima semana"),
}


def weekly_labels(language: str | None) -> dict[str, Any]:
    """Report labels for the weekly summary in ``language``."""
    code = (language or "en").split("-")[0].lower()
    title, advice = _TITLES.get(code, _TITLES["en"])
    return {**labels_for(code), "title": title, "advice": advice}


def _day_label(day: date) -> str:
    return f"{day.isoformat()} {day.strftime('%a')}"


def _totals(workouts: list[dict[str, Any]]) -> dict[str, Any]:
    minutes = sum(w.get("duration_minutes") or 0 for w in workouts)
    meters = sum(w.get("distance_meters") or 0 for w in workouts)
    return _compact(
        {
            "workouts": len(workouts),
            "hours": round(minutes / 60, 1),
            "distance_km": round(meters / 1000, 1),
            "ascent_m": round(sum(w.get("ascent_meters") or 0 for w in workouts)),
            "tss": round(sum(w.get("tss") or 0 for w in workouts)),
            "kcal": round(sum(w.get("energy_kcal") or 0 for w in workouts)),
        }
    )


def _mean(values: list[float | None], digits: int = 1) -> float | None:
    known = [v for v in values if v is not None]
    return round(sum(known) / len(known), digits) if known else None


def build_weekly_context(
    daily: dict[str, Any],
    fast: dict[str, Any] | None,
    week_end: date,
    per_day: dict[date, dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    """Compact, JSON-ready snapshot of the week ending on ``week_end``."""
    fast = fast or {}
    week_start = week_end - timedelta(days=6)
    prev_start = week_start - timedelta(days=7)
    month_start = week_start - timedelta(days=28)

    def local_day(workout: dict[str, Any]) -> date | None:
        start = workout.get("start_time")
        return dt_util.as_local(start).date() if start else None

    workouts = daily.get("workouts") or []
    this_week = [w for w in workouts if (d := local_day(w)) and week_start <= d <= week_end]
    last_week = [w for w in workouts if (d := local_day(w)) and prev_start <= d < week_start]
    four_weeks = [w for w in workouts if (d := local_day(w)) and month_start <= d < week_start]
    four_week_avg = {
        key: round(value / 4, 1)
        for key, value in _totals(four_weeks).items()
        if isinstance(value, (int, float))
    }

    by_sport: dict[str, list[dict[str, Any]]] = {}
    for workout in this_week:
        by_sport.setdefault(workout.get("activity") or "Other", []).append(workout)

    nights_all = daily.get("sleep_history") or []
    nights = [n for n in nights_all if n.get("date") and week_start <= n["date"] <= week_end]
    prev_nights = [n for n in nights_all if n.get("date") and prev_start <= n["date"] < week_start]

    def night_avg(items: list[dict[str, Any]]) -> dict[str, Any]:
        return _compact(
            {
                "nights": len(items) or None,
                "hours": _mean([n.get("duration_h") for n in items]),
                "hrv_ms": _mean([n.get("hrv") for n in items]),
                "resting_hr": _mean([n.get("rhr") for n in items], 0),
            }
        )

    baseline = daily.get("baseline") or {}
    load = daily.get("load") or {}
    forecast = daily.get("forecast") or {}
    activity = fast.get("activity") or {}

    days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        stats = dict(per_day.get(day) or {})
        if day == today:
            # Today's statistics lag the live sensors by up to an hour.
            stats["steps"] = activity.get("daily_steps", stats.get("steps"))
            stats["active_kcal"] = activity.get("daily_energy_kcal", stats.get("active_kcal"))
        days.append(
            _compact(
                {
                    "date": _day_label(day),
                    "steps": stats.get("steps"),
                    "active_kcal": stats.get("active_kcal"),
                    "readiness": _round(stats.get("readiness"), 0),
                    "workouts": sum(1 for w in this_week if local_day(w) == day) or None,
                    "partial": True if day == today else None,
                }
            )
        )

    best = [
        _compact(
            {
                "distance": label,
                "seconds": _round(effort.get("value"), 0),
                "activity": effort.get("activity"),
                "date": _day_label(dt_util.as_local(effort["start_time"]).date()),
            }
        )
        for label, effort in (daily.get("best_efforts") or {}).items()
        if isinstance(effort, dict)
        and isinstance(effort.get("start_time"), datetime)
        and week_start <= dt_util.as_local(effort["start_time"]).date() <= week_end
    ]

    return _compact(
        {
            "week": _totals(this_week),
            "last_week": _totals(last_week),
            "four_week_average": four_week_avg,
            "by_sport": {
                sport: _totals(items) for sport, items in sorted(by_sport.items())
            },
            "workouts": [
                _compact(
                    {
                        "date": f"{_day_label(local_day(w))}"
                        f" {dt_util.as_local(w['start_time']).strftime('%H:%M')}",
                        "activity": w.get("activity"),
                        "duration_min": _round(w.get("duration_minutes"), 0),
                        "distance_km": round(w["distance_meters"] / 1000, 1)
                        if w.get("distance_meters")
                        else None,
                        "avg_hr": w.get("avg_hr_bpm"),
                        "max_hr": w.get("max_hr_bpm"),
                        "tss": _round(w.get("tss")),
                        "pte": _round(w.get("pte")),
                        "ascent_m": _round(w.get("ascent_meters"), 0),
                        "feeling_1_5": w.get("feeling"),
                        "tags": w.get("tags"),
                    }
                )
                for w in sorted(this_week, key=lambda w: w["start_time"])
            ],
            "best_efforts_this_week": best,
            "nights": [
                _compact(
                    {
                        "night": _day_label(n["date"]),
                        "hours": _round(n.get("duration_h")),
                        "hrv_ms": _round(n.get("hrv")),
                        "resting_hr": _round(n.get("rhr"), 0),
                    }
                )
                for n in nights
            ],
            "sleep_week": night_avg(nights),
            "sleep_last_week": night_avg(prev_nights),
            "baselines": _compact(
                {
                    "hrv_baseline_ms": _round(baseline.get("hrv_baseline")),
                    "hrv_status_now": baseline.get("hrv_status"),
                    "resting_hr_baseline": _round(baseline.get("resting_hr_baseline")),
                    "unusual_recovery_now": baseline.get("unusual_recovery"),
                }
            ),
            "days": days,
            "load_now": _compact(
                {
                    "ctl": _round(load.get("ctl")),
                    "atl": _round(load.get("atl")),
                    "tsb": _round(load.get("tsb")),
                    "acwr": _round(load.get("acwr"), 2),
                    "suggestion": load.get("suggestion"),
                }
            ),
            "forecast": _compact(
                {
                    "peak_tsb": forecast.get("peak_tsb"),
                    "days_to_peak": forecast.get("days_to_peak"),
                    "maintenance_tss_week": forecast.get("maintenance_tss_week"),
                }
            ),
            "current_streak_days": daily.get("current_streak"),
            "patterns": patterns_context(daily),
            "goals": fast.get("goals"),
        }
    )


def build_instructions(
    context: dict[str, Any], week_end: date, language: str, extra: str | None
) -> str:
    """The full prompt for the week ending on ``week_end``."""
    code = language.split("-")[0].lower()
    extra = (extra or "").strip()
    return _INSTRUCTIONS.format(
        week_start=_day_label(week_end - timedelta(days=6)),
        week_end=_day_label(week_end),
        language=_LANGUAGE_NAMES.get(code, f"the language with code '{code}'"),
        extra=f"\nThe athlete's own notes (take them into account):\n{extra}\n" if extra else "",
        data=json.dumps(context, ensure_ascii=False, default=str, separators=(",", ":")),
    )


def _row_day(row: dict[str, Any]) -> date | None:
    """Local date of a statistics row (``start`` is a timestamp or a datetime)."""
    start = row.get("start")
    if isinstance(start, (int, float)):
        start = datetime.fromtimestamp(start, tz=timezone.utc)
    return dt_util.as_local(start).date() if isinstance(start, datetime) else None


class SuuntoAiWeekly:
    """Schedules, runs and stores the weekly AI summary for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        daily: SuuntoDailyCoordinator,
        fast: DataUpdateCoordinator[dict[str, Any]],
        ai_task_entity: str,
        extra_context: str | None,
        weekday: str,
        hour: int,
        language: str | None,
    ) -> None:
        """Initialize; nothing runs until async_start."""
        self.hass = hass
        self._entry = entry
        self._daily = daily
        self._fast = fast
        self.ai_task_entity = ai_task_entity
        self._extra = extra_context
        self.weekday = weekday if weekday in WEEKDAYS else "sun"
        self.hour = hour
        self._language = language
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.ai_weekly.{entry.entry_id}"
        )
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        # (week end, automatic runs for it), for the retry cap.
        self._attempts: tuple[str, int] = ("", 0)
        self.result: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.running = False
        # The "Automatic weekly AI summary" switch; the button still works.
        self.enabled = True

    async def async_start(self) -> None:
        """Load the stored state and hook up the triggers."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            result = stored.get("result")
            self.result = result if isinstance(result, dict) else None
            self.enabled = stored.get("enabled", True) is not False
        self._unsubs += [
            self._daily.async_add_listener(self._on_daily_update),
            async_track_time_change(
                self.hass, self._on_time, hour=self.hour, minute=0, second=0
            ),
        ]
        if self._due():
            self._run_in_background()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Switch automatic runs on or off."""
        if enabled == self.enabled:
            return
        self.enabled = enabled
        await self._async_save()
        self._notify()

    async def _async_save(self) -> None:
        await self._store.async_save({"enabled": self.enabled, "result": self.result})

    @callback
    def async_stop(self) -> None:
        """Remove every trigger (entry unload)."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        """Call ``update`` whenever the result or the running flag changes."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    def _scheduled(self) -> datetime:
        """The latest run time (weekday at the hour) at or before now."""
        now = dt_util.now()
        target = now.replace(hour=self.hour, minute=0, second=0, microsecond=0)
        target -= timedelta(days=(now.weekday() - WEEKDAYS.index(self.weekday)) % 7)
        if target > now:
            target -= timedelta(days=7)
        return target

    def _due(self) -> bool:
        """Whether this week's automatic summary should run now."""
        scheduled = self._scheduled()
        if dt_util.now() - scheduled > timedelta(hours=CATCH_UP_HOURS):
            return False
        # ISO dates compare as strings; a summary pressed for a later day
        # (the button) covers this week too.
        done = (self.result or {}).get("for_date") or ""
        return done < scheduled.date().isoformat()

    @callback
    def _on_time(self, _now: datetime) -> None:
        if self._due():
            self._run_in_background()

    @callback
    def _on_daily_update(self) -> None:
        # A failed run is retried here (capped per week).
        if not self.running and self._due():
            self._run_in_background()

    @callback
    def _run_in_background(self) -> None:
        """Start an AUTOMATIC run; skipped while the switch is off."""
        if not self.enabled:
            return
        week_end = self._scheduled().date().isoformat()
        day, count = self._attempts
        count = count if day == week_end else 0
        if count >= MAX_ATTEMPTS:
            return
        self._attempts = (week_end, count + 1)
        self._entry.async_create_background_task(
            self.hass, self._async_generate_quietly(), f"{DOMAIN} weekly AI summary"
        )

    async def _async_generate_quietly(self) -> None:
        if not self.enabled:
            return
        try:
            await self.async_generate(self._scheduled().date(), manual=False)
        except HomeAssistantError:
            pass  # already logged and kept in last_error

    async def async_generate(self, week_end: date | None = None, manual: bool = True) -> None:
        """Run the summary now (the week ending today unless given).

        Raises HomeAssistantError on failure; a press while a run is going is
        refused, an automatic run queues behind it.
        """
        if self._lock.locked() and manual:
            raise HomeAssistantError("The weekly AI summary is already being generated")
        async with self._lock:
            self.running = True
            self._notify()
            try:
                self.result = await self._async_call(week_end or dt_util.now().date())
                self.last_error = None
                await self._async_save()
                self._fire_event(manual)
            except Exception as err:  # noqa: BLE001 - any provider error ends up here
                self.last_error = explain_error(err)
                _LOGGER.warning("Weekly AI summary failed: %s", self.last_error)
                raise HomeAssistantError(
                    f"Weekly AI summary failed: {self.last_error}"
                ) from err
            finally:
                self.running = False
                self._notify()

    @callback
    def _fire_event(self, manual: bool) -> None:
        result = self.result or {}
        self._daily.async_fire_event(
            EVENT_AI_WEEKLY,
            {
                "entry_id": self._entry.entry_id,
                "manual": manual,
                **{
                    key: result.get(key)
                    for key in (
                        "headline", "status", "sections", "advice", "warning",
                        "summary", "for_date", "week_start",
                    )
                },
                "labels": weekly_labels(resolve_language(self.hass, self._language)),
            },
        )

    async def _async_per_day(self, start: date, end: date) -> dict[date, dict[str, Any]]:
        """Steps, active kcal and readiness per local day from the statistics.

        Best-effort: without the recorder (or before it has data) the days
        simply carry no numbers.
        """
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )

        ids = {f"{DOMAIN}:steps", f"{DOMAIN}:energy", f"{DOMAIN}:readiness"}
        begin = dt_util.start_of_local_day(start)
        finish = dt_util.start_of_local_day(end + timedelta(days=1))
        try:
            rows = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                begin,
                finish,
                ids,
                "day",
                None,
                {"change", "mean"},
            )
        except Exception:  # noqa: BLE001 - enrichment only
            _LOGGER.debug("Weekly statistics lookup failed", exc_info=True)
            return {}
        out: dict[date, dict[str, Any]] = {}
        for stat_id, field, kind in (
            (f"{DOMAIN}:steps", "steps", "change"),
            (f"{DOMAIN}:energy", "active_kcal", "change"),
            (f"{DOMAIN}:readiness", "readiness", "mean"),
        ):
            for row in (rows or {}).get(stat_id) or []:
                day = _row_day(row)
                value = row.get(kind)
                if day is None or value is None:
                    continue
                out.setdefault(day, {})[field] = round(value)
        return out

    async def _async_call(self, week_end: date) -> dict[str, Any]:
        daily = self._daily.data
        if not daily:
            raise HomeAssistantError("No Suunto data yet")
        today = dt_util.now().date()
        week_start = week_end - timedelta(days=6)
        per_day = await self._async_per_day(week_start, week_end)
        context = build_weekly_context(daily, self._fast.data, week_end, per_day, today)
        if not context.get("workouts") and not context.get("nights"):
            raise HomeAssistantError("No workouts and no sleep from the watch this week")
        data = await async_generate_data(
            self.hass,
            self.ai_task_entity,
            "Suunto weekly summary",
            build_instructions(
                context, week_end, resolve_language(self.hass, self._language), self._extra
            ),
            STRUCTURE,
        )
        parsed = parse_result(data)
        if not parsed["headline"] and not parsed["sections"] and not parsed["summary"]:
            raise HomeAssistantError("The AI returned an empty answer")
        return {
            **parsed,
            "for_date": week_end.isoformat(),
            "week_start": week_start.isoformat(),
            "generated_at": dt_util.utcnow().isoformat(),
            "ai_task_entity": self.ai_task_entity,
        }
