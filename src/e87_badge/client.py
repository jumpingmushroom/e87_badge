"""High-level `E87Client` — connects, authenticates, and dispatches upload
sessions. Accepts either a `bleak.BLEDevice` (HA's contract) or a MAC
address string (CLI convenience).
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import Any, Iterable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .auth import do_auth
from .const import (
    AE_NOTIFY_UUID,
    AE_WRITE_UUID,
    ALL_NOTIFY_UUIDS,
    EXTENSION_ANIMATED,
    EXTENSION_STATIC,
    FD_WRITE_UUID,
)
from .discovery import find_one
from .errors import E87ConnectError
from .frame import parse_fe_frame
from .notify import NotifyBus
from .protocol import UploadSession

log = logging.getLogger(__name__)

ImageInput = "str | pathlib.Path | bytes | Any"  # Any catches PIL.Image.Image without importing it at module scope


class E87Client:
    """Async context manager driving a single E87 badge.

    Parameters
    ----------
    device :
        Either a pre-resolved `bleak.BLEDevice` (the path Home Assistant
        uses, because habluetooth tracks which proxy currently sees the
        badge) or a MAC-address string (CLI / standalone use).
    """

    def __init__(self, device: BLEDevice | str) -> None:
        self._input = device
        self._client: BleakClient | None = None
        self._bus = NotifyBus()
        self._authed = False

    # ── async context ───────────────────────────────────────────────────

    async def __aenter__(self) -> "E87Client":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        target = await self._resolve_ble_device()

        def _on_notify(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            raw = bytes(data)
            f = parse_fe_frame(raw)
            if f is not None:
                log.debug(
                    "RX FE flag=0x%02x cmd=0x%02x len=%d body=%s",
                    f.flag, f.cmd, f.length, f.body.hex(),
                )
            else:
                log.debug("RX raw (%d): %s", len(raw), raw.hex())
            self._bus.push(raw)

        # Full-cycle retry loop. If the CCCD write for AE02 notify times out
        # at the ESPHome proxy (a common failure mode after a previous
        # connection didn't clean up), retrying start_notify on the same
        # BleakClient does nothing — the proxy's BLE stack is wedged on that
        # connection. Only a full disconnect/reconnect frees the slot.
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                self._client = await establish_connection(
                    BleakClient,
                    target,
                    name=getattr(target, "name", None) or str(target),
                    max_attempts=3,
                )
            except Exception as exc:
                raise E87ConnectError(f"could not connect to badge: {exc}") from exc

            log.info(
                "Connect attempt %d/3: connected, MTU=%s",
                attempt,
                getattr(self._client, "mtu_size", "?"),
            )
            try:
                await self._subscribe_ae02(_on_notify)
            except E87ConnectError as exc:
                last_exc = exc
                log.warning(
                    "Attempt %d/3: AE02 subscribe failed (%s); "
                    "disconnecting and retrying from scratch",
                    attempt,
                    exc,
                )
                await self._best_effort_disconnect()
                if attempt < 3:
                    await asyncio.sleep(3.0)  # let the proxy release the slot
                continue

            # AE02 OK — subscribe best-effort to the FD* side-channels
            await self._subscribe_side_channels(_on_notify)
            await asyncio.sleep(0.1)  # let queued notifications drain
            await do_auth(self._write_ae01, self._bus)
            self._authed = True
            return

        raise E87ConnectError(
            f"Could not establish a working session after 3 full reconnect "
            f"attempts: {last_exc}. Consider restarting the Bluetooth proxy "
            "or increasing its active_connections budget."
        )

    async def disconnect(self) -> None:
        await self._best_effort_disconnect()
        self._authed = False

    # ── Public send_* methods ──────────────────────────────────────────

    async def send_image(self, image: ImageInput) -> None:
        """Encode and send a static image. Accepts a path, bytes, or PIL Image."""
        from .media.image import encode_jpeg

        jpeg = encode_jpeg(image)
        await self._send_blob(jpeg, extension=EXTENSION_STATIC)

    async def send_text(
        self,
        text: str,
        *,
        font: str | None = None,
        size: int = 72,
        colour: str | tuple = "white",
        bg: str | tuple = "black",
    ) -> None:
        """Render `text` centered on a 368² frame and send as a static image."""
        from .media.image import render_text_image

        jpeg = render_text_image(text, font=font, size=size, colour=colour, bg=bg)
        await self._send_blob(jpeg, extension=EXTENSION_STATIC)

    async def send_slideshow(
        self,
        images: Iterable[ImageInput],
        *,
        frame_ms: int = 500,
        loop: bool = True,
    ) -> None:
        from .media.slideshow import build_slideshow

        avi = build_slideshow(images, frame_ms=frame_ms, loop=loop)
        await self._send_blob(avi, extension=EXTENSION_ANIMATED)

    async def send_gif(self, src: "str | pathlib.Path | bytes", *, max_fps: int = 24) -> None:
        from .media.gif import gif_to_avi

        avi = gif_to_avi(src, max_fps=max_fps)
        await self._send_blob(avi, extension=EXTENSION_ANIMATED)

    async def send_danmaku(
        self,
        text: str,
        *,
        fg: str | tuple = "white",
        bg: str | tuple = "black",
        font: str | None = None,
        font_size: int = 64,
        speed_px_per_frame: int = 4,
        fps: int = 20,
    ) -> None:
        from .media.danmaku import render_danmaku

        avi = render_danmaku(
            text,
            fg=fg,
            bg=bg,
            font=font,
            font_size=font_size,
            speed_px_per_frame=speed_px_per_frame,
            fps=fps,
        )
        await self._send_blob(avi, extension=EXTENSION_ANIMATED)

    # ── Internals ──────────────────────────────────────────────────────

    async def _send_blob(self, data: bytes, *, extension: str) -> None:
        if self._client is None or not self._authed:
            raise E87ConnectError("not connected — call connect() or use `async with`")
        session = UploadSession(self._write_ae01, self._write_fd02, self._bus)
        await session.run(data, extension=extension)

    async def _resolve_ble_device(self) -> BLEDevice | str:
        if isinstance(self._input, str):
            resolved = await find_one(address=self._input, timeout=15.0)
            if resolved is None:
                log.warning(
                    "Scanner did not surface %s; passing MAC directly to BleakClient",
                    self._input,
                )
                return self._input
            return resolved
        return self._input

    async def _write_ae01(self, data: bytes) -> None:
        assert self._client is not None
        await self._client.write_gatt_char(AE_WRITE_UUID, bytes(data), response=False)

    async def _write_fd02(self, data: bytes) -> None:
        assert self._client is not None
        try:
            await self._client.write_gatt_char(FD_WRITE_UUID, bytes(data), response=False)
        except Exception as exc:  # pragma: no cover - stack-dependent
            log.warning("FD02 write failed (%s): %s (continuing)", data.hex(), exc)

    async def _subscribe_ae02(self, callback) -> None:
        """Subscribe to AE02 exactly once. Raise E87ConnectError on failure.

        Retrying start_notify on the same BleakClient doesn't help when the
        proxy's BLE stack is wedged — only a full reconnect does. The outer
        retry loop in connect() handles that.
        """
        assert self._client is not None
        try:
            await self._client.start_notify(AE_NOTIFY_UUID, callback)
            log.info("Subscribed to notifications on %s", AE_NOTIFY_UUID)
        except Exception as exc:  # pragma: no cover - stack-dependent
            raise E87ConnectError(
                f"Could not subscribe to the badge's notification channel "
                f"({AE_NOTIFY_UUID}): {exc}"
            ) from exc

    async def _subscribe_side_channels(self, callback) -> None:
        """Subscribe to JieLi FD01 / FD03 / FD05 notifications (best-effort).

        These only carry JieLi RCSP device-info and bootstrap signals that
        the upload flow already tolerates missing.
        """
        assert self._client is not None
        for uuid in ALL_NOTIFY_UUIDS:
            if uuid == AE_NOTIFY_UUID:
                continue
            try:
                await self._client.start_notify(uuid, callback)
                log.info("Subscribed to notifications on %s", uuid)
            except Exception as exc:  # pragma: no cover - stack-dependent
                log.warning("start_notify failed on %s: %s (continuing)", uuid, exc)

    async def _best_effort_disconnect(self) -> None:
        """Tear down the current client without raising."""
        if self._client is None:
            return
        for uuid in ALL_NOTIFY_UUIDS:
            try:
                await self._client.stop_notify(uuid)
            except Exception:
                pass
        try:
            await self._client.disconnect()
        except Exception:
            pass
        self._client = None
