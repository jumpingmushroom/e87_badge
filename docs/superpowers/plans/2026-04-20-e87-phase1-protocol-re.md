# E87 Phase 1 — Protocol Reverse Engineering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover and document the BLE protocol the Zrun app uses to send still images to the E-Badge E87, and produce a standalone Python script that reproduces the upload without using Zrun.

**Architecture:** Human-in-the-loop reverse-engineering. Android captures the reference traffic (HCI snoop log), `jadx` decompiles the Zrun APK to explain the captured bytes, Wireshark analyses the capture, Python + `bleak` replays and then parametrises the protocol. Output is a documented spec (`docs/protocol.md`) and a throwaway working client (`spike/replay.py`).

**Tech Stack:** Android Developer Options, ADB, Wireshark, `jadx-gui`, Python 3.11+, `bleak`, `pillow`, `pytest`.

**Note to the executor:** This is RE work, not feature implementation. Several tasks require the human operator to perform physical steps with an Android phone. Those tasks are explicitly marked `[HUMAN]`. The executor's job on those tasks is to provide precise instructions, then wait for the human to confirm completion and paste or commit the resulting artifact before moving on. Do not attempt to automate what requires a physical phone.

**Spec reference:** `docs/superpowers/specs/2026-04-20-e87-badge-design.md`.

---

## File Structure

Phase 1 creates and populates:

- `README.md` — project README, short pointer to spec and protocol doc
- `.gitignore` — ignore `.venv/`, `__pycache__`, large captures
- `pyproject.toml` — minimal project metadata so the repo is `pip install -e .`-friendly later
- `docs/protocol.md` — the deliverable of this phase
- `docs/captures/README.md` — describes naming conventions for capture files
- `docs/captures/*.log` — committed btsnoop captures (gitignored if >5 MB)
- `docs/captures/*.png` — the exact images used during each capture
- `docs/captures/notes.md` — running notes during RE
- `spike/__init__.py`
- `spike/replay.py` — throwaway replay script (the exit-criteria deliverable)
- `spike/parametrize.py` — sends an arbitrary PNG using the understood protocol
- `spike/requirements.txt` — minimal `bleak`, `pillow` for the spike
- `tests/test_fixtures_present.py` — sanity check that capture fixtures exist in the expected shape

Nothing in `src/e87_badge/` is created in this phase. That is phase 2's scaffolding.

---

## Task 1: Repository scaffolding

**Files:**
- Create: `/home/johnny/code/E87_communicator/.gitignore`
- Create: `/home/johnny/code/E87_communicator/README.md`
- Create: `/home/johnny/code/E87_communicator/pyproject.toml`
- Create: `/home/johnny/code/E87_communicator/docs/captures/README.md`
- Create: `/home/johnny/code/E87_communicator/docs/captures/notes.md`
- Create: `/home/johnny/code/E87_communicator/spike/__init__.py`
- Create: `/home/johnny/code/E87_communicator/spike/requirements.txt`
- Create: `/home/johnny/code/E87_communicator/tests/test_fixtures_present.py`

- [ ] **Step 1: Initialise the git repository**

```bash
cd /home/johnny/code/E87_communicator
git init
git branch -m main
```

Expected: `Initialized empty Git repository in /home/johnny/code/E87_communicator/.git/` and `Reset branch 'main'` (or no output on the rename).

- [ ] **Step 2: Write `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
.venv/
venv/
.env
*.egg-info/
dist/
build/

# Editor
.idea/
.vscode/
*.swp

# OS
.DS_Store

# RE work
# Large captures (>5 MB) — gitignored by convention; commit small ones.
docs/captures/*.log.big
spike/.scratch/
```

- [ ] **Step 3: Write `README.md`**

```markdown
# E87 Communicator

Open-source client for the generic **E-Badge E87** round LCD Bluetooth pin (the one that
normally pairs with the Zrun app).

This repo reverse-engineers the BLE protocol and ships:

1. `docs/protocol.md` — protocol specification (phase 1)
2. `e87_badge` — Python library + `e87` CLI (phase 2)
3. `custom_components/e87_badge` — Home Assistant custom integration (phase 3)

See `docs/superpowers/specs/2026-04-20-e87-badge-design.md` for the full design.

## Status

Phase 1 in progress — protocol reverse-engineering. No working client yet.
```

- [ ] **Step 4: Write `pyproject.toml` (minimal — phase 2 will expand this)**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "e87-badge"
version = "0.0.0"
description = "Open client for the E-Badge E87 BLE pin"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 5: Write `docs/captures/README.md`**

```markdown
# Capture library

Each reverse-engineering capture is a triple:

- `<name>.log`    — raw Android btsnoop HCI log
- `<name>.png`    — the exact image sent to the badge during the capture
- `<name>.md`     — short notes: Android version, Zrun version, date, what was done

Filenames are `NN-description`, e.g. `01-solid-red-360.log`, numbered in the order captures
were taken. Do not rename — protocol tests in phase 2 will reference these names as fixtures.

Captures larger than 5 MB are gitignored (suffix `.log.big`) and kept locally only.
```

