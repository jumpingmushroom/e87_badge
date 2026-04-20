# E-Badge E87 BLE Protocol

> **Work in progress.** This document captures what is known about the BLE protocol used by
> the Zrun app (`com.zijun.zrun`) to drive the generic E-Badge E87 round LCD pin. It will
> be rewritten as more is learned; treat it as a living document until the phase 1 exit
> criterion (arbitrary-PNG upload from a Python client) is met.
>
> Findings here are derived from `docs/captures/01-solid-red-360.log` (a Zrun upload of a
> 360×360 solid red PNG from Samsung Galaxy S24 Ultra, Android 18, Zrun 2.2.5). Every
> claim below can be traced back to that capture; byte offsets cite
> `docs/captures/01-solid-red-360.ae01-writes.txt` unless noted.

## Hardware identification

- **SoC: JieLi (Zhuhai Jieli Technology) AC697 family.** Confirmed by ASCII string
  `jl_sdk_ac697_publish` in a badge notification on handle `0x0008` at t=261.62s
  (see `docs/captures/01-solid-red-360.notifications.txt`, line starting
  `261.620147000`).
- This is significant: JieLi chips use a well-known proprietary **RCSP (Remote Control
  Session Protocol)** framing that begins each frame with the sync byte `0x9E`. Traffic
  on the proprietary 128-bit service below matches this pattern — that path is generic
  JieLi RCSP, not badge-specific. The badge-specific image upload path runs on a separate
  16-bit service and uses a *different* framing (`fedcba…ef`), described in its own
  section below.

## Advertising

- Badge MAC: `46:8D:00:01:2C:25` (static random / locally administered)
- In the capture, the badge's presence was observed via the Android "Filter Accept List"
  pattern: the Zrun app adds the MAC, briefly scans (~10s), then removes it, repeatedly.
  Only one active advertising report from the badge is visible in the entire 330s capture.
- **No `Complete Local Name` AD field seen** in Android's regular BT settings — meaning
  Home Assistant auto-discovery cannot key on `local_name`. Use service-UUID matching
  (see below) and/or MAC OUI `46:8D:00:…` fingerprinting.

## Pairing / bonding

