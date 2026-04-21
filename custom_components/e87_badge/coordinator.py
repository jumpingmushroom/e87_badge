"""Coordinator for the E87 Smart Digital Badge integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from e87_badge import E87Client

_LOGGER = logging.getLogger(__name__)

type E87ConfigEntry = ConfigEntry["E87Coordinator"]


class E87Coordinator(ActiveBluetoothDataUpdateCoordinator[None]):
    """Coordinator that serialises send operations against a single E87 badge."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        """Initialise the coordinator for a given MAC address."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            address=address,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_update,
            mode=BluetoothScanningMode.ACTIVE,
            connectable=True,
        )
        self.last_sent_at: datetime | None = None
        self.last_sent_type: str | None = None
        self._lock = asyncio.Lock()

    @property
    def last_service_info(self) -> bluetooth.BluetoothServiceInfoBleak | None:
        """Expose the freshest advertisement the base class has seen.

        `ActiveBluetoothDataUpdateCoordinator._async_handle_bluetooth_event`
        writes `_last_service_info` on every advert, regardless of polling.
        Reading that directly gives us live RSSI + proxy-source data without
        piggybacking on `_needs_poll` (which fires only when HA evaluates a
        poll — and we always say "no poll needed").
        """
        return getattr(self, "_last_service_info", None)

    @callback
    def _needs_poll(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        last_poll: float | None,
    ) -> bool:
        """Never poll — badge is push-only."""
        return False

    async def _async_update(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """No-op poll method (required by base class but never called)."""
        return None

    async def _run(
        self,
        send_type: str,
        do_send: Callable[[E87Client], Awaitable[Any]],
    ) -> None:
        """Serialise a send operation against the badge."""
        async with self._lock:
            ble = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if ble is None:
                raise HomeAssistantError(
                    f"No Bluetooth proxy currently sees {self.address}"
                )
            try:
                async with E87Client(ble) as client:
                    await do_send(client)
            except Exception as exc:  # noqa: BLE001 — surface any library error
                raise HomeAssistantError(f"{send_type} failed: {exc}") from exc
            self.last_sent_at = dt_util.utcnow()
            self.last_sent_type = send_type
            self.async_update_listeners()

    async def send_image(self, image: Any) -> None:
        """Send a single image."""
        await self._run("image", lambda c: c.send_image(image))

    async def send_text(self, text: str, **opts: Any) -> None:
        """Render and send text."""
        await self._run("text", lambda c: c.send_text(text, **opts))

    async def send_slideshow(self, images: list[Any], **opts: Any) -> None:
        """Send a slideshow of frames."""
        await self._run("slideshow", lambda c: c.send_slideshow(images, **opts))

    async def send_gif(self, src: Any, **opts: Any) -> None:
        """Send an animated GIF."""
        await self._run("gif", lambda c: c.send_gif(src, **opts))

    async def send_danmaku(self, text: str, **opts: Any) -> None:
        """Send a danmaku-style scrolling text."""
        await self._run("danmaku", lambda c: c.send_danmaku(text, **opts))
