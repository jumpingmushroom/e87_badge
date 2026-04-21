"""Scrolling-text danmaku → MJPG AVI (Group E placeholder)."""

from __future__ import annotations


def render_danmaku(
    text: str,
    *,
    fg="white",
    bg="black",
    font=None,
    font_size: int = 64,
    speed_px_per_frame: int = 4,
    fps: int = 20,
) -> bytes:
    raise NotImplementedError("media.danmaku.render_danmaku not yet implemented")
