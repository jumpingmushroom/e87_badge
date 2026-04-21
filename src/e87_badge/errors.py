"""Typed exceptions for the e87_badge library."""

from __future__ import annotations


class E87Error(Exception):
    """Base class for all e87_badge errors."""


class E87ConnectError(E87Error):
    """BLE connect / discovery failure."""


class E87AuthError(E87Error):
    """JieLi RCSP auth handshake failed."""


class E87ProtocolError(E87Error):
    """The badge returned an unexpected frame or state during upload."""


class E87TransferAborted(E87Error):
    """Data transfer was interrupted mid-stream."""
