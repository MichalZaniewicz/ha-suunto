"""One-sentence daily brief built from sleep, HRV, readiness and form.

Pure functions (no Home Assistant or network dependencies), same as
metrics.py. The brief only restates what the other sensors already say - it
adds no new judgement of its own, so it can never disagree with them.
"""

from __future__ import annotations

# A sensor state is capped at 255 characters by Home Assistant.
MAX_STATE_LENGTH = 255

_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "slept": "Slept {hours} h",
        "no_sleep": "No sleep data for last night",
        "hrv_low": "HRV below your norm",
        "hrv_balanced": "HRV within your norm",
        "hrv_high": "HRV above your norm",
        "readiness": "readiness {value}",
        "form": "form {value}",
        "rest": "take a rest day",
        "easy": "keep it easy today",
        "moderate": "a moderate session fits today",
        "hard": "a good day for a hard session",
    },
    "pl": {
        "slept": "Spałeś {hours} h",
        "no_sleep": "Brak danych o śnie z ostatniej nocy",
        "hrv_low": "HRV poniżej normy",
        "hrv_balanced": "HRV w normie",
        "hrv_high": "HRV powyżej normy",
        "readiness": "gotowość {value}",
        "form": "forma {value}",
        "rest": "zrób dzień odpoczynku",
        "easy": "dziś tylko lekko",
        "moderate": "dziś pasuje umiarkowany trening",
        "hard": "dobry dzień na mocny trening",
    },
    "de": {
        "slept": "{hours} h geschlafen",
        "no_sleep": "Keine Schlafdaten der letzten Nacht",
        "hrv_low": "HRV unter deiner Norm",
        "hrv_balanced": "HRV in deiner Norm",
        "hrv_high": "HRV über deiner Norm",
        "readiness": "Bereitschaft {value}",
        "form": "Form {value}",
        "rest": "mach einen Ruhetag",
        "easy": "heute nur locker",
        "moderate": "heute passt eine moderate Einheit",
        "hard": "ein guter Tag für eine harte Einheit",
    },
    "fr": {
        "slept": "{hours} h de sommeil",
        "no_sleep": "Pas de données de sommeil pour la nuit dernière",
        "hrv_low": "VFC sous votre norme",
        "hrv_balanced": "VFC dans votre norme",
        "hrv_high": "VFC au-dessus de votre norme",
        "readiness": "forme du jour {value}",
        "form": "fraîcheur {value}",
        "rest": "prenez un jour de repos",
        "easy": "restez léger aujourd'hui",
        "moderate": "une séance modérée convient aujourd'hui",
        "hard": "bonne journée pour une séance intense",
    },
    "es": {
        "slept": "Dormiste {hours} h",
        "no_sleep": "Sin datos de sueño de anoche",
        "hrv_low": "VFC por debajo de tu norma",
        "hrv_balanced": "VFC dentro de tu norma",
        "hrv_high": "VFC por encima de tu norma",
        "readiness": "disposición {value}",
        "form": "forma {value}",
        "rest": "tómate un día de descanso",
        "easy": "hoy solo suave",
        "moderate": "hoy encaja una sesión moderada",
        "hard": "buen día para una sesión dura",
    },
    "it": {
        "slept": "Hai dormito {hours} h",
        "no_sleep": "Nessun dato sul sonno della notte scorsa",
        "hrv_low": "HRV sotto la tua norma",
        "hrv_balanced": "HRV nella tua norma",
        "hrv_high": "HRV sopra la tua norma",
        "readiness": "prontezza {value}",
        "form": "forma {value}",
        "rest": "prenditi un giorno di riposo",
        "easy": "oggi solo leggero",
        "moderate": "oggi va bene una seduta moderata",
        "hard": "giornata buona per una seduta intensa",
    },
    "nl": {
        "slept": "{hours} u geslapen",
        "no_sleep": "Geen slaapgegevens van afgelopen nacht",
        "hrv_low": "HRV onder je norm",
        "hrv_balanced": "HRV binnen je norm",
        "hrv_high": "HRV boven je norm",
        "readiness": "paraatheid {value}",
        "form": "vorm {value}",
        "rest": "neem een rustdag",
        "easy": "houd het vandaag rustig",
        "moderate": "een gematigde training past vandaag",
        "hard": "een goede dag voor een zware training",
    },
    "pt": {
        "slept": "Dormiu {hours} h",
        "no_sleep": "Sem dados de sono da noite passada",
        "hrv_low": "VFC abaixo da sua norma",
        "hrv_balanced": "VFC dentro da sua norma",
        "hrv_high": "VFC acima da sua norma",
        "readiness": "prontidão {value}",
        "form": "forma {value}",
        "rest": "faça um dia de descanso",
        "easy": "hoje só leve",
        "moderate": "hoje cabe um treino moderado",
        "hard": "bom dia para um treino forte",
    },
}


def daily_brief(
    *,
    language: str | None,
    sleep_hours: float | None,
    sleep_stale: bool | None,
    hrv_status: str | None,
    readiness: int | None,
    tsb: float | None,
    suggestion: str | None,
) -> str | None:
    """Build the brief, e.g. "Slept 8.0 h, HRV above your norm, readiness 76,
    form +27: a good day for a hard session."

    Every part is optional and simply left out when its input is unknown; a
    stale night says so instead of quoting old sleep. Returns None when there
    is nothing at all to say. Unknown languages fall back to English.
    """
    phrases = _PHRASES.get((language or "en").split("-")[0].lower(), _PHRASES["en"])
    facts: list[str] = []
    if sleep_stale:
        facts.append(phrases["no_sleep"])
    elif sleep_hours is not None:
        facts.append(phrases["slept"].format(hours=f"{sleep_hours:.1f}"))
    if not sleep_stale and hrv_status in ("low", "balanced", "high"):
        facts.append(phrases[f"hrv_{hrv_status}"])
    if readiness is not None:
        facts.append(phrases["readiness"].format(value=readiness))
    if tsb is not None:
        facts.append(phrases["form"].format(value=f"{round(tsb):+d}"))
    advice = phrases.get(suggestion or "")

    if not facts and not advice:
        return None
    text = ", ".join(facts)
    if advice:
        text = f"{text}: {advice}" if text else advice[0].upper() + advice[1:]
    return (text + ".")[:MAX_STATE_LENGTH]
