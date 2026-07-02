"""Offline tests: media encoding runs off the event loop.

Encoding (PIL decode/resize/JPEG) is CPU-bound and blocking. On a shared
loop (Home Assistant) it must run in a worker thread, not the loop thread,
or it stalls the whole instance — including the BLE traffic the upload
depends on. These tests assert the encode step executes on a different
thread than the running event loop.
"""

from __future__ import annotations

import threading

import e87_badge.client as client_mod
from e87_badge.client import E87Client


async def _loop_thread_ident() -> int:
    return threading.get_ident()


async def _make_connected_client(monkeypatch) -> tuple[E87Client, list[bytes]]:
    """An E87Client whose blob-send is stubbed so only encoding runs."""
    sent: list[bytes] = []

    client = E87Client("AA:BB:CC:DD:EE:FF")
    client._authed = True
    client._client = object()  # non-None so _send_blob's guard passes

    async def fake_send_blob(data: bytes, *, extension: str) -> None:
        sent.append(data)

    monkeypatch.setattr(client, "_send_blob", fake_send_blob)
    return client, sent


async def test_send_image_encodes_off_loop(monkeypatch):
    loop_ident = await _loop_thread_ident()
    encode_thread: list[int] = []

    def fake_encode_jpeg(image):
        encode_thread.append(threading.get_ident())
        return b"\xff\xd8fake\xff\xd9"

    monkeypatch.setattr(
        "e87_badge.media.image.encode_jpeg", fake_encode_jpeg
    )

    client, sent = await _make_connected_client(monkeypatch)
    await client.send_image("dummy.png")

    assert sent == [b"\xff\xd8fake\xff\xd9"]
    assert encode_thread and encode_thread[0] != loop_ident, (
        "encode_jpeg ran on the event loop thread"
    )


async def test_send_danmaku_renders_off_loop(monkeypatch):
    loop_ident = await _loop_thread_ident()
    render_thread: list[int] = []

    def fake_render_danmaku(text, **kwargs):
        render_thread.append(threading.get_ident())
        return b"AVI-bytes"

    monkeypatch.setattr(
        "e87_badge.media.danmaku.render_danmaku", fake_render_danmaku
    )

    client, sent = await _make_connected_client(monkeypatch)
    await client.send_danmaku("hello world")

    assert sent == [b"AVI-bytes"]
    assert render_thread and render_thread[0] != loop_ident, (
        "render_danmaku ran on the event loop thread"
    )
