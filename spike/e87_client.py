"""E87 badge client — minimum viable JPEG upload.

Ported from https://github.com/hybridherbst/web-bluetooth-e87 (MIT) — a Web
Bluetooth uploader for Jieli-based E87/L8 LED badges. Files referenced:
    web/src/lib/e87-protocol.ts     — upload state machine, framing, CRC
    web/src/lib/image-processing.ts — image resize/encode (JPEG)
    web/src/jl-auth.ts              — auth cipher (used via spike.jieli_auth)

This port implements the still-image path only. Video, AVI, pattern, and
sequence modes from upstream are deliberately omitted.

Upstream © 2026 Felix Herbst — MIT License.
"""

# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import pathlib
import random
import secrets
import sys
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from PIL import Image

from spike.jieli_auth import get_encrypted_auth_data

# ─── Constants ──────────────────────────────────────────────────────────────

# Primary data path (AE service).
AE_WRITE_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
AE_NOTIFY_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

# Jieli RCSP sideband (FD service). Writes on FD02, notifies on FD01/FD03/FD05.
FD_WRITE_UUID = "c2e6fd02-e966-1000-8000-bef9c223df6a"
FD_NOTIFY_UUIDS = (
    "c2e6fd01-e966-1000-8000-bef9c223df6a",
    "c2e6fd03-e966-1000-8000-bef9c223df6a",
    "c2e6fd05-e966-1000-8000-bef9c223df6a",
)

# Every notify UUID we subscribe to during auth / upload.
ALL_NOTIFY_UUIDS = (AE_NOTIFY_UUID,) + FD_NOTIFY_UUIDS

# Image encoding targets (upstream image-processing.ts E87_IMAGE_* / TARGET_BYTES).
E87_IMAGE_WIDTH = 368
E87_IMAGE_HEIGHT = 368
E87_TARGET_IMAGE_BYTES = 16_000
JPEG_QUALITY_STEPS = (88, 80, 72, 64, 56, 48, 40, 34)

# FE-framed protocol (upstream e87-protocol.ts).
E87_DATA_CHUNK_SIZE = 490  # file data bytes per cmd 0x01 data frame
FE_HEADER = b"\xfe\xdc\xba"
FE_TERMINATOR = 0xEF

# Flag byte values (FE frame header[3]).
FLAG_COMMAND = 0xC0  # phone→device request, or device→phone command
FLAG_RESPONSE = 0x00  # ack / response
FLAG_DATA = 0x80  # data or notification frame

# Log helper.
log = logging.getLogger("e87")


# ─── CRC-16 / XMODEM ────────────────────────────────────────────────────────
# Upstream utils.ts crc16xmodem. Poly 0x1021, init 0x0000, no reflection/XOR.

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


# ─── FE frame helpers ───────────────────────────────────────────────────────

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


def parse_fe_frame(data: bytes) -> Optional[E87Frame]:
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


# ─── Image encoding (Pillow equivalent of image-processing.ts) ───────────────

def encode_image_to_jpeg(path: pathlib.Path) -> bytes:
    """Load an image file, crop-to-square-center, scale to 368x368, JPEG encode
    with quality bracketing to fit under E87_TARGET_IMAGE_BYTES.

    Mirrors imageFileTo368JpegBytes() in upstream image-processing.ts.
    """
    with Image.open(path) as src:
        src.load()
        img = src.convert("RGB")

    w, h = img.size
    min_side = min(w, h)
    sx = (w - min_side) // 2
    sy = (h - min_side) // 2
    cropped = img.crop((sx, sy, sx + min_side, sy + min_side))

    resized = cropped.resize(
        (E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT),
        resample=Image.Resampling.LANCZOS,
    )

    # Composite over a solid black backdrop (upstream fills black before drawImage).
    backdrop = Image.new("RGB", resized.size, (0, 0, 0))
    backdrop.paste(resized, (0, 0))

    best: Optional[bytes] = None
    for quality in JPEG_QUALITY_STEPS:
        buf = io.BytesIO()
        backdrop.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        best = data
        if len(data) <= E87_TARGET_IMAGE_BYTES:
            log.info("Encoded JPEG: quality=%d size=%d bytes", quality, len(data))
            return data

    assert best is not None
    log.info(
        "Encoded JPEG: size=%d bytes (exceeds target %d; lowest quality used)",
        len(best),
        E87_TARGET_IMAGE_BYTES,
    )
    return best


# ─── Notification queue (mirrors upstream notificationQueue) ────────────────

