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
