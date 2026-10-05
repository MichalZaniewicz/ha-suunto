"""Once-a-day AI analysis of the watch data, through Home Assistant's AI Task.

No API key lives in this integration. The user sets up any AI provider
(Google Gemini, OpenAI, Anthropic, a local Ollama...) as a normal Home
Assistant integration and picks its ``ai_task`` entity in our options; we
only call the ``ai_task.generate_data`` action with a compact JSON snapshot of
metrics the coordinators have already computed. Nothing extra is fetched from
Suunto for this.

When it runs:
- after the morning sync: ``suunto_app_woke_up`` marks a new, finished night
  (a mid-night fragment does not count), and the
  analysis starts once that coordinator update has finished (the event fires
  mid-update, before the new data is published);
- at a fallback hour, if nothing was generated today yet (no sync, or a
  restart that swallowed the event);
- on demand, from the "Generate AI insight" button.
At most one automatic run per day, plus one more if the first one had to go
without last night's sleep and the night arrives later. The result is kept in
a Store, so a restart never pays for the same analysis twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, EVENT_AI_INSIGHT, EVENT_WOKE_UP

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Workouts and nights older than this are left out of the snapshot: enough to
# see a trend, small enough to stay around 2-4k tokens.
CONTEXT_DAYS = 14
# A sensor state is capped at 255 characters by Home Assistant.
MAX_STATE_LENGTH = 255
# A failed automatic run (provider down, quota) is retried on the next daily
# coordinator update, at most this many times a day.
MAX_ATTEMPTS_PER_DAY = 3
# The model's overall call for today; a card can color itself by it.
STATUSES = ("good", "ok", "caution", "rest")

_LANGUAGE_NAMES = {
    "en": "English",
    "pl": "Polish",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
}

# Per-section call, so a card can color each section on its own.
SECTION_STATUSES = ("good", "ok", "caution")
# Sections of the review, in display order: key -> what it covers. Each one
# comes back as `<key>` (text) and `<key>_status`, and is exposed on the
# sensor as ``sections[key] = {"status", "text"}`` for the cards.
SECTIONS: dict[str, str] = {
    "sleep": "Sleep: last night's duration, deep/REM and quality, and how the last"
    " nights compare (consistency, the sleep goal).",
    "recovery": "Health and recovery: HRV and resting heart rate against the baselines,"
    " readiness, recovery balance, stress, unusual_recovery.",
    "training": "Training: the last 14 days of workouts, load (CTL/ATL/TSB/ACWR),"
    " weekly volume against the training goal, and the form forecast.",
    "activity": "Daily activity: YESTERDAY's complete steps and active calories against"
    " the daily goals (today_so_far is only a partial day), the current streak, days"
    " since the last workout.",
}


def _structure() -> dict[str, dict[str, Any]]:
    """Schema of the answer, in the format the ai_task.generate_data action takes."""
    fields: dict[str, dict[str, Any]] = {
        "headline": {
            "description": "One sentence, at most 120 characters: the key message for today.",
            "required": True,
            "selector": {"text": {}},
        },
        "status": {
            "description": "Overall call for today.",
            "required": True,
            "selector": {"select": {"options": list(STATUSES)}},
        },
    }
    for key, covers in SECTIONS.items():
        fields[key] = {
            "description": (
                f"120-180 words in exactly two paragraphs separated by a blank line:"
                f" first what the data shows, then what it means and why. {covers}"
                " Empty string if there is no data for it."
            ),
            "required": True,
            "selector": {"text": {"multiline": True}},
        }
        fields[f"{key}_status"] = {
            "description": f"How the {key} section looks.",
            "required": True,
            "selector": {"select": {"options": list(SECTION_STATUSES)}},
        }
    fields["advice"] = {
        "description": "2-4 short, concrete recommendations for today and the next days.",
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
Below is a JSON snapshot of one athlete's data from a Suunto watch, as of {today}.
Write a thorough daily review of it, split into sections.

Rules:
- Write every field in {language}.
- Base every statement on the numbers given. Never invent data; ignore what is missing.
- Judge HRV and resting heart rate against the athlete's own baselines, not population norms.
- Look at trends over the last nights and workouts, not only at last night.
- Be specific: name the numbers that support a point.
- Keep each section to its own topic; do not repeat a point in two sections.
- LENGTH IS A HARD REQUIREMENT: every section (sleep, recovery, training, activity) is
  120-180 words in exactly two paragraphs, separated by a blank line. One or two
  sentences per section is too short and is a failed answer.
  Paragraph 1: what the data shows - last night or today, then the trend over the last
  nights and workouts, against the baselines and goals, with the numbers.
  Paragraph 2: what it means - cause and effect, how it ties to the other sections, and
  what to watch next.
- Use plain hyphens; never long dashes.
- Write numbers the way {language} does (for example a decimal comma where that is the norm).
- warning: only for something that genuinely needs attention (for example HRV suppressed
  together with an elevated resting heart rate for several nights, or ACWR above 1.5);
  otherwise leave it empty.
- You are not a doctor: no diagnoses, no medical advice.

Field notes: tsb = form (positive is fresh, negative is fatigued), ctl = fitness,
atl = fatigue, acwr = acute:chronic workload ratio (about 0.8-1.3 is the safe zone),
readiness = 0-100 heuristic score, pte = Suunto peak training effect (1-5),
tss = training stress score, suggestion = a rule-based hint from TSB and ACWR,
sleep.stale = true means last night has not synced yet (the night shown is older),
sleep.in_progress = true means only part of last night has synced so far (do not judge its length),
forecast = what form would do under full rest, goals = targets the athlete set in the Suunto app,
yesterday = the last complete day, today_so_far = the day until as_of (partial, do not judge
goals on it). Steps and active_kcal are the whole day INCLUDING workouts, not activity on top
of them; of_which_workouts_kcal is what that day's workouts burned, usually most of active_kcal,
so a high active_kcal on a workout day is the workout, not extra activity outside training.
goals.daily_energy_kcal is an active-calorie target.
{extra}
Data:
{data}"""


