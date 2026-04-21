"""Scrolling-text danmaku → MJPG AVI.

Renders the full string onto a long horizontal canvas (bg colour + text in
fg colour), then captures 368×368 windows stepping right by
`speed_px_per_frame` each frame. Each window is encoded as JPEG and packed
into an MJPG AVI at `fps`. The AVI loops on the badge, so the scroll
repeats indefinitely.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageDraw

from ..const import E87_IMAGE_HEIGHT, E87_IMAGE_WIDTH
from .avi import build_mjpg_avi
from .image import _load_font
from .slideshow import _encode_frame_jpeg

log = logging.getLogger(__name__)


def render_danmaku(
    text: str,
    *,
    fg: "str | tuple" = "white",
    bg: "str | tuple" = "black",
    font: str | None = None,
    font_size: int = 64,
    speed_px_per_frame: int = 4,
    fps: int = 20,
    lead_blank_frames: int = 8,
) -> bytes:
    """Return MJPG-AVI bytes of a scrolling-text animation."""
    if not text:
        raise ValueError("danmaku text is empty")
    if speed_px_per_frame <= 0:
        raise ValueError("speed_px_per_frame must be > 0")
    if fps <= 0:
        raise ValueError("fps must be > 0")

    # Measure the rendered text once, then build the long canvas.
    fnt = _load_font(font, font_size)
    measure = Image.new("RGB", (10, 10), bg)
    mdraw = ImageDraw.Draw(measure)
    bbox = mdraw.textbbox((0, 0), text, font=fnt)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Canvas is wide enough to pad a full screen on each end so the text
    # scrolls in from the right and fully off the left.
    canvas_w = E87_IMAGE_WIDTH * 2 + text_w
    canvas = Image.new("RGB", (canvas_w, E87_IMAGE_HEIGHT), bg)
    cdraw = ImageDraw.Draw(canvas)
    draw_x = E87_IMAGE_WIDTH - bbox[0]
    draw_y = (E87_IMAGE_HEIGHT - text_h) // 2 - bbox[1]
    cdraw.text((draw_x, draw_y), text, font=fnt, fill=fg)

    # Slide a 368-wide window across the canvas.
    total_scroll_px = canvas_w - E87_IMAGE_WIDTH
    frames: list[bytes] = []
    for _ in range(lead_blank_frames):
        blank = Image.new("RGB", (E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT), bg)
        frames.append(_encode_frame_jpeg(blank))
    offset = 0
    while offset <= total_scroll_px:
        window = canvas.crop(
            (offset, 0, offset + E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT)
        )
        frames.append(_encode_frame_jpeg(window))
        offset += speed_px_per_frame

    log.info(
        "danmaku: text=%r canvas=%dx%d frames=%d fps=%d",
        text, canvas_w, E87_IMAGE_HEIGHT, len(frames), fps,
    )
    return build_mjpg_avi(
        frames, fps=fps, width=E87_IMAGE_WIDTH, height=E87_IMAGE_HEIGHT,
    )
