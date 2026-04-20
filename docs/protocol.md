# E-Badge E87 BLE Protocol

> Findings here are derived from `docs/captures/01-solid-red-360.log` (a Zrun upload of a
> 360×360 solid red PNG from Samsung Galaxy S24 Ultra, Android 18, Zrun 2.2.5) and from
> static analysis of the Zrun APK (`docs/captures/jadx-notes.md`). Every capture claim can
> be traced back to `docs/captures/01-solid-red-360.ae01-writes.txt` unless noted.

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
characteristic `0xae02` (handle `0x0008`, badge→client) share the same RCSP envelope
(confirmed by `ParseHelper.packSendBasePacket()` in the Zrun APK):

```
 +----------+-------+--------+--------------+---------+----+
 | FE DC BA | flags | opCode | paramLen(2B) | body…   | EF |
 +----------+-------+--------+--------------+---------+----+
   magic(3B)  (1B)    (1B)   big-endian 16b  (N bytes) (1B)
```

- **Magic header:** `FE DC BA` (3 bytes, always present).
- **`flags` byte:**
  - bit 7 = direction: `1` = request (phone→badge), `0` = response (badge→phone)
  - bit 6 = hasResponse: `1` = phone expects an ack notification
  - Common values: `0xC0` (request + hasResponse), `0x80` (request, no ack expected)
- **`opCode`** — RCSP command ID (see table below); **not** 0xC0 or 0x80 (those are flags).
- **`paramLen`** — 16-bit big-endian count of body bytes.
- **`body`** — layout depends on direction:
  - Request: `[opCodeSn] [xmOpCode if opCode==1] [paramData...]`
  - Response: `[status] [opCodeSn] [xmOpCode if opCode==1] [paramData...]`
- **Trailer:** `0xEF` (1 byte). The `0xEF` in paramLen (e.g. `01 EF` = 495) is numeric,
  not the trailer; the parser uses paramLen to know where the frame ends.
- **Total frame size** = 8 + paramLen bytes.

### RCSP opCodes used in image upload session

| opCode (hex) | Name | Meaning |
|---|---|---|
| `0x01` | CMD_DATA | Raw data transport; actual sub-command in `xmOpCode` byte |
| `0x03` | CMD_GET_TARGET_INFO | Probe device info (used as session opener) |
| `0x06` | CMD_DISCONNECT_CLASSIC_BT | Session-init frame (repurposed opCode) |
| `0x07` | CMD_GET_SYS_INFO | Query system info |
| `0x1B` | CMD_START_LARGE_FILE_TRANSFER | Begin file transfer; carries size + CRC16 + filename |
| `0x1C` | CMD_STOP_LARGE_FILE_TRANSFER | End file transfer |
| `0x1D` | CMD_LARGE_FILE_TRANSFER_OP | xmOpCode for each data chunk inside CMD_DATA |
| `0x21` | CMD_NOTIFY_PREPARE_ENV | Prepare environment for file transfer |
| `0x27` | CMD_DEV_PARAM_EXTEND | Negotiate capabilities (CRC16 support, protocol version) |

### Control frames decoded

| t (s) | flags | opCode | opCodeSn | paramData | RCSP meaning |
|---|---|---|---|---|---|
| 260.87 | C0 | 06 | 00 | `01` | Session init (hard-coded `FEDCBAC00600020001EF`) |
| 261.56 | C0 | 03 | 46 | `ffffffff 00` | CMD_GET_TARGET_INFO — device info request |
| 261.63 | C0 | 07 | 47 | `ff000000 04` | CMD_GET_SYS_INFO — system info request |
| 282.06 | C0 | 21 | 48 | `00` | CMD_NOTIFY_PREPARE_ENV — arm file transfer |
| 282.44 | C0 | 27 | 49 | `00000000 02 01` | CMD_DEV_PARAM_EXTEND — negotiate CRC16 + version |
| 282.50 | C0 | 1B | 4A | see below | CMD_START_LARGE_FILE_TRANSFER |
| 284.75 | 00 | 20 | 34 | UTF-16 path | Post-upload path report (badge→phone, response) |
| 284.86 | 00 | 1C | 00 | `35` | CMD_STOP_LARGE_FILE_TRANSFER ack |

