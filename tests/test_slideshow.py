"""Tests for multi-image slideshow → MJPG AVI."""

from __future__ import annotations

import struct

import pytest
from PIL import Image

from e87_badge.media.slideshow import build_slideshow


def _img(colour):
    return Image.new("RGB", (500, 500), colour)


def test_three_colours_builds_avi():
    avi = build_slideshow(
        [_img((255, 0, 0)), _img((0, 255, 0)), _img((0, 0, 255))],
        frame_ms=500,
    )
    # Frame count from avih
    i = avi.find(b"avih")
    total_frames = struct.unpack_from("<I", avi, i + 8 + 16)[0]
    assert total_frames == 3


def test_rejects_empty_list():
    with pytest.raises(ValueError):
        build_slideshow([], frame_ms=500)


def test_rejects_zero_frame_ms():
    with pytest.raises(ValueError):
        build_slideshow([_img((0, 0, 0))], frame_ms=0)
