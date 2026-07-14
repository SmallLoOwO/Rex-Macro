# miningbot/ — PACKAGE GUIDE

Read `../AGENTS.md` first for source priority and hard runtime rules. Read `../CLAUDE.md` and the matching H incident before changing calibrated behavior.

## CURRENT SHAPE

The package contains 32 Python modules. `main.py` is a ~4,200-line I/O orchestrator; the useful boundary is no longer “six pure modules versus six untested wrappers.” Many modules deliberately combine pure helpers with hardware adapters, and tests now cover pure helpers, real image/OCR fixtures, and a few injected I/O wrappers.

### Runtime core

| Module | Responsibility |
|---|---|
| `main.py` | `Bot`, startup/preflight, workers, FSM commit, mining/harvest/re-entry/remote subflows, Discord dispatch, snapshot orchestration |
| `config.py` | `Region`, `Config`, `DEFAULT`; every coordinate, threshold, interval, hotkey, mode, and secret input |
| `states.py` | `State`, `Observation`, top-level transition/commit/pause/capacity/ability policies |
| `miner.py` | mining event priority and D1/D4/D5/scan/cave input sequences |
| `harvester.py` | harvest state/value objects and pure sweep/pitch/verify/give-up/post-success decisions; thin D2/D3 wrappers |
| `geometry.py` | marker aim decision |

### Detection and data

| Module | Responsibility |
|---|---|
| `vision.py` | template/edge/color/frame-diff helpers, tracker detection and near-ROI re-find |
| `ocr.py` | text normalization/diff/fuzzy classification, `ChatLedger`, tesserocr/pytesseract/RapidOCR adapters |
| `audio.py` | correlation scoring, rising/spike detectors, reset-chime recorder, chill listener, WASAPI capture |
| `game_data.py` | nine-world event/ore registries, world detection, keep-list matching, rare/common classification |
| `fetch_ores.py` | MediaWiki ore synchronization and conflict/advisory reports |
| `fetch_trackers.py` | wiki tracker download; these icons are not sufficient as runtime real-crop shape templates |

### Re-entry and remote control

| Module | Responsibility |
|---|---|
| `reentry.py` | automatic re-entry decisions (panel direction, movement, occlusion ladder, layer button) |
| `reentry_remote.py` | remote-reentry reply parsing, grid geometry, zoom plan, episode/click ledger records |
| `remote_aim.py` | harvest candidate ranking/overlay, reply parsing, yaw/pitch alignment plan |
| `roblox_menu.py` | menu OCR record matching and Movement Mode decisions |
| `notify.py` | Discord REST calls: text, grouped multi-image messages, embeds, reactions, edit/delete, async sink |

### Platform/UI/operations

| Module | Responsibility |
|---|---|
| `capture.py` | per-thread cached `mss` capture and crop |
| `input_control.py` | `pydirectinput`/Win32 key, mouse, wheel, yaw, pitch primitives |
| `window.py` | Win32 window query plus pure displacement verdict |
| `status_hud.py` | topmost Tk HUD and BMP-safe text |
| `sampler.py` | R-key sampling window/panel, snapshot + pitch sidecar writing |
| `diagnostics.py` | split loggers, categorized snapshots, retention cleanup |
| `events.py` | structured event records and sink fan-out |
| `preflight.py` | pure startup warning policy |

### Entrypoints/tools

`__main__.py` (splash/pythonw), `main.py`, `convert_audio.py`, `add_chill_ref.py`, `capture_template.py`, `calibrate.py`, `calibrate_surface.py`, `fetch_ores.py`, and `fetch_trackers.py` are runnable modules.

## MAIN.PY NAVIGATION

Do not use hardcoded line numbers. Search these symbols:

- Startup/lifecycle: `Bot.__init__`, `run`, `_collect_preflight_facts`, `_run_preflight`, `_focus_roblox`, `_ensure_chat_open`, `_ensure_player_list_closed`.
- Workers: `_hotkey_loop`, `_discord_poll_loop`, `_banner_ocr_loop`, `_snapshot_worker`, audio callbacks.
- FSM: `observe`, `_update_reset_complete`, `_on_enter`, `_tick`; also search every `self.state =` because recovery paths write state directly.
- Mining: `_tick_mining`, `_boost_needs_refresh`, `_activity_ready`.
- Harvest: `_harvest_boost_guard`, `_find_tracker*`, `_rotate_verified`, `_sweep_for_tracker`, `_tick_harvest`, `_harvest_success`, `_late_chat_confirm`, `_harvest_giveup`.
- Remote harvest: `_handle_aim_reply`, `_tick_remote_aim`, `_execute_remote_fire`.
- Re-entry: `_tick_reentry`, `_tick_reentry_remote`, all `_rr_*`, `_zoom_*`, `_pitch_*` helpers.
- Discord: `_poll_discord`, `_handle_discord_command`, remote-control embed/reaction helpers.
- Sampling/HUD: `_toggle_sampler`, `sync_sampler_ui`, `_sampler_*`.

## DEPENDENCY AND THREADING RULES

- `Bot` owns mutable runtime state. Background threads publish caches/pending commands; the main loop owns game input and stateful action sequences.
- `config.DEFAULT` is broadly imported. A field change must update callers, config-focused tests, docs/comments, and any serialized/manual calibration assumptions.
- `capture` and tesserocr instances are thread-local because their underlying objects are not thread-safe.
- Discord/network sends can block and belong behind the async sink or poller; never block the 50 ms target loop with HTTP.
- Snapshot encoding/writing is queued. Do not put synchronous full-frame `cv2.imwrite` back into aim→fire hot paths.
- RapidOCR is preferred for chat; tesserocr is preferred for small banner/menu reads; pytesseract is a fallback. Preserve lazy/failure-tolerant engine initialization.
- Optional assets must degrade with explicit preflight/log warnings, not silent behavior changes.

## INVARIANTS

1. All runtime coordinates/thresholds/modes remain in `Config`.
2. Preserve verified input timing and settle calls. Roblox eats early inputs without raising errors.
3. Preserve the “background thread writes intent, main thread performs input” boundary.
4. Preserve `resolve_state_transition`; adding a state also requires reviewing direct assignments and `_on_enter` downgrade behavior.
5. Tracker shape confirmation runs in candidate ROIs only. Keep per-HSV-range accounting, hue-independent center confirmation, reference-frame rejection, real-crop templates, and the 320 px ROI constraint.
6. Chat verification is episode-aware and conservative. Never collapse it to a single `contains` or a single before/after count.
7. `miner.init_mining_sequence()` is the canonical mining resume path. The removed `resume_mining` shortcut must not return.
8. `notify.py` no longer exposes the old `send_image_message`; use `send_images_message`/async sink patterns.
9. Capacity saturation is not a state transition trigger.
10. `reentry_mode` remote/auto paths are bounded, ledgered, and must restore camera pitch/zoom on finalize or abort.

## COMMON CHANGE CHECKLIST

- State change: `states.py` tests first; review `observe`, `_on_enter`, `_tick`, all direct assignments, pause/resume/Discord behavior.
- Tracker change: run synthetic and H fixture tests; measure TP and known equipment/UI negatives; read H039/H040.
- OCR change: run `test_ocr.py` and real fixture files; preserve per-pass self-consistency, RapidOCR fallback, diagnostics, H041 hyphen handling.
- Re-entry/remote change: test parser/geometry/ledger pure modules; then review main-loop consumption, reset interruption, anti-AFK, pitch/zoom restoration.
- Input macro change: compare root `.mcr` recordings and preserve release/settle ordering.
- UI text change: pass through BMP-safe constraints; no astral emoji in Tk.

## KNOWN HOTSPOTS

- `main.py` has too many responsibilities. Prefer extracting pure decisions/value objects into the relevant module instead of adding another long inline branch.
- `game_data.py` is large generated/static domain data. Use `fetch_ores.py` and conflict tests rather than hand-editing bulk ore tables casually.
- Automatic re-entry remains calibration-gated; remote re-entry is the current default and newest path.
- `scan_confirm_region` is not calibrated for the taskbar-visible layout while `scan_confirm_mode` is off.
