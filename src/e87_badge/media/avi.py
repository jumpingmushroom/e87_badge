"""MJPG AVI container builder (Group D placeholder — implemented next)."""

from __future__ import annotations

from typing import Iterable


def build_mjpg_avi(
    frames: Iterable[bytes],
    *,
    fps: int,
    width: int,
    height: int,
) -> bytes:
    raise NotImplementedError("media.avi.build_mjpg_avi not yet implemented")
