"""FE-framed wire format used on AE01/AE02.

Layout:
    3 bytes   header     FE DC BA
    1 byte    flag       0xC0 command, 0x00 response, 0x80 data/notify
    1 byte    cmd        command opcode
    2 bytes   length     big-endian body length
    N bytes   body
    1 byte    terminator 0xEF
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import FE_HEADER, FE_TERMINATOR


@dataclass
class E87Frame:
    flag: int
    cmd: int
    length: int
    body: bytes

    def __repr__(self) -> str:  # pragma: no cover - debug
        return (
            f"E87Frame(flag=0x{self.flag:02x}, cmd=0x{self.cmd:02x}, "
            f"len={self.length}, body={self.body.hex()})"
        )


def parse_fe_frame(data: bytes) -> E87Frame | None:
    """Return an `E87Frame` if `data` is a well-formed FE frame, else None."""
    if len(data) < 8:
        return None
    if data[:3] != FE_HEADER or data[-1] != FE_TERMINATOR:
        return None
    flag = data[3]
    cmd = data[4]
    length = (data[5] << 8) | data[6]
    body = bytes(data[7:-1])
    if len(body) != length:
        return None
    return E87Frame(flag, cmd, length, body)


def build_fe_frame(flag: int, cmd: int, body: bytes) -> bytes:
    if len(body) > 0xFFFF:
        raise ValueError("body too long for 16-bit length")
    return (
        FE_HEADER
        + bytes((flag & 0xFF, cmd & 0xFF, (len(body) >> 8) & 0xFF, len(body) & 0xFF))
        + bytes(body)
        + bytes((FE_TERMINATOR,))
    )
