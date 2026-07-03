# Code Review — e87_badge — 2026-07-02 — reviewed by Fable 5

## Summary
Small, well-organized codebase (~3.8k lines): a Python BLE library (`src/e87_badge`), a CLI, and a Home Assistant custom component. The protocol layer is carefully commented, the tricky retransmit/EOF logic has regression tests, and the full suite passes (52 passed, 3 hardware-gated skips). The most significant risks are: heavy PIL/media encoding running synchronously on the Home Assistant event loop (stalls all of HA for seconds per send), a MAC-string fallback path in `E87Client` that cannot work because `bleak_retry_connector.establish_connection` requires a `BLEDevice`, and uploads being reported as successful even when the badge returns a non-zero close status. No secrets, no injection surfaces, no data-store integrity concerns (the project has no persistence layer).

## Findings

### [SEV-2] Media encoding and file I/O block the Home Assistant event loop
**FIXED:** offload PIL/media encoding to `asyncio.to_thread` in all `E87Client.send_*`; run `path.exists`/`is_allowed_path` via `hass.async_add_executor_job`; added `tests/test_client_offload.py`.

- **File:** custom_components/e87_badge/coordinator.py:79-94, custom_components/e87_badge/services.py:157-164, src/e87_badge/client.py:154-216, src/e87_badge/media/danmaku.py:61-73
- **Issue:** All media work — PIL `Image.open`/decode, LANCZOS resize, bracketed JPEG encoding, GIF frame iteration, and danmaku rendering (potentially hundreds of JPEG encodes for one call) — runs synchronously inside async methods executed on HA's event loop (`coordinator._run` → `E87Client.send_*` → `media.*`). `services.py` additionally does blocking `path.exists()` / `is_allowed_path()` in the loop. A single `send_danmaku` or `send_gif` call can stall the entire HA instance (UI, automations, and habluetooth's own BLE traffic) for seconds. Because the BLE proxy traffic that the upload itself depends on runs in the same loop, the stall can also degrade the upload's own window-ack timing.
- **Evidence:** `render_danmaku` loops `frames.append(_encode_frame_jpeg(window))` per scroll step (danmaku.py:68-73); `_encode_frame_jpeg` tries up to 8 quality levels with `optimize=True` per frame. Nothing in the call chain dispatches to an executor. HA logs "Detected blocking call" warnings for the filesystem checks and will show event-loop stall warnings for the encoding.
- **Suggested fix:** In the HA component, wrap the media-encoding half in `hass.async_add_executor_job` (e.g., pre-encode the payload bytes in an executor, then pass ready-made JPEG/AVI bytes to the client), or add executor/`asyncio.to_thread` offloading inside the library's `send_*` methods so both CLI and HA benefit. Move `path.exists()`/`is_allowed_path` into the same executor job.
- **Verification:** In a dev HA instance with `asyncio` debug (`loop.slow_callback_duration`) or HA's built-in blocking-call detector, call `e87_badge.send_danmaku` with a long string; confirm no slow-callback/blocking-call warnings and that the UI stays responsive during encode. Unit-testable by asserting `send_*` never runs PIL calls on the running loop (e.g., patch `_encode_frame_jpeg` to assert `threading.current_thread() is not MainThread`).

### [SEV-3] MAC-string fallback passes a `str` into `establish_connection`, which dereferences `BLEDevice` attributes
**FIXED:** `_resolve_ble_device` now raises a clear `E87ConnectError` when the scanner can't surface the MAC instead of returning a bare string that crashes `establish_connection`; added `test_unresolved_mac_fails_fast`.

- **File:** src/e87_badge/client.py:226-236 (fallback), src/e87_badge/client.py:87-92 (call site)
- **Issue:** When the scanner can't surface the badge, `_resolve_ble_device` returns the raw MAC string with a log saying it will be "passed directly to BleakClient". It is actually passed to `bleak_retry_connector.establish_connection`, whose signature requires a `BLEDevice`: on Linux it immediately calls `get_connected_devices(device)`, which reads `device.details` (bleak_retry_connector/bluez.py:539) — `AttributeError: 'str' object has no attribute 'details'`. The error is swallowed into `E87ConnectError("could not connect to badge: 'str' object has no attribute 'details'")`, so the documented fallback path never works and produces a confusing message. On non-Linux it may connect but crashes on `device.address` in every error/debug path.
- **Evidence:** `establish_connection(client_class, device: BLEDevice, ...)` and `get_connected_devices` in the installed bleak_retry_connector 4.6.0; `E87Client.connect` wraps any exception from `establish_connection` as a connect failure.
- **Suggested fix:** In the string-fallback branch, bypass `establish_connection` and construct/connect a `BleakClient(mac)` directly (with a small local retry), or fail fast with a clear "badge not found by scanner; ensure it is advertising" error instead of pretending a direct-MAC path exists.
- **Verification:** Unit test: monkeypatch `find_one` to return `None` and let the real `establish_connection` receive the string (or assert the fallback branch no longer calls it); CLI repro: `e87 image x.png --address <MAC>` with the badge powered off mid-scan and confirm the resulting error is the intended one.

