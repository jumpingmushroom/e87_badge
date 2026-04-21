"""CRC-16/XMODEM — polynomial 0x1021, init 0x0000, no reflection, no final XOR."""

from __future__ import annotations


def crc16xmodem(data: bytes) -> int:
    crc = 0x0000
    for b in data:
        crc ^= (b & 0xFF) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc
