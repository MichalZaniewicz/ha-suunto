"""Readable logbook entries for the integration's bus events.

Without this the logbook shows nothing for suunto_app_new_workout and the
others (only the event entities' "event fired" lines). With it:
"Suunto Michał new workout: Cycling, 32.4 km, 1:12 h, TSS 85".

Logbook text is not run through Home Assistant's translations, so the few
phrases live here in the 8 languages of the integration, picked by the
server language. The readiness word comes from brief.py, so it reads the
same as on the daily brief sensor.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .brief import _PHRASES as _BRIEF_PHRASES
from .const import (
    DOMAIN,
    EVENT_AI_INSIGHT,
    EVENT_AI_WEEKLY,
    EVENT_NEW_WORKOUT,
    EVENT_WOKE_UP,
)

_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "workout": "new workout: {details}",
        "woke_up": "woke up after {sleep} of sleep",
        "woke_up_unknown": "last night's sleep synced",
        "ai_daily": "daily AI insight: {headline}",
        "ai_weekly": "weekly AI summary: {headline}",
    },
    "pl": {
        "workout": "nowy trening: {details}",
        "woke_up": "pobudka po {sleep} snu",
        "woke_up_unknown": "sen z ostatniej nocy zsynchronizowany",
        "ai_daily": "dzienna analiza AI: {headline}",
        "ai_weekly": "tygodniowe podsumowanie AI: {headline}",
    },
    "de": {
        "workout": "neues Training: {details}",
        "woke_up": "aufgewacht nach {sleep} Schlaf",
        "woke_up_unknown": "Schlaf der letzten Nacht synchronisiert",
        "ai_daily": "tägliche KI-Analyse: {headline}",
        "ai_weekly": "wöchentliche KI-Zusammenfassung: {headline}",
    },
    "fr": {
        "workout": "nouvel entraînement : {details}",
        "woke_up": "réveil après {sleep} de sommeil",
        "woke_up_unknown": "sommeil de la nuit dernière synchronisé",
        "ai_daily": "analyse IA du jour : {headline}",
        "ai_weekly": "résumé IA de la semaine : {headline}",
    },
    "es": {
        "workout": "nuevo entrenamiento: {details}",
        "woke_up": "despertar tras {sleep} de sueño",
        "woke_up_unknown": "sueño de anoche sincronizado",
        "ai_daily": "análisis diario de IA: {headline}",
        "ai_weekly": "resumen semanal de IA: {headline}",
    },
    "it": {
        "workout": "nuovo allenamento: {details}",
        "woke_up": "sveglia dopo {sleep} di sonno",
        "woke_up_unknown": "sonno della scorsa notte sincronizzato",
        "ai_daily": "analisi IA del giorno: {headline}",
        "ai_weekly": "riepilogo IA della settimana: {headline}",
    },
    "nl": {
        "workout": "nieuwe training: {details}",
        "woke_up": "wakker na {sleep} slaap",
        "woke_up_unknown": "slaap van afgelopen nacht gesynchroniseerd",
        "ai_daily": "dagelijkse AI-analyse: {headline}",
        "ai_weekly": "wekelijkse AI-samenvatting: {headline}",
    },
    "pt": {
        "workout": "novo treino: {details}",
        "woke_up": "acordou após {sleep} de sono",
        "woke_up_unknown": "sono da noite passada sincronizado",
        "ai_daily": "análise diária de IA: {headline}",
        "ai_weekly": "resumo semanal de IA: {headline}",
    },
}

# Event -> the event entity it shows up under (event.py's unique_id key).
_ENTITY_KEYS = {
    EVENT_NEW_WORKOUT: "workout",
    EVENT_WOKE_UP: "woke_up",
    EVENT_AI_INSIGHT: "ai_report",
    EVENT_AI_WEEKLY: "ai_report",
}


def _language(hass: HomeAssistant) -> str:
    language = (hass.config.language or "en").split("-")[0].lower()
    return language if language in _PHRASES else "en"


def _number(value: float, decimals: int, language: str) -> str:
    text = f"{value:.{decimals}f}"
    return text if language == "en" else text.replace(".", ",")


def _hours_minutes(minutes: float) -> str:
    """95 -> "1:35 h", 45 -> "45 min"."""
    total = round(minutes)
    if total < 60:
        return f"{total} min"
    return f"{total // 60}:{total % 60:02d} h"


def workout_details(data: dict[str, Any], language: str) -> str:
    """"Cycling, 32.4 km, 1:12 h, TSS 85" from the new-workout event data."""
    parts = [str(data.get("activity") or "?")]
    if meters := data.get("distance_meters"):
        parts.append(f"{_number(meters / 1000, 1, language)} km")
    if minutes := data.get("duration_minutes"):
        parts.append(_hours_minutes(minutes))
    if tss := data.get("tss"):
        parts.append(f"TSS {round(tss)}")
    return ", ".join(parts)


def describe(event_type: str, data: dict[str, Any], language: str) -> str:
    """The logbook message for one event (pure)."""
    phrases = _PHRASES.get(language, _PHRASES["en"])
    if event_type == EVENT_NEW_WORKOUT:
        return phrases["workout"].format(details=workout_details(data, language))
    if event_type == EVENT_WOKE_UP:
        hours = data.get("sleep_hours")
        if not hours:
            return phrases["woke_up_unknown"]
        text = phrases["woke_up"].format(sleep=_hours_minutes(hours * 60))
        if (value := data.get("readiness")) is not None:
            brief = _BRIEF_PHRASES.get(language, _BRIEF_PHRASES["en"])
            text += ", " + brief["readiness"].format(value=round(value))
        return text
    key = "ai_daily" if event_type == EVENT_AI_INSIGHT else "ai_weekly"
    return phrases[key].format(headline=data.get("headline") or "-")


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe the integration's bus events for the logbook."""

    @callback
    def _describe(event: Event) -> dict[str, str]:
        data = event.data
        entry_id = data.get("entry_id")
        entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
        result = {
            "name": entry.title if entry else "Suunto",
            "message": describe(event.event_type, data, _language(hass)),
        }
        if entry_id and (
            entity_id := er.async_get(hass).async_get_entity_id(
                "event", DOMAIN, f"{entry_id}_event_{_ENTITY_KEYS[event.event_type]}"
            )
        ):
            result["entity_id"] = entity_id
        return result

    for event_type in _ENTITY_KEYS:
        async_describe_event(DOMAIN, event_type, _describe)
