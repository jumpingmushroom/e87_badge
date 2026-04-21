"""Tests for static-image encoding + text rendering."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from e87_badge.const import E87_IMAGE_HEIGHT, E87_IMAGE_WIDTH, E87_TARGET_IMAGE_BYTES
from e87_badge.media.image import encode_jpeg, render_text_image

CAPTURE_PNG = (
    Path(__file__).parent.parent
    / "docs" / "captures" / "01-solid-red-360.png"
)


def _is_jpeg(data: bytes) -> bool:
    return data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


def _dimensions(jpeg: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(jpeg)).size


def test_encode_from_path():
    assert CAPTURE_PNG.is_file()
    data = encode_jpeg(CAPTURE_PNG)
    assert _is_jpeg(data)
    assert len(data) <= E87_TARGET_IMAGE_BYTES
    assert _dimensions(data) == (E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT)


def test_encode_from_bytes():
    img = Image.new("RGB", (500, 200), (0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = encode_jpeg(buf.getvalue())
    assert _is_jpeg(data)
    assert _dimensions(data) == (E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT)


def test_encode_from_pil():
    img = Image.new("RGB", (1000, 1000), (10, 20, 30))
    data = encode_jpeg(img)
    assert _is_jpeg(data)
    assert _dimensions(data) == (E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT)


def test_render_text():
    data = render_text_image("Hi", size=96)
    assert _is_jpeg(data)
    assert _dimensions(data) == (E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT)
    # Text on black background should yield a non-uniform image.
    arr = list(Image.open(io.BytesIO(data)).convert("L").getdata())
    assert min(arr) < 50 and max(arr) > 150, "rendered text image appears flat"
