"""E87 Smart Digital Badge integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import E87ConfigEntry, E87Coordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: E87ConfigEntry) -> bool:
    """Set up an E87 badge from a config entry.

    We intentionally do NOT gate setup on the badge being currently visible:
    this device advertises infrequently and competes with other BLE clients
    for proxy attention, so the entry should load whether or not a scanner
    has heard from it in the last few seconds. The sensor exposes
    availability via the coordinator, and actual send_* calls re-check
    reachability at invocation time and raise HomeAssistantError if no
    proxy can currently route to the badge.
    """
    address: str = entry.data[CONF_ADDRESS]

    if bluetooth.async_ble_device_from_address(hass, address, connectable=True) is None:
        _LOGGER.info(
            "E87 badge at %s is not currently visible to any Bluetooth "
            "adapter or proxy; setting up anyway — the sensor will become "
            "available once adverts are received",
            address,
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
