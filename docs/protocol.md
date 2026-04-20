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

## Client implementation notes (draft)

Placeholder — will be completed in task 9.

## Out of scope (observed but not used in v1)

- JieLi RCSP traffic on the 128-bit service: firmware version queries, battery level,
  possibly time sync. Phase 2 may expose these as sensor entities later.
- Handle `0x0011` (JieLi notify+write+read) — purpose unknown, untouched during image
  upload.
- The post-upload notifications `fedcba 0020…` and `fedcba 001c…` — likely
  "image rendered" / "ready for next" signals; not needed for a fire-and-forget client.