**CMD_START_LARGE_FILE_TRANSFER (0x1B) body** at t=282.50:
```
opCodeSn=4A  |  size(4B big-endian) = 00 00 0A B9 = 2745 bytes
             |  crc16(2B big-endian) = 32 AF = 0x32AF  (CRC16 of entire file)
             |  filename = "ddbdbf24.tmp\0"  (null-terminated ASCII, 13 bytes)
```
The `hash` field in `StartLargeFileTransferParam` is actually the temp filename, not a
cryptographic hash. The CRC16 is computed over the complete JPEG payload.

### Data frames decoded (opCode=0x01, xmOpCode=0x1D)

Each data frame body:
```
[opCodeSn]  [xmOpCode=0x1D]  [chunk_index]  [crc16_hi]  [crc16_lo]  [chunk_data...]
```
- `opCodeSn` — shared monotonic session counter (continues from control frames).
- `xmOpCode = 0x1D` — CMD_LARGE_FILE_TRANSFER_OP; identifies this as a file-transfer chunk.
- `chunk_index` — 0-based index within the current JPEG transfer; resets to 0 for each new file.
- `crc16` (2 bytes big-endian) — CRC16 of this chunk's data only (per-chunk integrity).
- `chunk_data` — raw JPEG bytes for this chunk.

Frame paramLen = `01 EF` = 495 for full-size chunks; `01 2C` = 300 for the shorter last chunk.
Total frame bytes = 8 + paramLen = 503 or 308 respectively.

Sample decoding (t=282.981, frame 10, first data chunk):
```
FE DC BA  80  01  01 EF  4B  1D  00  B7 04  <490 JPEG bytes>  EF
          ^   ^   ^       ^   ^   ^   ^      ^
        flags opC pLen  opCSn xmO idx crc16  JPEG data
```
- flags=0x80 (request, no hasResponse), opCode=0x01, paramLen=495
- opCodeSn=0x4B, xmOpCode=0x1D, chunk_index=0, crc16=0xB704
- JPEG continuation bytes (not SOI — this is mid-JPEG from a prior split)

Sample decoding (t=284.582, frame 15, second JPEG start):
```
FE DC BA  80  01  01 EF  50  1D  00  2C 12  FF D8 FF E0 ...  EF
```
- opCodeSn=0x50 (resets chunk_index to 0x00 for new JPEG), crc16=0x2C12
- JPEG SOI `FF D8` visible — start of second JPEG file

**The payload is JPEG.** The 308-byte chunk at t=283.77 ends with JPEG EOI `FF D9` before
the frame trailer `EF`. The 503-byte chunk at t=284.58 starts with JPEG SOI `FF D8 FF E0
00 10 4A 46 49 46` (JFIF APP0 header).

### Two-JPEG explanation

The session sends **two complete JPEG files** sequentially:
1. **JPEG #1** (chunks 0–4, opCodeSn 0x4B–0x4F): ~2.2 KB, ends with FF D9 in chunk 4.
2. **JPEG #2** (chunks 0–N, opCodeSn 0x50+): chunk_index resets to 0, starts with FF D8 SOI.

Both are sent on the same xmOpCode=0x1D channel. The `cr3` (jl_filebrowse) library
in the Zrun APK issues two `TransferTask` runs when saving to the badge's "BAG" folder.
This likely corresponds to a thumbnail (first JPEG) and the main display image (second JPEG),
but the exact role assignment requires further testing. A Python client replaying the
session must send both JPEGs in order.

## Authentication (control)

Before any image upload, an application-layer handshake runs over handles `0x0006`
(write) and `0x0008` (notify). Observed sequence (time-ordered, early connection):

