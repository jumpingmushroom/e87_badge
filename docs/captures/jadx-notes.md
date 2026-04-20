# jadx decompile notes — Zrun APK com.zijun.zrun v2.2.5

APK SHA-256: `59436cf584cac68cab75d75ee2460a08025530ab94e183a46388c5eedc50feaf`
jadx 1.5.5, decompile target: `/tmp/zrun-decompiled`
Command: `jadx --no-res -d /tmp/zrun-decompiled /home/johnny/zrun.apk`
146 class decompile errors (expected; ProGuard obfuscation). All critical classes readable.

---

## Key classes

### GATT UUIDs
`com/jieli/bluetooth_connect/constant/BluetoothConstant.java`
```java
UUID_SERVICE      = "0000ae00-0000-1000-8000-00805f9b34fb"
UUID_WRITE        = "0000ae01-0000-1000-8000-00805f9b34fb"  // handle 0x0006
UUID_NOTIFICATION = "0000ae02-0000-1000-8000-00805f9b34fb"  // handle 0x0008
```

### Frame magic constants
`com/jieli/jl_rcsp/constant/RcspConstant.java`
```java
PREFIX_FLAG_FIRST  = -2   // 0xFE
PREFIX_FLAG_SECOND = -36  // 0xDC
PREFIX_FLAG_THIRD  = -70  // 0xBA
END_FLAG           = -17  // 0xEF
JL_RCSP_LIB = "jl_auth"  // native library name
```

### RCSP frame builder
`com/jieli/jl_rcsp/tool/datahandles/ParseHelper.java`, method `packSendBasePacket()`

Full wire frame layout:
```
FE DC BA  [flags]  [opCode]  [paramLen_hi]  [paramLen_lo]  [body...]  EF
```
- `flags` byte: bit7 = direction (1=request/phone→badge, 0=response/badge→phone), bit6 = hasResponse
- `paramLen` = 16-bit big-endian, counts ALL body bytes (including opCodeSn and any headers)
- Total frame length = 8 + paramLen bytes

Body layout for **requests** (flags bit7=1):
```
[opCodeSn]  [xmOpCode if opCode==1]  [paramData...]
```

Body layout for **responses** (flags bit7=0):
```
[status]  [opCodeSn]  [xmOpCode if opCode==1]  [paramData...]
```

CHexConver.int2byte2() = big-endian: `(i>>8)&0xFF, i&0xFF`.

### RCSP command IDs
`com/jieli/jl_rcsp/constant/Command.java` (partial, relevant to badge upload):
```java
CMD_DATA                       = 1    // raw data transport (uses xmOpCode)
CMD_GET_TARGET_INFO            = 3    // 0x03
CMD_DISCONNECT_CLASSIC_BT      = 6    // 0x06 (session init uses opCode=0x06)
CMD_GET_SYS_INFO               = 7    // 0x07
CMD_START_LARGE_FILE_TRANSFER  = 27   // 0x1B
CMD_STOP_LARGE_FILE_TRANSFER   = 28   // 0x1C
CMD_LARGE_FILE_TRANSFER_OP     = 29   // 0x1D  (also xmOpCode for data chunks)
CMD_DATA_TRANSFER              = 48   // 0x30
CMD_NOTIFY_PREPARE_ENV         = 33   // 0x21
CMD_DEV_PARAM_EXTEND           = 39   // 0x27
CMD_ADV_SETTINGS               = 192  // 0xC0
```

### Auth implementation
`com/jieli/jl_rcsp/impl/RcspAuth.java`

Session init frame is a hard-coded constant:
```java
private byte[] b() {
    return CHexConver.hexStr2Bytes("FEDCBAC00600020001EF");
}
```
This is a normal RCSP frame: flags=0xC0 (request+hasResponse), opCode=0x06
(CMD_DISCONNECT_CLASSIC_BLUETOOTH repurposed as session-init), paramLen=2,
body=[opCodeSn=0x00, paramData=0x01].

After the session init, RcspAuth calls:
```java
public native byte[] getRandomAuthData();    // generates 16-byte challenge
public native byte[] getEncryptedAuthData(byte[] bArr);  // processes response
```
Both are JNI methods in `libjl_auth.so`. The auth is real cryptography (not ceremonial).

Wire format for auth packets (NOT wrapped in FE DC BA envelope):
- `00 <16 bytes>` = phone sends its own challenge
- `01 <16 bytes>` = phone responds to badge's challenge
- `02 70617373` = `\x02pass` = auth-accepted signal
The badge mirrors this pattern from its side.

The literal ASCII "pass" (`70617373`) is the acceptance token exchanged after the
challenge-response rounds complete. Both sides must verify the crypto before sending "pass".
Replaying a fixed 16-byte sequence may work if the badge does not enforce replay protection
(no nonce on the badge side was observed), but this requires empirical testing.

