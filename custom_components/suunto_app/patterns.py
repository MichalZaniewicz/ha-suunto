"""Patterns in the athlete's own history: sleep regularity, social jetlag,
aerobic decoupling and personal "what works for you" comparisons.

Pure functions (no Home Assistant or network dependencies), same as
metrics.py. The coordinator converts timestamps to plain local numbers first,
so everything here is plain arithmetic that can be tested directly.

Sleep timing convention: every time of night is MINUTES AFTER NOON of the
night key (the same noon-to-noon key the sleep sensors use), so 23:00 is 660
and 07:00 the next morning is 1140. That keeps a night on one linear scale
without wrapping at midnight.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

MINUTES_PER_DAY = 1440

# Sleep regularity looks at the most recent four weeks of nights.
REGULARITY_WINDOW_NIGHTS = 28
# Fewer consecutive-night pairs than this and the index is mostly noise.
REGULARITY_MIN_PAIRS = 5
# Social jetlag needs at least this many free nights AND work nights.
JETLAG_MIN_NIGHTS = 2
# Night keys (the evening the night starts on) treated as free nights:
# Friday and Saturday, i.e. the nights before a Saturday/Sunday morning.
FREE_NIGHT_WEEKDAYS = frozenset({4, 5})

# Aerobic decoupling: skip the warm-up, then require this much steady work.
DECOUPLING_WARMUP_S = 300
DECOUPLING_MIN_MINUTES = 40
# Below this speed a GPS segment counts as stopped (traffic lights, pauses).
DECOUPLING_MOVING_MS = 1.0
DECOUPLING_MIN_HR_SAMPLES = 10
DECOUPLING_HISTORY = 10

# Personal insights: minimum nights in EACH group, minimum effect size
# (Cohen's d) and minimum relative difference before a comparison is shown.
INSIGHT_MIN_GROUP = 4
INSIGHT_MIN_EFFECT = 0.4
INSIGHT_MIN_DIFF_PCT = 3.0
INSIGHT_LIMIT = 5
# A workout ending at or after this local hour counts as a late workout.
LATE_WORKOUT_HOUR = 20


def clock(minutes_after_noon: float) -> str:
    """Format minutes after noon as a local "HH:MM" clock time."""
    total = round(12 * 60 + minutes_after_noon) % MINUTES_PER_DAY
    return f"{total // 60:02d}:{total % 60:02d}"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sd(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _asleep_minutes(intervals: list[tuple[float, float]]) -> list[bool]:
    """One flag per minute of the noon-to-noon day: asleep or not."""
    asleep = [False] * MINUTES_PER_DAY
    for start, end in intervals:
        first = max(0, math.floor(start))
        last = min(MINUTES_PER_DAY, math.ceil(end))
        for minute in range(first, last):
            asleep[minute] = True
    return asleep


def sleep_regularity(nights: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Sleep Regularity Index plus average bed/wake times.

    ``nights``: ``{"night": date, "intervals": [(start_min, end_min), ...]}``
    with the night's sleep fragments in minutes after noon. The SRI (Phillips
    et al., 2017) is the chance of being in the same state (asleep or awake)
    at the same minute on two consecutive days, scaled to -100..100: 100 means
    an identical schedule every day, around 0 a random one. Gaps between the
    fragments of a night count as awake, as they are real wake-ups.

    Only pairs of consecutive nights that both have data are compared, so a
    night the watch was not worn costs a pair instead of reading as "awake
    all night". Returns None with fewer than REGULARITY_MIN_PAIRS pairs.
    """
    by_night = {
        n["night"]: n["intervals"] for n in nights if n.get("intervals")
    }
    if not by_night:
        return None
    recent = sorted(by_night)[-REGULARITY_WINDOW_NIGHTS:]
    agree = total = pairs = 0
    for night in recent:
        following = night + timedelta(days=1)
        if following not in by_night:
            continue
        today = _asleep_minutes(by_night[night])
        tomorrow = _asleep_minutes(by_night[following])
        agree += sum(1 for a, b in zip(today, tomorrow) if a == b)
        total += MINUTES_PER_DAY
        pairs += 1
    if pairs < REGULARITY_MIN_PAIRS:
        return None

    beds = [min(s for s, _ in by_night[n]) for n in recent]
    wakes = [max(e for _, e in by_night[n]) for n in recent]
    bed_sd, wake_sd = _sd(beds), _sd(wakes)
    return {
        "index": round(200 * agree / total - 100),
        "pairs": pairs,
        "nights": len(recent),
        "avg_bedtime": clock(_mean(beds)),
        "avg_wake_time": clock(_mean(wakes)),
        "bedtime_sd_min": round(bed_sd) if bed_sd is not None else None,
        "wake_time_sd_min": round(wake_sd) if wake_sd is not None else None,
    }