| t (s) | Direction | Payload | Meaning |
|---|---|---|---|
| 260.87 | phone → badge | `fedcba c0 0600 02 0001 ef` | session init (RCSP frame) |
| 261.37 | phone → badge | `00 <16 random bytes>` | phone challenge (no magic envelope, prefixed `0x00`) |
| 261.41 | badge → phone | `01 <16 random bytes>` | badge response/challenge (prefixed `0x01`) |
| 261.41 | phone → badge | `02 70617373` | ASCII `"\x02pass"` — auth accepted signal |
| 261.47 | badge → phone | `00 <16 random bytes>` | badge's own challenge (prefixed `0x00`) |
| 261.48 | phone → badge | `01 <16 random bytes>` | phone response (prefixed `0x01`) |
| 261.53 | badge → phone | `02 70617373` | badge echoes `"\x02pass"` — auth accepted |

**The 16-byte challenge/response is real cryptography.** The Zrun APK (`RcspAuth.java`)
calls two JNI native methods in `libjl_auth.so`:
```java
public native byte[] getRandomAuthData();         // generates 16-byte random challenge
public native byte[] getEncryptedAuthData(byte[] bArr);  // computes response to badge challenge
```
The algorithm cannot be read from Java; disassembly of `libjl_auth.so` is required to
extract the key and algorithm. The literal ASCII `"pass"` (`\x02 70 61 73 73`) is the
acceptance token sent by both sides *after* the crypto rounds complete — it is not the
only check.

**For a Python client:** empirical testing is needed to determine whether the badge
enforces replay protection (fresh nonce each connection) or whether any fixed 16-byte
value plus the `\x02pass` token is accepted. A captured working sequence is:
```
phone→badge: 00 70b759 92e05ea7 8fec533b a12979b5 90   (0x00 + 16 bytes)
phone→badge: 02 70617373                                (0x02 + "pass")
phone→badge: 01 dd08e8 78b7cfdc 5bef67cb fe80c993 b3   (0x01 + 16 bytes)
```

**These 6 packets do NOT use the `fedcba…ef` envelope.** They are raw writes with the
single-byte prefix (`00`, `01`, `02`). Only the RCSP control and data frames after the
handshake use the envelope.

## Notification behaviour

The badge sends frequent notifications on `0x0008` during and between operations. Pattern:
- Each client control frame (flags=0xC0) elicits a matching badge notification (flags=0x00,
  response direction). Example at t=282.97: client sends `fedcba c0 1b 00 14 4a …`, badge
  replies `fedcba 00 1b 00 04 00 4a 01 ea ef` (flags=0x00, opCode=0x1B, status=0x00).
- During image data bursts (flags=0x80), the badge emits flags=0x80 notifications (data
  acks). Example: `fedcba 80 1d 00 08 32 00 0f 50 00 00 01 ea ef` immediately after the
  first data chunk.
- A post-upload notification at t=284.84 contains flags=0xC0, opCode=0x20 with paramData
  `01 34` — likely a "transfer complete" signal.

## Observed write summary (for task 7 replay)

- Total ATT operations on handle `0x000f` connection: 140 packets
- Client writes to handle `0x0006` (target for image upload): **17 RCSP frames + 6 data frames + 5 auth packets = 28 writes**
  - 17 are control frames (flags=0xC0, opCode varies: 0x06/0x03/0x07/0x21/0x27/0x1B/0x1C)
  - 6 are image-data frames (flags=0x80, opCode=0x01 CMD_DATA, xmOpCode=0x1D)
  - 5 are the pre-handshake auth packets (no envelope: raw `00`/`01`/`02` prefix)
- Notifications received on handle `0x0008`: 12 plain notifications + 18 indications
- Writes to handle `0x000c` (JieLi RCSP 128-bit service): 11 (not related to image upload)

## Questions resolved by jadx analysis

The following questions from the initial analysis are now answered.

