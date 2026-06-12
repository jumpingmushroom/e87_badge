"""Offline tests for E87Client.connect() failure handling.

Regression for the auth-leak bug: when the JieLi handshake fails,
connect() must disconnect the half-open BleakClient (which otherwise
keeps holding a proxy connection slot — `__aexit__` never runs when
`__aenter__` raises) and retry the full connect cycle.
"""

from __future__ import annotations

import pytest

import e87_badge.client as client_mod
from e87_badge.client import E87Client
from e87_badge.errors import E87AuthError, E87ConnectError


class _FakeBleakClient:
    instances: list["_FakeBleakClient"] = []

    def __init__(self) -> None:
        self.mtu_size = 247
        self.notify_uuids: list[str] = []
        self.disconnect_calls = 0
        _FakeBleakClient.instances.append(self)

    async def start_notify(self, uuid, callback) -> None:
        self.notify_uuids.append(uuid)

    async def stop_notify(self, uuid) -> None:
        pass

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


@pytest.fixture
def patched_client(monkeypatch):
    _FakeBleakClient.instances = []

    async def fake_establish(cls, device, name=None, max_attempts=None, **kwargs):
        return _FakeBleakClient()

    async def fake_resolve(self):
        return "AA:BB:CC:DD:EE:FF"

    async def instant_sleep(_delay):
        return None

    monkeypatch.setattr(client_mod, "establish_connection", fake_establish)
    monkeypatch.setattr(E87Client, "_resolve_ble_device", fake_resolve)
    monkeypatch.setattr(client_mod.asyncio, "sleep", instant_sleep)
    return monkeypatch


async def test_auth_failure_disconnects_every_attempt(patched_client):
    async def failing_auth(write_ae01, bus):
        raise E87AuthError("simulated handshake timeout")

    patched_client.setattr(client_mod, "do_auth", failing_auth)

    client = E87Client("AA:BB:CC:DD:EE:FF")
    with pytest.raises(E87ConnectError, match="3 full reconnect"):
        await client.connect()

    assert len(_FakeBleakClient.instances) == 3
    for fake in _FakeBleakClient.instances:
        assert fake.disconnect_calls >= 1, "BleakClient leaked after auth failure"
    assert client._client is None


async def test_auth_success_after_transient_failure(patched_client):
    attempts = 0

    async def flaky_auth(write_ae01, bus):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise E87AuthError("transient")

    patched_client.setattr(client_mod, "do_auth", flaky_auth)

    client = E87Client("AA:BB:CC:DD:EE:FF")
    await client.connect()

    assert attempts == 2
    assert client._authed
    assert _FakeBleakClient.instances[0].disconnect_calls == 1
    assert client._client is _FakeBleakClient.instances[1]
    await client.disconnect()


async def test_stale_bus_frames_cleared_before_auth(patched_client):
    seen_at_auth: list[bytes] = []

    async def recording_auth(write_ae01, bus):
        seen_at_auth.extend(bus.queue)

    patched_client.setattr(client_mod, "do_auth", recording_auth)

    client = E87Client("AA:BB:CC:DD:EE:FF")
    client._bus.push(b"\x01" + bytes(16))  # would match an auth waiter
    await client.connect()

    assert seen_at_auth == [], "stale pre-connect frames leaked into auth"
    await client.disconnect()