def social_jetlag(nights: list[dict[str, Any]]) -> dict[str, Any] | None:
    """How much later (minutes) the sleep midpoint sits on free nights.

    Social jetlag (Wittmann et al., 2006) is the shift of mid-sleep between
    free days and work days. Free nights are Friday and Saturday nights
    (FREE_NIGHT_WEEKDAYS). Positive = later on weekends. Mid-sleep is the
    midpoint between the first fragment's start and the last fragment's end.
    """
    free: list[float] = []
    work: list[float] = []
    recent = sorted(
        (n for n in nights if n.get("intervals")), key=lambda n: n["night"]
    )[-REGULARITY_WINDOW_NIGHTS:]
    for night in recent:
        bed = min(s for s, _ in night["intervals"])
        wake = max(e for _, e in night["intervals"])
        midpoint = (bed + wake) / 2
        (free if night["night"].weekday() in FREE_NIGHT_WEEKDAYS else work).append(midpoint)
    if len(free) < JETLAG_MIN_NIGHTS or len(work) < JETLAG_MIN_NIGHTS:
        return None
    free_mid, work_mid = _mean(free), _mean(work)
    return {
        "minutes": round(free_mid - work_mid),
        "free_midpoint": clock(free_mid),
        "work_midpoint": clock(work_mid),
        "free_nights": len(free),
        "work_nights": len(work),
    }


def aerobic_decoupling(
    heartrates: list[tuple[float, float]], distances: list[tuple[float, float]]
) -> dict[str, Any] | None:
    """Heart-rate drift against speed between the two halves of a workout.

    ``heartrates``: ``(seconds_from_start, bpm)``; ``distances``:
    ``(seconds_from_start, cumulative_metres)``, both from the workout's
    ``/data`` response. After DECOUPLING_WARMUP_S, the rest is split in two
    halves by time. Each half's efficiency is moving speed / mean heart rate,
    and decoupling is how much that efficiency dropped in the second half, in
    percent (Friel's Pa:Hr). Under ~5 % is the classic sign of a solid aerobic
    base; a big positive number means the heart had to work harder for the
    same speed as the session went on (fatigue, heat, dehydration).

    Speed, not power: on a hilly or windy route the halves differ in terrain
    too, so treat a single value as rough and the trend as the useful part.
    Returns None for a workout that is too short, has no GPS distance or too
    few heart-rate samples.
    """
    hr = sorted((t, v) for t, v in heartrates if v and v > 0)
    dist = sorted(distances)
    if len(dist) < 2 or not hr:
        return None
    start = dist[0][0] + DECOUPLING_WARMUP_S
    end = dist[-1][0]
    if end - start < DECOUPLING_MIN_MINUTES * 60:
        return None
    middle = (start + end) / 2

    halves: list[dict[str, float]] = []
    for low, high in ((start, middle), (middle, end)):
        metres = seconds = 0.0
        for (t1, s1), (t2, s2) in zip(dist, dist[1:]):
            if t1 < low or t1 >= high:
                continue
            dt, ds = t2 - t1, s2 - s1
            if dt > 0 and ds / dt >= DECOUPLING_MOVING_MS:
                metres += ds
                seconds += dt
        beats = [v for t, v in hr if low <= t < high]
        if seconds < 300 or len(beats) < DECOUPLING_MIN_HR_SAMPLES:
            return None
        speed = metres / seconds
        mean_hr = sum(beats) / len(beats)
        halves.append({"speed": speed, "hr": mean_hr, "ef": speed / mean_hr})

    first, second = halves
    return {
        "decoupling_pct": round((first["ef"] - second["ef"]) / first["ef"] * 100, 1),
        "first_half_speed_kmh": round(first["speed"] * 3.6, 1),
        "first_half_hr": round(first["hr"]),
        "second_half_speed_kmh": round(second["speed"] * 3.6, 1),
        "second_half_hr": round(second["hr"]),
        "analyzed_minutes": round((end - start) / 60),
    }


# --- Personal insights -------------------------------------------------------

# Metric -> (night-series field, True when a higher value is the better one).
_METRICS: dict[str, tuple[str, bool]] = {
    "hrv": ("hrv", True),
    "resting_hr": ("rhr", False),
    "sleep": ("hours", True),
}

