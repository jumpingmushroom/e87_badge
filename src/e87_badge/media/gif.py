"""Animated GIF → MJPG AVI.

Uses Pillow's `Image.seek(n)` to iterate frames. Per-frame durations in a
GIF are often highly variable; AVI uses a fixed fps, so we average the GIF
durations into a single fps clamped to `max_fps`.
"""

from __future__ import annotations

import io
import logging
import pathlib
from statistics import median

from PIL import Image, ImageSequence

from ..const import E87_IMAGE_HEIGHT, E87_IMAGE_WIDTH
from .avi import build_mjpg_avi
from .image import _center_square_368
from .slideshow import _encode_frame_jpeg

log = logging.getLogger(__name__)


def _load_gif(src: "str | pathlib.Path | bytes") -> Image.Image:
    if isinstance(src, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(src)))
    return Image.open(pathlib.Path(src))


def gif_to_avi(
    src: "str | pathlib.Path | bytes",
    *,
    max_fps: int = 24,
) -> bytes:
    """Convert a GIF to an MJPG AVI of 368² JPEG frames."""
    gif = _load_gif(src)

    jpeg_frames: list[bytes] = []
    durations_ms: list[int] = []

    for frame in ImageSequence.Iterator(gif):
        durations_ms.append(int(frame.info.get("duration", 100)))
        rgb = frame.convert("RGB")
        squared = _center_square_368(rgb)
        jpeg_frames.append(_encode_frame_jpeg(squared))

    if not jpeg_frames:
        raise ValueError(f"no frames in GIF: {src}")

    # Prefer median duration to avoid one outlier frame dominating.
    typical_ms = max(1, int(median(durations_ms)))
    fps = max(1, min(max_fps, round(1_000 / typical_ms)))

    log.info(
        "gif_to_avi: %d frames, median %d ms → fps=%d (max_fps=%d)",
        len(jpeg_frames), typical_ms, fps, max_fps,
    )
    return build_mjpg_avi(
        jpeg_frames, fps=fps, width=E87_IMAGE_WIDTH, height=E87_IMAGE_HEIGHT,
    )
