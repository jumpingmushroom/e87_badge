# RE running notes

Running log of observations made while reverse-engineering the E87 protocol. New notes at
the top. Timestamp each entry.

---

## 2026-04-20 — Baseline

- Zrun version: 2.2.5
- Phone: Samsung Galaxy S24 Ultra, Android 18
- Badge firmware (from Zrun device-info screen): 11.1.0.3
- Badge MAC: `46:8D:00:01:2C:25`
- Pairing: success
- Upload: success (arbitrary test image rendered on badge)
- Zrun account: not required
- **Advertising name:** none visible in Android's Bluetooth settings — the phone's BT
  settings screen never shows the badge. Zrun connects directly. Implication: badge likely
  advertises with no `Complete Local Name` AD field, or only advertises in a "pairing mode"
  window that Android's main BT scan misses. Either way, the Home Assistant integration
  manifest cannot rely on `local_name` matching — plan to use service UUID and/or MAC OUI
  (`46:8D:00:…`) instead. Confirm during Task 5 Wireshark dissection.
