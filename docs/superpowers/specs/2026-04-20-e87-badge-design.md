# E87 Smart Digital Badge — Open Client & Home Assistant Integration

**Date:** 2026-04-20
**Status:** Draft — awaiting user approval
**Owner:** johnny@jumpingmushroom.com

## Summary

Reverse-engineer the Bluetooth Low Energy protocol used by the Zrun app to drive the "E-Badge E87" round LCD pin (360×360 IPS, BLE, ~32 MB storage). Produce:

1. A documented protocol specification.
2. A standalone Python library + CLI (`e87-badge`) for sending images to the badge.
3. A Home Assistant custom integration that uses the library and Home Assistant's Bluetooth proxy routing so automations can push images/text to the badge from anywhere in the house.

No public reverse-engineering work for this device exists at time of writing — the project fills that gap.

## Goals

- Send an arbitrary PNG/JPEG from a Linux terminal to the badge over BLE, without using the Zrun app.
- Expose the capability as a reusable Python library that accepts an externally-supplied `bleak` `BLEDevice`, allowing it to be embedded in Home Assistant (where Bluetooth routing goes through `habluetooth` / ESPHome `bluetooth_proxy` devices).
- Ship a Home Assistant custom integration that auto-discovers the badge via BLE advertising and exposes a service (e.g. `e87_badge.send_image`) that automations can call.
- Publish a `docs/protocol.md` that other hackers can use to build their own clients.

## Non-Goals (v1)

- Custom firmware for the badge SoC.
- Animated GIF / MP4 support. (Stretch — revisit after still-image path works.)
- Touch-gesture capture / bidirectional remote control.
- Multi-badge fleet management UI.
- Windows/macOS CLI packaging beyond best-effort (Linux is the target).

## Target Hardware & Environment

- **Badge:** Generic E-Badge E87, Zrun ecosystem. Single unit confirmed in hand.
- **Dev box:** Linux, with `bleak` for BLE and `jadx` for APK analysis.
- **Capture device:** Android phone with Developer Options → "Enable Bluetooth HCI snoop log".
- **Home Assistant deployment target:** Multiple ESPHome `bluetooth_proxy` devices distributed around the house; badge should be reachable via whichever proxy is closest. Library therefore must not assume a specific adapter — it must accept a `BLEDevice` supplied by Home Assistant's Bluetooth integration.

## Architecture

Single repository, three artifacts with a clean dependency arrow:

```
protocol RE (docs)  →  e87_badge (lib + CLI)  →  custom_components/e87_badge (HA)
```

### Repository layout

```
E87_communicator/
├── docs/
│   ├── protocol.md                        # RE findings — the deliverable of phase 1
│   ├── superpowers/specs/                 # this doc lives here
│   └── captures/                          # btsnoop logs (gitignored if large)
├── src/e87_badge/
│   ├── __init__.py
│   ├── client.py                          # E87Client: async high-level API
│   ├── protocol.py                        # Framing, chunking, opcodes, CRC
│   ├── image.py                           # PIL → badge-native pixel format
│   ├── discovery.py                       # BLE scan helpers (standalone use only)
│   └── cli.py                             # `e87` entrypoint
├── custom_components/e87_badge/           # HA integration (phase 3)
│   ├── manifest.json
│   ├── config_flow.py
│   ├── coordinator.py
│   ├── services.yaml
│   └── __init__.py
├── tests/
│   ├── fixtures/                          # captured btsnoop byte sequences
│   ├── test_protocol.py                   # offline, no badge required
│   └── test_client_integration.py         # requires E87_BADGE_MAC env var
├── pyproject.toml
└── README.md
```

### Runtime dependencies

- **Library:** `bleak`, `bleak-retry-connector`, `pillow`.
- **CLI:** library + `click` (or `typer`).
- **HA integration:** library + `habluetooth` (ships with HA core).

The library must not import any HA-specific module. HA integration imports the library, never the reverse.

## Phase 1 — Protocol Reverse Engineering

**Deliverable:** `docs/protocol.md` describing everything needed to write an independent client.

### Steps

