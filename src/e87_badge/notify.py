"""Async queue for incoming BLE notifications with predicate-based waiters."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .frame import E87Frame, parse_fe_frame

log = logging.getLogger(__name__)


@dataclass
class NotifyBus:
    queue: list[bytes] = field(default_factory=list)
    event: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, data: bytes) -> None:
        self.queue.append(data)
        # Bound the queue so a slow consumer can't exhaust memory.
        if len(self.queue) > 300:
            del self.queue[: len(self.queue) - 300]
        self.event.set()

    def consume(self, predicate: Callable[[bytes], bool]) -> bytes | None:
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
                (
                    f"frame(flag=0x{f.flag:02x},cmd=0x{f.cmd:02x},len={f.length})"
                    if (f := parse_fe_frame(r))
                    else f"raw({len(r)}):{r[:8].hex()}"
                )
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
