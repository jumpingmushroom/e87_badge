"""Constants for the E87 badge BLE protocol.

GATT service/characteristic UUIDs, FE-framing magic bytes, flag values, image
and transfer defaults. No runtime logic.
"""

from __future__ import annotations

# ── Advertising ────────────────────────────────────────────────────────────

LOCAL_NAME = "E87"
"""The badge's GAP local name in the scan response — used for HA auto-discovery."""


# ── Primary image-upload service (AE00) ────────────────────────────────────

AE_SERVICE_UUID = "0000ae00-0000-1000-8000-00805f9b34fb"
AE_WRITE_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
AE_NOTIFY_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"


# ── JieLi RCSP side-channel service (FD00) ─────────────────────────────────

FD_SERVICE_UUID = "c2e6fd00-e966-1000-8000-bef9c223df6a"
FD_WRITE_UUID = "c2e6fd02-e966-1000-8000-bef9c223df6a"
FD_NOTIFY_UUIDS: tuple[str, ...] = (
    "c2e6fd01-e966-1000-8000-bef9c223df6a",
    "c2e6fd03-e966-1000-8000-bef9c223df6a",
    "c2e6fd05-e966-1000-8000-bef9c223df6a",
)


ALL_NOTIFY_UUIDS: tuple[str, ...] = (AE_NOTIFY_UUID,) + FD_NOTIFY_UUIDS
"""Every notify UUID we subscribe to during auth + upload."""


# ── Image encoding targets ──────────────────────────────────────────────────

E87_IMAGE_WIDTH = 368
E87_IMAGE_HEIGHT = 368
E87_TARGET_IMAGE_BYTES = 16_000
"""Upstream image-processing.ts targets ≤16 KB for a single-image JPEG."""

JPEG_QUALITY_STEPS: tuple[int, ...] = (88, 80, 72, 64, 56, 48, 40, 34)
"""Descending JPEG quality values tried when encoding, to stay under target size."""


# ── FE-framed wire protocol ────────────────────────────────────────────────

FE_HEADER = b"\xfe\xdc\xba"
FE_TERMINATOR = 0xEF

FLAG_COMMAND = 0xC0
"""Phone→device request (or device→phone async command)."""

FLAG_RESPONSE = 0x00
"""Acknowledgement / response to a previous command."""

FLAG_DATA = 0x80
"""Data-bearing frame or data-channel notification (e.g. window ack cmd 0x1D)."""


# ── File-transfer defaults ──────────────────────────────────────────────────

E87_DATA_CHUNK_SIZE = 490
"""Default per-chunk payload in a cmd 0x01 data frame. The device advertises
its preferred value in the cmd 0x1B ack; honour that when present, fall back
to this default otherwise."""

EXTENSION_STATIC = "jpg"
"""Filename extension used in cmd 0x1B + cmd 0x20 path for a single static image."""

EXTENSION_ANIMATED = "avi"
"""Filename extension for any MJPG-AVI: slideshow, GIF, danmaku, video."""