1. **Baseline.** Install Zrun on Android, pair with badge, upload one still image. Confirm it renders. If Zrun is broken on current Android, fall back to an older Zrun APK from APKMirror. If still broken, identify and install a sister rebadge app.
2. **Capture.** Enable Android HCI snoop log. Perform a clean cycle: pair → upload a known image (e.g. a 360×360 solid red PNG) → disconnect. Pull `/sdcard/btsnoop_hci.log`.
3. **Dissect.** Open the log in Wireshark with the Bluetooth dissector. Extract: GATT service UUIDs, write characteristic UUIDs, notify characteristic UUIDs, MTU exchange value, connection parameters, pairing/bonding requirements.
4. **Decompile.** Run `jadx-gui` on the Zrun APK. Locate the BLE write code path — usually a class with `BluetoothGatt.writeCharacteristic` calls. Identify: opcode/command bytes, chunk header format, total-size prefix, per-chunk sequence numbers, checksum/CRC algorithm, image encoding (raw RGB565 vs JPEG-chunked vs proprietary).
5. **Replay.** Write a Python throwaway script using `bleak` that replays the captured bytes verbatim. Confirm the badge displays the originally-uploaded image.
6. **Parametrize.** Modify the replay to send a *different* 360×360 image using the discovered encoding + framing. This proves understanding of the protocol rather than tape-recorder playback.
7. **Document.** Write `docs/protocol.md` covering: advertising data, pairing/bonding, GATT structure, opcodes, framing, image encoding, error/ack behaviour, observed MTU, timing constraints.

### Exit criteria

A standalone Python script (not yet packaged as a library) accepts a PNG path on the command line and makes the badge display that image. Running it twice in a row with different images both succeed.

### Test data

Save every btsnoop capture and the exact PNG used during capture to `docs/captures/` (gitignored if any single file exceeds 5 MB; otherwise committed). These become offline fixtures for phase 2 protocol tests.

## Phase 2 — Python Library + CLI

### Public API (target shape)

```python
from e87_badge import E87Client, discover

# Standalone use (not through HA)
device = await discover(timeout=10.0)                 # returns bleak.BLEDevice | None
async with E87Client(device) as badge:
    await badge.send_image("cat.png")                 # auto-resizes to 360x360
    await badge.send_text("Hello", font="DejaVuSans") # PIL-rendered then sent as image
    info = await badge.get_info()                     # firmware ver, storage, etc.

# Embedded use (from Home Assistant)
client = E87Client(ble_device)   # ble_device supplied by HA's bluetooth integration
await client.connect()
await client.send_image(image_bytes)
await client.disconnect()
```

### Design constraints

- `E87Client.__init__` accepts either a `bleak.BLEDevice` or a MAC-address string. When passed a `BLEDevice`, it must use that object verbatim — no re-discovery. This is the contract that lets Home Assistant route connections through the correct proxy.
- All I/O is `asyncio`. No threads, no blocking calls.
- Reconnect logic uses `bleak-retry-connector`'s `establish_connection`.
- `send_image` accepts `str | Path | bytes | PIL.Image.Image`. Resizing/encoding happens client-side.
- Chunking is MTU-aware. The library negotiates MTU and adapts chunk size; it never hardcodes a value discovered during RE.
- All byte-level protocol constants live in `protocol.py` and are named — no magic numbers in `client.py`.

### CLI (target shape)

```
e87 discover                       # scan and print matching devices
e87 info --mac AA:BB:CC:DD:EE:FF
e87 send cat.png --mac AA:BB:...   # auto-discover if --mac omitted
e87 text "Hello" --mac AA:BB:...   --font DejaVuSans --size 48
```

Non-zero exit on BLE failure, with a clear error message. `--debug` flag enables verbose bleak logging.

### Testing strategy

- **Protocol tests (offline):** Feed captured btsnoop byte sequences into `protocol.py` encoders/decoders. Round-trip a known image through `encode → decode → compare`. No badge required, run on every commit.
- **Integration tests (hardware):** Gated behind `E87_BADGE_MAC` env var. Skip if unset. Cover: connect, send small image, send large image, disconnect cleanly, reconnect after drop.

### Exit criteria

- `pip install -e .` then `e87 send my_image.png` succeeds with only the badge's MAC/name known.
- Protocol tests pass in CI without hardware.

## Phase 3 — Home Assistant Custom Integration

