"""The Suunto App (unofficial) integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo

from .api import SportsTrackerClient
from .const import (
    CONF_FAST_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_KEY,
    DEFAULT_FAST_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SuuntoActivityCoordinator, SuuntoDailyCoordinator


@dataclass
class SuuntoAppRuntimeData:
    """Holds both coordinators for a config entry."""

    fast: SuuntoActivityCoordinator
    daily: SuuntoDailyCoordinator


type SuuntoAppConfigEntry = ConfigEntry[SuuntoAppRuntimeData]


def suunto_device_info(entry: SuuntoAppConfigEntry) -> DeviceInfo:
    """Shared device descriptor for every Suunto App entity (one device/entry).

    Model/manufacturer come from the last workout's recorded gear
    (SummaryExtension.gear), read off the daily coordinator's data at entity
    setup time - which runs after its first refresh (see async_setup_entry
    below), so this reflects real data on everything but a brand-new account
    with no workout history yet. If the model becomes known (or changes) on a
    later cycle, the daily coordinator pushes that update straight into the
    device registry itself (see SuuntoDailyCoordinator._sync_device_registry).
    """
    daily_data = entry.runtime_data.daily.data if entry.runtime_data else None
    device = (daily_data or {}).get("device") or {}
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=device.get("manufacturer") or "Suunto",
        model=device.get("model") or "Suunto App (unofficial)",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: SuuntoAppConfigEntry
) -> bool:
    """Set up the integration from a config entry."""
    # Only the revocable session key is used at runtime; no password is stored.
    client = SportsTrackerClient(
        async_get_clientsession(hass),
        entry.data[CONF_SESSION_KEY],
    )

    fast_minutes = entry.options.get(
        CONF_FAST_SCAN_INTERVAL, DEFAULT_FAST_SCAN_INTERVAL_MINUTES
    )
    daily_minutes = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
    )

    fast = SuuntoActivityCoordinator(
        hass, entry, client, timedelta(minutes=fast_minutes)
    )
    daily = SuuntoDailyCoordinator(
        hass, entry, client, timedelta(minutes=daily_minutes)
    )
    await fast.async_config_entry_first_refresh()
    await daily.async_config_entry_first_refresh()

    entry.runtime_data = SuuntoAppRuntimeData(fast=fast, daily=daily)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SuuntoAppConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: SuuntoAppConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
