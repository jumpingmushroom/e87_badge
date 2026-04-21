"""Standalone BLE discovery helpers (used by the CLI; HA passes a BLEDevice)."""

from __future__ import annotations

import logging
from typing import Iterable

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from .const import AE_SERVICE_UUID, LOCAL_NAME

log = logging.getLogger(__name__)


def _looks_like_badge(device: BLEDevice, advertised_uuids: Iterable[str]) -> bool:
    if (device.name or "").strip() == LOCAL_NAME:
        return True
    return AE_SERVICE_UUID.lower() in {u.lower() for u in advertised_uuids}


async def discover(timeout: float = 10.0) -> list[BLEDevice]:
    """Scan for E87 badges for up to `timeout` seconds."""
    discovered: dict[str, BLEDevice] = {}

    def detection_callback(device: BLEDevice, advertisement_data) -> None:
        uuids = getattr(advertisement_data, "service_uuids", None) or []
        if _looks_like_badge(device, uuids):
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
