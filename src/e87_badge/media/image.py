"""Static-image encoding and text rendering — both return JPEG bytes ready
for transmission as an `extension="jpg"` blob."""

from __future__ import annotations

import io
import logging
import pathlib
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..const import (
    E87_IMAGE_HEIGHT,
    E87_IMAGE_WIDTH,
    E87_TARGET_IMAGE_BYTES,
    JPEG_QUALITY_STEPS,
)

log = logging.getLogger(__name__)


def _load_to_rgb(src: "str | pathlib.Path | bytes | Image.Image") -> Image.Image:
    if isinstance(src, Image.Image):
        return src.convert("RGB")
    if isinstance(src, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(src))).convert("RGB")
    path = pathlib.Path(src)
    with Image.open(path) as img:
        img.load()
        return img.convert("RGB")


def _center_square_368(img: Image.Image) -> Image.Image:
    w, h = img.size
    min_side = min(w, h)
    sx = (w - min_side) // 2
    sy = (h - min_side) // 2
    cropped = img.crop((sx, sy, sx + min_side, sy + min_side))
    resized = cropped.resize(
        (E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT),
        resample=Image.Resampling.LANCZOS,
    )
    backdrop = Image.new("RGB", resized.size, (0, 0, 0))
    backdrop.paste(resized, (0, 0))
    return backdrop


def _encode_jpeg_bracketed(img: Image.Image, *, target_bytes: int) -> bytes:
    best: bytes | None = None
    for quality in JPEG_QUALITY_STEPS:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        best = data
        if len(data) <= target_bytes:
            log.info("Encoded JPEG: quality=%d size=%d bytes", quality, len(data))
            return data
    assert best is not None
    log.info(
        "Encoded JPEG: size=%d bytes (exceeds target %d; lowest quality used)",
        len(best), target_bytes,
    )
    return best


def encode_jpeg(
    src: "str | pathlib.Path | bytes | Image.Image",
    *,
    target_bytes: int = E87_TARGET_IMAGE_BYTES,
) -> bytes:
    """Encode `src` as a 368×368 JPEG suitable for a still-image upload."""
    img = _load_to_rgb(src)
    squared = _center_square_368(img)
    return _encode_jpeg_bracketed(squared, target_bytes=target_bytes)


# ── Text rendering ─────────────────────────────────────────────────────────

_DEFAULT_FONT_CANDIDATES = (
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def _load_font(font: str | None, size: int) -> ImageFont.ImageFont:
    if font is not None:
        return ImageFont.truetype(font, size=size)
    for cand in _DEFAULT_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(cand, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_text_image(
    text: str,
    *,
    font: str | None = None,
    size: int = 72,
    colour: "str | tuple" = "white",
    bg: "str | tuple" = "black",
) -> bytes:
    """Render `text` centered onto a 368² frame, return JPEG bytes."""
    img = Image.new("RGB", (E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT), bg)
    draw = ImageDraw.Draw(img)
    fnt = _load_font(font, size)
    # Pillow's textbbox returns (x0, y0, x1, y1) for text anchored at (0, 0)
    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (E87_IMAGE_WIDTH - tw) // 2 - bbox[0]
    y = (E87_IMAGE_HEIGHT - th) // 2 - bbox[1]
    draw.text((x, y), text, font=fnt, fill=colour)
    return _encode_jpeg_bracketed(img, target_bytes=E87_TARGET_IMAGE_BYTES)


def render_text_frame_rgb(
    text: str,
    *,
    canvas_width: int,
    canvas_height: int = E87_IMAGE_HEIGHT,
    font: str | None = None,
    size: int = 64,
    colour: "str | tuple" = "white",
    bg: "str | tuple" = "black",
    offset_x: int = 0,
) -> Image.Image:
    """Render `text` at `(offset_x, centered y)` on a fresh canvas of the
    given width. Used by the danmaku renderer."""
    img = Image.new("RGB", (canvas_width, canvas_height), bg)
    draw = ImageDraw.Draw(img)
    fnt = _load_font(font, size)
    bbox = draw.textbbox((0, 0), text, font=fnt)
    th = bbox[3] - bbox[1]
    y = (canvas_height - th) // 2 - bbox[1]
    draw.text((offset_x - bbox[0], y), text, font=fnt, fill=colour)
    return img
