"""Image platform: the route of the last workout (route_image.py).

For a notification ("image: /api/image_proxy/image.<...>_route") or a
picture card. Drawn from the GPS track the integration already holds, so no
request goes to Suunto; redrawn only when the last workout changes. An indoor
workout has no route, so the image is empty then.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SuuntoAppConfigEntry, suunto_device_info
from .route_image import render


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuuntoAppConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the route image."""
    async_add_entities([SuuntoRouteImage(hass, entry.runtime_data.daily, entry)])


class SuuntoRouteImage(CoordinatorEntity, ImageEntity):
    """The last workout's route, coloured by speed."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_workout_route"
    _attr_content_type = "image/png"

    def __init__(self, hass: HomeAssistant, coordinator: Any, entry: SuuntoAppConfigEntry) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{entry.entry_id}_last_workout_route"
        self._attr_device_info = suunto_device_info(entry)
        self._drawn_for: tuple[Any, int] | None = None
        self._image: bytes | None = None
        self._sync_route()

    def _workout(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("workout") or {}

    def _route_id(self) -> tuple[Any, int]:
        workout = self._workout()
        return (workout.get("key") or workout.get("start_time"), len(workout.get("route") or []))

    def _sync_route(self) -> None:
        """A new workout (or its track arriving later): draw it again."""
        route_id = self._route_id()
        if route_id != self._drawn_for:
            self._drawn_for = route_id
            self._image = None
            start = self._workout().get("start_time")
            self._attr_image_last_updated = start if start else dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync_route()
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        workout = self._workout()
        return {
            "activity": workout.get("activity"),
            "has_route": bool(workout.get("route")),
        }

    async def async_image(self) -> bytes | None:
        """The PNG (SVG without Pillow), drawn once per workout."""
        if self._image is None:
            route = self._workout().get("route") or []
            drawn = await self.hass.async_add_executor_job(render, route)
            if drawn is None:
                return None
            self._image, self._attr_content_type = drawn
        return self._image
