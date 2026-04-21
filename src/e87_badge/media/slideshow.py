"""Multi-image slideshow → MJPG AVI.

Each input image is center-cropped to a square, resized to 368², re-encoded as
a JPEG at a quality bracket that keeps the per-frame size small, then the
sequence is wrapped into an MJPG AVI. Slideshow duration-per-frame is
expressed in milliseconds; the AVI's fps is derived from that.
"""

from __future__ import annotations

import io
import logging
import pathlib
from typing import Iterable

from PIL import Image

from ..const import (
    E87_IMAGE_HEIGHT,
    E87_IMAGE_WIDTH,
    JPEG_QUALITY_STEPS,
)
from .avi import build_mjpg_avi
from .image import _center_square_368, _load_to_rgb

log = logging.getLogger(__name__)


def _encode_frame_jpeg(img: Image.Image, *, max_bytes: int = 32_000) -> bytes:
    """Encode a single 368² frame as JPEG, staying under `max_bytes`."""
    best: bytes | None = None
    for quality in JPEG_QUALITY_STEPS:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        best = data
        if len(data) <= max_bytes:
            return data
    assert best is not None
    return best


def build_slideshow(
    images: "Iterable[str | pathlib.Path | bytes | Image.Image]",
    *,
    frame_ms: int = 500,
    loop: bool = True,
) -> bytes:
    """Turn a list of images into an MJPG-AVI slideshow.

    Parameters
    ----------
    images :
        Iterable of image inputs (path, bytes, or PIL Image).
    frame_ms :
        Duration each frame is displayed. Clamped so fps ≥ 1.
    loop :
        Ignored in v1 — the badge loops AVI files natively. Retained for
        API forward compatibility.
    """
    if frame_ms <= 0:
        raise ValueError("frame_ms must be > 0")

    # fps ≈ 1000 / frame_ms, clamped to [1, 60]
    fps = max(1, min(60, round(1_000 / frame_ms)))

    frames: list[bytes] = []
    for src in images:
        img = _load_to_rgb(src)
        squared = _center_square_368(img)
        frames.append(_encode_frame_jpeg(squared))

    if not frames:
        raise ValueError("build_slideshow requires at least one image")

    log.info("slideshow: %d frames @ %d fps (%d ms/frame target)", len(frames), fps, frame_ms)
    return build_mjpg_avi(
        frames, fps=fps, width=E87_IMAGE_WIDTH, height=E87_IMAGE_HEIGHT,
    )