@dataclass
class NotifyBus:
    queue: list[bytes] = field(default_factory=list)
    event: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, data: bytes) -> None:
        self.queue.append(data)
        # Bound the queue to avoid runaway memory if caller is slow.
        if len(self.queue) > 300:
            del self.queue[: len(self.queue) - 300]
        self.event.set()

    def consume(self, predicate: Callable[[bytes], bool]) -> Optional[bytes]:
        for i, raw in enumerate(self.queue):
            if predicate(raw):
                return self.queue.pop(i)
        return None


async def wait_for_raw(
    bus: NotifyBus,
    predicate: Callable[[bytes], bool],
    timeout: float,
    label: str,
) -> bytes:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        hit = bus.consume(predicate)
        if hit is not None:
            return hit
        remaining = deadline - loop.time()
        if remaining <= 0:
            tail_preview = ", ".join(
                (f"frame(flag=0x{f.flag:02x},cmd=0x{f.cmd:02x},len={f.length})"
                 if (f := parse_fe_frame(r)) else f"raw({len(r)}):{r[:8].hex()}")
                for r in bus.queue[-6:]
            ) or "no queued notifications"
            raise TimeoutError(f"timeout waiting for {label}; recent: {tail_preview}")
        bus.event.clear()
        try:
            await asyncio.wait_for(bus.event.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            pass  # loop around, consume() will re-check then raise


async def wait_for_frame(
    bus: NotifyBus,
    predicate: Callable[[E87Frame], bool],
    timeout: float,
    label: str,
) -> E87Frame:
    def pred(raw: bytes) -> bool:
        f = parse_fe_frame(raw)
        return bool(f and predicate(f))

    raw = await wait_for_raw(bus, pred, timeout, label)
    frame = parse_fe_frame(raw)
    assert frame is not None
    return frame


# ─── BLE helpers ────────────────────────────────────────────────────────────

async def _start_notify_tolerant(
    client: BleakClient,
    uuid: str,
    callback: Callable[[BleakGATTCharacteristic, bytearray], None],
) -> bool:
    """Subscribe to notifications, tolerating 'not supported' on BlueZ for the
    FD0x characteristics (they enable via JS/WinRT stacks but can fail to write
    the CCCD on Linux)."""
    try:
        await client.start_notify(uuid, callback)
        log.info("Subscribed to notifications on %s", uuid)
        return True
    except Exception as exc:  # pragma: no cover - stack-dependent
        log.warning("start_notify failed on %s: %s (continuing)", uuid, exc)
        return False


async def _write_ae01(client: BleakClient, data: bytes) -> None:
    """Write to AE01 (write-without-response)."""
    await client.write_gatt_char(AE_WRITE_UUID, bytes(data), response=False)


async def _write_fd02(client: BleakClient, data: bytes) -> None:
    """Write to FD02. Upstream uses writeValueWithoutResponse when advertised;
    BlueZ accepts write-without-response here. Tolerate occasional failures —
    these phases are best-effort bootstrap on the RCSP sideband."""
    try:
        await client.write_gatt_char(FD_WRITE_UUID, bytes(data), response=False)
    except Exception as exc:  # pragma: no cover - stack-dependent
        log.warning("FD02 write failed (%s): %s (continuing)", data.hex(), exc)


# ─── Auth handshake (mirrors ensureE87Auth in upstream) ─────────────────────

async def do_auth(client: BleakClient, bus: NotifyBus) -> None:
    log.info("Auth: starting Jieli RCSP crypto handshake")

    # Step 1: Phone → Device [0x00, rand*16]
    rand16 = secrets.token_bytes(16)
    await _write_ae01(client, b"\x00" + rand16)
    log.info("Auth TX: [0x00, rand*16]")

    # Step 2: Device → Phone [0x01, enc*16]
    dev_resp = await wait_for_raw(
        bus,
        lambda r: len(r) == 17 and r[0] == 0x01,
        timeout=5.0,
        label="auth device response [0x01, encrypted*16]",
    )
    log.info("Auth RX: %s", dev_resp.hex())

    # Step 3: Phone → Device [0x02, "pass"]
    await _write_ae01(client, b"\x02pass")
    log.info("Auth TX: [0x02, 'pass']")

    # Step 4: Device → Phone [0x00, challenge*16]
    dev_chal = await wait_for_raw(
        bus,
        lambda r: len(r) == 17 and r[0] == 0x00,
        timeout=5.0,
        label="auth device challenge [0x00, challenge*16]",
    )
    log.info("Auth RX challenge: %s", dev_chal.hex())

    # Step 5: Phone → Device [0x01, encrypted*16]
    encrypted = get_encrypted_auth_data(dev_chal[1:17])
    await _write_ae01(client, b"\x01" + encrypted)
    log.info("Auth TX encrypted: %s", encrypted.hex())

    # Step 6: Device → Phone [0x02, "pass"]
    confirm = await wait_for_raw(
        bus,
        lambda r: len(r) >= 5 and r[0] == 0x02 and r[1:5] == b"pass",
        timeout=5.0,
        label="auth pass confirmation",
    )
    log.info("Auth SUCCESS: %s", confirm.hex())


# ─── Upload state machine (mirrors writeFileE87) ────────────────────────────

def _build_file_path_response(device_seq: int) -> bytes:
    """Build the cmd 0x20 path response body. Upstream uses a fixed prefix
    character U+555C (HIRAGANA-ish placeholder; the device stores this verbatim
    as the gallery filename) plus YYYYMMDDHHMMSS and an extension."""
    import datetime
    now = datetime.datetime.now()
    date_str = now.strftime("%Y%m%d%H%M%S")
    device_path = "\u555c" + date_str + ".jpg"
    path_utf16 = device_path.encode("utf-16-le") + b"\x00\x00"
    return bytes((0x00, device_seq & 0xFF)) + path_utf16


def _random_temp_name() -> str:
    # Upstream randomTempName: 6 hex chars + ".tmp".
    return f"{random.randint(0, 0xFFFFFF):06x}.tmp"


async def _upload_state_machine(
    client: BleakClient,
    bus: NotifyBus,
    jpeg_bytes: bytes,
) -> None:
    log.info("Upload: payload is %d bytes of JPEG", len(jpeg_bytes))

    # Shared flag driven by both the main state machine and the fast-path
    # auto-responder for cmd 0x20 (the device has a ~100 ms timeout on this).
    file_complete_handled = {"done": False}

    async def send_fe(flag: int, cmd: int, body: bytes) -> None:
        frame = build_fe_frame(flag, cmd, body)
        log.info("TX FE flag=0x%02x cmd=0x%02x len=%d", flag, cmd, len(body))
        await _write_ae01(client, frame)

    seq = 0x00

    # ── PHASE 1: cmd 0x06 (reset auth flag) ──
    log.info("Phase 1: cmd 0x06 (reset auth flag)")
    await send_fe(FLAG_COMMAND, 0x06, bytes((0x02, 0x00, 0x01)))
    seq = 0x01
    await _write_fd02(client, bytes.fromhex("9EBD0B600D0003"))
    try:
        await wait_for_frame(
            bus, lambda f: f.cmd == 0x06, timeout=3.0, label="ack cmd 0x06",
        )
        log.info("cmd 0x06 acked")
    except TimeoutError:
        log.info("cmd 0x06 ack not received (continuing)")

    # ── PHASE 2: FD02 control writes (time, settings, heartbeat) ──
    log.info("Phase 2: FD02 control writes")
    import datetime
    now = datetime.datetime.now()
    year = now.year
    time_payload = bytes((
        0x9E, 0x45, 0x08, 0x02, 0x07, 0x00,
        year & 0xFF, (year >> 8) & 0xFF,
        now.month, now.day, 0x00,
        now.hour, now.minute,
    ))
    await _write_fd02(client, time_payload)
    await asyncio.sleep(0.02)
    await _write_fd02(client, bytes.fromhex("9E2008160100 01".replace(" ", "")))
    await asyncio.sleep(0.02)
    await _write_fd02(client, bytes.fromhex("9EB50B2901 0080".replace(" ", "")))
    await asyncio.sleep(0.2)

    # ── PHASE 3: cmd 0x03 (best-effort device info) ──
    try:
        log.info("Phase 3: cmd 0x03 (device info, best-effort)")
        await send_fe(FLAG_COMMAND, 0x03, bytes((seq, 0xFF, 0xFF, 0xFF, 0xFF, 0x01)))
        seq += 1
        await _write_fd02(client, bytes.fromhex("9ED30BC60100 01".replace(" ", "")))
        await asyncio.sleep(0.02)
        await _write_fd02(client, bytes.fromhex("9E3008200200 FF07".replace(" ", "")))
        await wait_for_frame(bus, lambda f: f.cmd == 0x03, timeout=3.0, label="ack cmd 0x03")
    except TimeoutError:
        log.info("cmd 0x03 not acked (continuing)")

    # ── PHASE 4: cmd 0x07 (best-effort device config) ──
    try:
        log.info("Phase 4: cmd 0x07 (device config, best-effort)")
        await send_fe(FLAG_COMMAND, 0x07, bytes((seq, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF)))
        seq += 1
        await _write_fd02(client, bytes.fromhex("9E2B08FF02002200"))
        await asyncio.sleep(0.04)
        await _write_fd02(client, bytes.fromhex("9E2D08FF02002400"))
        await wait_for_frame(bus, lambda f: f.cmd == 0x07, timeout=3.0, label="ack cmd 0x07")
    except TimeoutError:
        log.info("cmd 0x07 not acked (continuing)")

    # ── PHASE 5: FD02 bootstrap (heartbeat, info request, ready) ──
    log.info("Phase 5: FD02 bootstrap")
    await _write_fd02(client, bytes.fromhex("9EB50B29010080"))
    await asyncio.sleep(0.4)
    await _write_fd02(client, bytes.fromhex("9ED30BC6010001"))
    try:
        await wait_for_raw(
            bus,
            lambda r: len(r) >= 5 and r[0] == 0x9E and (r[3] == 0xC7 or r[2] == 0xC7),
            timeout=3.0,
            label="FD01 device info (C7)",
        )
    except TimeoutError:
        log.info("FD01 C7 not observed (continuing)")
    await _write_fd02(client, bytes.fromhex("9EF40BDC0100 0C".replace(" ", "")))
    try:
        await wait_for_raw(
            bus,
            lambda r: len(r) >= 4 and r[0] == 0x9E and r[1] == 0xE6,
            timeout=3.0,
            label="FD03 ready signal (9EE6)",
        )
        log.info("Device ready signal received")
    except TimeoutError:
        log.info("FD03 ready signal not observed (continuing)")

    # ── PHASE 6: cmd 0x21 (begin upload) ──
    log.info("Phase 6: cmd 0x21 (begin upload)")
    await send_fe(FLAG_COMMAND, 0x21, bytes((seq, 0x00)))
    seq += 1
    await wait_for_frame(bus, lambda f: f.cmd == 0x21, timeout=8.0, label="ack cmd 0x21")

    # ── PHASE 7: cmd 0x27 (transfer params) ──
    log.info("Phase 7: cmd 0x27 (transfer params)")
    await send_fe(
        FLAG_COMMAND, 0x27, bytes((seq, 0x00, 0x00, 0x00, 0x00, 0x02, 0x01)),
    )
    seq += 1
    await wait_for_frame(bus, lambda f: f.cmd == 0x27, timeout=8.0, label="ack cmd 0x27")

    # ── PHASE 8: cmd 0x1b (file metadata) ──
    log.info("Phase 8: cmd 0x1b (file metadata)")
    file_size = len(jpeg_bytes)
    temp_name = _random_temp_name()
    name_bytes = temp_name.encode("ascii")
    file_crc = crc16xmodem(jpeg_bytes)
    log.info("Whole-file CRC-16/XMODEM = 0x%04x, temp name = %s", file_crc, temp_name)

    meta = bytearray(3 + 2 + 4 + len(name_bytes) + 1)
    meta[0] = seq & 0xFF
    seq += 1
    meta[1] = (file_size >> 24) & 0xFF
    meta[2] = (file_size >> 16) & 0xFF
    meta[3] = (file_size >> 8) & 0xFF
    meta[4] = file_size & 0xFF
    meta[5] = (file_crc >> 8) & 0xFF
    meta[6] = file_crc & 0xFF
    meta[7] = secrets.randbits(8)
    meta[8] = secrets.randbits(8)
    meta[9 : 9 + len(name_bytes)] = name_bytes
    meta[-1] = 0x00

    await send_fe(FLAG_COMMAND, 0x1B, bytes(meta))
    meta_ack = await wait_for_frame(
        bus, lambda f: f.cmd == 0x1B, timeout=8.0, label="ack cmd 0x1b",
    )

    chunk_size = E87_DATA_CHUNK_SIZE
    if len(meta_ack.body) >= 4:
        hinted = (meta_ack.body[2] << 8) | meta_ack.body[3]
        log.info("Device chunk-size hint from 0x1b ack: %d", hinted)
        if 0 < hinted <= 4096:
            chunk_size = hinted
        else:
            log.info("Unusual chunk-size hint (%d); staying with %d", hinted, E87_DATA_CHUNK_SIZE)

    # ── PHASE 9: windowed data transfer ──
    log.info("Phase 9: data transfer (chunk=%d)", chunk_size)
    total_chunks = (len(jpeg_bytes) + chunk_size - 1) // chunk_size
    log.info("Total: %d bytes, %d chunks", len(jpeg_bytes), total_chunks)

    data_seq = seq  # starts at 0x06 under normal flow
    sent_chunks = 0
    total_bytes_sent = 0

    async def send_window(offset: int, win_size: int) -> None:
        nonlocal data_seq, sent_chunks, total_bytes_sent
        slot = 0
        bytes_in_window = 0
        chunks_in_window = 0
        while bytes_in_window < win_size:
            chunk_offset = offset + bytes_in_window
            if chunk_offset >= len(jpeg_bytes):
                break
            remaining = min(win_size - bytes_in_window, len(jpeg_bytes) - chunk_offset)
            chunk_len = min(chunk_size, remaining)
            payload = jpeg_bytes[chunk_offset : chunk_offset + chunk_len]
            crc = crc16xmodem(payload)
            body = bytearray(5 + len(payload))
            body[0] = data_seq & 0xFF
            body[1] = 0x1D
            body[2] = slot & 0xFF
            body[3] = (crc >> 8) & 0xFF
            body[4] = crc & 0xFF
            body[5:] = payload

            frame = build_fe_frame(FLAG_DATA, 0x01, bytes(body))
            await _write_ae01(client, frame)

            sent_chunks += 1
            total_bytes_sent += chunk_len
            chunks_in_window += 1
            if sent_chunks == 1 or sent_chunks == total_chunks or sent_chunks % 8 == 0:
                log.info(
                    "Data chunk %d/%d seq=0x%02x slot=%d crc=0x%04x "
                    "(%d/%d bytes)",
                    sent_chunks,
                    total_chunks,
                    data_seq & 0xFF,
                    slot,
                    crc,
                    total_bytes_sent,
                    len(jpeg_bytes),
                )

            data_seq = (data_seq + 1) & 0xFF
            slot = (slot + 1) & 0x07
            bytes_in_window += chunk_len
        log.info(
            "Window done: %d chunks, %d bytes (total %d/%d)",
            chunks_in_window,
            bytes_in_window,
            total_bytes_sent,
            len(jpeg_bytes),
        )

    # The device ALWAYS sends a window ack (flag=0x80, cmd=0x1D) to start the
    # transfer. Upstream waits with a generous timeout and aborts cleanly if
    # nothing arrives, rather than falling back to an uncontrolled stream.
    try:
        current_ack = await wait_for_frame(
            bus,
            lambda f: f.flag == FLAG_DATA and f.cmd == 0x1D,
            timeout=10.0,
            label="initial window ack",
        )
    except TimeoutError as exc:
        raise RuntimeError(
            "Device did not send the initial window ACK within 10 s — "
            "cannot start data transfer. Please retry the upload."
        ) from exc

    done = False
    while not done:
        if current_ack is not None and current_ack.cmd == 0x1D and len(current_ack.body) >= 8:
            ack_seq = current_ack.body[0]
            ack_status = current_ack.body[1]
            win_size = (current_ack.body[2] << 8) | current_ack.body[3]
            next_offset = (
                (current_ack.body[4] << 24)
                | (current_ack.body[5] << 16)
                | (current_ack.body[6] << 8)
                | current_ack.body[7]
            )
            log.info(
                "Window ack #%d: status=0x%02x winSize=%d nextOffset=%d",
                ack_seq, ack_status, win_size, next_offset,
            )
            if ack_status != 0x00:
                log.warning("Non-zero window ack status: 0x%02x", ack_status)
            await send_window(next_offset, win_size)

        frame = await wait_for_frame(
            bus,
            lambda f: (f.flag == FLAG_DATA and f.cmd == 0x1D)
            or f.cmd == 0x20
            or f.cmd == 0x1C,
            timeout=15.0,
            label="window ack, FILE_COMPLETE or session close",
        )

        if frame.cmd == 0x20 and frame.flag == FLAG_COMMAND:
            device_seq_20 = frame.body[0] if frame.body else (data_seq & 0xFF)
            log.info("RX cmd 0x20 (FILE_COMPLETE) seq=%d", device_seq_20)
            if not file_complete_handled["done"]:
                await send_fe(FLAG_RESPONSE, 0x20, _build_file_path_response(device_seq_20))
                file_complete_handled["done"] = True
                log.info("Sent path response")
            close_frame = await wait_for_frame(
                bus,
                lambda f: f.cmd == 0x1C,
                timeout=15.0,
                label="session close (cmd 0x1c)",
            )
            await _finalize(send_fe, close_frame)
            done = True
            break

        if frame.cmd == 0x1C:
            await _finalize(send_fe, frame)
            done = True
            break

        current_ack = frame


async def _finalize(
    send_fe: Callable[[int, int, bytes], Awaitable[None]],
    close_frame: E87Frame,
) -> None:
    body_hex = close_frame.body.hex()
    device_seq = close_frame.body[0] if close_frame.body else 0
    status = close_frame.body[1] if len(close_frame.body) >= 2 else 0xFF
    log.info(
        "RX cmd 0x%02x (SESSION_CLOSE): body=%s deviceSeq=%d status=0x%02x",
        close_frame.cmd, body_hex, device_seq, status,
    )
    await send_fe(FLAG_RESPONSE, 0x1C, bytes((0x00, device_seq & 0xFF)))
    if status == 0x00:
        log.info("Upload complete")
    else:
        log.warning("Device reported non-zero status 0x%02x on session close", status)


# ─── Public entry point ─────────────────────────────────────────────────────

async def send_image(mac: str, image_path: str | pathlib.Path) -> None:
    """Connect to the E87 badge at `mac`, authenticate, encode `image_path` as
    a suitable JPEG, upload it, and make the badge display it as a new gallery
    image.
    """
    image_path = pathlib.Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    log.info("Encoding %s for E87 (%dx%d JPEG)…",
             image_path, E87_IMAGE_WIDTH, E87_IMAGE_HEIGHT)
    jpeg = encode_image_to_jpeg(image_path)

    log.info("Scanning / connecting to %s …", mac)

    # Resolve the device via BleakScanner first (helps on Linux BlueZ; on macOS
    # the MAC isn't stable but BleakClient(str) also accepts raw addresses so
    # we fall back if discovery doesn't find it).
    device = await BleakScanner.find_device_by_address(mac, timeout=15.0)
    target: str | object = device if device is not None else mac
    if device is None:
        log.warning("Scanner did not surface %s; trying BleakClient(mac) directly", mac)

    bus = NotifyBus()

    def _on_notify(_char: BleakGATTCharacteristic, data: bytearray) -> None:
        raw = bytes(data)
        f = parse_fe_frame(raw)
        if f is not None:
            log.debug(
                "RX FE flag=0x%02x cmd=0x%02x len=%d body=%s",
                f.flag, f.cmd, f.length, f.body.hex(),
            )
        else:
            log.debug("RX raw (%d): %s", len(raw), raw.hex())
        bus.push(raw)

    async with BleakClient(target) as client:  # type: ignore[arg-type]
        log.info("Connected. MTU=%s", getattr(client, "mtu_size", "?"))

        # Subscribe to everything the device might notify on. FD* CCCD writes
        # commonly return "not supported" on BlueZ — we warn and keep going
        # because AE02 is what the upload state machine strictly needs.
        for uuid in ALL_NOTIFY_UUIDS:
            await _start_notify_tolerant(client, uuid, _on_notify)

        # Small settle delay before the auth handshake so queued notifications
        # from the connect event don't confuse the first waitRaw.
        await asyncio.sleep(0.1)

        await do_auth(client, bus)
        await _upload_state_machine(client, bus, jpeg)

        # Gracefully tear down notify subscriptions before disconnect.
        for uuid in ALL_NOTIFY_UUIDS:
            try:
                await client.stop_notify(uuid)
            except Exception:
                pass

    log.info("Done. Badge should display the new image shortly.")


# ─── CLI ────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m spike.e87_client",
        description=(
            "Upload a still image to an E87 / L8 LED badge over BLE. "
            "Ported from web-bluetooth-e87 (MIT, Felix Herbst)."
        ),
    )
    parser.add_argument("--mac", required=True, help="BLE MAC address of the badge")
    parser.add_argument(
        "--image",
        required=True,
        type=pathlib.Path,
        help="Path to a PNG/JPEG/etc. image to upload",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging (includes per-frame wire dumps)",
    )
    return parser


def _cli(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(send_image(args.mac, args.image))
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        return 130
    except Exception as exc:  # pragma: no cover - CLI surface
        log.error("Upload failed: %s", exc, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
