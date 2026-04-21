"""Tests for e87_badge.jieli_cipher — JieLi RCSP auth cipher port.

Test vector from protocol-understanding/jl_auth_v3.py and verify_crypto.py:
    Device challenge (wire, 17 bytes): 00 b6 e0 80 ec af f3 22 91 6d 88 fa d5 aa 34 c2 ac
    App response    (wire, 17 bytes):  01 1d 88 97 ac 46 04 d3 32 e8 17 5e 81 bb 29 25 24

The 0x00/0x01 leading byte is a protocol prefix and is NOT part of the 16-byte
cipher input/output.  get_encrypted_auth_data() takes the 16-byte challenge
(no prefix) and returns the 16-byte response (no prefix).
"""

import pytest
from e87_badge.jieli_cipher import get_encrypted_auth_data, get_random_auth_data, encrypt_block


# ── Test 1: Known-answer / test vector ───────────────────────────────────────

def test_known_answer_vector():
    """
    Verify the cipher against the empirically captured BLE auth exchange.

    Wire challenge: 00 b6 e0 80 ec af f3 22 91 6d 88 fa d5 aa 34 c2 ac
    Wire response:  01 1d 88 97 ac 46 04 d3 32 e8 17 5e 81 bb 29 25 24

    Strip the protocol prefix (first byte) before passing to the cipher.
    """
    # 16-byte challenge (prefix 0x00 stripped)
    challenge = bytes.fromhex("b6e080ecaff322916d88fad5aa34c2ac")
    # 16-byte expected response (prefix 0x01 stripped)
    expected = bytes.fromhex("1d8897ac4604d332e8175e81bb292524")

    result = get_encrypted_auth_data(challenge)

    assert result == expected, (
        f"Cipher mismatch:\n"
        f"  challenge: {challenge.hex()}\n"
        f"  expected:  {expected.hex()}\n"
        f"  got:       {result.hex()}"
    )


# ── Test 2: get_random_auth_data() basics ────────────────────────────────────

def test_random_auth_data_is_16_bytes():
    """get_random_auth_data() must return exactly 16 bytes."""
    data = get_random_auth_data()
    assert isinstance(data, bytes)
    assert len(data) == 16


def test_random_auth_data_is_nondeterministic():
    """Successive calls to get_random_auth_data() should differ (with overwhelming probability)."""
    # The chance of a collision across two 16-byte random values is 1/2^128 — negligible.
    a = get_random_auth_data()
    b = get_random_auth_data()
    assert a != b, "Two successive random challenges were identical — this is astronomically unlikely unless the RNG is broken"


# ── Test 3: Determinism / round-trip ─────────────────────────────────────────

def test_encrypt_is_deterministic():
    """get_encrypted_auth_data(c) must return the same result on repeated calls."""
    challenge = bytes.fromhex("b6e080ecaff322916d88fad5aa34c2ac")
    r1 = get_encrypted_auth_data(challenge)
    r2 = get_encrypted_auth_data(challenge)
    assert r1 == r2, "Cipher is not deterministic — second call returned a different result"


def test_different_challenges_give_different_responses():
    """Different challenges should produce different responses."""
    c1 = bytes.fromhex("b6e080ecaff322916d88fad5aa34c2ac")
    c2 = bytes(range(16))
    r1 = get_encrypted_auth_data(c1)
    r2 = get_encrypted_auth_data(c2)
    assert r1 != r2, "Different challenges produced the same response — cipher may be degenerate"


# ── Test 4: Output length ─────────────────────────────────────────────────────

def test_encrypted_auth_data_is_16_bytes():
    """get_encrypted_auth_data() must return exactly 16 bytes."""
    challenge = bytes.fromhex("b6e080ecaff322916d88fad5aa34c2ac")
    result = get_encrypted_auth_data(challenge)
    assert isinstance(result, bytes)
    assert len(result) == 16


# ── Test 5: encrypt_block output length ──────────────────────────────────────

def test_encrypt_block_is_16_bytes():
    """encrypt_block() must return exactly 16 bytes."""
    data = bytes(range(16))
    result = encrypt_block(data)
    assert isinstance(result, bytes)
    assert len(result) == 16