- [ ] **Step 6: Write `docs/captures/notes.md`**

```markdown
# RE running notes

Running log of observations made while reverse-engineering the E87 protocol. New notes at
the top. Timestamp each entry.

---
```

- [ ] **Step 7: Write `spike/__init__.py`**

Leave empty (marks the directory as a package).

- [ ] **Step 8: Write `spike/requirements.txt`**

```
bleak>=0.22
pillow>=10.0
```

- [ ] **Step 9: Write `tests/test_fixtures_present.py`**

```python
"""Sanity check: RE captures exist in the shape later phases will consume."""

from pathlib import Path

import pytest

CAPTURES = Path(__file__).parent.parent / "docs" / "captures"


def test_captures_dir_exists():
    assert CAPTURES.is_dir(), f"{CAPTURES} must exist"


@pytest.mark.skipif(
    not any(CAPTURES.glob("*.log")),
    reason="No btsnoop captures yet — phase 1 task 4 not complete",
)
def test_every_capture_has_matching_png_and_notes():
    missing = []
    for log in CAPTURES.glob("*.log"):
        stem = log.stem
        png = CAPTURES / f"{stem}.png"
        notes = CAPTURES / f"{stem}.md"
        if not png.is_file():
            missing.append(str(png))
        if not notes.is_file():
            missing.append(str(notes))
    assert not missing, f"Missing companion files: {missing}"
```

- [ ] **Step 10: Create venv and install spike deps**

```bash
cd /home/johnny/code/E87_communicator
python3 -m venv .venv
.venv/bin/pip install -r spike/requirements.txt pytest
```

Expected: `bleak`, `pillow`, `pytest` installed without errors.

- [ ] **Step 11: Run the sanity test (captures absent, skip expected)**

```bash
cd /home/johnny/code/E87_communicator
.venv/bin/pytest tests/test_fixtures_present.py -v
```

Expected: `test_captures_dir_exists` PASSES; `test_every_capture_has_matching_png_and_notes` is SKIPPED with reason "No btsnoop captures yet — phase 1 task 4 not complete".

- [ ] **Step 12: Commit**

```bash
cd /home/johnny/code/E87_communicator
git add .gitignore README.md pyproject.toml docs/ spike/ tests/
git commit -m "chore: scaffold E87 RE repo"
```

---

## Task 2: `[HUMAN]` Baseline — confirm Zrun works with the badge

**Files:** none (this is a human verification step; output is a note in `docs/captures/notes.md`).

- [ ] **Step 1: Install the Zrun app on an Android phone**

Human action: install `com.zijun.zrun` ("Zrun") from Google Play on an Android phone that also has Developer Options available. If it's not on the Play Store in your region, download the latest APK from APKMirror.

- [ ] **Step 2: Pair the E87 badge with Zrun**

Human action: power the E87 on (short-press until it wakes), open Zrun, add a new device, follow the pairing flow until the badge shows up as connected inside the app.

- [ ] **Step 3: Upload a known image**

Human action: prepare a plain 360×360 PNG — pure red (hex `#FF0000`), filled. In Zrun, pick this image from the phone's gallery and send it to the badge. Confirm the badge actually displays red.

- [ ] **Step 4: Record the outcome in `docs/captures/notes.md`**

Append a new entry at the top of `docs/captures/notes.md` (human or executor — executor transcribes what the human reports):

```markdown
## 2026-04-20 — Baseline

- Zrun version: <VERSION FROM PLAY STORE OR APK>
- Android version: <VERSION>
- Badge firmware hint (any version string visible in Zrun's device info screen): <OR "none visible">
- Pairing: <success | failed — details>
- Upload: <success — red rendered correctly | failed — details>
- Advertising name observed during pairing: <e.g. "E87-XXXX">
- Zrun account required: <yes/no — if yes, note the account used>
```

- [ ] **Step 5: Commit**

```bash
cd /home/johnny/code/E87_communicator
git add docs/captures/notes.md
git commit -m "docs: baseline Zrun + badge verification"
```

**Gate:** if step 3 failed (Zrun cannot upload to the badge at all), stop. Options: try older Zrun APK from APKMirror; try a sister rebadge app (Beambox etc.); if none works, file a blocker issue and pause the project. Do not proceed to task 3 without a working baseline.

---

## Task 3: `[HUMAN]` Enable Bluetooth HCI snoop log on Android

**Files:** none.

- [ ] **Step 1: Enable Developer Options**

Human action: Settings → About phone → tap "Build number" seven times.

- [ ] **Step 2: Enable HCI snoop log**

