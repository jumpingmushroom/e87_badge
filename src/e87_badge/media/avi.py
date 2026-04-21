"""MJPG AVI container builder for the E87 badge.

Ported from https://github.com/hybridherbst/web-bluetooth-e87 (MIT) —
`web/src/avi-builder.ts`. Layout matches what the official iOS Zrun app
sends, including the JUNK padding sections that align the `movi` chunk to
offset ~5742. Frames must be complete JPEG byte strings (FF D8 … FF D9).

Upstream © 2026 Felix Herbst — MIT License.
"""

# SPDX-License-Identifier: MIT

from __future__ import annotations

import struct
from typing import Iterable, Sequence

from ..const import E87_IMAGE_HEIGHT, E87_IMAGE_WIDTH

__all__ = ["build_mjpg_avi"]


def _fourcc(s: str) -> bytes:
    b = s.encode("ascii")
    if len(b) != 4:
        raise ValueError(f"fourcc must be 4 bytes: {s!r}")
    return b


def _u32le(v: int) -> bytes:
    return struct.pack("<I", v & 0xFFFFFFFF)


def _u16le(v: int) -> bytes:
    return struct.pack("<H", v & 0xFFFF)


def _pad_even(data: bytes) -> bytes:
    return data + b"\x00" if len(data) & 1 else data


def _chunk(fourcc: str, data: bytes) -> bytes:
    return _fourcc(fourcc) + _u32le(len(data)) + _pad_even(data)


def _list(list_type: str, *children: bytes) -> bytes:
    inner = _fourcc(list_type) + b"".join(children)
    return _fourcc("LIST") + _u32le(len(inner)) + inner


