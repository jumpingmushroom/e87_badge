"""9-phase upload state machine for the E87 badge.

The `UploadSession` class takes two writer callables (one for AE01, one for
FD02) and a `NotifyBus` that is already receiving notifications from AE02
(and ideally also from FD01/FD03/FD05). Calling `run(data, extension=...)`
negotiates with the badge through the pre-upload setup phases and streams
the data in windowed chunks. The `extension` parameter decides whether the
badge treats the file as a still image (`"jpg"`) or an animated MJPG-AVI
(`"avi"`).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random
import secrets
from typing import Awaitable, Callable

from .const import (
    E87_DATA_CHUNK_SIZE,
    EXTENSION_STATIC,
    FLAG_COMMAND,
    FLAG_DATA,
    FLAG_RESPONSE,
)
from .crc import crc16xmodem
from .errors import E87ProtocolError, E87TransferAborted
from .frame import E87Frame, build_fe_frame
from .notify import NotifyBus, wait_for_frame, wait_for_raw

log = logging.getLogger(__name__)

Writer = Callable[[bytes], Awaitable[None]]


class UploadSession:
    def __init__(
        self,
        write_ae01: Writer,
        write_fd02: Writer,
        bus: NotifyBus,
    ) -> None:
        self._write_ae01 = write_ae01
        self._write_fd02 = write_fd02
        self._bus = bus
        self._seq = 0x00
        self._file_complete_handled = False

    async def run(self, data: bytes, *, extension: str = EXTENSION_STATIC) -> None:
        """Upload `data` (already fully encoded — JPEG bytes for static, AVI
        bytes for animated) with the filename extension `.ext`."""
        log.info("Upload: payload is %d bytes, extension=.%s", len(data), extension)
        self._seq = 0x00
        self._file_complete_handled = False

        await self._phase1_reset_auth()
        await self._phase2_fd02_control()
        await self._phase3_device_info()
        await self._phase4_device_config()
        await self._phase5_fd02_bootstrap()
        await self._phase6_begin_upload()
        await self._phase7_transfer_params()
        chunk_size = await self._phase8_file_metadata(data, extension)
        await self._phase9_transfer(data, chunk_size, extension)

    # ── Phase helpers ──────────────────────────────────────────────────────

    async def _send_fe(self, flag: int, cmd: int, body: bytes) -> None:
        frame = build_fe_frame(flag, cmd, body)
        log.info("TX FE flag=0x%02x cmd=0x%02x len=%d", flag, cmd, len(body))
        await self._write_ae01(frame)

    async def _phase1_reset_auth(self) -> None:
        log.info("Phase 1: cmd 0x06 (reset auth flag)")
        await self._send_fe(FLAG_COMMAND, 0x06, bytes((0x02, 0x00, 0x01)))
        self._seq = 0x01
        await self._write_fd02(bytes.fromhex("9EBD0B600D0003"))
        try:
            await wait_for_frame(
                self._bus, lambda f: f.cmd == 0x06, timeout=3.0, label="ack cmd 0x06",
            )
            log.info("cmd 0x06 acked")
        except TimeoutError:
            log.info("cmd 0x06 ack not received (continuing)")

    async def _phase2_fd02_control(self) -> None:
        log.info("Phase 2: FD02 control writes")
        now = dt.datetime.now()
        time_payload = bytes(
            (
                0x9E, 0x45, 0x08, 0x02, 0x07, 0x00,
                now.year & 0xFF, (now.year >> 8) & 0xFF,
                now.month, now.day, 0x00,
                now.hour, now.minute,
            )
        )
        await self._write_fd02(time_payload)
        await asyncio.sleep(0.02)
        await self._write_fd02(bytes.fromhex("9E200816010001"))
        await asyncio.sleep(0.02)
        await self._write_fd02(bytes.fromhex("9EB50B29010080"))
        await asyncio.sleep(0.2)

    async def _phase3_device_info(self) -> None:
        try:
            log.info("Phase 3: cmd 0x03 (device info, best-effort)")
            await self._send_fe(FLAG_COMMAND, 0x03, bytes((self._seq, 0xFF, 0xFF, 0xFF, 0xFF, 0x01)))
            self._seq += 1
            await self._write_fd02(bytes.fromhex("9ED30BC6010001"))
            await asyncio.sleep(0.02)
            await self._write_fd02(bytes.fromhex("9E30082002 00FF07".replace(" ", "")))
            await wait_for_frame(self._bus, lambda f: f.cmd == 0x03, timeout=3.0, label="ack cmd 0x03")
        except TimeoutError:
            log.info("cmd 0x03 not acked (continuing)")

    async def _phase4_device_config(self) -> None:
        try:
            log.info("Phase 4: cmd 0x07 (device config, best-effort)")
            await self._send_fe(FLAG_COMMAND, 0x07, bytes((self._seq, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF)))
            self._seq += 1
            await self._write_fd02(bytes.fromhex("9E2B08FF02002200"))
            await asyncio.sleep(0.04)
            await self._write_fd02(bytes.fromhex("9E2D08FF02002400"))
            await wait_for_frame(self._bus, lambda f: f.cmd == 0x07, timeout=3.0, label="ack cmd 0x07")
        except TimeoutError:
            log.info("cmd 0x07 not acked (continuing)")

    async def _phase5_fd02_bootstrap(self) -> None:
        log.info("Phase 5: FD02 bootstrap")
        await self._write_fd02(bytes.fromhex("9EB50B29010080"))
        await asyncio.sleep(0.4)
        await self._write_fd02(bytes.fromhex("9ED30BC6010001"))
        try:
            await wait_for_raw(
                self._bus,
                lambda r: len(r) >= 5 and r[0] == 0x9E and (r[3] == 0xC7 or r[2] == 0xC7),
                timeout=3.0,
                label="FD01 device info (C7)",
            )
        except TimeoutError:
            log.info("FD01 C7 not observed (continuing)")
        await self._write_fd02(bytes.fromhex("9EF40BDC01000C"))
        try:
            await wait_for_raw(
                self._bus,
                lambda r: len(r) >= 4 and r[0] == 0x9E and r[1] == 0xE6,
                timeout=3.0,
                label="FD03 ready signal (9EE6)",
            )
            log.info("Device ready signal received")
        except TimeoutError:
            log.info("FD03 ready signal not observed (continuing)")

    async def _phase6_begin_upload(self) -> None:
        log.info("Phase 6: cmd 0x21 (begin upload)")
        await self._send_fe(FLAG_COMMAND, 0x21, bytes((self._seq, 0x00)))
        self._seq += 1
        try:
            await wait_for_frame(self._bus, lambda f: f.cmd == 0x21, timeout=8.0, label="ack cmd 0x21")
        except TimeoutError as exc:
            raise E87ProtocolError("device did not ack begin-upload (cmd 0x21)") from exc

    async def _phase7_transfer_params(self) -> None:
        log.info("Phase 7: cmd 0x27 (transfer params)")
        await self._send_fe(
            FLAG_COMMAND, 0x27, bytes((self._seq, 0x00, 0x00, 0x00, 0x00, 0x02, 0x01)),
        )
        self._seq += 1
        try:
            await wait_for_frame(self._bus, lambda f: f.cmd == 0x27, timeout=8.0, label="ack cmd 0x27")
        except TimeoutError as exc:
            raise E87ProtocolError("device did not ack transfer params (cmd 0x27)") from exc

    async def _phase8_file_metadata(self, data: bytes, extension: str) -> int:
        log.info("Phase 8: cmd 0x1b (file metadata)")
        file_size = len(data)
        temp_name = _random_temp_name(extension)
        name_bytes = temp_name.encode("ascii")
        file_crc = crc16xmodem(data)
        log.info("Whole-file CRC-16/XMODEM = 0x%04x, temp name = %s", file_crc, temp_name)

        meta = bytearray(3 + 2 + 4 + len(name_bytes) + 1)
        meta[0] = self._seq & 0xFF
        self._seq += 1
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

        await self._send_fe(FLAG_COMMAND, 0x1B, bytes(meta))
        try:
            meta_ack = await wait_for_frame(
                self._bus, lambda f: f.cmd == 0x1B, timeout=8.0, label="ack cmd 0x1b",
            )
        except TimeoutError as exc:
            raise E87ProtocolError("device did not ack file metadata (cmd 0x1b)") from exc

        chunk_size = E87_DATA_CHUNK_SIZE
        if len(meta_ack.body) >= 4:
            hinted = (meta_ack.body[2] << 8) | meta_ack.body[3]
            log.info("Device chunk-size hint from 0x1b ack: %d", hinted)
            if 0 < hinted <= 4096:
                chunk_size = hinted
            else:
                log.info("Unusual chunk-size hint (%d); staying with %d", hinted, E87_DATA_CHUNK_SIZE)
        return chunk_size

    async def _phase9_transfer(self, data: bytes, chunk_size: int, extension: str) -> None:
        log.info("Phase 9: data transfer (chunk=%d)", chunk_size)
        total_chunks = (len(data) + chunk_size - 1) // chunk_size
        log.info("Total: %d bytes, %d chunks", len(data), total_chunks)

        state = _TransferState(data_seq=self._seq, total_chunks=total_chunks)

        try:
            current_ack = await wait_for_frame(
                self._bus,
                lambda f: f.flag == FLAG_DATA and f.cmd == 0x1D,
                timeout=10.0,
                label="initial window ack",
            )
        except TimeoutError as exc:
            raise E87TransferAborted(
                "device did not send the initial window ack within 10s"
            ) from exc

        while True:
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
                await self._send_window(data, chunk_size, next_offset, win_size, state)

            try:
                frame = await wait_for_frame(
                    self._bus,
                    lambda f: (f.flag == FLAG_DATA and f.cmd == 0x1D)
                    or f.cmd == 0x20
                    or f.cmd == 0x1C,
                    timeout=15.0,
                    label="window ack, FILE_COMPLETE or session close",
                )
            except TimeoutError as exc:
                raise E87TransferAborted("no window ack / completion within 15s") from exc

            if frame.cmd == 0x20 and frame.flag == FLAG_COMMAND:
                device_seq_20 = frame.body[0] if frame.body else (state.data_seq & 0xFF)
                log.info("RX cmd 0x20 (FILE_COMPLETE) seq=%d", device_seq_20)
                if not self._file_complete_handled:
                    await self._send_fe(
                        FLAG_RESPONSE, 0x20,
                        _build_file_path_response(device_seq_20, extension),
                    )
                    self._file_complete_handled = True
                    log.info("Sent path response")
                close_frame = await wait_for_frame(
                    self._bus, lambda f: f.cmd == 0x1C, timeout=15.0,
                    label="session close (cmd 0x1c)",
                )
                await self._finalize(close_frame)
                return

            if frame.cmd == 0x1C:
                await self._finalize(frame)
                return

            current_ack = frame

    async def _send_window(
        self,
        data: bytes,
        chunk_size: int,
        offset: int,
        win_size: int,
        state: _TransferState,
    ) -> None:
        slot = 0
        bytes_in_window = 0
        chunks_in_window = 0
        while bytes_in_window < win_size:
            chunk_offset = offset + bytes_in_window
            if chunk_offset >= len(data):
                break
            remaining = min(win_size - bytes_in_window, len(data) - chunk_offset)
            chunk_len = min(chunk_size, remaining)
            payload = data[chunk_offset : chunk_offset + chunk_len]
            crc = crc16xmodem(payload)
            body = bytearray(5 + len(payload))
            body[0] = state.data_seq & 0xFF
            body[1] = 0x1D
            body[2] = slot & 0xFF
            body[3] = (crc >> 8) & 0xFF
            body[4] = crc & 0xFF
            body[5:] = payload

            frame = build_fe_frame(FLAG_DATA, 0x01, bytes(body))
            await self._write_ae01(frame)

            state.sent_chunks += 1
            state.total_bytes_sent += chunk_len
            chunks_in_window += 1
            if state.sent_chunks == 1 or state.sent_chunks == state.total_chunks or state.sent_chunks % 8 == 0:
                log.info(
                    "Data chunk %d/%d seq=0x%02x slot=%d crc=0x%04x (%d/%d bytes)",
                    state.sent_chunks, state.total_chunks,
                    state.data_seq & 0xFF, slot, crc,
                    state.total_bytes_sent, len(data),
                )
            state.data_seq = (state.data_seq + 1) & 0xFF
            slot = (slot + 1) & 0x07
            bytes_in_window += chunk_len

        log.info(
            "Window done: %d chunks, %d bytes (total %d/%d)",
            chunks_in_window, bytes_in_window, state.total_bytes_sent, len(data),
        )

    async def _finalize(self, close_frame: E87Frame) -> None:
        body_hex = close_frame.body.hex()
        device_seq = close_frame.body[0] if close_frame.body else 0
        status = close_frame.body[1] if len(close_frame.body) >= 2 else 0xFF
        log.info(
            "RX cmd 0x%02x (SESSION_CLOSE): body=%s deviceSeq=%d status=0x%02x",
            close_frame.cmd, body_hex, device_seq, status,
        )
        await self._send_fe(FLAG_RESPONSE, 0x1C, bytes((0x00, device_seq & 0xFF)))
        if status == 0x00:
            log.info("Upload complete")
        else:
            log.warning("Device reported non-zero status 0x%02x on session close", status)


# ── helpers ────────────────────────────────────────────────────────────────

class _TransferState:
    def __init__(self, *, data_seq: int, total_chunks: int) -> None:
        self.data_seq = data_seq
        self.total_chunks = total_chunks
        self.sent_chunks = 0
        self.total_bytes_sent = 0


def _random_temp_name(extension: str) -> str:
    return f"{random.randint(0, 0xFFFFFF):06x}.{extension}"


def _build_file_path_response(device_seq: int, extension: str) -> bytes:
    """Body of the cmd 0x20 reply. Upstream uses a fixed prefix character
    U+555C plus YYYYMMDDHHMMSS plus the file extension; the device stores
    this verbatim as the gallery filename."""
    now = dt.datetime.now()
    date_str = now.strftime("%Y%m%d%H%M%S")
    device_path = "\u555c" + date_str + "." + extension
    path_utf16 = device_path.encode("utf-16-le") + b"\x00\x00"
    return bytes((0x00, device_seq & 0xFF)) + path_utf16
