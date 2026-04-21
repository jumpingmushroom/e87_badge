"""Hardware integration test for E87Client.

Gated behind the `E87_BADGE_MAC` environment variable. Set it to your
badge's MAC address to run, e.g.::

    E87_BADGE_MAC=46:8D:00:01:2C:25 pytest tests/test_client_integration.py
"""

from __future__ import annotations

import os
import pathlib

import pytest

from e87_badge import E87Client

pytestmark = pytest.mark.skipif(
    not os.environ.get("E87_BADGE_MAC"),
    reason="set E87_BADGE_MAC to run hardware integration tests",
)

CAPTURE_PNG = (
    pathlib.Path(__file__).parent.parent
    / "docs" / "captures" / "01-solid-red-360.png"
)


@pytest.mark.asyncio
async def test_connect_authenticate_disconnect() -> None:
    mac = os.environ["E87_BADGE_MAC"]
    async with E87Client(mac) as _client:
        pass  # connect() runs the full auth handshake


@pytest.mark.asyncio
async def test_send_static_image() -> None:
    mac = os.environ["E87_BADGE_MAC"]
    async with E87Client(mac) as client:
        await client.send_image(CAPTURE_PNG)


@pytest.mark.asyncio
async def test_send_text() -> None:
    mac = os.environ["E87_BADGE_MAC"]
    async with E87Client(mac) as client:
        await client.send_text("Hello", size=72)