Human action: Settings → System → Developer options → "Enable Bluetooth HCI snoop log" → toggle ON. Some phones label this "Bluetooth HCI snoop logging" or hide it under a different submenu — search the settings app for "snoop" if not obvious.

- [ ] **Step 3: Toggle Bluetooth off and back on**

Human action: Quick settings → Bluetooth OFF, then ON. This starts a fresh log file.

- [ ] **Step 4: Record the phone details in notes**

Append to `docs/captures/notes.md`:

```markdown
## 2026-04-20 — HCI snoop enabled

- Phone model: <MODEL>
- Android version: <VERSION>
- Log path on this phone (varies by vendor): <e.g. /sdcard/btsnoop_hci.log or /data/misc/bluetooth/logs/btsnoop_hci.log>
```

- [ ] **Step 5: Commit**

```bash
cd /home/johnny/code/E87_communicator
git add docs/captures/notes.md
git commit -m "docs: HCI snoop log enabled"
```

**Hint for the executor:** different Android vendors store the log in different places. If the human cannot find it, have them run `adb bugreport bugreport.zip` — the bugreport ZIP always contains the current btsnoop under `FS/data/misc/bluetooth/logs/` or `FS/sdcard/`.

---

## Task 4: `[HUMAN]` Capture a clean Zrun upload session

**Files:**
- Create: `docs/captures/01-solid-red-360.log`
- Create: `docs/captures/01-solid-red-360.png`
- Create: `docs/captures/01-solid-red-360.md`

- [ ] **Step 1: Generate the exact PNG that will be sent**

Executor action (Python, using the spike venv):

```bash
cd /home/johnny/code/E87_communicator
.venv/bin/python -c "
from PIL import Image
img = Image.new('RGB', (360, 360), (255, 0, 0))
img.save('docs/captures/01-solid-red-360.png')
"
```

Expected: `docs/captures/01-solid-red-360.png` exists and is 360×360, solid red.

- [ ] **Step 2: Transfer the PNG to the phone**

Human action: copy `docs/captures/01-solid-red-360.png` to the phone (e.g. via `adb push`, Nextcloud, email — whatever works). Place it in the phone's gallery folder.

Executor hint: `adb push docs/captures/01-solid-red-360.png /sdcard/Download/` usually works when USB debugging is on.

- [ ] **Step 3: Reset the HCI snoop log**

Human action: toggle Bluetooth OFF then ON on the phone. This starts a fresh log.

- [ ] **Step 4: Perform exactly one upload cycle**

Human action, in this strict order, with no extra BLE activity in between:

1. Open Zrun.
2. Connect to the badge (if not already connected).
3. Send `01-solid-red-360.png` to the badge.
4. Wait for Zrun to report "sent" / the badge to show red.
5. Disconnect in Zrun or close the app.
6. Toggle Bluetooth OFF on the phone.

- [ ] **Step 5: Pull the log**

Human action (executor can script this once phone is connected via ADB):

```bash
# Try the common locations. Only one will succeed per phone.
adb pull /sdcard/btsnoop_hci.log ./docs/captures/01-solid-red-360.log 2>/dev/null \
  || adb pull /data/misc/bluetooth/logs/btsnoop_hci.log ./docs/captures/01-solid-red-360.log
```

If neither works, fall back to `adb bugreport bugreport.zip`, then:

```bash
unzip -p bugreport.zip "FS/data/misc/bluetooth/logs/btsnoop_hci.log" > docs/captures/01-solid-red-360.log
```

Expected: `docs/captures/01-solid-red-360.log` exists and is non-empty (`ls -la` shows > 10 KB).

- [ ] **Step 6: Write capture notes**

Create `docs/captures/01-solid-red-360.md`:

```markdown
# Capture 01 — solid red 360x360

- Date: 2026-04-20
- Phone: <MODEL>, Android <VERSION>
- Zrun version: <VERSION>
- Image: `01-solid-red-360.png` — 360×360 solid #FF0000
- Upload outcome: <success — badge displayed red | anomaly: ...>
- Cycle: reset BT → open Zrun → connect → send image → wait for success → disconnect → BT off
- Log size: <bytes>
```

- [ ] **Step 7: Re-run the sanity test**

```bash
cd /home/johnny/code/E87_communicator
.venv/bin/pytest tests/test_fixtures_present.py -v
```

Expected: both tests PASS (the previously-skipped one should now run and pass).

- [ ] **Step 8: Commit**

If the log is ≤ 5 MB:

```bash
cd /home/johnny/code/E87_communicator
git add docs/captures/01-solid-red-360.log docs/captures/01-solid-red-360.png docs/captures/01-solid-red-360.md
git commit -m "feat(captures): 01 solid red 360x360 Zrun upload"
```

If the log is > 5 MB, rename to `.log.big` (gitignored) and commit only the PNG and notes, adding a note line pointing to where the big log lives on the local disk.

