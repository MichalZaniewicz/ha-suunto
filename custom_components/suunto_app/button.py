"""Button platform: sync now, and the AI insight / weekly summary on demand."""

from __future__ import annotations

import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SuuntoAppConfigEntry, suunto_device_info
from .ai_insight import SuuntoAiInsight
from .ai_weekly import SuuntoAiWeekly
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuuntoAppConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Sync now always, the AI buttons only while the AI is configured."""
    async_add_entities([SuuntoSyncButton(entry)])
    runtime = entry.runtime_data
    if runtime.ai is not None:
        async_add_entities([SuuntoAiInsightButton(runtime.ai, entry)])
    if runtime.weekly is not None:
        async_add_entities([SuuntoAiWeeklyButton(runtime.weekly, entry)])
    registry = er.async_get(hass)
    for runner, suffix in (
        (runtime.ai, "ai_insight_generate"),
        (runtime.weekly, "ai_weekly_generate"),
    ):
        if runner is None and (
            entity_id := registry.async_get_entity_id(
                "button", DOMAIN, f"{entry.entry_id}_{suffix}"
            )
        ):
            registry.async_remove(entity_id)


class SuuntoAiInsightButton(ButtonEntity):
    """Run the AI analysis now, even if today's is already done."""

    _attr_has_entity_name = True
    _attr_translation_key = "ai_insight_generate"

    def __init__(self, insight: SuuntoAiInsight, entry: SuuntoAppConfigEntry) -> None:
        """Initialize the button."""
        self._insight = insight
        self._attr_unique_id = f"{entry.entry_id}_ai_insight_generate"
        self._attr_device_info = suunto_device_info(entry)

    async def async_press(self) -> None:
        """Generate; a failure surfaces in the UI as an error toast."""
        await self._insight.async_generate()


class SuuntoAiWeeklyButton(ButtonEntity):
    """Write the weekly AI summary now, for the seven days ending today."""

    _attr_has_entity_name = True
    _attr_translation_key = "ai_weekly_generate"

    def __init__(self, weekly: SuuntoAiWeekly, entry: SuuntoAppConfigEntry) -> None:
        """Initialize the button."""
        self._weekly = weekly
        self._attr_unique_id = f"{entry.entry_id}_ai_weekly_generate"
        self._attr_device_info = suunto_device_info(entry)

    async def async_press(self) -> None:
        """Generate; a failure surfaces in the UI as an error toast."""
        await self._weekly.async_generate()


class SuuntoSyncButton(ButtonEntity):
    """Fetch everything from Suunto now instead of waiting for the next poll.

    It refreshes both coordinators at once, the same requests a scheduled poll
    makes, with the stored session (no new login, so no login email). It cannot
    reach the watch: data only exists here once the watch has synced with the
    Suunto app. A press while a sync is still running is ignored.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "sync_now"

    def __init__(self, entry: SuuntoAppConfigEntry) -> None:
        """Initialize the button."""
        self._entry = entry
        self._lock = asyncio.Lock()
        self._attr_unique_id = f"{entry.entry_id}_sync_now"
        self._attr_device_info = suunto_device_info(entry)

    async def async_press(self) -> None:
        """Refresh both coordinators; a failure shows up as an error toast."""
        if self._lock.locked():
            return
        async with self._lock:
            data = self._entry.runtime_data
            await asyncio.gather(data.fast.async_refresh(), data.daily.async_refresh())
            if not (data.fast.last_update_success and data.daily.last_update_success):
                raise HomeAssistantError(
                    "Suunto sync failed, see the log; the next scheduled poll will try again"
                )
