"""Binary sensor entities for CT002 Grid Meter Emulator."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CT002EmulatorCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CT002 emulator binary sensors from a config entry."""
    coordinator: CT002EmulatorCoordinator = entry.runtime_data

    async_add_entities(
        [
            CT002EmulatorRunningSensor(coordinator, entry),
        ]
    )


class CT002EmulatorRunningSensor(
    BinarySensorEntity, CoordinatorEntity[CT002EmulatorCoordinator]
):
    """Binary sensor showing if the UDP server is active."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "server_active"

    def __init__(
        self,
        coordinator: CT002EmulatorCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{coordinator.ct_mac}_server_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.ct_mac)},
            name=coordinator._name,
            manufacturer="CT002 Emulator",
            model="Grid Meter",
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the server is active."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("server_active")
