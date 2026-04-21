"""Sensor platform for the E87 Smart Digital Badge."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import E87ConfigEntry, E87Coordinator


async def async_setup_entry(
    hass: Any,
    entry: E87ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the E87 sensor platform from a config entry."""
    coordinator: E87Coordinator = entry.runtime_data
    async_add_entities([E87StatusSensor(coordinator, entry)])


class E87StatusSensor(CoordinatorEntity[E87Coordinator], SensorEntity):
    """Status sensor exposing availability, last send, and proxy/RSSI data."""

    _attr_has_entity_name = True
    _attr_name = "E87 Badge Status"

    def __init__(self, coordinator: E87Coordinator, entry: E87ConfigEntry) -> None:
        """Initialise the status sensor."""
        super().__init__(coordinator)
        address = coordinator.address
        self._attr_unique_id = f"{entry.unique_id}-status"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            identifiers={(DOMAIN, address)},
            name=entry.title,
            manufacturer="E87",
            model="Smart Digital Badge",
        )

    @property
    def available(self) -> bool:
        """Return True if the coordinator currently sees the badge."""
        return self.coordinator.available

    @property
    def native_value(self) -> str:
        """Return 'available' or 'unavailable' based on coordinator state."""
        return "available" if self.coordinator.available else "unavailable"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes: last send metadata + RSSI + proxy source."""
        service_info = self.coordinator.last_service_info
        last_sent_at = self.coordinator.last_sent_at
        return {
            "last_sent_at": last_sent_at.isoformat() if last_sent_at else None,
            "last_sent_type": self.coordinator.last_sent_type,
            "rssi": service_info.rssi if service_info else None,
            "proxy_source": service_info.source if service_info else None,
        }
