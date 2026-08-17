"""The CT002 Grid Meter Emulator integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import CT002EmulatorCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CT002 Grid Meter Emulator from a config entry."""
    coordinator = CT002EmulatorCoordinator(hass, entry)

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await coordinator.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator: CT002EmulatorCoordinator = entry.runtime_data
    coordinator.update_options()
    await coordinator.async_stop()
    await coordinator.async_start()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: CT002EmulatorCoordinator = entry.runtime_data
    await coordinator.async_stop()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
