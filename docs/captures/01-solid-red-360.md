# Capture 01 — solid red 360x360

- Date: 2026-04-20
- Phone: Samsung Galaxy S24 Ultra, Android 18
- Zrun version: 2.2.5
- Badge firmware: 11.1.0.3
- Badge MAC: `46:8D:00:01:2C:25`
- Image: `01-solid-red-360.png` — 360×360 solid `#FF0000` (1,167 bytes as PNG)
- Upload outcome: success — badge displayed pure red
- Cycle: BT off → BT on (fresh log) → open Zrun → connect → send image → await success → disconnect → BT off
- Log size: 4,107,941 bytes
- Log source: Samsung bugreport — path inside `e87-bugreport.zip` is
  `FS/data/log/bt/btsnoop_hci.log` (not the more common `/data/misc/bluetooth/logs/`).
  Direct `adb pull` does not work on Samsung stock firmware — bugreport is required.
- Log format: BTSnoop version 1, HCI UART (H4) — confirmed via `file(1)`
