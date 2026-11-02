"""Conditions for the automation editor: "Suunto: recovering" and friends.

Shown under the integration in the condition picker with their own fields,
so "only if readiness is below 50" or "only on a rest day" needs no entity
lookup and no template. Each condition reads the daily coordinator's data
directly, the same values the sensors show, and never makes a request.

With several Suunto accounts, pick one in the condition; without a pick it
passes when any account matches.

Needs Home Assistant 2025.12 or newer (integration-provided conditions).
Home Assistant 2026.6 changed the Condition base class (``_async_check``
instead of ``async_get_checker``); both are implemented here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

try:
    import probatio as vol
except ImportError:  # Home Assistant before 2026.10
    import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_OPTIONS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.condition import Condition, ConditionConfig
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import DOMAIN

CONF_CONFIG_ENTRY = "config_entry"
SUGGESTIONS = ("rest", "easy", "moderate", "hard")

_ENTRY = {vol.Optional(CONF_CONFIG_ENTRY): str}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _options_schema(fields: dict[Any, Any], *validators: Any) -> Any:
    return vol.Schema(
        {
            vol.Optional(CONF_OPTIONS, default={}): vol.All(
                vol.Schema({**_ENTRY, **fields}), *validators
            )
        }
    )


def _needs_a_bound(options: dict[str, Any]) -> dict[str, Any]:
    if options.get("above") is None and options.get("below") is None:
        raise vol.Invalid("Set at least one of above or below")
    return options


def _in_range(value: Any, options: dict[str, Any]) -> bool:
    """Strictly above ``above`` and strictly below ``below``; unknown fails."""
    if value is None:
        return False
    above, below = options.get("above"), options.get("below")
    if above is not None and not value > above:
        return False
    if below is not None and not value < below:
        return False
    return True


# ---------------------------------------------------------------------------
# What each condition tests (pure: daily coordinator data in, bool out)
# ---------------------------------------------------------------------------


def is_recovering(data: dict[str, Any], options: dict[str, Any], now: datetime) -> bool:
    recovered = (data.get("workout") or {}).get("recovered_at")
    return bool(recovered and recovered > now)


def workout_today(data: dict[str, Any], options: dict[str, Any], now: datetime) -> bool:
    wanted = [str(item).casefold().strip() for item in options.get("activity") or []]
    today = dt_util.as_local(now).date()
    for workout in data.get("workouts") or []:
        start = workout.get("start_time")
        if start is None or dt_util.as_local(start).date() != today:
            continue
        if not wanted or str(workout.get("activity") or "").casefold() in wanted:
            return True
    return False


def readiness(data: dict[str, Any], options: dict[str, Any], now: datetime) -> bool:
    return _in_range((data.get("baseline") or {}).get("readiness"), options)


def training_suggestion(
    data: dict[str, Any], options: dict[str, Any], now: datetime
) -> bool:
    return (data.get("load") or {}).get("suggestion") in (options.get("suggestion") or [])


def last_night_sleep(data: dict[str, Any], options: dict[str, Any], now: datetime) -> bool:
    """Last night's length; a night not synced yet (stale) counts as unknown."""
    sleep = data.get("sleep") or {}
    if sleep.get("stale"):
        return False
    return _in_range(sleep.get("duration_hours"), options)


# ---------------------------------------------------------------------------
# Condition classes
# ---------------------------------------------------------------------------


class _SuuntoCondition(Condition):
    """Passes when the test holds for the picked account (or any account)."""

    _SCHEMA: Any = _options_schema({})
    _TEST: Callable[[dict[str, Any], dict[str, Any], datetime], bool]

    @classmethod
    async def async_validate_config(
        cls, hass: HomeAssistant, config: ConfigType
    ) -> ConfigType:
        """Validate the condition's options."""
        return cls._SCHEMA(config)

    def __init__(self, hass: HomeAssistant, config: ConditionConfig) -> None:
        """Initialize the condition."""
        super().__init__(hass, config)
        self._hass = hass
        self._options: dict[str, Any] = dict(config.options or {})

    def _test(self) -> bool:
        wanted = self._options.get(CONF_CONFIG_ENTRY)
        now = dt_util.utcnow()
        test = type(self)._TEST
        for entry in self._hass.config_entries.async_entries(DOMAIN):
            if wanted and entry.entry_id != wanted:
                continue
            if entry.state is not ConfigEntryState.LOADED:
                continue
            runtime = getattr(entry, "runtime_data", None)
            data = runtime.daily.data if runtime is not None else None
            if data and test(data, self._options, now):
                return True
        return False

    def _async_check(self, **kwargs: Any) -> bool:
        """Home Assistant 2026.6 and newer."""
        return self._test()

    async def async_get_checker(self) -> Callable[..., bool]:
        """Home Assistant before 2026.6."""

        def _check(*args: Any, **kwargs: Any) -> bool:
            return self._test()

        return _check


class IsRecoveringCondition(_SuuntoCondition):
    _TEST = staticmethod(is_recovering)


class WorkoutTodayCondition(_SuuntoCondition):
    _TEST = staticmethod(workout_today)
    _SCHEMA = _options_schema(
        {vol.Optional("activity", default=[]): vol.All(_list, [str])}
    )


_BOUNDS = {
    vol.Optional("above"): vol.Coerce(float),
    vol.Optional("below"): vol.Coerce(float),
}


class ReadinessCondition(_SuuntoCondition):
    _TEST = staticmethod(readiness)
    _SCHEMA = _options_schema(_BOUNDS, _needs_a_bound)


class TrainingSuggestionCondition(_SuuntoCondition):
    _TEST = staticmethod(training_suggestion)
    _SCHEMA = _options_schema(
        {vol.Required("suggestion"): vol.All(_list, [vol.In(SUGGESTIONS)])}
    )


class LastNightSleepCondition(_SuuntoCondition):
    _TEST = staticmethod(last_night_sleep)
    _SCHEMA = _options_schema(_BOUNDS, _needs_a_bound)


CONDITIONS: dict[str, type[Condition]] = {
    "is_recovering": IsRecoveringCondition,
    "workout_today": WorkoutTodayCondition,
    "readiness": ReadinessCondition,
    "training_suggestion": TrainingSuggestionCondition,
    "last_night_sleep": LastNightSleepCondition,
}


async def async_get_conditions(hass: HomeAssistant) -> dict[str, type[Condition]]:
    """Return the conditions this integration provides."""
    return CONDITIONS