# Labels for a report built from the insight (the suunto_app_ai_insight event
# carries them), in the HA language: blueprints have no access to the
# integration's translations.
_LABELS: dict[str, dict[str, Any]] = {
    "en": {
        "title": "AI insight", "advice": "Advice", "warning": "Warning",
        "statuses": {"good": "Good", "ok": "OK", "caution": "Caution", "rest": "Rest"},
        "sections": {"sleep": "Sleep", "recovery": "Health and recovery",
                     "training": "Training", "activity": "Daily activity"},
    },
    "pl": {
        "title": "Analiza AI", "advice": "Rady", "warning": "Uwaga",
        "statuses": {"good": "Dobrze", "ok": "OK", "caution": "Uwaga", "rest": "Odpoczynek"},
        "sections": {"sleep": "Sen", "recovery": "Zdrowie i regeneracja",
                     "training": "Treningi", "activity": "Aktywność dzienna"},
    },
    "de": {
        "title": "KI-Analyse", "advice": "Tipps", "warning": "Achtung",
        "statuses": {"good": "Gut", "ok": "OK", "caution": "Vorsicht", "rest": "Ruhe"},
        "sections": {"sleep": "Schlaf", "recovery": "Gesundheit und Erholung",
                     "training": "Training", "activity": "Tagesaktivität"},
    },
    "fr": {
        "title": "Analyse IA", "advice": "Conseils", "warning": "Attention",
        "statuses": {"good": "Bien", "ok": "OK", "caution": "Prudence", "rest": "Repos"},
        "sections": {"sleep": "Sommeil", "recovery": "Santé et récupération",
                     "training": "Entraînement", "activity": "Activité du jour"},
    },
    "es": {
        "title": "Análisis con IA", "advice": "Consejos", "warning": "Atención",
        "statuses": {"good": "Bien", "ok": "OK", "caution": "Precaución", "rest": "Descanso"},
        "sections": {"sleep": "Sueño", "recovery": "Salud y recuperación",
                     "training": "Entrenamiento", "activity": "Actividad diaria"},
    },
    "it": {
        "title": "Analisi IA", "advice": "Consigli", "warning": "Attenzione",
        "statuses": {"good": "Bene", "ok": "OK", "caution": "Cautela", "rest": "Riposo"},
        "sections": {"sleep": "Sonno", "recovery": "Salute e recupero",
                     "training": "Allenamento", "activity": "Attività giornaliera"},
    },
    "nl": {
        "title": "AI-analyse", "advice": "Adviezen", "warning": "Let op",
        "statuses": {"good": "Goed", "ok": "OK", "caution": "Opgepast", "rest": "Rust"},
        "sections": {"sleep": "Slaap", "recovery": "Gezondheid en herstel",
                     "training": "Training", "activity": "Dagelijkse activiteit"},
    },
    "pt": {
        "title": "Análise com IA", "advice": "Conselhos", "warning": "Atenção",
        "statuses": {"good": "Bom", "ok": "OK", "caution": "Cuidado", "rest": "Descanso"},
        "sections": {"sleep": "Sono", "recovery": "Saúde e recuperação",
                     "training": "Treino", "activity": "Atividade diária"},
    },
}


