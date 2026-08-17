"""Switch entity for CT002 Grid Meter Emulator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CT002EmulatorCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CT002 emulator switch from a config entry."""
    coordinator: CT002EmulatorCoordinator = entry.runtime_data

    async_add_entities([CT002EmulatorSwitch(coordinator, entry)])


class CT002EmulatorSwitch(SwitchEntity, CoordinatorEntity[CT002EmulatorCoordinator]):
    """Switch to enable/disable the CT002 UDP server."""

    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "enabled"

    def __init__(
        self,
        coordinator: CT002EmulatorCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.ct_mac}_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.ct_mac)},
            name=coordinator._name,
            manufacturer="CT002 Emulator",
            model="Grid Meter",
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the server is enabled."""
        return self.coordinator.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the CT002 server."""
        self.coordinator.set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the CT002 server."""
        self.coordinator.set_enabled(False)
