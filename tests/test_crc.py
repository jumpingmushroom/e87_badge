from e87_badge.crc import crc16xmodem


def test_crc16xmodem_123456789_vector():
    """CRC-16/XMODEM standard test vector."""
    assert crc16xmodem(b"123456789") == 0x31C3


def test_crc16xmodem_empty():
    assert crc16xmodem(b"") == 0x0000


def test_crc16xmodem_determinism():
    a = crc16xmodem(b"the quick brown fox")
    b = crc16xmodem(b"the quick brown fox")
    assert a == b