def labels_for(language: str | None) -> dict[str, Any]:
    """Report labels in ``language``, English when it is not one of ours."""
    return _LABELS.get((language or "en").split("-")[0].lower(), _LABELS["en"])


def _is_schema_error(err: BaseException) -> bool:
    """Whether a service call was rejected by its schema, before running.

    Checked by class name on purpose: current cores raise voluptuous'
    ``Invalid``, the newest ones probatio's, and this must work on both.
    """
    return isinstance(err, ServiceValidationError) or any(
        cls.__name__ == "Invalid" for cls in type(err).__mro__
    )


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    """Drop unknown values so the model is not told about fields with no data."""
    return {key: value for key, value in values.items() if value not in (None, [], {})}


def _round(value: Any, digits: int = 1) -> Any:
    return round(value, digits) if isinstance(value, float) else value


def build_context(
    daily: dict[str, Any], fast: dict[str, Any] | None, today: date
) -> dict[str, Any]:
    """Compact, JSON-ready snapshot of the already-computed metrics."""
    fast = fast or {}
    sleep = daily.get("sleep") or {}
    baseline = daily.get("baseline") or {}
    load = daily.get("load") or {}
    forecast = daily.get("forecast") or {}
    recovery = daily.get("recovery") or {}
    fitness = daily.get("fitness") or {}
    activity = fast.get("activity") or {}
    cutoff = today - timedelta(days=CONTEXT_DAYS)

    workouts = []
    # Workout calories per local day: the day totals below include them, and
    # spelling that out stops the model reading them as activity on top.
    workout_kcal: dict[date, int] = {}
    for workout in daily.get("workouts") or []:
        start = workout.get("start_time")
        if not start or dt_util.as_local(start).date() < cutoff:
            continue
        day = dt_util.as_local(start).date()
        workout_kcal[day] = workout_kcal.get(day, 0) + (workout.get("energy_kcal") or 0)
        distance = workout.get("distance_meters")
        workouts.append(
            _compact(
                {
                    "date": dt_util.as_local(start).strftime("%Y-%m-%d %H:%M"),
                    "activity": workout.get("activity"),
                    "duration_min": _round(workout.get("duration_minutes"), 0),
                    "distance_km": round(distance / 1000, 1) if distance else None,
                    "avg_hr": workout.get("avg_hr_bpm"),
                    "max_hr": workout.get("max_hr_bpm"),
                    "tss": _round(workout.get("tss")),
                    "pte": _round(workout.get("pte")),
                    "ascent_m": _round(workout.get("ascent_meters"), 0),
                    "kcal": workout.get("energy_kcal"),
                    "feeling_1_5": workout.get("feeling"),
                    "tags": workout.get("tags"),
                }
            )
        )

    nights = [
        _compact(
            {
                "night": night.get("date"),
                "hours": _round(night.get("duration_h")),
                "hrv_ms": _round(night.get("hrv")),
                "resting_hr": _round(night.get("rhr"), 0),
            }
        )
        for night in daily.get("sleep_history") or []
        if night.get("date") and night["date"] >= cutoff
    ]

    return _compact(
        {
            "sleep": _compact(
                {
                    "night": sleep.get("night"),
                    "stale": sleep.get("stale"),
                    "in_progress": True if sleep and not sleep.get("finished") else None,
                    "hours": _round(sleep.get("duration_hours")),
                    "deep_min": sleep.get("deep_minutes"),
                    "rem_min": sleep.get("rem_minutes"),
                    "light_min": sleep.get("light_minutes"),
                    "quality_pct": _round(sleep.get("quality_pct")),
                    "hrv_ms": _round(sleep.get("avg_hrv_ms")),
                    "resting_hr": sleep.get("min_hr_bpm"),
                    "spo2_pct": _round(sleep.get("spo2_pct")),
                }
            ),
            "nap_min": (daily.get("nap") or {}).get("duration_minutes"),
            "sleep_history": nights,
            "baselines": _compact(
                {
                    "hrv_baseline_ms": _round(baseline.get("hrv_baseline")),
                    "hrv_status": baseline.get("hrv_status"),
                    "resting_hr_baseline": _round(baseline.get("resting_hr_baseline")),
                    "readiness": baseline.get("readiness"),
                    "unusual_recovery": baseline.get("unusual_recovery"),
                }
            ),
            "recovery": _compact(
                {
                    "balance_pct": _round(recovery.get("balance_pct")),
                    "stress_state": recovery.get("stress_state"),
                }
            ),
            "load": _compact(
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
            "week": _compact(
                {
                    **(daily.get("weekly") or {}),
                    "workouts": daily.get("count_7d"),
                    "workouts_30d": daily.get("count_30d"),
                    "current_streak_days": daily.get("current_streak"),
                    "days_since_last_workout": (daily.get("workout") or {}).get("days_since"),
                }
            ),
            # Yesterday is the last complete day; in the morning "today" has
            # barely started, so it goes in as an explicitly partial figure.
            "yesterday": _compact(
                {
                    "steps": activity.get("yesterday_steps"),
                    "active_kcal": activity.get("yesterday_energy_kcal"),
                    "of_which_workouts_kcal": workout_kcal.get(today - timedelta(days=1))
                    if activity.get("yesterday_steps") is not None
                    else None,
                }
            ),
            "today_so_far": _compact(
                {
                    "as_of": dt_util.now().strftime("%H:%M")
                    if activity.get("daily_steps") is not None
                    else None,
                    "steps": activity.get("daily_steps"),
                    "active_kcal": activity.get("daily_energy_kcal"),
                    "of_which_workouts_kcal": workout_kcal.get(today)
                    if activity.get("daily_steps") is not None
                    else None,
                }
            ),
            "goals": fast.get("goals"),
            "vo2max": fitness.get("vo2max"),
            "workouts": workouts,
        }
    )


def build_instructions(
    context: dict[str, Any], today: date, language: str | None, extra: str | None
) -> str:
    """The full prompt: rules, field notes, the user's own notes and the data."""
    code = (language or "en").split("-")[0].lower()
    extra = (extra or "").strip()
    return _INSTRUCTIONS.format(
        today=today.isoformat(),
        language=_LANGUAGE_NAMES.get(code, f"the language with code '{code}'"),
        extra=f"\nThe athlete's own notes (take them into account):\n{extra}\n" if extra else "",
        data=json.dumps(context, ensure_ascii=False, default=str, separators=(",", ":")),
    )


def _text(value: Any) -> str | None:
    return str(value or "").strip() or None


def parse_result(data: Any) -> dict[str, Any]:
    """Normalize the model's answer; tolerate plain text and loose types.

    ``summary`` is only filled when the answer came back as plain text (a
    core without structured output); otherwise the text is in ``sections``.
    """
    if not isinstance(data, dict):
        text = str(data or "").strip()
        headline = text.split("\n", 1)[0].split(". ", 1)[0]
        return {
            "headline": headline, "status": None, "sections": {},
            "summary": text or None, "advice": [], "warning": None,
        }
    advice = data.get("advice") or []
    if isinstance(advice, str):
        advice = [line.strip(" -*\t") for line in advice.splitlines()]
    status = str(data.get("status") or "").strip().lower()
    sections: dict[str, dict[str, Any]] = {}
    for key in SECTIONS:
        if text := _text(data.get(key)):
            section_status = str(data.get(f"{key}_status") or "").strip().lower()
            sections[key] = {
                "status": section_status if section_status in SECTION_STATUSES else None,
                "text": text,
            }
    return {
        "headline": _text(data.get("headline")),
        "status": status if status in STATUSES else None,
        "sections": sections,
        "summary": _text(data.get("summary")),
        "advice": [str(item).strip() for item in advice if str(item).strip()],
        "warning": _text(data.get("warning")),
    }


class SuuntoAiInsight:
    """Schedules, runs and stores the daily AI insight for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        daily: DataUpdateCoordinator[dict[str, Any]],
        fast: DataUpdateCoordinator[dict[str, Any]],
        ai_task_entity: str,
        extra_context: str | None,
        fallback_hour: int,
    ) -> None:
        """Initialize; nothing runs until async_start."""
        self.hass = hass
        self._entry = entry
        self._daily = daily
        self._fast = fast
        self.ai_task_entity = ai_task_entity
        self._extra = extra_context
        self._hour = fallback_hour
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.ai_insight.{entry.entry_id}"
        )
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        # Set by the woke-up event; acted on after that coordinator update ends.
        self._pending = False
        # (local date, automatic runs that day), for the retry cap.
        self._attempts: tuple[str, int] = ("", 0)
        self.result: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.running = False
        # The "Automatic AI insight" switch: off pauses every automatic run
        # (morning, fallback hour, retries) so nothing is spent; the button
        # still works. Kept in the same Store as the result, so it is known
        # before any trigger can fire after a restart.
        self.enabled = True

    async def async_start(self) -> None:
        """Load the stored state and hook up the triggers."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            if "result" in stored or "enabled" in stored:
                result = stored.get("result")
                self.result = result if isinstance(result, dict) else None
                self.enabled = stored.get("enabled", True) is not False
            else:
                self.result = stored  # 1.0.30b1-b6 stored the bare result
        self._unsubs += [
            self.hass.bus.async_listen(EVENT_WOKE_UP, self._on_woke_up),
            self._daily.async_add_listener(self._on_daily_update),
            async_track_time_change(
                self.hass, self._on_fallback_time, hour=self._hour, minute=0, second=0
            ),
        ]
        if dt_util.now().hour >= self._hour and not self._done_today():
            self._run_in_background()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Switch automatic runs on or off.

        Turning it on after the fallback hour, with nothing generated today,
        runs today's analysis right away instead of waiting for tomorrow.
        """
        if enabled == self.enabled:
            return
        self.enabled = enabled
        await self._async_save()
        self._notify()
        if enabled and dt_util.now().hour >= self._hour and not self._done_today():
            self._run_in_background()

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

    def _done_today(self) -> bool:
        return bool(self.result) and self.result.get("for_date") == dt_util.now().date().isoformat()

    def _has_current_night(self) -> bool:
        """Whether today's result was built with all of last night's sleep in it."""
        return bool(
            self._done_today()
            and self.result
            and not self.result.get("sleep_stale")
            and self.result.get("sleep_finished", True)
        )

    @callback
    def _on_woke_up(self, event: Event) -> None:
        if event.data.get("entry_id") == self._entry.entry_id:
            self._pending = True

    @callback
    def _on_daily_update(self) -> None:
        if self._pending:
            self._pending = False
            if not self._has_current_night():
                self._run_in_background()
        elif (
            self.last_error
            and not self.running
            and not self._done_today()
            and dt_util.now().hour >= self._hour
        ):
            self._run_in_background()  # retry a failed run, capped per day

    @callback
    def _on_fallback_time(self, _now: datetime) -> None:
        if not self._done_today():
            self._run_in_background()

    @callback
    def _run_in_background(self) -> None:
        """Start an AUTOMATIC run; skipped while the switch is off."""
        if not self.enabled:
            return
        today = dt_util.now().date().isoformat()
        day, count = self._attempts
        count = count if day == today else 0
        if count >= MAX_ATTEMPTS_PER_DAY:
            return
        self._attempts = (today, count + 1)
        self._entry.async_create_background_task(
            self.hass, self._async_generate_quietly(), f"{DOMAIN} AI insight"
        )

    async def _async_generate_quietly(self) -> None:
        if not self.enabled:
            return  # switched off while this run was queued
        try:
            await self.async_generate(wait=True)
        except HomeAssistantError:
            pass  # already logged and kept in last_error

    async def async_generate(self, wait: bool = False) -> None:
        """Run the analysis now. Raises HomeAssistantError on failure.

        A press while a run is going is refused; an automatic run (``wait``)
        queues behind it instead, e.g. the morning night arriving while the
        fallback-hour run is still busy.
        """
        if self._lock.locked() and not wait:
            raise HomeAssistantError("The AI insight is already being generated")
        async with self._lock:
            self.running = True
            self._notify()
            try:
                self.result = await self._async_call()
                self.last_error = None
                await self._async_save()
                self._fire_event(manual=not wait)
            except Exception as err:  # noqa: BLE001 - any provider error ends up here
                self.last_error = str(err) or type(err).__name__
                _LOGGER.warning("AI insight failed: %s", self.last_error)
                raise HomeAssistantError(f"AI insight failed: {self.last_error}") from err
            finally:
                self.running = False
                self._notify()

    @callback
    def _fire_event(self, manual: bool) -> None:
        """Announce a fresh insight; ``manual`` = started from the button."""
        result = self.result or {}
        self.hass.bus.async_fire(
            EVENT_AI_INSIGHT,
            {
                "entry_id": self._entry.entry_id,
                "manual": manual,
                **{
                    key: result.get(key)
                    for key in (
                        "headline", "status", "sections", "advice", "warning",
                        "summary", "for_date", "sleep_night", "sleep_stale",
                    )
                },
                "labels": labels_for(self.hass.config.language),
            },
        )

    async def _async_call(self) -> dict[str, Any]:
        daily = self._daily.data
        if not daily:
            raise HomeAssistantError("No Suunto data yet")
        if not self.hass.services.has_service("ai_task", "generate_data"):
            raise HomeAssistantError(
                "The AI Task integration is not available (Home Assistant 2025.8 or newer is needed)"
            )
        today = dt_util.now().date()
        context = build_context(daily, self._fast.data, today)
        service_data: dict[str, Any] = {
            "task_name": "Suunto daily insight",
            "entity_id": self.ai_task_entity,
            "instructions": build_instructions(
                context, today, self.hass.config.language, self._extra
            ),
        }
        try:
            response = await self.hass.services.async_call(
                "ai_task",
                "generate_data",
                {**service_data, "structure": STRUCTURE},
                blocking=True,
                return_response=True,
            )
        except Exception as err:
            if not _is_schema_error(err):
                raise
            # A core whose ai_task has no `structure` support rejects the call
            # before it reaches the model, so retrying as plain text is free.
            _LOGGER.debug("Structured AI task rejected (%s), retrying as text", err)
            response = await self.hass.services.async_call(
                "ai_task", "generate_data", service_data, blocking=True, return_response=True
            )
        parsed = parse_result((response or {}).get("data"))
        if not parsed["headline"] and not parsed["sections"] and not parsed["summary"]:
            raise HomeAssistantError("The AI returned an empty answer")
        sleep = daily.get("sleep") or {}
        return {
            **parsed,
            "for_date": today.isoformat(),
            "generated_at": dt_util.utcnow().isoformat(),
            "sleep_night": str(sleep["night"]) if sleep.get("night") else None,
            "sleep_stale": bool(sleep.get("stale")) if sleep else True,
            "sleep_finished": bool(sleep.get("finished")) if sleep else False,
            "ai_task_entity": self.ai_task_entity,
        }
