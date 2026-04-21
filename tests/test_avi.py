"""Tests for the MJPG-AVI container builder."""

from __future__ import annotations

import io
import struct

import pytest
from PIL import Image

from e87_badge.const import E87_IMAGE_HEIGHT, E87_IMAGE_WIDTH
from e87_badge.media.avi import build_mjpg_avi


def _jpeg(colour, w=368, h=368) -> bytes:
    img = Image.new("RGB", (w, h), colour)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def test_riff_header_validates():
    avi = build_mjpg_avi([_jpeg((255, 0, 0)), _jpeg((0, 255, 0))], fps=2)
    assert avi[:4] == b"RIFF"
    declared = struct.unpack_from("<I", avi, 4)[0]
    # RIFF size excludes the 8-byte RIFF header itself.
    assert declared == len(avi) - 8
    assert avi[8:12] == b"AVI "


def test_fourcc_markers_present():
    avi = build_mjpg_avi([_jpeg((255, 0, 0))], fps=1)
    for marker in (b"hdrl", b"avih", b"strl", b"strh", b"strf", b"vprp",
                   b"INFO", b"ISFT", b"movi", b"idx1"):
        assert marker in avi, f"missing {marker!r} in AVI"


def test_stream_header_declares_mjpg():
    avi = build_mjpg_avi([_jpeg((255, 0, 0)), _jpeg((0, 255, 0))], fps=2)
    # Find strh then check the 4-byte fccHandler 4 bytes in.
    i = avi.find(b"strh")
    assert i > 0
    strh_body_start = i + 8  # 'strh' + u32 length
    fcc_type = avi[strh_body_start : strh_body_start + 4]
    fcc_handler = avi[strh_body_start + 4 : strh_body_start + 8]
    assert fcc_type == b"vids"
    assert fcc_handler == b"MJPG"


def test_frame_count_and_dimensions_in_avih():
    frames = [_jpeg((i * 30, 0, 0)) for i in range(5)]
    avi = build_mjpg_avi(frames, fps=5, width=368, height=368)
    i = avi.find(b"avih")
    body = avi[i + 8 : i + 8 + 56]
    # total frames is the 5th u32 (offset 16)
    total_frames = struct.unpack_from("<I", body, 16)[0]
    width = struct.unpack_from("<I", body, 32)[0]
    height = struct.unpack_from("<I", body, 36)[0]
    assert total_frames == 5
    assert width == E87_IMAGE_WIDTH == 368
    assert height == E87_IMAGE_HEIGHT == 368


def test_idx1_has_one_entry_per_frame():
    frames = [_jpeg((c, c, c)) for c in (10, 50, 100, 200)]
    avi = build_mjpg_avi(frames, fps=4)
    i = avi.rfind(b"idx1")
    assert i > 0
    idx1_len = struct.unpack_from("<I", avi, i + 4)[0]
    # 16 bytes per entry
    assert idx1_len == 16 * len(frames)


def test_empty_frames_rejects():
    with pytest.raises(ValueError):
        build_mjpg_avi([], fps=1)
