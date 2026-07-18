# miningbot/ — PACKAGE GUIDE

Read `../AGENTS.md` first. This file only describes package ownership and local
change rules; repository-wide behavior belongs in the root contract.

## MODULE OWNERSHIP

### Runtime core

| Module | Responsibility |
|---|---|
| `main.py` | `Bot`, startup, workers, FSM commit, mining/harvest/re-entry/remote subflows, Discord dispatch |
| `config.py` | `Region`, `Config`, `DEFAULT`; coordinates, thresholds, intervals, hotkeys, modes, secrets |
| `states.py` | top-level transition, commit, pause, capacity, and ability policies |
| `miner.py` | mining priority and D1/D4/D5/scan/cave sequences |
| `harvester.py` | sweep/pitch/verify/give-up/post-success decisions and thin D2/D3 wrappers |
| `geometry.py` | marker aim decisions |

### Detection and data

| Module | Responsibility |
|---|---|
| `vision.py` | template/edge/color/frame-diff helpers and tracker detection |
| `ocr.py` | text normalization/diff/fuzzy classification, `ChatLedger`, OCR adapters |
| `audio.py` | correlation, edge/spike detection, reset recorder, chill listener, WASAPI capture |
| `game_data.py` | active-world events/ores, world detection, keep matching, classification |
| `fetch_ores.py` | MediaWiki synchronization and conflict reports |
| `fetch_trackers.py` | wiki icon download; icons are not runtime real-crop templates |

### Re-entry, remote control, and operations

| Module | Responsibility |
|---|---|
| `reentry.py` | automatic re-entry decisions |
| `reentry_remote.py` | reply parsing, grid geometry, zoom plan, episode/click ledger records |
| `remote_aim.py` | candidate ranking, reply parsing, yaw/pitch alignment |
| `roblox_menu.py` | menu OCR and Movement Mode decisions |
| `notify.py` | Discord REST and async notification sink |
| `discord_commands.py` | pure Discord command whitelist/parser |
| `capture.py` | per-thread cached capture and crop |
| `input_control.py` | Win32/pydirectinput key, mouse, wheel, yaw, pitch primitives |
| `window.py` | Win32 window query and displacement verdict |
| `status_hud.py` | topmost Tk HUD and BMP-safe text |
| `sampler.py` | numbered manual-sample files and pitch sidecars (UI retired; capture via remote-control 📷) |
| `diagnostics.py` | split loggers, snapshots, retention |
| `metrics.py` | bounded latency samples and percentile summaries |
| `events.py` | structured events and sink fan-out |
| `preflight.py` | pure startup warning policy |

Runnable tools include `main.py`, `__main__.py`, `convert_audio.py`,
`add_chill_ref.py`, `capture_template.py`, `calibrate*.py`, `fetch_ores.py`, and
`fetch_trackers.py`.

## MAIN.PY NAVIGATION

Search symbols instead of line numbers:

- Startup: `Bot.__init__`, `run`, `_collect_preflight_facts`, `_run_preflight`,
  `_focus_roblox`, `_ensure_chat_open`, `_ensure_player_list_closed`.
- Workers: `_hotkey_loop`, `_discord_poll_loop`, `_banner_ocr_loop`,
  `_snapshot_worker`, audio callbacks.
- FSM: `observe`, `_update_reset_complete`, `_on_enter`, `_tick`, and every
  `self.state =` assignment.
- Harvest: `_find_tracker*`, `_rotate_verified`, `_sweep_for_tracker`,
  `_tick_harvest`, `_harvest_success`, `_late_chat_confirm`, `_harvest_giveup`.
- Remote/re-entry: `_handle_aim_reply`, `_tick_remote_aim`, `_tick_reentry*`, and
  `_rr_*`/`_zoom_*`/`_pitch_*` helpers.
- Sampling/HUD: `_sampler_pitch_prepare`, remote-control 📷 branch in
  `_poll_remote_reactions` (the R-key Tk sampler window is retired).

## DEPENDENCY AND THREADING RULES

- `Bot` owns mutable runtime state. Workers publish caches/pending commands; the
  main loop owns game input and stateful action sequences.
- A `Config` field change must update callers, focused tests, and any calibration
  assumptions. Do not copy defaults into guidance prose.
- Capture and OCR engine instances are thread-local where their libraries are not
  thread-safe.
- Discord/network sends belong behind the async sink or poller; never block the main
  loop with HTTP.
- Snapshot encoding/writing is queued; do not restore synchronous full-frame writes
  to aim/fire paths.
- RapidOCR is preferred for chat, tesserocr for small banner/menu reads, and the
  tested fallback paths remain failure-tolerant.
- Optional assets must produce explicit preflight/log warnings rather than silent
  behavior changes.

## INVARIANTS

1. Runtime coordinates, thresholds, intervals, and modes stay in `Config`.
2. Preserve verified input timing and settle calls; Roblox can eat early input.
3. Preserve the worker-intent/main-thread-input boundary.
4. State changes require reviewing `resolve_state_transition`, direct assignments,
   `_on_enter`, pause/resume, and Discord behavior.
5. Tracker shape confirmation runs only in candidate ROIs and retains per-range HSV,
   hue-independent center confirmation, reference rejection, and real-crop templates.
6. Chat verification remains episode-aware and conservative.
7. `miner.init_mining_sequence()` remains the mining resume path.
8. Capacity saturation is not a state transition trigger.
9. Remote/automatic re-entry stays bounded and restores camera pitch/zoom on every
   finalize or abort path.
10. Tk UI text remains BMP-safe.

## CHANGE CHECKLIST

- State: test `states.py` policies first, then review all orchestration consumers.
- Tracker: run synthetic plus relevant H fixtures and both TP/negative brackets.
- OCR: preserve per-pass self-consistency, engine fallbacks, diagnostics, and H041.
- Re-entry/remote: test parser/geometry/ledger modules, main-loop consumption,
  interruption, and camera restoration.
- Input macro: compare root `.mcr` recordings and preserve release/settle order.
- UI text: pass through BMP-safe constraints; no astral emoji in Tk.

## KNOWN HOTSPOTS

- Prefer extracting pure decisions from `main.py` instead of adding another inline
  orchestration branch.
- Treat `game_data.py` as static/generated domain data; use `fetch_ores.py` and
  conflict tests rather than casual bulk edits.
- Automatic re-entry remains calibration gated.
- `scan_confirm_region` is not calibrated while `scan_confirm_mode` is off.
