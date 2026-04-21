"""Tests for GIF → MJPG AVI conversion."""

from __future__ import annotations

import io
import struct

from PIL import Image

from e87_badge.media.gif import gif_to_avi


def _make_gif(n_frames: int, duration_ms: int = 100) -> bytes:
    frames = [Image.new("RGB", (360, 360), (i * 30, 0, 0)) for i in range(n_frames)]
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:],
        duration=duration_ms, loop=0,
    )
    return buf.getvalue()


def test_four_frame_gif_roundtrip():
    gif = _make_gif(4, duration_ms=100)
    avi = gif_to_avi(gif)
    i = avi.find(b"avih")
    total_frames = struct.unpack_from("<I", avi, i + 8 + 16)[0]
    assert total_frames == 4


def test_max_fps_clamp():
    # 50 ms per frame → 20 fps native. Clamp to 10.
    gif = _make_gif(3, duration_ms=50)
    avi = gif_to_avi(gif, max_fps=10)
    # dwRate in strh (offset 24 into strh body) is our fps.
    i = avi.find(b"strh")
    fps = struct.unpack_from("<I", avi, i + 8 + 24)[0]
    assert fps <= 10
