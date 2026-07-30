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

### Web UI layer (`web_*.py`)

| Module | Responsibility |
|---|---|
| `web_protocol.py` | `WebMessage` dataclass, `serialize/parse_message`, `parse_fire_at/reentry_click_payload` (thin validators), `client_to_native_coords` (P1 pure math, kept for reference) |
| `web_ipc.py` | `routing_key`, `PendingReplies` (first-wins), `FallbackState` (grace period) |
| `web_server.py` | `create_app` (FastAPI + WS endpoint + HTTP routes), `WebIPCThread` (uvicorn daemon), `ConnectionRegistry` (cross-thread broadcast) |
| `web_sink.py` | `WebEventSink` (EventLog → WS broadcast); parallel to `notify.make_discord_sink` |
| `web_config_whitelist.py` | `WEB_CONFIGURABLE_FIELDS` (4 fields), `is_web_configurable`, `validate_value` |
| `web_config_persistence.py` | `load/save/apply_overrides_to_config` (atomic JSON write; idempotent on restart) |
| `web_static.py` | `render_index_html` (settings), `render_intervention_html` (pinch-zoom + tap), `render_history_html`, `render_annotate_html` (single or tier queue), `render_failures_html` / `render_stats_html` (agent-facing: ugly layout, complete data) |
| `web_annotation.py` | `build_annotation`, `normalize_symptom`, `symptom_from_observation` (player states what he sees; symptom is derived), `rarity_choices_from_game_data`, `validate_annotation`, `verdict_agrees` + `NO_LABEL` sentinel |
| `web_history.py` | `load_episodes`, `load_episode_detail`, `list_annotations_for_episode` (recursive `os.walk`), `annotation_tier` / `build_queue` (multi-tier queue), `label_verdict` (bot's live accept/reject + coords, parsed from the snapshot label), `aggregate_labels` (`written_at` only, never directory mtime), `verdict_category` |

Design spec: `docs/superpowers/specs/2026-07-26-web-ui-design.md`. Commit
history: `docs/superpowers/plans/2026-07-26-web-ui-p[1-5]-*.md`.

Runnable tools include `main.py`, `__main__.py`, `convert_audio.py`,
`add_chill_ref.py`, `capture_template.py`, `calibrate*.py`, `fetch_ores.py`,
`fetch_trackers.py`, and `build_reentry_dataset.py` (offline; never imports `main`).

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
- Web UI: `_web_pending`, `_web_fallback`, `_web_thread`, `_consume_web_pending`,
  `_execute_remote_fire_from_web`, `_rr_click_from_web`, `_reentry_await_player_click`,
  `_send_web_intervention_event`, `_await_web_pointer_reply`, `_save_auto_fixture`,
  `_resolve_ping_if_any`, `_send_needs_human_ping`, `_handle_web_aim_click`,
  `_push_web_aim_candidates`.
- Web 遙控器鏡射（2026-07-28，跟 Discord ▶️⏸️⚡📷🏠 對應）：`_status_snapshot`,
  `_player_state_snapshot`, `_broadcast_status`, `_broadcast_status_note`,
  `_broadcast_frame_snapshot`；`_consume_web_pending` 內對應
  `control:pause/resume/ability/reenter/request_frame/request_status/
  radar_toggle/keep_add/keep_remove/keep_clear` 分支。

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
- `WebIPCThread` runs uvicorn on a daemon thread; broadcast calls go through
  `asyncio.run_coroutine_threadsafe` and must never block the main loop. The
  `web_pending` queue is consumed only at safe points in `_tick`, never from
  inside a state handler.

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
11. Web UI surfaces only `WEB_CONFIGURABLE_FIELDS` to players; never expose
    thresholds, ROI, detection params, or secrets through HTTP routes. Player
    taps compute native coords client-side; the server is a thin validator.
    Auto-collected fixtures are best-effort and must not raise into the main
    loop on write failure.

## CHANGE CHECKLIST

- State: test `states.py` policies first, then review all orchestration consumers.
- Tracker: run synthetic plus relevant H fixtures and both TP/negative brackets.
- OCR: preserve per-pass self-consistency, engine fallbacks, diagnostics, and H041.
- Re-entry/remote: test parser/geometry/ledger modules, main-loop consumption,
  interruption, and camera restoration.
- Input macro: compare root `.mcr` recordings and preserve release/settle order.
- UI text: pass through BMP-safe constraints; no astral emoji in Tk.
- Web UI: pure-function tests cover wire protocol, race routing, whitelist,
  persistence, history/annotation loaders, and HTML renderers; integration
  tests exercise TestClient through `WebIPCThread.app`. Real pinch-zoom + tap
  behavior is live-game validation, not a unit-test gate.

## KNOWN HOTSPOTS

- Prefer extracting pure decisions from `main.py` instead of adding another inline
  orchestration branch.
- Treat `game_data.py` as static/generated domain data; use `fetch_ores.py` and
  conflict tests rather than casual bulk edits.
- Automatic re-entry remains calibration gated.
- `scan_confirm_region` now holds the whole bottom-right effect row; badge slots shift
  as buffs stack, so locate them with `vision.find_effect_slots` and OCR per slot —
  never hardcode a single slot, and never OCR the whole strip at once.