def build_mjpg_avi(
    frames: Iterable[bytes],
    *,
    fps: int | None = None,
    width: int = E87_IMAGE_WIDTH,
    height: int = E87_IMAGE_HEIGHT,
) -> bytes:
    """Build an AVI file from a sequence of pre-encoded JPEG frames.

    Parameters
    ----------
    frames :
        Iterable of JPEG byte strings (each beginning with FF D8 and ending
        FF D9). The iterable is materialised into a list.
    fps :
        Frame rate. Default 1 for ≤6 frames, 12 otherwise (matches upstream).
    width, height :
        Frame dimensions. Default 368×368 (the badge's display).
    """
    frame_list: Sequence[bytes] = list(frames)
    if not frame_list:
        raise ValueError("build_mjpg_avi requires at least one frame")

    if fps is None:
        fps = 1 if len(frame_list) <= 6 else 12
    if fps <= 0:
        raise ValueError("fps must be > 0")

    usec_per_frame = round(1_000_000 / fps)
    max_frame_size = max(len(f) for f in frame_list)
    total_frames = len(frame_list)

    # ── avih (main AVI header, 56 bytes) ──
    avih_data = b"".join(
        (
            _u32le(usec_per_frame),        # dwMicroSecPerFrame
            _u32le(25000),                 # dwMaxBytesPerSec
            _u32le(0),                     # dwPaddingGranularity
            _u32le(0x0910),                # dwFlags: HASINDEX | ISINTERLEAVED
            _u32le(total_frames),          # dwTotalFrames
            _u32le(0),                     # dwInitialFrames
            _u32le(1),                     # dwStreams
            _u32le(0x00100000),            # dwSuggestedBufferSize (1 MB)
            _u32le(width),                 # dwWidth
            _u32le(height),                # dwHeight
            b"\x00" * 16,                  # dwReserved[4]
        )
    )
    avih = _chunk("avih", avih_data)

    # ── strh (stream header) ──
    strh_data = b"".join(
        (
            _fourcc("vids"),               # fccType
            _fourcc("MJPG"),               # fccHandler
            _u32le(0),                     # dwFlags
            _u16le(0),                     # wPriority
            _u16le(0),                     # wLanguage
            _u32le(0),                     # dwInitialFrames
            _u32le(1),                     # dwScale
            _u32le(fps),                   # dwRate
            _u32le(0),                     # dwStart
            _u32le(total_frames),          # dwLength
            _u32le(max_frame_size),        # dwSuggestedBufferSize
            _u32le(0xFFFFFFFF),            # dwQuality (-1 = default)
            _u32le(0),                     # dwSampleSize
            _u16le(0),                     # rcFrame.left
            _u16le(0),                     # rcFrame.top
            _u16le(width),                 # rcFrame.right
            _u16le(height),                # rcFrame.bottom
        )
    )
    strh = _chunk("strh", strh_data)

    # ── strf (BITMAPINFOHEADER, 40 bytes) ──
    img_size = width * height * 3
    strf_data = b"".join(
        (
            _u32le(40),                    # biSize
            _u32le(width),                 # biWidth
            _u32le(height),                # biHeight
            _u16le(1),                     # biPlanes
            _u16le(24),                    # biBitCount
            _fourcc("MJPG"),               # biCompression
            _u32le(img_size),              # biSizeImage
            _u32le(0),                     # biXPelsPerMeter
            _u32le(0),                     # biYPelsPerMeter
            _u32le(0),                     # biClrUsed
            _u32le(0),                     # biClrImportant
        )
    )
    strf = _chunk("strf", strf_data)

    # ── JUNK (OpenDML super-index placeholder, 4120 bytes) ──
    junk_super = bytearray(4120)
    junk_super[0] = 0x04
    junk_super[8:12] = _fourcc("00dc")
    junk_super_chunk = _chunk("JUNK", bytes(junk_super))

    # ── strl LIST ──
    strl = _list("strl", strh, strf, junk_super_chunk)

    # ── vprp (video properties, 68 bytes) ──
    vprp_data = b"".join(
        (
            _u32le(0),                     # VideoFormatToken
            _u32le(0),                     # VideoStandard
            _u32le(fps),                   # dwVerticalRefreshRate
            _u32le(width),                 # dwHTotalInT
            _u32le(height),                # dwVTotalInLines
            _u32le(1 | (1 << 16)),         # dwFrameAspectRatio (1:1)
            _u32le(width),                 # dwFrameWidthInPixels
            _u32le(height),                # dwFrameHeightInLines
            _u32le(1),                     # nFieldPerFrame
            # Field info (1 entry):
            _u32le(width),                 # CompressedBMWidth
            _u32le(height),                # CompressedBMHeight
            _u32le(width),                 # ValidBMWidth
            _u32le(height),                # ValidBMHeight
            _u32le(0),                     # ValidBMXOffset
            _u32le(0),                     # ValidBMYOffset
            _u32le(0),                     # VideoXOffsetInT
            _u32le(0),                     # VideoYValidStartLine
        )
    )
    vprp = _chunk("vprp", vprp_data)

    # ── JUNK padding (260 bytes) ──
    junk_pad = _chunk("JUNK", b"\x00" * 260)

    # ── hdrl LIST ──
    hdrl = _list("hdrl", avih, strl, vprp, junk_pad)

    # ── INFO LIST ──
    isft_bytes = b"AviBuilder\x00"
    isft = _chunk("ISFT", isft_bytes)
    info = _list("INFO", isft)

    # ── JUNK padding to align movi to offset ~5742 ──
    header_so_far = 12 + len(hdrl) + len(info) + 8  # RIFF header + hdrl + info + JUNK overhead
    target_movi_offset = 5742
    junk_pad_size = max(0, target_movi_offset - header_so_far - 8)
    junk_align = _chunk("JUNK", b"\x00" * junk_pad_size)

    # ── movi LIST ──
    movi_children = [_chunk("00dc", frame) for frame in frame_list]
    movi = _list("movi", *movi_children)

    # ── idx1 (legacy index, 16 bytes per frame) ──
    idx1_entries = []
    movi_data_offset = 4  # offset within movi data (after LIST type FOURCC)
    for frame in frame_list:
        idx1_entries.append(
            _fourcc("00dc")
            + _u32le(0x10)                 # AVIIF_KEYFRAME
            + _u32le(movi_data_offset)
            + _u32le(len(frame))
        )
        movi_data_offset += 8 + len(frame) + (len(frame) & 1)
    idx1 = _chunk("idx1", b"".join(idx1_entries))

    # ── RIFF container ──
    riff_content = _fourcc("AVI ") + hdrl + info + junk_align + movi + idx1
    return _fourcc("RIFF") + _u32le(len(riff_content)) + riff_content
