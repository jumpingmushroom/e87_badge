"""Predicate tests for CLI badge discovery.

`_looks_like_badge` must recognise the same fingerprints as the HA config-flow
matcher (`config_flow._is_e87`): local name, AE00/0xFD00 service UUID, or the
JieLi manufacturer ID. The name appears only in the scan response, so a passive
scanner that never hears it still has to identify the badge by the passive-safe
UUID/manufacturer fingerprints — otherwise `e87 discover` misses badges HA finds.
"""

from __future__ import annotations

from e87_badge.const import (
    ADVERT_MANUFACTURER_ID,
    ADVERT_SERVICE_UUID_16,
    AE_SERVICE_UUID,
    LOCAL_NAME,
)
from e87_badge.discovery import _looks_like_badge


class _Device:
    def __init__(self, name: str | None = None) -> None:
        self.name = name
        self.address = "AA:BB:CC:DD:EE:FF"


class _Adv:
    def __init__(self, service_uuids=None, manufacturer_data=None) -> None:
        self.service_uuids = service_uuids or []
        self.manufacturer_data = manufacturer_data or {}


def test_matches_local_name():
    assert _looks_like_badge(_Device(name=LOCAL_NAME), _Adv())


def test_matches_ae_service_uuid():
    assert _looks_like_badge(_Device(), _Adv(service_uuids=[AE_SERVICE_UUID]))


def test_matches_fd00_service_uuid():
    assert _looks_like_badge(_Device(), _Adv(service_uuids=[ADVERT_SERVICE_UUID_16]))


def test_matches_manufacturer_id_only():
    # Passive-safe fingerprint: no name, no service UUIDs, only the JieLi
    # company ID in manufacturer data — what a passive scanner typically sees.
    adv = _Adv(manufacturer_data={ADVERT_MANUFACTURER_ID: b"\x00\x01"})
    assert _looks_like_badge(_Device(), adv)


def test_ignores_unrelated_advert():
    adv = _Adv(
        service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"],  # battery service
        manufacturer_data={0x004C: b"\x00"},  # Apple
    )
    assert not _looks_like_badge(_Device(name="Someone's Watch"), adv)
