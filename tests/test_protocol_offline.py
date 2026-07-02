"""Offline tests for protocol helpers.

Driving the full UploadSession state machine offline would require
simulating the device's window-ack protocol; instead we test the pure
helpers that determine how the extension parameter affects on-wire
filenames + the path-response body.
"""

from __future__ import annotations

import re

import pytest

from e87_badge.const import FLAG_COMMAND, FLAG_DATA
from e87_badge.errors import E87ProtocolError
from e87_badge.frame import E87Frame, build_fe_frame
from e87_badge.notify import NotifyBus
from e87_badge.protocol import (
    MAX_POST_EOF_RESENDS,
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


# ── Phase-9 post-EOF re-request handling ──────────────────────────────────


def _window_ack(next_offset: int, *, win: int = 300, seq: int = 0, status: int = 0) -> bytes:
    body = bytes(
        (
            seq,
            status,
            (win >> 8) & 0xFF,
            win & 0xFF,
            (next_offset >> 24) & 0xFF,
            (next_offset >> 16) & 0xFF,
            (next_offset >> 8) & 0xFF,
            next_offset & 0xFF,
        )
    )
    return build_fe_frame(FLAG_DATA, 0x1D, body)


def _session_close(status: int = 0, seq: int = 0) -> bytes:
    return build_fe_frame(FLAG_COMMAND, 0x1C, bytes((seq, status)))


async def _run_phase9_with_acks(data: bytes, chunk_size: int, acks: list[bytes]):
    """Drive _phase9_transfer against a pre-scripted sequence of device
    frames, recording the offsets handed to _send_window."""
    session = _make_session()
    for raw in acks:
        session._bus.push(raw)

    calls: list[int] = []
    orig = session._send_window

    async def spy(data_, chunk_size_, offset, win_size, state):
        calls.append(offset)
        await orig(data_, chunk_size_, offset, win_size, state)

    session._send_window = spy  # type: ignore[method-assign]
    await session._phase9_transfer(data, chunk_size, "jpg")
    return calls


async def test_phase9_resends_legit_rerequest_after_eof():
    """A single re-request of an already-delivered offset (failed window CRC)
    must be re-sent, not refused."""
    data = bytes(300)
    acks = [
        _window_ack(0),      # initial window ack
        _window_ack(0),      # re-request after EOF — legitimate retransmit
        _window_ack(300),    # now at EOF
        _session_close(0),   # clean close
    ]
    calls = await _run_phase9_with_acks(data, 100, acks)
    assert calls == [0, 0], calls  # initial send + one honoured resend


async def test_phase9_bounds_repeated_rerequests():
    """A badge stuck re-requesting the same offset is honoured only
    MAX_POST_EOF_RESENDS times, then ignored — no infinite loop."""
    data = bytes(300)
    acks = [_window_ack(0)]                       # initial
    acks += [_window_ack(0) for _ in range(5)]    # 5 re-requests
    acks += [_session_close(0)]
    calls = await _run_phase9_with_acks(data, 100, acks)
    # 1 initial + MAX_POST_EOF_RESENDS honoured resends, rest ignored.
    assert len(calls) == 1 + MAX_POST_EOF_RESENDS, calls
    assert all(off == 0 for off in calls)


# ── Session-close status handling ─────────────────────────────────────────


def _close_frame(status: int, seq: int = 0x42) -> E87Frame:
    body = bytes((seq, status))
    return E87Frame(flag=0x00, cmd=0x1C, length=len(body), body=body)


async def test_finalize_raises_on_nonzero_status():
    session = _make_session()
    with pytest.raises(E87ProtocolError, match="0x01"):
        await session._finalize(_close_frame(status=0x01))


async def test_finalize_ok_on_zero_status():
    session = _make_session()
    await session._finalize(_close_frame(status=0x00))  # no raise


# ── NotifyBus session hygiene ─────────────────────────────────────────────


def test_notify_bus_clear_drops_stale_frames():
    bus = NotifyBus()
    bus.push(b"\xfe\xdc\xba stale")
    bus.clear()
    assert bus.consume(lambda r: True) is None
