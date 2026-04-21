"""e87_badge — open client for the E-Badge E87 / L8 round LCD BLE pin.

Public API:
    E87Client        — async context manager; takes BLEDevice or MAC string
    discover         — scan for badges (standalone use; HA passes BLEDevice directly)
    find_one         — return a single badge

    E87Error                 — base exception
    E87ConnectError          — BLE connect failure
    E87AuthError             — JieLi RCSP auth failed
    E87ProtocolError         — unexpected state during upload
    E87TransferAborted       — transfer interrupted mid-stream

    LOCAL_NAME       — GAP local name used for HA discovery matchers
    AE_SERVICE_UUID  — primary service UUID (discovery fallback)
"""

from __future__ import annotations

from .client import E87Client
from .const import AE_SERVICE_UUID, LOCAL_NAME
from .discovery import discover, find_one
from .errors import (
    E87AuthError,
    E87ConnectError,
    E87Error,
    E87ProtocolError,
    E87TransferAborted,
)

__all__ = [
    "E87Client",
    "discover",
    "find_one",
    "E87Error",
    "E87ConnectError",
    "E87AuthError",
    "E87ProtocolError",
    "E87TransferAborted",
    "LOCAL_NAME",
    "AE_SERVICE_UUID",
]
