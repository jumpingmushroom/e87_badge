"""E87 Smart Digital Badge integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import E87ConfigEntry, E87Coordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: E87ConfigEntry) -> bool:
    """Set up an E87 badge from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if ble_device is None:
        raise ConfigEntryNotReady(
            f"E87 badge at {address} is not currently visible to any "
            "Bluetooth adapter or proxy"
        )

    coordinator = E87Coordinator(hass, address)
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_start())

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once, on the first entry setup.
    if not hass.services.has_service(DOMAIN, "send_image"):
        async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: E87ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # If this was the last E87 entry, tear the services back down.
    remaining = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not remaining:
        async_unload_services(hass)

    return unloaded
