"""Full-timeline session replay: every captured write across every service,
in the original time order, with the 3 auth packets substituted by fresh
live values.

This is the ultimate "verbatim replay" test. If this does not result in the
badge displaying the solid red from capture 01, then the badge maintains
per-session state that we can't reproduce without porting the upstream
e87-protocol.ts in full.

Usage:
    python -m spike.send_live_full --mac 46:8D:00:01:2C:25
"""

import argparse
import asyncio
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

from bleak import BleakClient, BleakScanner

from spike.jieli_auth import get_encrypted_auth_data

CAPTURE = Path(__file__).parent.parent / "docs" / "captures" / "01-solid-red-360.all-writes.txt"

# GATT handles (from the capture) mapped to their 128-bit characteristic UUIDs.
# Handles that don't correspond to characteristic VALUE writes are CCCDs
# (Client Characteristic Configuration Descriptors), used to enable
# notifications. We subscribe via bleak's start_notify instead of replaying
# these manually.
HANDLE_TO_UUID = {
    0x0006: "0000ae01-0000-1000-8000-00805f9b34fb",  # AE01 (badge image-upload write)
    0x000c: "c2e6fd02-e966-1000-8000-bef9c223df6a",  # FD02 (JieLi RCSP write)
}

# CCCD handles observed in the capture, mapped to the UUID of the
# characteristic whose notifications they gate.
CCCD_HANDLE_TO_NOTIFY_UUID = {
    0x0009: "0000ae02-0000-1000-8000-00805f9b34fb",  # AE02 notify
    0x000f: "c2e6fd03-e966-1000-8000-bef9c223df6a",  # FD03 notify
    0x0012: "c2e6fd04-e966-1000-8000-bef9c223df6a",  # FD04 notify — note this
                                                     # char is Write-no-Response
                                                     # so this CCCD may be a noop
}


@dataclass(frozen=True)
class Write:
    frame: int
    t: float
    handle: int
    opcode: int
    payload: bytes


def load_all_writes() -> list[Write]:
    rows: list[Write] = []
    for line in CAPTURE.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 5:
            raise RuntimeError(f"bad line: {line!r}")
        frame, t, handle, opcode, value = parts
        rows.append(
            Write(
                frame=int(frame),
                t=float(t),
                handle=int(handle, 16),
                opcode=int(opcode, 16),
                payload=bytes.fromhex(value) if value else b"",
            )
        )
    return rows