### StartLargeFileTransferParam (0x1B body)
`com/jieli/jl_rcsp/model/parameter/StartLargeFileTransferParam.java`

`getParamData()` produces:
```
[size 4 bytes big-endian]  [crc16 2 bytes big-endian]  [hash/filename bytes...]
```
The `hash` field is misnamed — it is the filename of the temp file being transferred
(null-terminated ASCII string, up to ~13 bytes in observed capture: "ddbdbf24.tmp\0").

Decoding of capture frame (t=282.499, `fedcba c0 1b 00 14 4a 00000ab9 32af 64646264626632342e746d7000 ef`):
- flags=0xC0 (request+hasResponse), opCode=0x1B, paramLen=0x0014=20
- opCodeSn = 0x4A
- paramData (19 bytes):
  - size  = `00 00 0a b9` = 2745 bytes  (total JPEG file size)
  - crc16 = `32 af` = 0x32AF  (CRC16 of the entire file)
  - filename = `64 64 62 64 62 66 32 34 2e 74 6d 70 00` = "ddbdbf24.tmp\0"

CRC16 is computed by `CryptoUtil.CRC16()` (standard CRC-16/BUYPASS or similar).

### Data chunk structure (opCode=0x01 / CMD_DATA)
`com/jieli/jl_rcsp/task/TransferTask.java` (inner method building SendData packets)

Each data frame body (after magic+flags+opCode+paramLen):
```
[opCodeSn]  [xmOpCode=0x1D]  [chunk_index]  [crc16_hi]  [crc16_lo]  [chunk_data...]
```
- `xmOpCode = 0x1D` = CMD_LARGE_FILE_TRANSFER_OP (29)
- `chunk_index` = 0-based index within current file transfer, increments per MTU chunk
- `crc16` = CRC16 of this chunk's data only (per-chunk integrity check)
- CRC present only when `appHasCrc16 && firmwareHasCrc16` (both flags true in observed traffic)

If no CRC:
```
[opCodeSn]  [xmOpCode=0x1D]  [chunk_index]  [chunk_data...]
```

Decoding sample frame (t=282.981, frame 10):
- flags=0x80 (request, no hasResponse), opCode=0x01, paramLen=0x01EF=495
- opCodeSn=0x4B, xmOpCode=0x1D, chunk_index=0x00
- crc16 = `b7 04` = 0xB704
- chunk_data: `17 18 19 1a 26 27...` (JPEG continuation, 490 bytes)

Decoding new-JPEG frame (t=284.582, frame 15):
- flags=0x80, opCode=0x01, paramLen=0x01EF=495
- opCodeSn=0x50, xmOpCode=0x1D, chunk_index=0x00 (RESET for new file)
- crc16 = `2c 12` = 0x2C12
- chunk_data: `ff d8 ff e0 00 10 4a 46 49 46...` (JPEG SOI + JFIF APP0 = new JPEG)

### Sequence counter (opCodeSn)
`com/jieli/jl_rcsp/tool/SnGenerator.java` — not read in full, but from RcspOpImpl behavior:
- opCodeSn is a shared monotonic byte counter across ALL commands in a session
- Starts at some non-zero value (observed: 0x46 = 70 for first real command after session init)
- Session-init frame uses opCodeSn=0x00 (hard-coded)
- Increments by 1 per frame (both control and data frames share the same counter)
- Does NOT reset between image transfers within a session
- Wraps at 0xFF → 0x00

Observed sequence in capture: 0x00 (init), 0x46, 0x47, 0x48, 0x49, 0x4A, 0x4B, 0x4C,
0x4D, 0x4E, 0x4F, 0x50 — monotonic across the entire control+data sequence.

### FileType enum
`com/zijun/zrun/model/FileType.java`
```
BADGE = 12 (0x0C)  -- used for e-badge image transfers
```
Set via `command_a2d_setSendFileType((byte)12)` before starting file transfer.

### Two-JPEG explanation
The badge write sequence sends TWO complete JPEGs in sequence:
1. JPEG #1: chunks 0–4 (seq 0x4B–0x4F), ends with FF D9 in chunk 04
2. JPEG #2: chunk 0 resets (seq 0x50), starts with FF D8 (JPEG SOI)

Both are sent on the same xmOpCode=0x1D channel. The second JPEG's chunk_index resets
to 00. This is consistent with the badge's file system expecting two image files (e.g.,
a thumbnail/preview + main display image), OR with the `cr3` library (jl_filebrowse)
internally preparing and sending two image variants.