**Q1 — Is the 16-byte challenge/response real cryptography?**
Yes. `RcspAuth.getRandomAuthData()` and `RcspAuth.getEncryptedAuthData()` are JNI native
methods in `libjl_auth.so`. The algorithm is genuinely cryptographic. The literal `"pass"`
token is sent *after* both challenge-response rounds succeed, not instead of them. For a
Python client, try replaying the captured fixed sequences first; if the badge rejects them,
disassembly of `libjl_auth.so` is the next step.

**Q2 — What do each control sub-opcode do?**
The "sub-opcode" is the `opCode` field (byte after flags), not a sub-field. Decoded:
- `0x06` CMD_DISCONNECT_CLASSIC_BLUETOOTH — session-init frame (hard-coded constant in RcspAuth)
- `0x03` CMD_GET_TARGET_INFO — device info query (probe)
- `0x07` CMD_GET_SYS_INFO — system info query
- `0x21` CMD_NOTIFY_PREPARE_ENV — arm the file transfer subsystem (1-byte param `00`)
- `0x27` CMD_DEV_PARAM_EXTEND — negotiate CRC16 support and protocol version
- `0x1B` CMD_START_LARGE_FILE_TRANSFER — announce file: size(4B) + CRC16(2B) + filename(N bytes null-terminated)
- `0x1C` CMD_STOP_LARGE_FILE_TRANSFER — close the file transfer
- `0x1D` appears as `xmOpCode` in every data frame, identifying them as large-file chunks

The `0x1B` paramData carries the **CRC16** of the entire file and the **byte size** of the
file, not a SHA hash. See "Control frames decoded" table above.

**Q3 — Why are there two JPEG blocks?**
The badge's `cr3` (jl_filebrowse) library sends two separate JPEG files to the badge's
"BAG" directory. Chunk index resets to 0 for the second file. Both use xmOpCode=0x1D.
JPEG #1 (chunks 0–4, seq 0x4B–0x4F) is ~2.2 KB and ends with FF D9.
JPEG #2 (chunk 0+, seq 0x50+) starts with JPEG SOI FF D8 and is the main display image
(or a thumbnail/preview variant). A Python client must send both files.

**Q4 — What is the sequence-counter reset rule?**
The `opCodeSn` byte is a shared monotonic counter across the entire session (both control
and data frames). It does NOT reset between JPEG transfers. It starts at `0x00` for the
hard-coded session-init frame, then begins at some value (observed: `0x46` = 70) for
regular commands. It increments by 1 per frame and wraps `0xFF → 0x00`.
The chunk_index (separate field within data frame body) resets to 0 for each new file.

**Q5 — Is there a CRC/hash?**
Yes, two CRCs:
1. **Per-file CRC16** in CMD_START_LARGE_FILE_TRANSFER (0x1B) body: 2-byte big-endian
   CRC16 of the complete JPEG file, computed by `CryptoUtil.CRC16(file_bytes, (short)0)`.
   Observed value: `32 AF` = 0x32AF for the 2745-byte JPEG.
2. **Per-chunk CRC16** in each data frame: 2 bytes big-endian after chunk_index, computed
   by `CryptoUtil.CRC16(chunk_bytes, (short)0)`. Present when both `appHasCrc16` and
   `firmwareHasCrc16` flags are true (both true in the observed session).
There is no SHA-1 or CRC32. No CRC in the frame trailer.

## Phase 1 exit status — protocol confirmed working

As of 2026-04-20, `spike/e87_client.py` uploads arbitrary JPEG images to the badge and
renders them as new gallery entries. Two images verified on hardware:

1. `docs/captures/01-solid-red-360.png` — 1.1 KB as PNG, encoded to 1.1 KB JPEG, 3 chunks
2. Arbitrary 360×360 blue-and-yellow-circle — 7.7 KB JPEG, 16 chunks, 3 windowed bursts

So the remainder of this document should be read as a conceptual description; for concrete
wire behaviour the authoritative references are the working client (`spike/e87_client.py`),
the MIT-licensed upstream (`hybridherbst/web-bluetooth-e87`, `web/src/lib/e87-protocol.ts`),
and the validated auth cipher port (`spike/jieli_auth.py` + test vector in
`tests/test_jieli_auth.py`).

