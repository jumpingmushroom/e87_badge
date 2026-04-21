"""Offline tests for protocol helpers.

Driving the full UploadSession state machine offline would require
simulating the device's window-ack protocol; instead we test the pure
helpers that determine how the extension parameter affects on-wire
filenames + the path-response body.
"""

from __future__ import annotations

import re

from e87_badge.protocol import _build_file_path_response, _random_temp_name


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