The first JPEG (#1 = chunks 0-4 = ~2.2 KB) is the primary display image.
The second JPEG (#2 = starting at seq 0x50) appears to be continuation/completion of the
same transfer or a second image. Both use identical chunk structure.

### DeviceExtendParamCmd (0x27 = CMD_DEV_PARAM_EXTEND)
`com/jieli/jl_rcsp/model/command/file_op/DeviceExtendParamCmd.java` — not read in full.
From context: the 0x27 frame (`fedcba c0 27 00 07 49 00000000 02 01 ef`) negotiates
file-transfer capabilities: `00000000` (likely a bitmask/flags field), `02` (protocol version?),
`01` (indicates app supports CRC16?).

### NotifyPrepareEnvCmd (0x21 = CMD_NOTIFY_PREPARE_ENV)
From LargeFileTransferCmdHandler: paramData[0] is a single-byte param.
Capture: `fedcba c0 21 00 02 48 00 ef` → opCodeSn=0x48, paramData=`00`.
This is the "prepare environment for file transfer" command, sent before 0x27.

### Post-upload frames
Frame at t=284.746 (`fedcba 00 20 00 26 00 34 5c55 66 00 5f 00 31...ef`):
- flags=0x00 (response), opCode=0x20 (32 decimal = CMD_SET_REAL_SYNCH in watch proto, or
  0x20=32 in RCSP = some status report). Payload contains UTF-16LE path string
  `\5f\31\37\37\36\37\31\35\38\34\32\2e\6a\70\67\00` = "\_1776715842.jpg\0"

Frame at t=284.858 (`fedcba 00 1c 00 02 00 35 ef`):
- flags=0x00, opCode=0x1C = CMD_STOP_LARGE_FILE_TRANSFER
- opCodeSn=0x35 in the response? Actually: status=0x00, opCodeSn=0x35, no paramData.

Wait — re-examining: `00 1c 00 02 00 35 ef` with response body [status][opCodeSn][paramData]:
- status=0x1C? No — this is a client→badge write (0x52), so it's a REQUEST frame:
  flags=0x00, opCode=0x1C, paramLen=0x0002, body=[opCodeSn=0x00, paramData=0x35].
  So this is CMD_STOP_LARGE_FILE_TRANSFER with opCodeSn=0, paramData=0x35.
  (The 0x35=53 decimal may be a status/reason code.)

---

## Auth bypass notes

The pre-handshake packets (lines 2–4 in ae01-writes.txt) are RAW writes without the
FE DC BA envelope:
```
0070b75992e05ea78fec533ba12979b590  -> 0x00 + 16 random bytes (phone challenge)
0270617373                          -> 0x02 + "pass" (phone signals auth passed)
01dd08e878b7cfdc5bef67cbfe80c993b3  -> 0x01 + 16 bytes (phone responds to badge challenge)
```
The 16-byte values come from `getRandomAuthData()` and `getEncryptedAuthData()` in
libjl_auth.so. To bypass, one would need to either:
a) Disassemble libjl_auth.so to extract the key/algorithm, or
b) Empirically test whether replaying any fixed 16-byte sequence is accepted.

---

## Watch/smartwatch protocol (separate, not for E87)

`com/qix/library/sdk/BTCommandManager.java` uses a different protocol:
- Frame starts with `CommandCode.COMMAND_MARK = -98 = 0x9E`
- Second byte is a checksum
- Then: [flags][opCode][len_lo][len_hi][payload...]
- No FE DC BA magic
This is the WATCH BT protocol (for wristbands), NOT the E-badge protocol.

`com/qix/library/command/CommandCode.java`:
```java
COMMAND_MARK              = -98   // 0x9E (not 0xFEDCBA)
COMMAND_REQ_BADGE_INFO    = -58   // 0xC6
COMMAND_REP_BADGE_INFO    = -57   // 0xC7
COMMAND_CON_SendFileSt    = -121  // 0x87
COMMAND_SET_SEND_FILE_TYPE = -36  // 0xDC
```
`command_a2d_setSendFileType(byte)` sends opCode 0xDC with the file type byte.
This is on a different GATT service (the paired smartwatch service, not the E87 badge
service `0x00ae`).

---

## DialTool (watch image format — not for E87)

`com/qix/library/sdk/DialTool.java` builds image payloads for watch dial faces:
- 8-byte image header: [0x42='B'][0x4D='M'][width_lo][width_hi][height_lo][height_hi][0x10][0x80]
  (BM = Windows BMP magic? or 'BM' + RGB565 header)
- 27-byte file header with CRC16 and file type/index fields
- Data = header + raw RGB565 pixel data
This format is for the SMARTWATCH, not the E87 badge.

---

## CryptoUtil.CRC16
`com/jieli/jl_rcsp/util/CryptoUtil.java` — not read in full.
Called as `CryptoUtil.CRC16(data, (short)0)` — initial value 0, standard polynomial.
Used for: per-chunk CRC16 in data frames, total-file CRC16 in 0x1B StartLargeFileTransfer.