## Client implementation notes

### Authentication (verified)

The 16-byte values in the `0x00`/`0x01` handshake packets are **real AES-like block-cipher
output** from a bespoke JieLi algorithm, not AES. It is implemented in `libjl_auth.so`
(ARM64 binary in the Zrun split APK) with these parameters:

- Three 256-byte lookup tables (`KS_TABLE`, `SBOX`, `ISBOX`) at `.so` offsets
  `0x1B4C`, `0x1C4C`, `0x1D4C`.
- Hardcoded static key `06 77 5F 87 91 8D D4 23 00 5D F1 D8 CF 0C 14 2B`.
- Hardcoded 6-byte magic `11 22 33 33 22 11` used as the repeated-pattern second key.
- 16 rounds with rotate-3-left, SBOX/ISBOX swap, Fibonacci-butterfly mix, `0x9999` mask.

Test vector (from the real Zrun capture in `docs/captures/01-solid-red-360.log`):
- challenge `70 B7 59 92 E0 5E A7 8F EC 53 3B A1 29 79 B5 90`
- response `FF E9 E6 C8 0C E1 F4 0F 5C CE AE 20 83 1C 58 79`

Our Python port (`spike/jieli_auth.py`) produces this response byte-exactly for the given
challenge. Same key across our device and the upstream maintainer's device, so likely
universal for this SDK revision. If a future vendor customizes the key, extract it from
the target device's own `libjl_auth.so` at the same offset.

### Advertising-name is "E87"

The badge's GAP advertising name is literally `E87`, visible in the **scan response**.
Android's system Bluetooth settings hides this because Zrun scans and connects directly
using the Filter Accept List without populating the user-facing list — but BlueZ / any
active scanner sees it. Home Assistant's `bluetooth:` manifest matcher can safely use
`{ "local_name": "E87" }` for auto-discovery. Fallback: match on service UUID
`0000ae00-0000-1000-8000-00805f9b34fb`.

### MTU

BlueZ on Linux does not auto-negotiate a higher MTU for `write-without-response` on
GATT characteristics; `bleak` reports `mtu_size=23` even when larger would work. In
practice the badge accepts writes up to **~500 bytes** (close to MTU=517 as negotiated by
Zrun on Android) — BlueZ sends these as multi-packet L2CAP fragments. No explicit MTU
negotiation is required from our client code for the upload to succeed.

### Image encoding

