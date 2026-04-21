"""FE-framing unit tests + round-trip against real capture fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from e87_badge.const import FLAG_COMMAND, FLAG_DATA, FLAG_RESPONSE
from e87_badge.frame import build_fe_frame, parse_fe_frame

CAPTURE = (
    Path(__file__).parent.parent
    / "docs" / "captures" / "01-solid-red-360.ae01-writes.txt"
)


def test_roundtrip_simple():
    body = b"\x01\x02\x03"
    wire = build_fe_frame(FLAG_COMMAND, 0x21, body)
    f = parse_fe_frame(wire)
    assert f is not None
    assert f.flag == FLAG_COMMAND
    assert f.cmd == 0x21
    assert f.body == body
    assert f.length == 3


def test_roundtrip_empty_body():
    wire = build_fe_frame(FLAG_RESPONSE, 0x1C, b"")
    f = parse_fe_frame(wire)
    assert f is not None
    assert f.length == 0
    assert f.body == b""


def test_parse_rejects_short():
    assert parse_fe_frame(b"\xfe\xdc\xba") is None
    assert parse_fe_frame(b"") is None


def test_parse_rejects_bad_magic():
    assert parse_fe_frame(b"\x00\x00\x00\xc0\x06\x00\x00\xef") is None


def test_parse_rejects_missing_terminator():
    wire = build_fe_frame(FLAG_COMMAND, 0x06, b"\x00")
    # Replace the trailing EF with something else
    assert parse_fe_frame(wire[:-1] + b"\x00") is None


def test_parse_rejects_length_mismatch():
    # Claim body length 5 but only ship 2 bytes
    wire = b"\xfe\xdc\xba\xc0\x06\x00\x05\x01\x02\xef"
    assert parse_fe_frame(wire) is None


def test_build_rejects_oversize_body():
    with pytest.raises(ValueError):
        build_fe_frame(FLAG_COMMAND, 0x01, b"\x00" * (0x10000))


def test_parse_every_capture_write():
    """The phase-1 capture contains 17 writes to AE01 — 12 FE frames + 5 raw
    auth bytes. Every FE frame must parse; auth packets do not start with
    FE DC BA and therefore must NOT parse."""
    if not CAPTURE.is_file():
        pytest.skip(f"capture missing: {CAPTURE}")

    fe_count = 0
    non_fe_count = 0
    flags_seen: set[int] = set()
    cmds_seen: set[int] = set()
    for line in CAPTURE.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        hex_payload = parts[3]
        raw = bytes.fromhex(hex_payload)
        f = parse_fe_frame(raw)
        if raw[:3] == b"\xfe\xdc\xba":
            assert f is not None, f"FE-prefixed payload failed to parse: {hex_payload}"
            fe_count += 1
            flags_seen.add(f.flag)
            cmds_seen.add(f.cmd)
        else:
            assert f is None
            non_fe_count += 1

    # Sanity: we should have seen a mix of auth and framed writes.
    assert fe_count >= 8, f"expected ≥8 FE frames in capture, got {fe_count}"
    assert non_fe_count >= 3, f"expected ≥3 auth writes in capture, got {non_fe_count}"
    # Expected opcodes from protocol.md — 0x06, 0x03, 0x07, 0x21, 0x27, 0x1b,
    # 0x01 (data), 0x20 (path response), 0x1c (session close).
    assert FLAG_COMMAND in flags_seen
    assert FLAG_DATA in flags_seen or FLAG_RESPONSE in flags_seen
