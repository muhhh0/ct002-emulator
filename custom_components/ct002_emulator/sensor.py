"""Sensor entities for CT002 Grid Meter Emulator."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
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
    """Set up CT002 emulator sensors from a config entry."""
    coordinator: CT002EmulatorCoordinator = entry.runtime_data

    async_add_entities(
        [
            CT002EmulatorPowerSensor(coordinator, entry),
            CT002EmulatorTimestampSensor(coordinator, entry),
        ]
    )


class CT002EmulatorSensorBase(
    SensorEntity, CoordinatorEntity[CT002EmulatorCoordinator]
):
    """Base class for CT002 emulator sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CT002EmulatorCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.ct_mac)},
            name=coordinator._name,
            manufacturer="CT002 Emulator",
            model="Grid Meter",
        )


class CT002EmulatorPowerSensor(CT002EmulatorSensorBase):
    """Sensor for the last reported power value."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_translation_key = "last_reported_power"

    def __init__(
        self,
        coordinator: CT002EmulatorCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{coordinator.ct_mac}_last_reported_power"
        self._attr_device_info = self._device_info

    @property
    def native_value(self) -> int | None:
        """Return the last reported power value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("last_reported_power")


class CT002EmulatorTimestampSensor(CT002EmulatorSensorBase):
    """Sensor for the last packet timestamp."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_packet_timestamp"

    def __init__(
        self,
        coordinator: CT002EmulatorCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{coordinator.ct_mac}_last_packet_timestamp"
        self._attr_device_info = self._device_info

    @property
    def native_value(self) -> datetime | None:
        """Return the last packet timestamp."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("last_packet_timestamp")
