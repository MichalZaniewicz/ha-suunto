"""Button platform: generate the AI insight on demand (see ai_insight.py)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Add the button only while the AI insight is configured."""
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