class NotifyBus:
    """Demultiplexes notifications from every subscribed characteristic."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[bytes]] = {}

    def make_callback(self, uuid: str):
        q: asyncio.Queue[bytes] = asyncio.Queue()
        self._queues[uuid] = q

        def cb(_handle: int, data: bytearray) -> None:
            payload = bytes(data)
            q.put_nowait(payload)
            logging.info("← [%s] %s", uuid.split("-")[0], payload.hex())

        return cb

    async def get(self, uuid: str, timeout: float = 5.0) -> bytes:
        return await asyncio.wait_for(self._queues[uuid].get(), timeout=timeout)

    def try_drain(self, uuid: str) -> list[bytes]:
        q = self._queues[uuid]
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out


async def replay(mac: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    writes = load_all_writes()
    logging.info("loaded %d rows from capture", len(writes))

    device = await BleakScanner.find_device_by_address(mac, timeout=20.0)
    if device is None:
        raise SystemExit(f"badge {mac} not found; wake it and retry")

    async with BleakClient(device) as client:
        logging.info("connected, mtu=%d", client.mtu_size)

        bus = NotifyBus()
        for _, notify_uuid in CCCD_HANDLE_TO_NOTIFY_UUID.items():
            try:
                await client.start_notify(notify_uuid, bus.make_callback(notify_uuid))
                logging.info("subscribed %s", notify_uuid.split("-")[0])
            except Exception as e:
                logging.warning("cannot subscribe %s: %s", notify_uuid, e)

        ae02_uuid = CCCD_HANDLE_TO_NOTIFY_UUID[0x0009]
        ae01_uuid = HANDLE_TO_UUID[0x0006]

        # Walk the capture. For AE01 auth packets we substitute live values;
        # everything else we send verbatim.
        phone_challenge: bytes | None = None
        badge_challenge: bytes | None = None
        auth_step = 0  # 0 = waiting for phone_challenge substitution, 1 = phone_response

        for i, w in enumerate(writes):
            if w.payload == b"":
                # CCCD write — handled via start_notify above
                logging.info("skip CCCD handle=0x%04x", w.handle)
                continue

            uuid = HANDLE_TO_UUID.get(w.handle)
            if uuid is None:
                logging.warning("unknown handle 0x%04x, skipping", w.handle)
                continue

            # Detect AE01 auth slots and substitute with live values
            payload = w.payload
            if w.handle == 0x0006 and len(payload) == 17 and payload[0] == 0x00 and auth_step == 0:
                phone_challenge = secrets.token_bytes(16)
                payload = b"\x00" + phone_challenge
                logging.info("AUTH step 1: substituting phone challenge %s", phone_challenge.hex())
                await client.write_gatt_char(uuid, payload, response=False)

                # Expect badge 01+response on AE02
                resp = await bus.get(ae02_uuid, timeout=3.0)
                if resp[0] != 0x01 or len(resp) != 17:
                    raise RuntimeError(f"bad badge auth resp1: {resp.hex()}")
                expected = get_encrypted_auth_data(phone_challenge)
                match = "✓" if resp[1:] == expected else "✗"
                logging.info("badge resp1 verify: %s", match)

                auth_step = 1
                continue

            if w.handle == 0x0006 and len(payload) == 17 and payload[0] == 0x01 and auth_step == 1:
                # Need badge challenge first — should already be queued
                try:
                    msg = await bus.get(ae02_uuid, timeout=3.0)
                except asyncio.TimeoutError:
                    raise RuntimeError("timed out waiting for badge challenge")
                if msg[0] != 0x00:
                    raise RuntimeError(f"expected badge challenge, got {msg.hex()}")
                badge_challenge = msg[1:17]
                phone_response = get_encrypted_auth_data(badge_challenge)
                payload = b"\x01" + phone_response
                logging.info("AUTH step 2: sending phone response %s", phone_response.hex())
                await client.write_gatt_char(uuid, payload, response=False)

                # Expect badge's final "pass"
                final = await bus.get(ae02_uuid, timeout=3.0)
                if final != b"\x02pass":
                    raise RuntimeError(f"auth failed: {final.hex()}")
                logging.info("AUTHENTICATED ✓")
                auth_step = 2
                continue

            # Default: send as captured
            service_tag = "AE01" if w.handle == 0x0006 else "FD02"
            is_ae01_req = (
                w.handle == 0x0006
                and len(payload) >= 4
                and payload[:3] == b"\xfe\xdc\xba"
                and bool(payload[3] & 0x40)
            )
            await client.write_gatt_char(uuid, payload, response=False)
            logging.info(
                "→ %2d/%d  %s  len=%-3d  head=%s%s",
                i + 1,
                len(writes),
                service_tag,
                len(payload),
                payload[:10].hex(),
                "  [hasResponse]" if is_ae01_req else "",
            )
            if is_ae01_req:
                try:
                    await bus.get(ae02_uuid, timeout=2.0)
                except asyncio.TimeoutError:
                    logging.warning("  no ack within 2s")
            else:
                await asyncio.sleep(0.03)

        logging.info("replay complete, draining final notifications for 3s")
        await asyncio.sleep(3.0)
        for uuid in (ae02_uuid, CCCD_HANDLE_TO_NOTIFY_UUID[0x000f]):
            for n in bus.try_drain(uuid):
                logging.info("← (drain) %s  %s", uuid.split("-")[0], n.hex())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", required=True, help="E87 badge BLE MAC address")
    args = parser.parse_args()
    asyncio.run(replay(args.mac))


if __name__ == "__main__":
    main()
