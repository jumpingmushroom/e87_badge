"""Standalone BLE discovery helpers (used by the CLI; HA passes a BLEDevice)."""

from __future__ import annotations

import logging

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from .const import (
    ADVERT_MANUFACTURER_ID,
    ADVERT_SERVICE_UUID_16,
    AE_SERVICE_UUID,
    LOCAL_NAME,
)

log = logging.getLogger(__name__)


def _looks_like_badge(device: BLEDevice, advertisement_data) -> bool:
    """Mirror the HA config-flow matcher (`config_flow._is_e87`).

    Match on the local name (scan-response only, needs active scan), the AE00
    or 0xFD00 service UUID, or the JieLi manufacturer ID — the latter two are
    passive-safe fingerprints, so a passive scanner that never sees the name
    still identifies the badge.
    """
    if (device.name or "").strip() == LOCAL_NAME:
        return True
    uuids = {
        u.lower()
        for u in (getattr(advertisement_data, "service_uuids", None) or [])
    }
    if AE_SERVICE_UUID.lower() in uuids or ADVERT_SERVICE_UUID_16.lower() in uuids:
        return True
    mfr = getattr(advertisement_data, "manufacturer_data", None) or {}
    return ADVERT_MANUFACTURER_ID in mfr


async def discover(timeout: float = 10.0) -> list[BLEDevice]:
    """Scan for E87 badges for up to `timeout` seconds."""
    discovered: dict[str, BLEDevice] = {}

    def detection_callback(device: BLEDevice, advertisement_data) -> None:
        if _looks_like_badge(device, advertisement_data):
            discovered[device.address] = device

    async with BleakScanner(detection_callback=detection_callback):
        import asyncio

        await asyncio.sleep(timeout)
    return list(discovered.values())


async def find_one(
    address: str | None = None,
    timeout: float = 15.0,
) -> BLEDevice | None:
    """Return the first matching badge, optionally filtered by MAC address."""
    if address is not None:
        return await BleakScanner.find_device_by_address(address, timeout=timeout)
    devices = await discover(timeout=timeout)
    return devices[0] if devices else None