- **Not bonded.** No SMP Pairing Request / Response is visible on the connection handle
  `0x000f` (the badge's connection in this capture). Writes succeed without encryption.
- An application-layer auth handshake is performed instead — see "Authentication (control)"
  below.

## Connection parameters

- Connection established at t=257.08s (LE Enhanced Connection Complete event, frame 14981,
  subevent `0x0a`), connection handle `0x000f`.
- **MTU: 517 (negotiated maximum).** Both sides request 517 (frames 15405 client request,
  15439 server response).

## GATT structure

| Handle range | Service UUID | Notes |
|---|---|---|
| `0x0001–0x0003` | `0x1800` (GAP) | Standard Device Name characteristic only |
| `0x0004–0x0009` | **`0x00ae`** (proprietary 16-bit) | **Image upload + control** |
| `0x000a–0x0017` | **`c2e6fd00-e966-1000-8000-bef9c223df6a`** (proprietary 128-bit) | **JieLi RCSP** — device info, battery, firmware version, generic control |
| `0x0018–0x001b` | `0x180F` (Battery Service) | Standard battery level |

### Service `0x00ae` — image upload and badge-specific control

| Handle | UUID | Properties | Role |
|---|---|---|---|
| `0x0006` | `0xae01` | Write Without Response | **Client → badge: control commands AND image data** |
| `0x0008` | `0xae02` | Notify | **Badge → client: command acks + data-complete signals** |

Both control commands and image-data chunks are sent as writes to handle `0x0006`. The
two message types are distinguished by their opcode byte (see framing below).

### Service `c2e6fd00-e966-1000-8000-bef9c223df6a` — JieLi RCSP

The JieLi SDK (`jl_sdk`) exposes a pair of characteristics for the RCSP protocol.
Framing for all packets on this service begins with sync byte `0x9E`. This service is
out of scope for phase 1 (image upload does not use it) but is documented because
phase 2's `get_info()` / battery queries will likely go through here.

| Handle | UUID | Properties | Role |
|---|---|---|---|
| `0x000c` | `c2e6fd02-e966-1000-8000-bef9c223df6a` | Write + Write Without Response | Client → badge: RCSP commands |
| `0x000e` | `c2e6fd01-e966-1000-8000-bef9c223df6a` | Notify | Badge → client: RCSP responses |
| `0x0011` | `c2e6fd03-e966-1000-8000-bef9c223df6a` | Notify + Write + Read | Unclear — possibly OTA / firmware upgrade channel |
| `0x0014` | `c2e6fd04-e966-1000-8000-bef9c223df6a` | Write Without Response | Unclear |

Early on the connection, an indication on `0x000e` carries the byte sequence
`9e940461 1e0000 32 2e 37 31 31 2e 31 2e 30 2e 33 00 00` — the ASCII substring
`2.711.1.0.3` is visible, matching the firmware "11.1.0.3" displayed by Zrun's device
info screen (the `2.` prefix is the JL SDK version; the "7" then "11.1.0.3" is the
product firmware).

## Framing — image-upload service (`0x00ae`)

All packets on characteristic `0xae01` (handle `0x0006`, client→badge) and notify
characteristic `0xae02` (handle `0x0008`, badge→client) share the same envelope:

```
 +-------+--------+---------+---------+-----+
 | FE DC | BA     | OPCODE  | BODY…   | EF  |
 +-------+--------+---------+---------+-----+
   magic (3 bytes)    (1 byte)  (N B)   (1 B)
```

- **Magic header:** `FE DC BA` (3 bytes, always present).
- **Opcode byte:**
  - `0xC0` — control/command frame (client → badge or badge → client as ack)
  - `0x80` — image-data frame (client → badge) or bulk-data notification (badge → client).
- **Trailer:** `0xEF` (1 byte) at the end of every frame.
- **Body structure** differs by opcode and is described below.

### Body — control (`0xC0`)

Observed control packets (phone → badge, handle 0x0006, from `*.ae01-writes.txt`):

| t (s) | Hex | Likely meaning |
|---|---|---|
| 260.87 | `fedcba c0 0600 02 0001 ef`                            | session init / hello |
| 261.56 | `fedcba c0 0300 06 46ffffffff 00 ef`                   | unknown — contains `0xFFFFFFFF` (all-white color pattern?) |
| 261.63 | `fedcba c0 0700 06 47ff000000 04 ef`                   | unknown — mirror of above with different constants |
| 282.06 | `fedcba c0 2100 02 4800 ef`                            | pre-image-upload cmd |
| 282.44 | `fedcba c0 2700 07 49 00000000 02 01 ef`              | pre-image-upload cmd (contains image size?) |
| 282.50 | `fedcba c0 1b00 14 4a 00000ab9 32af 6464 6264 6266…` | pre-image-upload cmd — **20-byte blob, possibly SHA-1 of image** |
| 284.75 | `fedcba 0020 0026 0034 5c5566…`                        | post-upload — unclear purpose |
| 284.86 | `fedcba 001c 0002 0035 ef`                             | post-upload trailer |

Structure is not yet fully decoded. Observations:
- Byte immediately after opcode (`06`, `03`, `07`, `21`, `27`, `1b`) appears to be a
  **sub-opcode / command ID**, tracked as hex values 0x06 / 0x03 / 0x07 / 0x21 / 0x27 /
  0x1b / 0x00 (!).
- The next byte is always `0x00`, suggesting a 16-bit little-endian sub-opcode or a
  length field.
- A sequence byte appears to increment across control frames during a session (`46`,
  `47`, `48`, `49`, `4a`, `4b`, `4c`, `4d`, `4e`, `4f`, `50`) — the same sequence
  continues into the data frames (`4b`…`50`), so it is a shared monotonic counter, not
  a per-opcode counter.

Phase 6 (jadx decompile) will map each sub-opcode to a named command.

### Body — image data (`0x80`)

Observed data packets (phone → badge, handle 0x0006):

```
 fedcba 80 01 01 XX YY 1D ZZ  <JPEG or payload bytes>  ef
```

- `01 01` — purpose unclear, constant across all image-data frames observed.
- `XX` — varies: usually `EF` (overlaps with trailer marker — probably a 1-byte length
  indicator, not the trailer; this explains the "inner EF" problem when naively splitting
  on EF). On the 308-byte final chunk it was `2C` instead.
- `YY` — monotonic sequence number shared with control frames (saw `4B`, `4C`, `4D`, `4E`,
  `4F`, `50`).
- `1D ZZ` — 2-byte field, `ZZ` increments 00, 01, 02, 03, 04 across the first 5
  image-data frames then resets to `00` on the 6th (frame that begins a fresh JPEG),
  suggesting **`ZZ` is a per-image chunk index and `1D` is its type/image-slot marker**.

**The payload is JPEG.** Direct evidence: chunk 6 (frame at t=284.58, 503 bytes) payload
starts at offset 10 with `FF D8 FF E0 00 10 4A 46 49 46 …` — the JPEG Start-of-Image (SOI)
marker followed by JFIF APP0 header. The prior 5 chunks + 1 shorter chunk contain JPEG
bytes without the SOI — they are either (a) a different JPEG sent first (e.g. a preview
frame, or the previous-image-buffer being re-played), or (b) tail fragments of a JPEG
whose SOI was in an earlier unseen write. **This is not yet resolved** and is a priority
for task 6 (jadx).

The last 503-byte image chunk ends with `… 72d10a162434e125f1ef`. JPEG's
End-of-Image marker `FF D9` is visible on the 308-byte chunk (t=283.77) at the
tail: `… a28a0028a28a00 FF D9 ef` — so there is at least one complete JPEG (chunks 1–5)
of ~2.2 KB uncompressed frame, and a second partial JPEG starting in chunk 6.

## Authentication (control)

Before any image upload, an application-layer handshake runs over handles `0x0006`
(write) and `0x0008` (notify). Observed sequence (time-ordered, early connection):

| t (s) | Direction | Payload | Meaning |
|---|---|---|---|
| 260.87 | phone → badge | `fedcba c0 0600 02 0001 ef` | session init |
| 261.37 | phone → badge | `00 <16 random bytes>` | phone challenge (no magic envelope, prefixed `0x00`) |
| 261.41 | badge → phone | `01 <16 random bytes>` | badge response/challenge (prefixed `0x01`) |
| 261.41 | phone → badge | `02 70617373` | ASCII `"\x02pass"` — literal string |
| 261.47 | badge → phone | `00 <16 random bytes>` | (badge's own challenge, prefixed `0x00`) |
| 261.48 | phone → badge | `01 <16 random bytes>` | phone response (prefixed `0x01`) |
| 261.53 | badge → phone | `02 70617373` | badge echoes `"\x02pass"` — auth accepted |

**Interpretation (tentative):** this looks like a challenge-response handshake where
each side sends a 16-byte challenge prefixed with `0x00`, replies to the other side's
challenge prefixed with `0x01`, and then both sides send the literal string `"pass"`
prefixed with `0x02` to signal "authentication passed". The 16-byte payloads are
possibly:
- AES-128 challenge/response (classical), OR
- Random material for session key derivation, OR
- Not cryptographic at all — a pure challenge-echo with the "pass" string as the only
  real auth token.

The literal ASCII `"pass"` echo strongly suggests this is a weak or ceremonial
handshake rather than real cryptography. Phase 6 (jadx) will confirm.

**These 6 packets do NOT use the `fedcba…ef` envelope.** They are raw writes with the
single-byte prefix (`00`, `01`, `02`). Only the control and image-data frames after the
handshake use the envelope.

## Notification behaviour

The badge sends frequent notifications on `0x0008` during and between operations. Pattern:
- Each client control frame (`0xC0`) elicits a matching badge notification with opcode
  `0x00` (still within the `fedcba…ef` envelope). Example at t=282.97: client sends
  `fedcba c0 1b00 14 4a …`, badge replies at t=282.97 with `fedcba 001b 00 04 004a 01eaef`.
- During image data bursts (`0x80`), the badge emits opcode-`0x80` notifications (data
  acks). Example at t=282.97: `fedcba 80 1d 00 08 32 00 0f 50 00 00 01 ea ef` immediately
  after the first data chunk.
- A post-upload notification at t=284.84 contains opcode `0xC0 20 00 01 34 ef` — likely a
  "transfer complete" signal.

## Observed write summary (for task 7 replay)

- Total ATT operations on handle `0x000f` connection: 140 packets
- Client writes to handle `0x0006` (target for image upload): **28 writes**
  - 17 are control frames (`0xC0`)
  - 6 are image-data frames (`0x80`)
  - 5 are the pre-handshake auth packets (no envelope)
- Notifications received on handle `0x0008`: 12 plain notifications + 18 indications
- Writes to handle `0x000c` (JieLi RCSP): 11 (not related to image upload)

## Open questions (priority order for task 6 / jadx)

1. **Is the 16-byte challenge/response real cryptography?** If yes, we need to reproduce
   the algorithm (hopefully a simple fixed-key AES). If no (hypothesis: the "pass" string
   is the only real check), we can skip the 16-byte exchange entirely or replay any
   constants.
2. **What do each of the control sub-opcodes (`0x06`, `0x03`, `0x07`, `0x21`, `0x27`,
   `0x1b`, `0x00`) do?** In particular which one is "begin image transfer" and what are
   its parameters — image dimensions, byte size, SHA/CRC.
3. **Why are there two JPEG blocks in the capture (5 chunks then 1 more starting with
   SOI)?** Are we seeing preview+full, or partial+full, or something else?
4. **What is the sequence-counter `YY` reset rule?** Does it reset per session, per
   image, or monotonically increment forever?
5. **Is there a CRC in the trailer or in the sub-command payload?** The 20-byte blob in
   frame 282.50 (`fedcba c0 1b00 14 4a 00000ab9 32af 6464…`) is a candidate for a SHA-1
   or CRC32 of the image payload.

## Client implementation notes (draft)

Placeholder — will be completed in task 9.

## Out of scope (observed but not used in v1)

- JieLi RCSP traffic on the 128-bit service: firmware version queries, battery level,
  possibly time sync. Phase 2 may expose these as sensor entities later.
- Handle `0x0011` (JieLi notify+write+read) — purpose unknown, untouched during image
  upload.
- The post-upload notifications `fedcba 0020…` and `fedcba 001c…` — likely
  "image rendered" / "ready for next" signals; not needed for a fire-and-forget client.