_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "late_workout": "After a workout ending after {hour}:00",
        "training_day": "On training days",
        "hard_day": "After your hardest training days",
        "early_bed": "When you go to bed before {time}",
        "free_night": "On Friday and Saturday nights",
        "hrv": "HRV",
        "resting_hr": "resting HR",
        "sleep": "sleep",
        "higher": "higher",
        "lower": "lower",
        "longer": "longer",
        "shorter": "shorter",
        "template": "{condition}, your {metric} is {pct}% {direction} ({with_value} vs {without_value})",
    },
    "pl": {
        "late_workout": "Po treningu kończonym po {hour}:00",
        "training_day": "W dni treningowe",
        "hard_day": "Po najcięższych dniach treningowych",
        "early_bed": "Gdy kładziesz się przed {time}",
        "free_night": "W noce z piątku i soboty",
        "hrv": "HRV",
        "resting_hr": "tętno spoczynkowe",
        "sleep": "sen",
        "higher": "wyższe",
        "lower": "niższe",
        "longer": "dłuższy",
        "shorter": "krótszy",
        "template": "{condition} twoje {metric} jest o {pct}% {direction} ({with_value} vs {without_value})",
        # Polish needs gender agreement with "sen" (masculine).
        "template_sleep": "{condition} twój {metric} jest o {pct}% {direction} ({with_value} vs {without_value})",
    },
    "de": {
        "late_workout": "Nach einem Training mit Ende nach {hour}:00",
        "training_day": "An Trainingstagen",
        "hard_day": "Nach deinen härtesten Trainingstagen",
        "early_bed": "Wenn du vor {time} ins Bett gehst",
        "free_night": "In den Nächten auf Samstag und Sonntag",
        "hrv": "HRV",
        "resting_hr": "Ruhepuls",
        "sleep": "Schlaf",
    },
    "fr": {
        "late_workout": "Après une séance terminée après {hour}h",
        "training_day": "Les jours d'entraînement",
        "hard_day": "Après vos journées d'entraînement les plus dures",
        "early_bed": "Quand vous vous couchez avant {time}",
        "free_night": "Les nuits du vendredi et du samedi",
        "hrv": "VFC",
        "resting_hr": "FC au repos",
        "sleep": "sommeil",
    },
    "es": {
        "late_workout": "Tras un entrenamiento que acaba después de las {hour}:00",
        "training_day": "Los días de entrenamiento",
        "hard_day": "Tras tus días de entrenamiento más duros",
        "early_bed": "Cuando te acuestas antes de las {time}",
        "free_night": "Las noches de viernes y sábado",
        "hrv": "VFC",
        "resting_hr": "FC en reposo",
        "sleep": "sueño",
    },
    "it": {
        "late_workout": "Dopo un allenamento finito dopo le {hour}:00",
        "training_day": "Nei giorni di allenamento",
        "hard_day": "Dopo i tuoi giorni di allenamento più duri",
        "early_bed": "Quando vai a letto prima delle {time}",
        "free_night": "Le notti di venerdì e sabato",
        "hrv": "HRV",
        "resting_hr": "FC a riposo",
        "sleep": "sonno",
    },
    "nl": {
        "late_workout": "Na een training die na {hour}:00 eindigt",
        "training_day": "Op trainingsdagen",
        "hard_day": "Na je zwaarste trainingsdagen",
        "early_bed": "Als je voor {time} naar bed gaat",
        "free_night": "In de nachten van vrijdag en zaterdag",
        "hrv": "HRV",
        "resting_hr": "rusthartslag",
        "sleep": "slaap",
    },
    "pt": {
        "late_workout": "Depois de um treino que acaba após as {hour}:00",
        "training_day": "Nos dias de treino",
        "hard_day": "Depois dos seus dias de treino mais duros",
        "early_bed": "Quando se deita antes das {time}",
        "free_night": "Nas noites de sexta e sábado",
        "hrv": "VFC",
        "resting_hr": "FC em repouso",
        "sleep": "sono",
    },
}

_UNITS = {"hrv": "ms", "resting_hr": "bpm", "sleep": "h"}


def _format_value(metric: str, value: float) -> str:
    if metric == "sleep":
        return f"{value:.1f} h"
    return f"{round(value)} {_UNITS[metric]}"


def _insight_text(finding: dict[str, Any], language: str | None) -> str:
    phrases = _TEXT.get((language or "en").split("-")[0].lower(), _TEXT["en"])
    metric = finding["metric"]
    higher = finding["diff_pct"] > 0
    if metric == "sleep":
        direction = phrases.get("longer" if higher else "shorter")
    else:
        direction = phrases.get("higher" if higher else "lower")
    condition = phrases[finding["condition"]].format(
        hour=LATE_WORKOUT_HOUR, time=finding.get("threshold") or ""
    )
    template = phrases.get(f"template_{metric}", phrases.get("template"))
    if template is None:
        # Languages without a grammatical sentence (gender agreement of the
        # metric name would need a table per language) get a neutral line.
        return "{condition}: {metric} {pct:+d}% ({with_value} vs {without_value})".format(
            condition=condition,
            metric=phrases[metric],
            pct=round(finding["diff_pct"]),
            with_value=_format_value(metric, finding["with"]),
            without_value=_format_value(metric, finding["without"]),
        )
    return template.format(
        condition=condition,
        metric=phrases[metric],
        pct=abs(round(finding["diff_pct"])),
        direction=direction,
        with_value=_format_value(metric, finding["with"]),
        without_value=_format_value(metric, finding["without"]),
    )


