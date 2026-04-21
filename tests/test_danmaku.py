"""Tests for the danmaku scrolling-text renderer."""

from __future__ import annotations

import io
import struct

import pytest
from PIL import Image

from e87_badge.media.danmaku import render_danmaku


def test_empty_text_rejected():
    with pytest.raises(ValueError):
        render_danmaku("")


def test_bad_speed_rejected():
    with pytest.raises(ValueError):
        render_danmaku("hi", speed_px_per_frame=0)


def test_hello_world_produces_frames():
    avi = render_danmaku("Hello World", font_size=48, speed_px_per_frame=8, fps=10,
                        lead_blank_frames=2)
    i = avi.find(b"avih")
    total_frames = struct.unpack_from("<I", avi, i + 8 + 16)[0]
    assert total_frames > 3, f"expected multiple scroll frames, got {total_frames}"


def test_first_and_last_frames_differ():
    """A scrolling animation must not produce identical first/last frames."""
    avi = render_danmaku("ABCDE", font_size=64, speed_px_per_frame=8, fps=10,
                        lead_blank_frames=0)

    # Locate the movi LIST, then the first and last 00dc chunks inside it.
    movi_idx = avi.find(b"movi")
    assert movi_idx > 0
    cursor = movi_idx + 4  # skip the 'movi' FOURCC (inside the LIST payload)
    jpegs: list[bytes] = []
    while True:
        marker = avi.find(b"00dc", cursor)
        if marker < 0 or marker >= movi_idx + 5742:  # cap search in movi region
            break
        length = struct.unpack_from("<I", avi, marker + 4)[0]
        jpegs.append(avi[marker + 8 : marker + 8 + length])
        cursor = marker + 8 + length + (length & 1)
        if len(jpegs) > 200:  # sanity bound
            break

    assert len(jpegs) >= 2
    first_rgb = list(Image.open(io.BytesIO(jpegs[0])).convert("L").getdata())
    last_rgb = list(Image.open(io.BytesIO(jpegs[-1])).convert("L").getdata())
    assert first_rgb != last_rgb, "first and last frames are identical"
