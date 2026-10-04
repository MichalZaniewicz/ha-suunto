"""Switch platform: pause or resume the automatic AI insight (see ai_insight.py)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
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
    """Add the switch only while the AI insight is configured."""
    insight = entry.runtime_data.ai
    if insight is not None:
        async_add_entities([SuuntoAiInsightSwitch(insight, entry)])
        return
    registry = er.async_get(hass)
    if entity_id := registry.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_ai_insight_enabled"
    ):
        registry.async_remove(entity_id)


class SuuntoAiInsightSwitch(SwitchEntity):
    """On: the analysis runs by itself every day. Off: only from the button."""

    _attr_has_entity_name = True
    _attr_translation_key = "ai_insight_enabled"
    _attr_should_poll = False

    def __init__(self, insight: SuuntoAiInsight, entry: SuuntoAppConfigEntry) -> None:
        """Initialize the switch."""
        self._insight = insight
        self._attr_unique_id = f"{entry.entry_id}_ai_insight_enabled"
        self._attr_device_info = suunto_device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Follow the insight's updates."""
        self.async_on_remove(self._insight.async_add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        """Return whether automatic runs are on."""
        return self._insight.enabled

    @property
    def icon(self) -> str:
        """Filled sparkles while on, outlined while paused."""
        return "mdi:creation" if self._insight.enabled else "mdi:creation-outline"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Resume automatic runs."""
        await self._insight.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause automatic runs."""
        await self._insight.async_set_enabled(False)