- Resize the input to **368×368** (not 360×360 as suggested by the Amazon product
  description, and not 384×384 as upstream's README title claims). `spike/e87_client.py`
  uses Pillow's `LANCZOS` resample.
- Encode as **JPEG** with quality ~88. Typical output: 1–15 KB for images up to full frame.
  The whole JPEG file is what the badge stores and displays. No further container or
  wrapper.
- Orientation: 360° round panel; top of JPEG maps to top of badge. No rotation needed.

### Upload flow (high level)

Upstream's full state machine is the authoritative reference. The rough 9-phase sequence
that `spike/e87_client.py` follows:

1. **Connect, subscribe to all four notify characteristics** (`AE02`, `FD01`, `FD03`,
   `FD05`). FD04's CCCD may fail with "not supported" on some platforms; ignored.
2. **Authentication** (mutual handshake as described above).
3. **Phase 1:** send `0x06` (CMD_DISCONNECT_CLASSIC_BT) to reset the auth flag server-side.
4. **Phase 2:** three FD02 control writes (time sync / session hello / keepalive).
5. **Phase 3:** `0x03` (CMD_GET_TARGET_INFO) — device info probe. Response identifies the
   JieLi SDK build (`jl_sdk_ac697_publish` in our case).
6. **Phase 4:** `0x07` (CMD_GET_SYS_INFO) — system info probe.
7. **Phase 5:** FD02 bootstrap — wait for ready signal (0x9E…C7 pattern).
8. **Phase 6:** `0x21` (CMD_NOTIFY_PREPARE_ENV) — arm the file-transfer subsystem.
9. **Phase 7:** `0x27` (CMD_DEV_PARAM_EXTEND) — negotiate CRC16 and protocol flags.
10. **Phase 8:** `0x1B` (CMD_START_LARGE_FILE_TRANSFER) — announce file with size,
    CRC-16/XMODEM of the file, and a generated temp filename like `ac263d.tmp`. The badge
    responds with a chunk-size hint (observed: **490 bytes**, not MTU-derived).
11. **Phase 9:** data transfer with window-based flow control:
    - Each data frame is `FE DC BA 80 01 LEN seq 1D slot CRC16 <chunk_bytes> EF`.
    - Chunks batched into windows (badge advertises window size in its ack; ~3920 bytes
      = 8 chunks of 490).
    - Badge emits `0x1D` notifications on AE02 with the next-offset pointer and window
      size; client sends that window, then waits for the next ack.
    - Final chunk advertises the trailing `FF D9` JPEG End-of-Image marker.
12. **Phase 10 — Completion handshake:**
    - Badge notifies `0xC0 0x20` (FILE_COMPLETE) with a device sequence number.
    - Client responds with `0x00 0x20` containing a UTF-16LE path string
      (`\Udd5c\U55...jpg\0`) that names the final location the badge stored the file.
    - Badge notifies `0xC0 0x1C` (SESSION_CLOSE).
    - Client responds `0x00 0x1C`, disconnects.

### CRC-16/XMODEM

Standard CRC-16/XMODEM (polynomial `0x1021`, init `0x0000`, no reflection, no final XOR).
Verified against the test vector `CRC16("123456789") = 0x31C3`. Used in two places:

- Whole-file CRC in the `0x1B` body (2 bytes, big-endian).
- Per-chunk CRC in each data frame after the chunk_index (2 bytes, big-endian).

### Filenames

The temp filename sent in `0x1B` is generated by the client as `<6-hex-chars>.tmp` (hex
of a random 3-byte prefix). The badge responds in its `0x20` ack with the final filename
it stored the file under, which is arbitrary-looking (e.g.
`\5c\55 32 30 32 36 30 34 32 30 32 33 33 39 32 37 2e 6a 70 67 00` in UTF-16LE —
the `5c55` prefix is not ASCII, it is the two bytes of the Chinese char `囜` (U+555C);
the rest is the date-time `20260420233927.jpg`). The client echoes this back verbatim
in its own `0x20` response.

## JieLi RCSP side-channel (`FD01`/`FD02`/`FD03`/`FD05`)

The service `c2e6fd00-e966-1000-8000-bef9c223df6a` is standard JieLi RCSP. For image
upload we send three short FD02 commands in Phase 2 (time-sync, session-hello, keep-alive)
and one in Phase 5 (bootstrap). All four are verbatim hex blobs from upstream; their
semantics are unused by our client.

Other RCSP commands (battery level via AC697 system events, firmware version, file
listing) are documented in upstream's README and JieLi's own `jl_rcsp` SDK; out of
scope for v1 of the image uploader but useful for phase 3 (Home Assistant sensor entities).

## Out of scope (observed but not used in v1)

- Most JieLi RCSP traffic on the 128-bit service: battery level sensing (via AC697 system
  events), firmware version queries, OTA upgrade. Phase 2 (Home Assistant integration)
  may expose these as sensor entities.
- AVI / multi-frame / video upload — the badge supports animated uploads; our client
  sends a single JPEG at a time. The upstream `e87-protocol.ts` has the code if/when
  we want this.
- Pattern / QR / sequence modes from upstream's UI.
- JPEG quality tuning — we use a fixed `quality=88`. Larger quality produces bigger files;
  the badge's practical max file size is unknown.
- Retry policies for mid-transfer disconnects — current client errors out; a real library
  would reconnect and resume (or retry the whole upload).