---

## Task 5: Wireshark dissection of the capture

**Files:**
- Create: `docs/protocol.md` (initial skeleton, filled in during this task)

- [ ] **Step 1: Open the log in Wireshark**

Executor instruction to human: open `docs/captures/01-solid-red-360.log` in Wireshark. Wireshark auto-detects the btsnoop format.

- [ ] **Step 2: Find the badge in the capture**

Apply display filter:

```
btle && btle.advertising_address
```

Scroll until you see the badge's advertising packets — the advertising address matches the MAC you saw in Zrun's device list. Note the full MAC and any `adv_data` payload (local name, service UUIDs in advertisement).

- [ ] **Step 3: Find the MTU exchange**

Apply display filter:

```
btatt.opcode == 0x02 || btatt.opcode == 0x03
```

(`0x02` = ATT MTU Request, `0x03` = ATT MTU Response.)

Record the negotiated MTU (the smaller of the two values).

- [ ] **Step 4: List all GATT services and characteristics discovered**

Apply display filter `btatt` and scroll through the service/characteristic discovery phase. Note, in order:

- Each Service UUID (128-bit preferred, 16-bit if standard)
- Each Characteristic UUID, its handle, and its properties (read/write/write-no-response/notify)

- [ ] **Step 5: Identify the image-write characteristic**

Filter:

```
btatt.opcode == 0x52 || btatt.opcode == 0x12
```

(`0x52` = Write Command / write-no-response, `0x12` = Write Request.)

After the service discovery phase, the bulk of writes during an image upload goes to one characteristic. That is the image-write target. Note its handle and the UUID it maps to.

- [ ] **Step 6: Extract the write sequence**

Export all write PDUs to that characteristic, in order, as hex. Wireshark: File → Export Packet Dissections → As Plain Text, with the filter above active. Save as `docs/captures/01-solid-red-360.writes.txt`.

- [ ] **Step 7: Look for notifications (acks) from the badge**

Filter:

```
btatt.opcode == 0x1b || btatt.opcode == 0x1d
```

(`0x1b` = Handle Value Notification, `0x1d` = Handle Value Indication.)

Note whether the badge notifies after each write, after every Nth write, or only at end of transfer. This tells us if the protocol uses per-chunk acks.

- [ ] **Step 8: Draft `docs/protocol.md` skeleton**

Create `docs/protocol.md` with the following — fill in the findings from steps 2–7:

```markdown
# E-Badge E87 BLE Protocol

> Work in progress. This document captures what is known about the BLE protocol used by
> the Zrun app (`com.zijun.zrun`) to drive the generic E-Badge E87 round LCD pin. It will
> be rewritten as more is learned; treat it as a living document until the phase 1 exit
> criterion (arbitrary-PNG upload from a Python client) is met.

## Advertising

- Local name observed: `<FILL IN>`
- Service UUIDs in advertisement: `<FILL IN or "none">`

## Pairing / bonding

- Bonding required: `<yes | no>` (derived from whether Android issues SMP Pairing Request
  and whether subsequent writes require encryption)

## GATT structure

Services and characteristics observed during discovery:

| Service UUID | Characteristic UUID | Handle | Properties |
|---|---|---|---|
| `<UUID>` | `<UUID>` | `<hex>` | `<read / write / write-no-response / notify>` |

## MTU

- Requested by client: `<N>`
- Negotiated: `<N>`

## Image-write characteristic

- UUID: `<UUID>`
- Handle: `<hex>`
- Opcode used: `<Write Command (0x52) | Write Request (0x12)>`

## Observed write pattern

- Total bytes written during a single image upload: `<N>`
- Number of writes: `<N>`
- Per-write payload size: `<N>` (or variable — describe)
- Notifications received: `<never | per-chunk | per-N-chunks | at end>`

## Framing (TBD — filled during task 6)

## Image encoding (TBD — filled during task 6)

## Open questions

- `<list observations that are unclear and need APK decompile to explain>`
```

- [ ] **Step 9: Commit**

```bash
cd /home/johnny/code/E87_communicator
git add docs/captures/01-solid-red-360.writes.txt docs/protocol.md
git commit -m "docs: initial protocol observations from wireshark"
```

---

## Task 6: Decompile Zrun and explain the observed bytes

**Files:**
- Modify: `docs/protocol.md` (fill in Framing + Image encoding sections)
- Create: `docs/captures/jadx-notes.md`

- [ ] **Step 1: Obtain the Zrun APK**

Human action: pull the APK from the phone:

```bash
adb shell pm path com.zijun.zrun
# Output: package:/data/app/~~.../com.zijun.zrun-.../base.apk
adb pull <THE PATH FROM ABOVE> zrun.apk
```