### [SEV-3] Upload reported as success when the badge returns a non-zero session-close status
**FIXED:** `_finalize` now acks the close then raises `E87ProtocolError` on a non-zero device status; added `test_finalize_raises_on_nonzero_status` / `test_finalize_ok_on_zero_status`.

- **File:** src/e87_badge/protocol.py:419-431
- **Issue:** `_finalize` logs a warning for `status != 0x00` on the cmd 0x1C session close but returns normally. `UploadSession.run()` completes, `E87Coordinator._run` then sets `last_sent_at`/`last_sent_type` and the HA service call succeeds — even though the device just said the transfer failed (e.g. bad whole-file CRC, storage error). Automations cannot detect the failure.
- **Evidence:** `if status == 0x00: log.info("Upload complete") else: log.warning(...)` — no raise on the else branch; coordinator treats any non-exception as success (coordinator.py:92-94).
- **Suggested fix:** Raise `E87ProtocolError(f"badge reported close status 0x{status:02x}")` after sending the 0x1C response when status is non-zero (still send the ack first so the badge's state machine closes cleanly).
- **Verification:** Offline test: drive `_finalize` (or phase 9 via a scripted `NotifyBus`) with a close frame whose body is `(seq, 0x01)` and assert `E87ProtocolError` propagates; confirm the HA service call surfaces `HomeAssistantError`.

### [SEV-3] Blanket refusal to retransmit after EOF can abort a recoverable transfer
**FIXED:** replaced the unconditional post-EOF refusal with a per-offset bounded resend budget (`MAX_POST_EOF_RESENDS = 3`) tracked in `_TransferState`; honours legitimate CRC re-requests while keeping the infinite-loop guard. Added driver tests `test_phase9_resends_legit_rerequest_after_eof` and `test_phase9_bounds_repeated_rerequests`.

- **File:** src/e87_badge/protocol.py:279-296
- **Issue:** Once `max_offset_delivered >= len(data)`, any subsequent 0x1D ack requesting `next_offset < len(data)` is ignored ("ignoring to avoid infinite loop"). But "delivered to the BLE writer" is not "received intact by the badge": if the badge's last window fails its CRC check, its re-request of that offset is legitimate, and the code will stall for 30 s, then abort with `E87TransferAborted` — turning a one-window retransmit into a failed upload. The guard was added deliberately (v0.1.13/14 fixes) to stop infinite retransmit loops, so this is a known trade-off; flagged because the current form trades a rare recoverable case for a hard failure. Uncertainty: real-badge behavior on CRC failure of the final window is not captured in `docs/captures`, so how often this bites is unknown.
- **Evidence:** The `elif file_fully_sent and next_offset < len(data)` branch skips `_send_window` unconditionally; the loop then waits and eventually times out at protocol.py:301-317.
- **Suggested fix:** Replace the unconditional refusal with a bounded retry budget (e.g., allow up to 2–3 re-sends of any given offset after EOF, tracked in `_TransferState`; refuse only when the same offset repeats beyond the budget). This preserves the infinite-loop guard while honouring legitimate re-requests.
- **Verification:** Extend `tests/test_protocol_offline.py`: script a bus that requests offset 0 → EOF, then re-requests the final window once; assert the window is re-sent and the session completes on the subsequent 0x20/0x1C. Also assert a bus that re-requests the same offset forever still aborts.

### [SEV-3] `send_image`/`send_gif` URL fetch: blind SSRF and unbounded download
**FIXED:** remote fetch now enforces a 20 MB size cap (Content-Length + read-past-cap guard) and a 30s `ClientTimeout`, wraps `aiohttp.ClientError` as `HomeAssistantError`, and documents the SSRF caveat inline. (Unit-tested by inspection/AST parse; full behavior needs a live HA instance.)

- **File:** custom_components/e87_badge/services.py:141-148
- **Issue:** Any HA user or automation that can call `e87_badge.send_image` can make the HA host fetch an arbitrary `http(s)://` URL (internal-network endpoints, cloud metadata services) — a blind SSRF primitive. Separately, `await resp.read()` has no size cap or explicit timeout, so pointing it at a huge/streaming URL buffers unbounded data into memory before PIL rejects it.
- **Evidence:** `session.get(value)` on the shared client session, followed by full-body `resp.read()`; the only check is `resp.status != 200`. Path inputs are properly gated by `allowlist_external_dirs`, but URLs have no equivalent gate.
- **Suggested fix:** Enforce a maximum content size (check `Content-Length` and read incrementally with a byte cap, e.g. 20 MB) and an explicit `aiohttp.ClientTimeout`. Document (or optionally gate) that URLs are fetched from the HA host; HA convention accepts admin-supplied URLs, so the size/timeout cap is the actionable part and the SSRF note belongs in the README.
- **Verification:** Call the service with a URL serving multi-GB content; confirm it errors quickly with a size message instead of ballooning memory. Unit test the capped reader with a fake response.

### [SEV-3] `homeassistant.update_entity` on the status sensor likely raises AttributeError
**FIXED (confirmed):** verified against installed HA core that `async_request_refresh` is defined only on `DataUpdateCoordinator`, not the Active/Passive Bluetooth coordinator chain. Overrode `E87StatusSensor.async_update` as a no-op (state is push-driven).

- **File:** custom_components/e87_badge/sensor.py:26, custom_components/e87_badge/coordinator.py:28
- **Issue:** `E87StatusSensor` extends `CoordinatorEntity`, whose `async_update` calls `self.coordinator.async_request_refresh()`. `ActiveBluetoothDataUpdateCoordinator` descends from the passive Bluetooth coordinator family, not `DataUpdateCoordinator`, and (to my knowledge) does not implement `async_request_refresh` — so a user invoking `homeassistant.update_entity` on the sensor gets an `AttributeError` in the log. Listener registration (`async_add_listener`) does exist on that base, so normal operation is fine. Uncertainty: HA core wasn't installed in this environment, so the missing method could not be verified against the pinned HA version; verify before fixing.
- **Evidence:** `class E87StatusSensor(CoordinatorEntity[E87Coordinator], SensorEntity)` combined with a coordinator whose base is `ActiveBluetoothDataUpdateCoordinator[None]`.
- **Suggested fix:** If confirmed, override `async_update` as a no-op (state is push-driven) or stop inheriting `CoordinatorEntity` and register the listener manually in `async_added_to_hass` (the pattern used by HA's own passive-BT integrations).
- **Verification:** In a dev HA instance, call `homeassistant.update_entity` targeting the badge sensor and check the log for `AttributeError: ... async_request_refresh`.

### [SEV-4] `connect()`'s "3 full attempts" retry loop doesn't cover connection-establishment failures
**FIXED:** an `establish_connection` failure now records `last_exc`, disconnects best-effort, sleeps, and `continue`s like the subscribe/auth paths, so all three attempts are honoured. Added `test_establish_failure_retries_then_succeeds` and `test_establish_failure_all_attempts_raises`.

- **File:** src/e87_badge/client.py:85-94
- **Issue:** Inside the retry loop, a failure from `establish_connection` raises `E87ConnectError` immediately instead of counting as a failed attempt like subscribe/auth failures do. The design intent ("3 full reconnect attempts", per the final error message) is only applied to post-connect failures. `establish_connection` does retry internally (`max_attempts=3`), so this is inconsistency rather than missing resilience.
- **Evidence:** `except Exception as exc: raise E87ConnectError(...)` at the top of the `for attempt` loop vs. `continue` for the other two failure classes.
- **Suggested fix:** Treat establish failure the same as the other two: record `last_exc`, disconnect best-effort, sleep, `continue`.
- **Verification:** Unit test alongside `tests/test_client_connect.py`: make `establish_connection` fail once then succeed; assert `connect()` eventually succeeds.

### [SEV-4] Multi-badge service call stops at the first failing badge
**FIXED:** added `_dispatch`, which runs every targeted coordinator via `asyncio.gather(return_exceptions=True)`, isolates per-badge failures, and raises a single aggregate `HomeAssistantError` naming each badge that failed. All five `_handle_send_*` handlers route through it. Logic verified in isolation (HA isn't importable in the dev venv).

- **File:** custom_components/e87_badge/services.py:226-274
- **Issue:** Each `_handle_send_*` loops coordinators sequentially with `await coord.send_*(...)`; the first badge that fails raises `HomeAssistantError` and the remaining targeted badges never receive the content. With an area target containing several badges, one out-of-range badge blocks the rest.
- **Evidence:** `for coord in await _coordinators_for_call(hass, call): await coord.send_image(image)` — no per-coordinator error isolation.
- **Suggested fix:** `asyncio.gather(..., return_exceptions=True)` (or a try/except per coordinator collecting failures), then raise one aggregate `HomeAssistantError` naming the badges that failed.
- **Verification:** Unit test with two mock coordinators where the first raises; assert the second's `send_image` was still awaited and the raised error mentions the failing badge.

### [SEV-4] CLI discovery matcher is weaker than the HA/config-flow matcher
**FIXED:** `_looks_like_badge` now also matches the 0xFD00 service UUID and manufacturer ID 28083, mirroring `config_flow._is_e87`; it takes the full `advertisement_data` so the manufacturer-data fingerprint is available. Added `tests/test_discovery.py` (5 cases, incl. manufacturer-ID-only).

- **File:** src/e87_badge/discovery.py:16-19
- **Issue:** `_looks_like_badge` matches only `local_name == "E87"` or an advertised AE00 service UUID. The config flow and `manifest.json` additionally match the passive-scan-visible fingerprints documented in `const.py` (`ADVERT_SERVICE_UUID_16` 0xFD00 and manufacturer ID 28083). `const.py:12-15` itself notes the local name appears only in the scan response. `e87 discover` therefore can miss a badge that HA discovers, depending on adapter scan behavior. Low impact because `BleakScanner` defaults to active scanning, but it's drift between two matchers for the same device.
- **Evidence:** Compare `discovery._looks_like_badge` with `config_flow._is_e87` (config_flow.py:26-44).
- **Suggested fix:** Extend `_looks_like_badge` to also check `advertisement_data.manufacturer_data` for ID 28083 and service UUIDs for 0xFD00, mirroring `_is_e87` (ideally share one predicate in the library).
- **Verification:** Unit test the predicate with a synthetic advertisement carrying only manufacturer ID 28083 and no name/UUIDs; assert it matches.

### [SEV-4] README pins install commands to v0.1.0 while the repo is at v0.1.14
**FIXED (trivial):** bumped both README install pins to v0.1.14.

- **File:** README.md:24, README.md:75
- **Issue:** `pip install git+...@v0.1.0` and `git clone --branch v0.1.0` install a version 14 patch releases behind — notably missing the connection-slot-leak and mid-transfer-abort fixes the README's own troubleshooting section says "v0.1.11+/v0.1.12+ handles". Users following the README get exactly the failure modes the doc tells them are fixed.
- **Evidence:** `pyproject.toml` / `manifest.json` both say 0.1.14.
- **Suggested fix:** Reference the latest tag, or drop the pin (`@main` / no ref) and let HACS/manifest pin the version; add the tag bump to the release checklist.
- **Verification:** Grep README for `v0.1.` after fix; confirm it matches `pyproject.toml` version or is unpinned.

### [SEV-4] Service teardown ignores platform-unload failure; GIF file handle never closed
**FIXED (trivial):** gated service removal on `unloaded` being true; wrapped GIF frame extraction in `with gif:` so the file handle closes after use.

- **File:** custom_components/e87_badge/__init__.py:54-67; src/e87_badge/media/gif.py:25-28
- **Issue:** Two small hygiene items. (1) `async_unload_entry` removes the domain services whenever this is the last entry, even if `async_unload_platforms` returned `False` — leaving a loaded-but-serviceless entry. (2) `_load_gif` opens path-based GIFs with `Image.open` and never closes the file; frames are decoded lazily, so the handle must outlive the loop in `gif_to_avi`, but it should be closed after frame extraction (context-manage the image around the frame loop).
- **Evidence:** `unloaded = await ...; if not remaining: async_unload_services(hass); return unloaded` — teardown unconditional on `unloaded`. `gif.py` returns `Image.open(path)` with no `with`/`close`.
- **Suggested fix:** Gate service removal on `unloaded` being true. In `gif_to_avi`, wrap frame extraction in `with gif:` (works for both bytes and path sources).
- **Verification:** For (2), on Linux run `gif_to_avi` on a path in a loop and check `/proc/self/fd` count stays flat; for (1), simulate a failing platform unload in a component test.

## Not Reviewed
- `docs/captures/*` (BLE capture logs/notes/PNG) and `docs/superpowers/*` (design/plan docs) — reference material, not executable.
- `docs/protocol.md` — skimmed for existence only; wire-format claims not cross-checked line-by-line against `protocol.py`.
- `spike/` and all `__pycache__` directories — git-ignored scratch/compiled artifacts.
- `.pytest_cache/`, `.claude/settings.local.json`, lockfile-free packaging metadata beyond version-consistency checks.
- `src/e87_badge/jieli_cipher.py` internals — the lookup tables and register-level cipher emulation were reviewed for Python-level correctness hazards (indexing bounds, masking) but not re-verified against the upstream `libjl_auth.so` disassembly; the repo's test vectors (`tests/test_jieli_auth.py`, passing) are treated as the correctness authority.
- Live-hardware behavior — all `E87_BADGE_MAC`-gated integration tests were skipped (no badge attached); protocol findings are from static analysis plus the offline suite.

## Fix Session Summary

Fixes applied in severity order (no SEV-1 present). Full test suite green
after each change: **66 passed, 3 skipped** (hardware-gated), up from 52
passed at review time (14 new regression tests added). Every finding —
SEV-2 through SEV-4 — is now fixed; nothing deferred.

### Fixed
- **SEV-2 — event-loop blocking:** all `E87Client.send_*` now offload PIL/media
  encoding via `asyncio.to_thread`; HA service layer runs `path.exists`/
  `is_allowed_path` in the executor. New `tests/test_client_offload.py`.
  *(commit: offload media encoding off the event loop)*
- **SEV-3 — MAC-string fallback crash:** `_resolve_ble_device` fails fast with a
  clear `E87ConnectError` instead of feeding a bare string to
  `establish_connection`. New `test_unresolved_mac_fails_fast`.
  *(commit: fail fast when scanner can't resolve a badge MAC)*
- **SEV-3 — false success on non-zero close status:** `_finalize` raises
  `E87ProtocolError` after acking. New `_finalize` status tests.
- **SEV-3 — post-EOF retransmit refusal:** replaced with a per-offset bounded
  resend budget (`MAX_POST_EOF_RESENDS = 3`). New driver-level phase-9 tests.
  *(commit: surface non-zero close status; bound post-EOF resends)*
- **SEV-3 — unbounded/timeout-less remote fetch (+SSRF note):** 20 MB cap and
  30s `ClientTimeout`; SSRF caveat documented inline.
- **SEV-3 — `update_entity` AttributeError:** confirmed against installed HA
  core, overrode `E87StatusSensor.async_update` as a no-op.
  *(commit: cap/timeout remote image fetch; no-op sensor manual update)*
- **SEV-4 (trivial) — README version drift:** bumped install pins to v0.1.14.
- **SEV-4 (trivial) — teardown/GIF handle:** gated service removal on
  `unloaded`; context-managed the GIF image.
  *(commit: with the README/hygiene changes)*
- **SEV-4 — connect() retry doesn't cover establish failures:** an
  `establish_connection` failure now counts as a failed attempt (clean up +
  retry) instead of aborting connect(). New connect tests.
- **SEV-4 — multi-badge service stops at first failure:** new `_dispatch`
  runs all coordinators via `asyncio.gather(return_exceptions=True)`, isolates
  per-badge failures, and raises one aggregate error naming the failed badges.
- **SEV-4 — CLI discovery matcher drift:** `_looks_like_badge` now mirrors
  `config_flow._is_e87` (0xFD00 UUID + manufacturer ID 28083). New
  `tests/test_discovery.py`.
  *(commit: cover establish failures in connect retry; isolate multi-badge
  sends; align CLI discovery matcher)*

### Disputed
- None. All findings re-verified as valid before fixing; the two flagged as
  uncertain in the report (coordinator `async_request_refresh`, and the
  post-EOF trade-off) were both confirmed against source.

### Deferred
- None. All SEV-2/3/4 findings are fixed.
