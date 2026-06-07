"""The Suunto App (unofficial) integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SportsTrackerClient
from .const import (
    CONF_FAST_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_KEY,
    DEFAULT_FAST_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    PLATFORMS,
)
from .coordinator import SuuntoActivityCoordinator, SuuntoDailyCoordinator


@dataclass
class SuuntoAppRuntimeData:
    """Holds both coordinators for a config entry."""

    fast: SuuntoActivityCoordinator
    daily: SuuntoDailyCoordinator


type SuuntoAppConfigEntry = ConfigEntry[SuuntoAppRuntimeData]


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
