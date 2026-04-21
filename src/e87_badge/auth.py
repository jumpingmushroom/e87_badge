"""JieLi RCSP mutual-auth handshake over the AE01/AE02 characteristic pair.

Six-step exchange (prefix byte + 16 random / encrypted bytes, then literal
"\\x02pass" on each side). Uses `jieli_cipher.get_encrypted_auth_data` to
compute the response to the device's challenge.
"""

from __future__ import annotations

import logging
import secrets
from typing import Awaitable, Callable

from .errors import E87AuthError
from .jieli_cipher import get_encrypted_auth_data
from .notify import NotifyBus, wait_for_raw

log = logging.getLogger(__name__)

AuthWriter = Callable[[bytes], Awaitable[None]]


async def do_auth(write_ae01: AuthWriter, bus: NotifyBus) -> None:
    """Run the 6-step mutual handshake.

    `write_ae01(data)` must write-without-response to AE01 on the badge.
    `bus` must already be receiving notifications from AE02.
    """
    log.info("Auth: starting Jieli RCSP crypto handshake")

    # Step 1: Phone → Device [0x00, rand*16]
    rand16 = secrets.token_bytes(16)
    await write_ae01(b"\x00" + rand16)
    log.info("Auth TX: [0x00, rand*16]")

    # Step 2: Device → Phone [0x01, enc*16]
    try:
        dev_resp = await wait_for_raw(
            bus,
            lambda r: len(r) == 17 and r[0] == 0x01,
            timeout=5.0,
            label="auth device response [0x01, encrypted*16]",
        )
    except TimeoutError as exc:
        raise E87AuthError("device did not respond to challenge") from exc
    log.info("Auth RX: %s", dev_resp.hex())

    # Step 3: Phone → Device [0x02, "pass"]
    await write_ae01(b"\x02pass")
    log.info('Auth TX: [0x02, "pass"]')

    # Step 4: Device → Phone [0x00, challenge*16]
    try:
        dev_chal = await wait_for_raw(
            bus,
            lambda r: len(r) == 17 and r[0] == 0x00,
            timeout=5.0,
            label="auth device challenge [0x00, challenge*16]",
        )
    except TimeoutError as exc:
        raise E87AuthError("device never sent its challenge") from exc
    log.info("Auth RX challenge: %s", dev_chal.hex())

    # Step 5: Phone → Device [0x01, encrypted*16]
    encrypted = get_encrypted_auth_data(dev_chal[1:17])
    await write_ae01(b"\x01" + encrypted)
    log.info("Auth TX encrypted: %s", encrypted.hex())

    # Step 6: Device → Phone [0x02, "pass"]
    try:
        confirm = await wait_for_raw(
            bus,
            lambda r: len(r) >= 5 and r[0] == 0x02 and r[1:5] == b"pass",
            timeout=5.0,
            label="auth pass confirmation",
        )
    except TimeoutError as exc:
        raise E87AuthError("device never confirmed our response") from exc
    log.info("Auth SUCCESS: %s", confirm.hex())
