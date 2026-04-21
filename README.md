# e87_badge

Open-source Python client + Home Assistant integration for the **E-Badge E87 / L8** round-screen Bluetooth pin (the one that normally pairs with the Zrun app).

- 🖼️ Static images (JPEG/PNG upload)
- 📝 Rendered text
- 🎞️ Multi-image slideshows (MJPG AVI)
- 🖼️ Animated GIFs
- 🧧 Danmaku — scrolling text with custom colours

Built on top of:

- Reverse-engineered **JieLi RCSP** framing and mutual-auth cipher
- Upstream [hybridherbst/web-bluetooth-e87](https://github.com/hybridherbst/web-bluetooth-e87) (MIT) for protocol flow + AVI container
- Home Assistant's `habluetooth` → ESPHome `bluetooth_proxy` path so a single badge is reachable from anywhere in the house

See [`docs/protocol.md`](docs/protocol.md) for the full wire-level protocol write-up.

---

## Install — Python library + CLI

```bash
pip install git+https://github.com/jumpingmushroom/e87_badge@v0.1.0
```

Usage:

```bash
e87 discover                                 # scan for nearby badges
e87 image my-photo.png                       # upload a still image
e87 text "Hello" --size 96 --colour white    # rendered text
e87 slideshow a.png b.png c.png --ms 600     # multi-image slideshow
e87 gif pulse.gif                            # animated GIF
e87 danmaku "Welcome!" --fg red --bg yellow  # scrolling text
```

Pass `--address AA:BB:CC:DD:EE:FF` to target a specific badge (otherwise discovery picks the first one).

Library API:

```python
import asyncio
from e87_badge import E87Client

async def main():
    async with E87Client("46:8D:00:01:2C:25") as badge:
        await badge.send_image("welcome.png")
        await badge.send_text("Hi")
        await badge.send_slideshow(["a.png", "b.png", "c.png"], frame_ms=500)
        await badge.send_gif("party.gif")
        await badge.send_danmaku("breaking news!", fg="red", bg="black")

asyncio.run(main())
```

`E87Client` accepts either a MAC-address string or a pre-resolved `bleak.BLEDevice`. The `BLEDevice` form is what Home Assistant uses to route through whichever Bluetooth proxy is currently closest.

---

## Install — Home Assistant integration

The custom component lives under `custom_components/e87_badge/` and installs the library automatically via its `manifest.json` requirements.

**HACS (recommended):**

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/jumpingmushroom/e87_badge` as an **Integration**
3. Install "E87 Smart Digital Badge", restart Home Assistant

**Manual:**

```bash
cd /config
git clone --branch v0.1.0 https://github.com/jumpingmushroom/e87_badge
ln -s e87_badge/custom_components/e87_badge custom_components/e87_badge
```

Restart HA. When the badge advertises, it will appear under **Settings → Devices & Services → Discovered** as "E87 Smart Digital Badge". Add it once and you get:

- One sensor entity showing connection status (`last_sent_at`, `last_sent_type`, `rssi`, `proxy_source` attributes)
- Five services:

| Service | Fields |
|---|---|
| `e87_badge.send_image` | `image` (path, URL, or base64) |
| `e87_badge.send_text` | `text`, optional `font`, `size`, `colour`, `bg` |
| `e87_badge.send_slideshow` | `images` (list), optional `frame_ms` |
| `e87_badge.send_gif` | `image` (GIF path/URL/base64), optional `max_fps` |
| `e87_badge.send_danmaku` | `text`, optional `fg`, `bg`, `font`, `font_size`, `speed`, `fps` |

Example automation:

```yaml
- alias: Welcome badge on arrival
  trigger:
    - platform: state
      entity_id: person.johnny
      to: "home"
  action:
    - service: e87_badge.send_image
      target:
        entity_id: sensor.e87_badge_status
      data:
        image: /config/www/badges/welcome.png
```

### Home Assistant integration notes

**Recommend `connection_slots: 5` on the ESPHome `bluetooth_proxy` nearest to the badge.** The badge's upload protocol uses a single long-lived GATT connection plus several short command round-trips per send; on a proxy configured with the default `connection_slots: 3`, a previous failed session that hasn't fully released its slot can block the next send with `Could not subscribe to the badge's notification channel`. Up to 5 slots is safe on Wi-Fi proxies (Ethernet proxies can go higher).

```yaml
bluetooth_proxy:
  active: true
  connection_slots: 5

esp32_ble_tracker:
  scan_parameters:
    active: true   # needed for the "E87" local_name matcher
```

If sends still fail from a specific proxy, **reboot it once** — this clears any stale internal state. Long-term, distribute proxies so each is within ~3 m of the badge in typical use.

**Uploads take ~5–15 seconds** for a small still image, 30–60 seconds for a slideshow/GIF/danmaku. Service calls don't time out at HA's end, but keep this in mind when writing automations — don't fire consecutive sends in rapid succession.

**If a send fails mid-transfer**, v0.1.12+ sends a `CMD_STOP` to the badge so the next attempt starts clean. Earlier versions required waiting a few minutes for the badge to time itself out. If you're on an older version and hit this, the workaround is to power-cycle the badge or wait ~3 minutes.

---

## Requirements

- Linux or HA OS host with Bluetooth, or an ESPHome `bluetooth_proxy`
- Python 3.11+ (HA itself requires 3.12+)
- `bleak`, `bleak-retry-connector`, `pillow` (pulled in automatically)

## License

MIT. See [`LICENSE`](LICENSE). The JieLi auth cipher tables and AVI builder are ported from [web-bluetooth-e87](https://github.com/hybridherbst/web-bluetooth-e87) (© 2026 Felix Herbst, MIT).
