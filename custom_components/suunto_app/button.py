"""Button platform: sync now, and generate the AI insight on demand (see ai_insight.py)."""

from __future__ import annotations

import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SuuntoAppConfigEntry, suunto_device_info
from .ai_insight import SuuntoAiInsight
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuuntoAppConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Sync now always, the AI insight button only while it is configured."""
    async_add_entities([SuuntoSyncButton(entry)])
    insight = entry.runtime_data.ai
    if insight is not None:
        async_add_entities([SuuntoAiInsightButton(insight, entry)])
        return
    registry = er.async_get(hass)
    if entity_id := registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_ai_insight_generate"
    ):
        registry.async_remove(entity_id)


class SuuntoAiInsightButton(ButtonEntity):
    """Run the AI analysis now, even if today's is already done."""

    _attr_has_entity_name = True
    _attr_translation_key = "ai_insight_generate"
    _attr_icon = "mdi:creation-outline"

    def __init__(self, insight: SuuntoAiInsight, entry: SuuntoAppConfigEntry) -> None:
        """Initialize the button."""
        self._insight = insight
        self._attr_unique_id = f"{entry.entry_id}_ai_insight_generate"
        self._attr_device_info = suunto_device_info(entry)

    async def async_press(self) -> None:
        """Generate; a failure surfaces in the UI as an error toast."""
        await self._insight.async_generate()


class SuuntoSyncButton(ButtonEntity):
    """Fetch everything from Suunto now instead of waiting for the next poll.

    It refreshes both coordinators at once, the same requests a scheduled poll
    makes, with the stored session (no new login, so no login email). It cannot
    reach the watch: data only exists here once the watch has synced with the
    Suunto app. A press while a sync is still running is ignored.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "sync_now"
    _attr_icon = "mdi:sync"

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