Keep `zrun.apk` outside the git repo (no redistribution — it's copyrighted). Record its SHA-256:

```bash
sha256sum zrun.apk > docs/captures/zrun-apk-sha256.txt
```

Commit only the checksum file, not the APK.

- [ ] **Step 2: Open the APK in `jadx-gui`**

Install if needed (`pacman -S jadx` on Arch). Open `zrun.apk` in `jadx-gui`.

- [ ] **Step 3: Search for BLE write calls**

In `jadx-gui`'s search (Ctrl-Shift-F), search across "Source code" for:

- `writeCharacteristic`
- `BluetoothGattCharacteristic`
- The image-write characteristic UUID discovered in task 5, step 5

Each hit is a place where Zrun writes to a BLE characteristic. The class that wraps the repeating write loop for the image upload is the target.

- [ ] **Step 4: Identify chunk framing**

In the class that writes image bytes in a loop, find:

- A constant or computed value for chunk size (expect something ≤ MTU − 3)
- A header prefix per chunk — commonly: `[opcode][sequence_number][payload]` or `[opcode][length][payload]`
- A total-size prefix or a "begin transfer" packet sent before the first chunk
- An "end transfer" packet sent after the last chunk
- Any CRC / checksum function applied to each chunk or the whole payload

Record the structure with field names and sizes. Look for Java/Kotlin fields named `CMD_*`, `OP_*`, `HEADER_*`, `MAGIC_*` — those usually map directly onto the protocol bytes.

- [ ] **Step 5: Identify image encoding**

In the same area of code, find the function that converts a `Bitmap` (or `InputStream` of a PNG) into the bytes that get chunked. Common shapes:

- Raw RGB565 (2 bytes per pixel, little-endian) — for a 360×360 panel that's 259,200 bytes
- Raw RGB888 (3 bytes per pixel) — 388,800 bytes
- JPEG as a whole, sent across chunks — variable size; Zrun calls `Bitmap.compress(JPEG, ...)` somewhere
- Proprietary compressed (look for calls into native `.so` files via JNI — noted as "needs deeper work" if hit)

Record which one it is, plus any pixel order / row stride quirks.

- [ ] **Step 6: Cross-check against the capture**

Take the first write payload from `docs/captures/01-solid-red-360.writes.txt`. Compare against the framing derived in step 4:

- Does the first byte match the expected "begin transfer" opcode?
- Does the length field match the total image byte count from step 5?

Take the last write payload. Does the last byte(s) match the expected "end" opcode?

Take a middle write. Strip the header bytes (per step 4). Is the remaining payload uniformly `F8 00` (RGB565 encoding of pure red — R=11111, G=000000, B=00000, little-endian) or `FF 00 00` (RGB888) or does it look like JPEG (`FF D8 FF ...` near the start chunks)?

This is how you know you've understood the protocol: the bytes in the capture explain themselves.

- [ ] **Step 7: Write up findings in `docs/captures/jadx-notes.md`**

```markdown
# jadx notes — Zrun BLE write path

- APK SHA-256: see `zrun-apk-sha256.txt`
- Java package containing the write loop: `<com.zijun.zrun.something>`
- Class that owns the write loop: `<ClassName>`
- Method that kicks off an image upload: `<ClassName#method(sig)>`
- Chunk size constant: `<N>` bytes (named `<FIELD_NAME>` in the source)
- Header format per chunk: `<describe>`
- Begin-transfer packet: `<hex>`
- End-transfer packet: `<hex>`
- Checksum algorithm: `<none | CRC8 | CRC16-CCITT | XOR | other>` with polynomial `<N>` (if CRC)
- Image encoding: `<raw RGB565 | raw RGB888 | JPEG | other>`
- Pixel order / row direction: `<top-to-bottom left-to-right | other>`
- Auth / token required in any packet: `<no | yes — source: ClassName#method>`
```

- [ ] **Step 8: Update `docs/protocol.md`**

Fill in the Framing and Image encoding sections with the findings. Cross-reference the capture: for each framing rule, cite a byte offset in `docs/captures/01-solid-red-360.writes.txt` where it's visible.

- [ ] **Step 9: Commit**

```bash
cd /home/johnny/code/E87_communicator
git add docs/protocol.md docs/captures/jadx-notes.md docs/captures/zrun-apk-sha256.txt
git commit -m "docs: protocol framing and encoding from jadx analysis"
```

---

## Task 7: Replay the capture from Python

**Files:**
- Create: `spike/replay.py`

- [ ] **Step 1: Extract the write sequence as a raw byte list**

Create a helper file `spike/_fixture.py`:

```python
"""Parse docs/captures/01-solid-red-360.writes.txt (Wireshark plain text export)
into an ordered list of raw write payloads (bytes)."""

from pathlib import Path
import re

CAPTURE = Path(__file__).parent.parent / "docs" / "captures" / "01-solid-red-360.writes.txt"


def load_writes() -> list[bytes]:
    """Return all write payloads to the image-write characteristic, in order."""
    writes: list[bytes] = []
    current_hex: list[str] = []
    in_value = False

    for line in CAPTURE.read_text().splitlines():
        # Wireshark plain-text export puts each packet in a block separated by blank lines.
        # Inside a block, the line "Value: <hex with colons or spaces>" carries the payload.
        m = re.search(r"Value:\s*([0-9a-fA-F: ]+)", line)
        if m:
            hex_str = re.sub(r"[^0-9a-fA-F]", "", m.group(1))
            writes.append(bytes.fromhex(hex_str))

    if not writes:
        raise RuntimeError(
            f"No 'Value:' lines found in {CAPTURE}. "
            "Re-export the writes from Wireshark with packet dissection details included."
        )
    return writes


if __name__ == "__main__":
    ws = load_writes()
    print(f"{len(ws)} writes, total {sum(len(w) for w in ws)} bytes")
    print(f"first:  {ws[0].hex()}")
    print(f"last:   {ws[-1].hex()}")
```

Run it once to sanity-check:

```bash
cd /home/johnny/code/E87_communicator
.venv/bin/python -m spike._fixture
```

Expected: prints a non-zero count, first and last write hex strings.

If the export format doesn't match (empty result), either re-export with different Wireshark settings or write a small tshark-based script instead. Adjust the parser until `load_writes()` returns the expected count (same as the capture's write count observed in task 5 step 7).

- [ ] **Step 2: Write the replay script**

Create `spike/replay.py`:

```python
"""Replay the captured Zrun image upload against the E87 badge, verbatim.

This is a sanity check: if this does NOT make the badge display red again, our
understanding of the GATT structure is wrong. If it does, we've reproduced Zrun's
write sequence byte-for-byte, which is the precondition for parametrising it in
spike/parametrize.py.

Usage:
    python -m spike.replay --mac AA:BB:CC:DD:EE:FF
"""

import argparse
import asyncio
import logging

from bleak import BleakClient, BleakScanner

from spike._fixture import load_writes

# These three constants are filled in from docs/protocol.md after task 5 completes.
# If they differ in your capture, edit them here. They are not yet "the API" — this is a
# throwaway script.
IMAGE_WRITE_CHAR_UUID = "REPLACE_WITH_UUID_FROM_PROTOCOL_MD"
USE_WRITE_WITHOUT_RESPONSE = True  # True if Wireshark showed 0x52, False if 0x12
INTER_WRITE_DELAY_S = 0.0  # bump if the badge drops writes; 0 is the optimistic start


async def main(mac: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    writes = load_writes()
    logging.info("loaded %d writes, %d bytes total", len(writes), sum(len(w) for w in writes))

    device = await BleakScanner.find_device_by_address(mac, timeout=15.0)
    if device is None:
        raise SystemExit(f"badge {mac} not found in scan")

    async with BleakClient(device) as client:
        logging.info("connected, mtu=%d", client.mtu_size)
        for i, payload in enumerate(writes):
            await client.write_gatt_char(
                IMAGE_WRITE_CHAR_UUID,
                payload,
                response=not USE_WRITE_WITHOUT_RESPONSE,
            )
            if INTER_WRITE_DELAY_S:
                await asyncio.sleep(INTER_WRITE_DELAY_S)
            if i % 50 == 0:
                logging.info("wrote %d/%d", i + 1, len(writes))
        logging.info("replay complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mac", required=True, help="E87 badge BLE MAC address")
    args = parser.parse_args()
    asyncio.run(main(args.mac))
```

- [ ] **Step 3: Fill in `IMAGE_WRITE_CHAR_UUID` from `docs/protocol.md`**

Replace the placeholder string with the UUID of the image-write characteristic recorded in task 5 step 5.

- [ ] **Step 4: Run the replay**

Human action: wake the badge (short-press) so it's advertising. Then:

```bash
cd /home/johnny/code/E87_communicator
.venv/bin/python -m spike.replay --mac <BADGE_MAC>
```

Expected: the script connects, writes all N chunks, logs "replay complete" — and the badge shows pure red.

- [ ] **Step 5: If it does not work, iterate**

Likely problems and fixes (executor: try in this order, one at a time):

1. **Wrong opcode.** Flip `USE_WRITE_WITHOUT_RESPONSE`. If the capture showed `0x52` it must be `True`; if `0x12` it must be `False`.
2. **Missing CCCD subscribe.** If the badge expects notifications-enabled before accepting writes, add `await client.start_notify(NOTIFY_CHAR_UUID, lambda _, __: None)` before the write loop. The notify characteristic UUID is also in `docs/protocol.md`.
3. **Timing.** Set `INTER_WRITE_DELAY_S = 0.01` and retry. Some cheap BLE stacks drop writes if the client doesn't pace itself.
4. **Bonding required.** If Wireshark showed an SMP pairing exchange in the capture and the badge is now "forgotten" on the replay phone's OS side, the badge may demand pairing. Pair once manually via `bluetoothctl pair <MAC>`, then re-run.
5. **Stale connection state on the badge.** Power-cycle the badge (long-press off, short-press on) and retry.

Each iteration: record in `docs/captures/notes.md` what was changed and whether it worked.

- [ ] **Step 6: Record success in notes**

Append to `docs/captures/notes.md`:

```markdown
## 2026-04-20 — Replay success

- Replay script: `spike/replay.py`
- Badge MAC: <MAC>
- Capture used: `01-solid-red-360`
- Outcome: badge displayed red, `replay complete` logged after N writes
- Deviations from naïve replay (e.g. "had to enable CCCD first"): <list or "none">
```

- [ ] **Step 7: Commit**

```bash
cd /home/johnny/code/E87_communicator
git add spike/_fixture.py spike/replay.py docs/captures/notes.md
git commit -m "feat(spike): replay captured Zrun upload from Python"
```

**Gate:** do not proceed to task 8 until the badge actually renders red from the Python replay.

---

## Task 8: Parametrise the upload — send an arbitrary image

**Files:**
- Create: `spike/parametrize.py`

- [ ] **Step 1: Prepare a second test image**

```bash
cd /home/johnny/code/E87_communicator
.venv/bin/python -c "
from PIL import Image, ImageDraw
img = Image.new('RGB', (360, 360), (0, 0, 255))
d = ImageDraw.Draw(img)
d.ellipse((60, 60, 300, 300), fill=(255, 255, 0))
img.save('docs/captures/99-blue-with-yellow-circle.png')
"
```

- [ ] **Step 2: Write `spike/parametrize.py`**

This script encodes an arbitrary PNG using the framing + encoding documented in `docs/protocol.md`, then sends the result. The exact code depends on what task 6 discovered. The template below assumes raw RGB565 with a 2-byte sequence-numbered header + 2-byte CRC16 suffix per chunk and a one-byte `0xA0`/`0xA1` begin/end opcode. **Replace the marked sections with the real constants from `docs/protocol.md`.**

```python
"""Send an arbitrary 360x360 PNG to the E87 badge using the understood protocol.

This is the phase 1 exit-criteria deliverable: running this twice with two different
PNGs must render both images correctly on the badge.

Usage:
    python -m spike.parametrize --mac AA:BB:CC:DD:EE:FF --image path/to/image.png
"""

import argparse
import asyncio
import logging
import struct
from pathlib import Path

from bleak import BleakClient, BleakScanner
from PIL import Image

# ---- Protocol constants — copied from docs/protocol.md after task 6 ----
IMAGE_WRITE_CHAR_UUID = "REPLACE_WITH_UUID"
NOTIFY_CHAR_UUID = "REPLACE_WITH_UUID_OR_NONE"  # set to None if not needed
USE_WRITE_WITHOUT_RESPONSE = True
CHUNK_PAYLOAD_BYTES = 180   # MTU - ATT header - our own header; actual value from protocol.md
BEGIN_OPCODE = 0xA0         # actual value from protocol.md
END_OPCODE = 0xA1           # actual value from protocol.md
DATA_OPCODE = 0xA2          # actual value from protocol.md
# -----------------------------------------------------------------------


def encode_rgb565(path: Path) -> bytes:
    """Load a PNG, resize to 360x360, return raw RGB565 little-endian bytes."""
    img = Image.open(path).convert("RGB").resize((360, 360))
    out = bytearray()
    for r, g, b in img.getdata():
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out += struct.pack("<H", v)
    return bytes(out)


def frame(payload: bytes) -> list[bytes]:
    """Split the whole-image payload into wire-format chunks per docs/protocol.md."""
    chunks: list[bytes] = []
    chunks.append(bytes([BEGIN_OPCODE]) + struct.pack("<I", len(payload)))
    for seq, i in enumerate(range(0, len(payload), CHUNK_PAYLOAD_BYTES)):
        body = payload[i : i + CHUNK_PAYLOAD_BYTES]
        chunks.append(bytes([DATA_OPCODE]) + struct.pack("<H", seq) + body)
    chunks.append(bytes([END_OPCODE]))
    return chunks


async def main(mac: str, image: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    payload = encode_rgb565(image)
    chunks = frame(payload)
    logging.info("image %s -> %d bytes -> %d chunks", image, len(payload), len(chunks))

    device = await BleakScanner.find_device_by_address(mac, timeout=15.0)
    if device is None:
        raise SystemExit(f"badge {mac} not found in scan")

    async with BleakClient(device) as client:
        logging.info("connected, mtu=%d", client.mtu_size)
        if NOTIFY_CHAR_UUID:
            await client.start_notify(NOTIFY_CHAR_UUID, lambda _h, _d: None)
        for i, chunk in enumerate(chunks):
            await client.write_gatt_char(
                IMAGE_WRITE_CHAR_UUID,
                chunk,
                response=not USE_WRITE_WITHOUT_RESPONSE,
            )
            if i % 50 == 0:
                logging.info("wrote %d/%d", i + 1, len(chunks))
        logging.info("upload complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mac", required=True)
    parser.add_argument("--image", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.mac, args.image))
```

- [ ] **Step 3: Fill in the real constants**

Replace every `REPLACE_WITH_*` and every comment-marked constant with the actual values from `docs/protocol.md`. If the encoding is JPEG rather than RGB565, rewrite `encode_rgb565` accordingly (call it `encode_image` and have it emit JPEG bytes). If the framing has a CRC, add it to `frame()`. **Do not leave placeholder code that "works by coincidence" — if a value was not determined in task 6, go back and determine it.**

- [ ] **Step 4: Run — image A**

```bash
cd /home/johnny/code/E87_communicator
.venv/bin/python -m spike.parametrize --mac <BADGE_MAC> --image docs/captures/01-solid-red-360.png
```

Expected: badge displays pure red. `upload complete` logged.

- [ ] **Step 5: Run — image B (the blue-with-yellow-circle)**

```bash
cd /home/johnny/code/E87_communicator
.venv/bin/python -m spike.parametrize --mac <BADGE_MAC> --image docs/captures/99-blue-with-yellow-circle.png
```

Expected: badge displays a blue square with a yellow circle in the middle. Colours visibly correct.

- [ ] **Step 6: Run — image C (your own arbitrary JPEG or PNG)**

Human action: pick any 360×360-ish photo from your own library, point the script at it.

Expected: recognisable rendering of that image on the badge.

- [ ] **Step 7: Record phase-1 exit**

Append to `docs/captures/notes.md`:

```markdown
## 2026-04-20 — Phase 1 exit criteria met

- Script: `spike/parametrize.py`
- Images tested: solid-red, blue-with-yellow-circle, <your-photo>
- All three rendered correctly on the badge without using Zrun.
- Protocol doc: `docs/protocol.md` — complete as of commit <SHA once committed>.
```

- [ ] **Step 8: Commit**

```bash
cd /home/johnny/code/E87_communicator
git add spike/parametrize.py docs/captures/99-blue-with-yellow-circle.png docs/captures/notes.md
git commit -m "feat(spike): parametrised uploader sends arbitrary PNG"
```

---

## Task 9: Finalise the protocol document

**Files:**
- Modify: `docs/protocol.md`

- [ ] **Step 1: Review `docs/protocol.md` end-to-end**

Read the document from top to bottom. Every section should be filled in (no "TBD", no "`<FILL IN>`"). Every framing rule should cite at least one byte offset in the capture that demonstrates it. If any rule was inferred from the APK but not seen in the capture, mark it "inferred from source, not yet observed in traffic".

- [ ] **Step 2: Add a "Client implementation notes" section**

Append a section covering:

- MTU negotiation: client must negotiate, not cache. Recommended initial MTU request: 247.
- Chunk size derivation: `CHUNK_PAYLOAD_BYTES = negotiated_mtu - 3 - <our header size>`.
- Reconnection: badge's behaviour when a connection drops mid-transfer (document what you observed — does it accept a fresh BEGIN, or does it need a power-cycle?).
- Timing: any `INTER_WRITE_DELAY_S` that turned out to be necessary in practice.
- Error signals: what a "bad chunk" looks like on the notify characteristic, if anything.

- [ ] **Step 3: Add an "Out of scope (known but not used)" section**

Anything observed during RE that phase 2 does NOT need: GIF upload opcodes, brightness commands, touch-gesture reporting, clock-sync packets. One line each. This is for future phases.

- [ ] **Step 4: Commit**

```bash
cd /home/johnny/code/E87_communicator
git add docs/protocol.md
git commit -m "docs: finalise phase 1 protocol specification"
```

---

## Phase 1 exit criteria (re-stated for convenience)

All of the following must be true to declare phase 1 complete:

1. `docs/protocol.md` is complete — no "TBD" or `<FILL IN>` placeholders. Every framing rule is either cited against a byte offset in a capture or explicitly marked "inferred from source".
2. `spike/parametrize.py` runs successfully against the badge with at least three distinct images, and each renders correctly.
3. `pytest tests/test_fixtures_present.py` passes.
4. All captures live under `docs/captures/` with the triple (`.log`, `.png`, `.md`) convention, and the sanity test enforces this.
5. The git history tells a coherent story: scaffolding → baseline → capture → dissection → decompile → replay → parametrise → finalise.

When all five hold, open a new plan for phase 2 (library + CLI). Do not start phase 2 in this plan — the library's API depends on what phase 1 discovered, and was deliberately left unspecified here.
