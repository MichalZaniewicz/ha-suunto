"""Gear service as a to-do list.

One item per piece of gear set up under Configure > Gear (chain, tyres,
shoes). An item is "to do" once its service interval is reached and done
otherwise; its description shows the distance so far against the interval.
Ticking a "to do" item off is the same as Configure > Gear service: the
gear's counter starts again from 0 km. Items can't be added, renamed or
deleted here; the list mirrors Configure > Gear.

The list exists only while some gear is set up. Changing the gear reloads
the entry, so the list is always current.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SuuntoAppConfigEntry, suunto_device_info
from .const import CONF_GEAR, DOMAIN
from .coordinator import gear_after_service


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuuntoAppConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the gear service list while gear is set up."""
    if any(g.get("id") for g in entry.options.get(CONF_GEAR) or []):
        async_add_entities([SuuntoGearServiceList(entry.runtime_data.daily, entry)])
    elif entity_id := er.async_get(hass).async_get_entity_id(
        "todo", DOMAIN, f"{entry.entry_id}_gear_service"
    ):
        er.async_get(hass).async_remove(entity_id)


def _km(value: Any) -> str:
    return f"{round(value):,}".replace(",", " ") if isinstance(value, (int, float)) else "?"


class SuuntoGearServiceList(CoordinatorEntity, TodoListEntity):
    """Gear due for a service, ticked off when it has been done."""

    _attr_has_entity_name = True
    _attr_translation_key = "gear_service"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coordinator: Any, entry: SuuntoAppConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_gear_service"
        self._attr_device_info = suunto_device_info(entry)

    @property
    def todo_items(self) -> list[TodoItem]:
        snapshot = (self.coordinator.data or {}).get("gear") or {}
        items = []
        for gear in self._entry.options.get(CONF_GEAR) or []:
            gear_id = gear.get("id")
            if not gear_id:
                continue
            state = snapshot.get(gear_id) or {}
            distance, interval = state.get("distance_km"), state.get("interval_km")
            description = (
                f"{_km(distance)} / {_km(interval)} km"
                if interval
                else f"{_km(distance)} km"
            )
            if state.get("activity"):
                description += f" · {state['activity']}"
            items.append(
                TodoItem(
                    uid=gear_id,
                    summary=gear.get("name") or "Gear",
                    status=(
                        TodoItemStatus.NEEDS_ACTION
                        if state.get("service_due")
                        else TodoItemStatus.COMPLETED
                    ),
                    description=description,
                )
            )
        return items

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Ticked off: the service was done, so the counter starts again."""
        current = next((i for i in self.todo_items if i.uid == item.uid), None)
        if current is None:
            raise HomeAssistantError(f"No gear with id {item.uid}")
        if item.status == TodoItemStatus.COMPLETED and current.status == TodoItemStatus.NEEDS_ACTION:
            by_activity = ((self.coordinator.data or {}).get("stats") or {}).get("by_activity")
            if not by_activity:
                # Without the lifetime totals the new starting point is
                # unknown; resetting now would count the gear's old km again.
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="gear_totals_missing"
                )
            gear = gear_after_service(
                list(self._entry.options.get(CONF_GEAR) or []), item.uid, by_activity
            )
            # Saving the options reloads the entry, which rebuilds the list.
            self.hass.config_entries.async_update_entry(
                self._entry, options={**self._entry.options, CONF_GEAR: gear}
            )
            return
        # Anything else (unticking, a rename) has no meaning here: show the
        # list as it really is again.
        self.async_write_ha_state()