def _compare(
    condition: str,
    metric: str,
    with_values: list[float],
    without_values: list[float],
) -> dict[str, Any] | None:
    """One "with vs without" comparison, or None when it is not convincing."""
    if len(with_values) < INSIGHT_MIN_GROUP or len(without_values) < INSIGHT_MIN_GROUP:
        return None
    mean_with, mean_without = _mean(with_values), _mean(without_values)
    if not mean_without:
        return None
    sd_with, sd_without = _sd(with_values), _sd(without_values)
    pooled = math.sqrt(((sd_with or 0) ** 2 + (sd_without or 0) ** 2) / 2)
    if pooled <= 0:
        return None
    effect = (mean_with - mean_without) / pooled
    diff_pct = (mean_with - mean_without) / mean_without * 100
    if abs(effect) < INSIGHT_MIN_EFFECT or abs(diff_pct) < INSIGHT_MIN_DIFF_PCT:
        return None
    better_high = _METRICS[metric][1]
    return {
        "condition": condition,
        "metric": metric,
        "with": round(mean_with, 1),
        "without": round(mean_without, 1),
        "diff_pct": round(diff_pct, 1),
        "effect_size": round(effect, 2),
        "n_with": len(with_values),
        "n_without": len(without_values),
        "favorable": (diff_pct > 0) == better_high,
    }


def personal_insights(
    nights: list[dict[str, Any]],
    days: dict[date, dict[str, Any]],
    language: str | None = None,
) -> dict[str, Any] | None:
    """The strongest "with vs without" patterns in the athlete's own history.

    ``nights``: ``{"night": date, "hrv", "rhr", "hours", "bed_min"}`` (any
    value may be None); ``days``: local date -> ``{"tss": float, "late":
    bool}`` for days with at least one workout. A night is matched with the
    day it starts on (night key == that day), so "after a late workout" means
    the night right after it.

    Every comparison is the mean over nights WITH the condition against
    nights WITHOUT it. A finding needs INSIGHT_MIN_GROUP nights on both sides,
    a standardized effect of at least INSIGHT_MIN_EFFECT and a difference of
    at least INSIGHT_MIN_DIFF_PCT, so small or noisy differences never show.
    These are correlations in a small personal sample, not proof of cause.
    """
    if not nights:
        return None
    training_tss = sorted(d["tss"] for d in days.values() if d.get("tss"))
    hard_cutoff = (
        training_tss[len(training_tss) * 2 // 3] if len(training_tss) >= 6 else None
    )
    beds = sorted(n["bed_min"] for n in nights if n.get("bed_min") is not None)
    bed_cutoff = beds[len(beds) // 2] if len(beds) >= 2 * INSIGHT_MIN_GROUP else None

    # condition -> night -> True (with) / False (without) / None (not comparable)
    def classify(condition: str, night: dict[str, Any]) -> bool | None:
        day = days.get(night["night"])
        if condition == "training_day":
            return day is not None
        if condition == "late_workout":
            return None if day is None else bool(day.get("late"))
        if condition == "hard_day":
            if day is None or hard_cutoff is None or not day.get("tss"):
                return None
            return day["tss"] >= hard_cutoff
        if condition == "early_bed":
            if bed_cutoff is None or night.get("bed_min") is None:
                return None
            return night["bed_min"] < bed_cutoff
        if condition == "free_night":
            return night["night"].weekday() in FREE_NIGHT_WEEKDAYS
        return None

    findings: list[dict[str, Any]] = []
    for condition in ("late_workout", "training_day", "hard_day", "early_bed", "free_night"):
        for metric, (field, _) in _METRICS.items():
            with_values: list[float] = []
            without_values: list[float] = []
            for night in nights:
                value = night.get(field)
                if value is None:
                    continue
                group = classify(condition, night)
                if group is True:
                    with_values.append(value)
                elif group is False:
                    without_values.append(value)
            finding = _compare(condition, metric, with_values, without_values)
            if finding is None:
                continue
            if condition == "early_bed":
                finding["threshold"] = clock(bed_cutoff)
            findings.append(finding)

    findings.sort(key=lambda f: abs(f["effect_size"]), reverse=True)
    findings = findings[:INSIGHT_LIMIT]
    for finding in findings:
        finding["text"] = _insight_text(finding, language)
    return {
        "insights": findings,
        "nights": len(nights),
        "training_days": len(days),
    }
