"""Live E87 session: fresh auth + verbatim replay of captured image upload.

Unlike `spike/replay.py` (verbatim replay, auth fails because the badge enforces
session-specific crypto), this script runs the JieLi auth cipher ourselves with
fresh nonces, and only replays the post-auth portion of the capture.

If successful, the badge should display the solid-red JPEG from capture 01.

Usage:
    python -m spike.send_live --mac 46:8D:00:01:2C:25
"""

import argparse
import asyncio
import logging
import secrets

from bleak import BleakClient, BleakScanner

from spike._fixture import load_writes
from spike.jieli_auth import get_encrypted_auth_data

WRITE_CHAR_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

SESSION_INIT = bytes.fromhex("fedcbac00600020001ef")
PASS_TOKEN = b"\x02pass"


class NotifyQueue:
    """Receive-side buffer for handle 0xae02 notifications."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[bytes] = asyncio.Queue()

    def push(self, _handle: int, data: bytearray) -> None:
        self._q.put_nowait(bytes(data))

    async def get(self, timeout: float = 5.0) -> bytes:
        return await asyncio.wait_for(self._q.get(), timeout=timeout)

    def try_drain(self) -> list[bytes]:
        items = []
        while not self._q.empty():
            items.append(self._q.get_nowait())
        return items


async def authenticate(client: BleakClient, notifies: NotifyQueue) -> None:
    """Run the full mutual-auth handshake with fresh nonces."""
    logging.info("→ session init")
    await client.write_gatt_char(WRITE_CHAR_UUID, SESSION_INIT, response=False)
    await asyncio.sleep(0.2)

    phone_challenge = secrets.token_bytes(16)
    logging.info("→ phone challenge %s", phone_challenge.hex())
    await client.write_gatt_char(WRITE_CHAR_UUID, b"\x00" + phone_challenge, response=False)

    resp = await notifies.get(timeout=3.0)
    logging.info("← %s", resp.hex())
    if resp[0] != 0x01 or len(resp) != 17:
        raise RuntimeError(f"expected 01+16 bytes, got {resp.hex()}")
    badge_response = resp[1:]
    expected = get_encrypted_auth_data(phone_challenge)
    if badge_response == expected:
        logging.info("badge response verified")
    else:
        logging.warning(
            "badge response MISMATCH — cipher or key mismatch? proceeding anyway"
        )
        logging.warning("  got      %s", badge_response.hex())
        logging.warning("  expected %s", expected.hex())

    logging.info('→ phone says "pass"')
    await client.write_gatt_char(WRITE_CHAR_UUID, PASS_TOKEN, response=False)

    badge_challenge_msg = await notifies.get(timeout=3.0)
    logging.info("← %s", badge_challenge_msg.hex())
    if badge_challenge_msg[0] != 0x00:
        raise RuntimeError(f"expected badge challenge 00+..., got {badge_challenge_msg.hex()}")
    badge_challenge = badge_challenge_msg[1:17]

    phone_response = get_encrypted_auth_data(badge_challenge)
    logging.info("→ phone response %s", phone_response.hex())
    await client.write_gatt_char(
        WRITE_CHAR_UUID, b"\x01" + phone_response, response=False
    )

    final = await notifies.get(timeout=3.0)
    logging.info("← %s", final.hex())
    if final != PASS_TOKEN:
        raise RuntimeError(f'expected "\\x02pass" from badge, got {final.hex()}')
    logging.info("AUTHENTICATED ✓")


async def replay_post_auth(client: BleakClient, notifies: NotifyQueue) -> None:
    """Send the captured writes from the 'device info' step onward, verbatim.

    Our fresh session restarts opCodeSn at 00 on session init, so the captured
    sequence numbers (46, 47, 48, ...) should line up as long as we only send
    the commands the capture sent.
    """
    writes = load_writes()
    # writes[0] = session init (already sent by authenticate())
    # writes[1..4] = auth packets (already handled live by authenticate())
    post_auth = writes[5:]
    logging.info("replaying %d post-auth writes", len(post_auth))

    for i, w in enumerate(post_auth):
        await client.write_gatt_char(WRITE_CHAR_UUID, w.payload, response=False)
        is_req_with_response = (
            len(w.payload) >= 4
            and w.payload[:3] == b"\xfe\xdc\xba"
            and bool(w.payload[3] & 0x40)
        )
        tag = "[hasResponse]" if is_req_with_response else ""
        logging.info(
            "→ %2d/%d len=%-3d head=%s %s",
            i + 1,
            len(post_auth),
            len(w.payload),
            w.payload[:10].hex(),
            tag,
        )
        if is_req_with_response:
            try:
                ack = await notifies.get(timeout=2.0)
                logging.info("  ← %s", ack.hex())
            except asyncio.TimeoutError:
                logging.warning("  ↯ no ack within 2s; continuing")
        else:
            await asyncio.sleep(0.02)

    # Drain any final notifications (transfer-complete etc.)
    await asyncio.sleep(1.5)
    for leftover in notifies.try_drain():
        logging.info("← (late) %s", leftover.hex())


async def run(mac: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    logging.info("scanning for %s…", mac)
    device = await BleakScanner.find_device_by_address(mac, timeout=20.0)
    if device is None:
        raise SystemExit(f"badge {mac} not found; wake it and retry")

    async with BleakClient(device) as client:
        logging.info("connected, mtu=%d", client.mtu_size)

        notifies = NotifyQueue()
        await client.start_notify(NOTIFY_CHAR_UUID, notifies.push)
        try:
            await authenticate(client, notifies)
            await replay_post_auth(client, notifies)
        finally:
            await client.stop_notify(NOTIFY_CHAR_UUID)

        logging.info("session complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", required=True, help="E87 badge BLE MAC address")
    args = parser.parse_args()
    asyncio.run(run(args.mac))


if __name__ == "__main__":
    main()
