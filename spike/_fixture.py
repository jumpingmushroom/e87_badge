"""Parse the tshark-fields export of the 01-solid-red-360 capture into an ordered
list of raw write payloads (bytes) addressed to characteristic 0xae01.

Columns produced by `tshark -T fields` are tab-separated:
    frame.number  frame.time_relative  btatt.opcode  btatt.value

Only btatt.value is needed for replay.
"""

from dataclasses import dataclass
from pathlib import Path

CAPTURE = Path(__file__).parent.parent / "docs" / "captures" / "01-solid-red-360.ae01-writes.txt"


@dataclass(frozen=True)
class Write:
    frame: int
    t: float
    opcode: int
    payload: bytes


def load_writes() -> list[Write]:
    writes: list[Write] = []
    for line in CAPTURE.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            raise RuntimeError(f"unexpected column count in {CAPTURE}: {line!r}")
        frame, t, opcode, value = parts
        writes.append(
            Write(
                frame=int(frame),
                t=float(t),
                opcode=int(opcode, 16),
                payload=bytes.fromhex(value),
            )
        )
    if not writes:
        raise RuntimeError(f"no writes parsed from {CAPTURE}")
    return writes


if __name__ == "__main__":
    ws = load_writes()
    total = sum(len(w.payload) for w in ws)
    print(f"{len(ws)} writes, {total} bytes total")
    print(f"first: t={ws[0].t:.2f}s  len={len(ws[0].payload)}  head={ws[0].payload[:10].hex()}")
    print(f"last:  t={ws[-1].t:.2f}s  len={len(ws[-1].payload)}  head={ws[-1].payload[:10].hex()}")
