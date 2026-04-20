"""Replay the captured Zrun image upload against the E87 badge, verbatim.

Sanity check for phase 1: if this does NOT make the badge display red again, either
our understanding of the GATT structure is wrong, or the badge's auth handshake
enforces nonce freshness (in which case bit-for-bit replay cannot succeed and we
need to emulate the JieLi `libjl_auth.so` native library).

Usage:
    python -m spike.replay --mac 46:8D:00:01:2C:25
"""

import argparse
import asyncio
import logging

from bleak import BleakClient, BleakScanner

from spike._fixture import Write, load_writes

# Standardized 16-bit UUIDs expanded to 128-bit form (Bluetooth Base UUID).
# Service 0xae00, write characteristic 0xae01, notify characteristic 0xae02.
WRITE_CHAR_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

# All captured writes were opcode 0x52 (Write Without Response).
USE_WRITE_WITHOUT_RESPONSE = True

# Base delay between writes. Too aggressive (0) can overrun the badge's BLE stack;
# too conservative wastes time. 0.02 is a safe start.
INTER_WRITE_DELAY_S = 0.02

# Per the RCSP framing: bit 6 of the flags byte means "hasResponse" — the phone
# expects the badge to notify before the next command is sent. When replaying we
# wait a little longer after these to let the notification arrive.
HAS_RESPONSE_DELAY_S = 0.2


def has_response_flag(payload: bytes) -> bool:
    """True if this is a `FE DC BA <flags> …` frame with the hasResponse bit set."""
    if len(payload) < 5 or payload[:3] != b"\xfe\xdc\xba":
        return False
    flags = payload[3]
    return bool(flags & 0x40)


async def replay(mac: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    writes: list[Write] = load_writes()
    logging.info("loaded %d writes, %d bytes total", len(writes), sum(len(w.payload) for w in writes))

    logging.info("scanning for badge %s …", mac)
    device = await BleakScanner.find_device_by_address(mac, timeout=20.0)
    if device is None:
        raise SystemExit(f"badge {mac} not found; wake it (short-press) and retry")

    async with BleakClient(device) as client:
        logging.info("connected, mtu=%d", client.mtu_size)

        received: list[bytes] = []

        def on_notify(_handle: int, data: bytearray) -> None:
            received.append(bytes(data))
            logging.info("← notify %d bytes: %s", len(data), bytes(data).hex())

        await client.start_notify(NOTIFY_CHAR_UUID, on_notify)
        logging.info("notifications enabled on %s", NOTIFY_CHAR_UUID)

        for i, w in enumerate(writes):
            delay = HAS_RESPONSE_DELAY_S if has_response_flag(w.payload) else INTER_WRITE_DELAY_S
            await client.write_gatt_char(
                WRITE_CHAR_UUID,
                w.payload,
                response=not USE_WRITE_WITHOUT_RESPONSE,
            )
            logging.info(
                "→ write %2d/%d  len=%-3d  head=%s%s",
                i + 1,
                len(writes),
                len(w.payload),
                w.payload[:10].hex(),
                "  [hasResponse]" if delay == HAS_RESPONSE_DELAY_S else "",
            )
            await asyncio.sleep(delay)

        # Give the badge a moment to finish processing the last data frame.
        await asyncio.sleep(1.0)
        await client.stop_notify(NOTIFY_CHAR_UUID)
        logging.info("replay complete — %d notifications received", len(received))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", required=True, help="E87 badge BLE MAC address")
    args = parser.parse_args()
    asyncio.run(replay(args.mac))


if __name__ == "__main__":
    main()
