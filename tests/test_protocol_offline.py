"""Offline tests for protocol helpers.

Driving the full UploadSession state machine offline would require
simulating the device's window-ack protocol; instead we test the pure
helpers that determine how the extension parameter affects on-wire
filenames + the path-response body.
"""

from __future__ import annotations

import re

from e87_badge.notify import NotifyBus
from e87_badge.protocol import (
    UploadSession,
    _TransferState,
    _build_file_path_response,
    _random_temp_name,
)


def test_temp_name_has_extension_jpg():
    name = _random_temp_name("jpg")
    assert re.fullmatch(r"[0-9a-f]{6}\.jpg", name), name


def test_temp_name_has_extension_avi():
    name = _random_temp_name("avi")
    assert re.fullmatch(r"[0-9a-f]{6}\.avi", name), name


def test_temp_names_are_distinct():
    names = {_random_temp_name("jpg") for _ in range(20)}
    assert len(names) > 1, "RNG produced identical names across 20 samples"


def test_path_response_format_jpg():
    body = _build_file_path_response(device_seq=0x85, extension="jpg")
    # Header: 00 <seq> ...
    assert body[0] == 0x00
    assert body[1] == 0x85
    # Body (utf-16-le) after the 2-byte header ends with ".jpg\0\0" in UTF-16LE
    tail_utf16 = body[2:].decode("utf-16-le")
    assert tail_utf16.endswith(".jpg\x00"), tail_utf16
    # First character is U+555C per upstream
    assert tail_utf16[0] == "\u555c"


def test_path_response_format_avi():
    body = _build_file_path_response(device_seq=0x86, extension="avi")
    assert body[0] == 0x00
    assert body[1] == 0x86
    tail_utf16 = body[2:].decode("utf-16-le")
    assert tail_utf16.endswith(".avi\x00"), tail_utf16
    assert tail_utf16[0] == "\u555c"


def test_path_response_device_seq_wraps():
    body = _build_file_path_response(device_seq=0x1FF, extension="jpg")
    assert body[1] == 0xFF


# ── Window-send offset tracking ───────────────────────────────────────────


def _make_session() -> UploadSession:
    async def write_ae01(data: bytes) -> None:
        pass

    async def write_fd02(data: bytes) -> None:
        pass

    return UploadSession(write_ae01, write_fd02, NotifyBus())


async def test_send_window_tracks_delivered_offset():
    session = _make_session()
    data = bytes(1000)
    state = _TransferState(data_seq=0, total_chunks=10)
    await session._send_window(data, 100, 0, 300, state)
    assert state.max_offset_delivered == 300
    assert state.total_bytes_sent == 300


async def test_retransmit_does_not_fake_eof():
    """A re-sent window inflates total_bytes_sent past len(data), but
    max_offset_delivered must only reflect what was actually covered —
    otherwise phase 9 marks the file fully sent while a gap remains and
    refuses the badge's legitimate re-requests."""
    session = _make_session()
    data = bytes(600)
    state = _TransferState(data_seq=0, total_chunks=6)
    await session._send_window(data, 100, 0, 300, state)
    await session._send_window(data, 100, 0, 300, state)  # badge re-request
    assert state.total_bytes_sent == 600  # overcounts — why it can't gate EOF
    assert state.max_offset_delivered == 300  # file is NOT fully sent
    await session._send_window(data, 100, 300, 300, state)
    assert state.max_offset_delivered == 600


async def test_send_window_clamps_at_eof():
    session = _make_session()
    data = bytes(250)
    state = _TransferState(data_seq=0, total_chunks=3)
    await session._send_window(data, 100, 0, 300, state)
    assert state.max_offset_delivered == 250
    assert state.total_bytes_sent == 250


# ── NotifyBus session hygiene ─────────────────────────────────────────────


def test_notify_bus_clear_drops_stale_frames():
    bus = NotifyBus()
    bus.push(b"\xfe\xdc\xba stale")
    bus.clear()
    assert bus.consume(lambda r: True) is None