Follows the standard modern HA BT integration pattern used by SwitchBot, Inkbird, Govee, etc.

### Manifest & discovery

```json
{
  "domain": "e87_badge",
  "name": "E87 Smart Digital Badge",
  "bluetooth": [
    { "local_name": "E87*" }
  ],
  "dependencies": ["bluetooth"],
  "iot_class": "local_push",
  "requirements": ["e87-badge==<version>"],
  "version": "0.1.0"
}
```

Exact advertising-name match pattern is confirmed during phase 1 via `bluetoothctl` scan. The manifest matcher is updated once known.

### Config flow

- Triggered by BLE discovery or user "Add Integration".
- Lists discovered E87 badges by MAC + RSSI.
- User picks one, names it. One badge = one config entry.

### Coordinator

- Owns an `E87Client` constructed with the `BLEDevice` obtained from `bluetooth.async_ble_device_from_address`. This is the critical glue — HA's bluetooth integration is responsible for tracking which proxy currently has the best RSSI to the badge, and supplies the corresponding `BLEDevice` object. The library just writes to it.
- Reconnect on disconnect handled by `bleak-retry-connector`.

### Entities & services

- **Services:**
  - `e87_badge.send_image`: fields = `entity_id`, `image` (path, URL, or base64 bytes).
  - `e87_badge.send_text`: fields = `entity_id`, `text`, optional `font`, `size`, `colour`.
- **Entities (v1):**
  - One `sensor` per badge exposing connection status + last-send timestamp.
- **Entities (stretch, out of scope):** `camera` showing last-sent image; `button` entities for preset rotations.

### Example automation (shipped in README)

```yaml
alias: "Welcome badge on arrival"
trigger:
  - platform: state
    entity_id: person.johnny
    to: "home"
action:
  - service: e87_badge.send_image
    data:
      entity_id: sensor.e87_badge_office
      image: /config/www/badges/welcome.png
```

### Exit criteria

- Integration installs via HACS (or manual copy), auto-discovers the badge, and the `send_image` service works in an automation.
- When the user physically carries the badge from one room to another, the next send uses the proxy now closest to the badge — no reconfiguration needed. (Validated manually with two ESPHome proxies during development.)

## Risks & Unknowns

- **Zrun app broken.** Multiple Play Store reviews report Zrun barely works. Mitigation: older APK from APKMirror, or a sister rebadge app (Beambox ecosystem). If no working app exists, project blocks — we need a working baseline flow to capture.
- **Auth/bonding tokens.** Zrun may embed a per-session or per-account token in BLE writes. If so, the APK decompile step must extract it or document the token-derivation algorithm. Worst case: library requires a one-time "pair in Zrun, extract token" setup step.
- **Proprietary image encoding.** If the badge expects a custom compressed format rather than raw RGB565 or plain JPEG, more APK archaeology is required. Mitigation: protocol doc explicitly lists encoding as a known unknown at start of phase 1; phase 2 does not begin until it is resolved.
- **MTU over BT proxy.** ESPHome BT proxy MTU is typically smaller than a direct connection. Chunking must negotiate MTU on every connect, not cache it. Validated in phase 3 with real proxies.
- **Rebadge protocol drift.** This spec targets the generic "E-Badge E87" / Zrun variant only. Rebadges pairing with different apps (e.g. Beambox) are explicitly out of scope and may use a different protocol.

## Open Questions (to resolve during execution)

- Does the badge bond (require pairing key) or accept unauthenticated writes?
- Is there a "clear display" / "set backlight" / "set brightness" command worth exposing, or is the write-image path the only useful surface?
- Does the badge expose battery level via a standard Battery Service UUID? (Would make a nice HA sensor entity.)

## Glossary

- **BLE:** Bluetooth Low Energy.
- **GATT:** Generic Attribute Profile — how BLE devices expose services and characteristics.
- **MTU:** Maximum Transmission Unit — max bytes per BLE write.
- **HCI snoop log:** Android-side capture of raw Bluetooth host-controller-interface traffic.
- **BT proxy (ESPHome):** An ESP32 running ESPHome firmware that relays nearby BLE devices to Home Assistant over Wi-Fi, extending BT range across a house.
