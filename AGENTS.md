# PROJECT KNOWLEDGE BASE

**Audited:** 2026-07-13

**Snapshot:** branch `feature/optimization-roadmap`, commit `96b01c1`

**Tests:** `python -m pytest --collect-only -q` → **651 collected** (2026-07-13). The full OCR/fixture suite can take more than 3 minutes on this machine; never replace this count with a guessed “passed” number.

## OVERVIEW

Windows-only Python 3.11+ automation bot for Roblox REX. It mines, maintains D5 boost, rerolls/keeps D4 events, detects rare-ore chill audio, sweeps/aims/fires D3, verifies success from chat, exposes Discord controls, and handles mine reset through manual, Discord-remote, or experimental automatic re-entry.

The architecture is still state-machine driven, but this is no longer the small 2026-06 prototype. `miningbot/main.py` is a ~4,200-line I/O orchestrator with background workers and multiple bounded subflows. Do not infer current behavior from old line numbers, old test counts, or the frozen June plans.

## SOURCE OF TRUTH

When sources disagree, use this order:

1. Current code + tests + `miningbot/config.py` defaults.
2. `CLAUDE.md` hard-won runtime rules and `docs/incidents.md` evidence.
3. The newest relevant design/spec **plus its implementing commits/tests**. A plan checkbox alone is not proof that code shipped.
4. `docs/game-mechanics.md` for game-domain facts and `docs/manual-sampling.md` for R-key calibration.
5. `docs/HANDOFF.md`, `docs/HANDOFF_false_positives.md`, and older `docs/superpowers/*` as historical context only.

Known documentation drift as of this audit:

- `docs/HANDOFF.md` still says branch `main`, 133/401 tests, recommends shrinking tracker ROI to 80, calls vertical sweep/world support missing, and omits the shipped remote-aim/remote-reentry flows. Current code/CLAUDE says ROI 320, pitch layers shipped, nine-world data shipped, and `reentry_mode` defaults to `remote`.
- `docs/HANDOFF_false_positives.md` is a 2026-06-29 investigation, not the current detector specification.
- `CLAUDE.md` is current in its long hard-rule section, but its opening sentence/module summary still describes manual-only reset handling and the old small pure-module set. Read the later REENTRY/remote sections before using that summary.
- `README.md`, `.env.example`, and `assets/README.md` still use “Phase 2”/early-template language and omit current startup, remote control, re-entry, RapidOCR, and tracked JSON datasets.
- A few source docstrings are historical: `notify.py` still advertises removed `send_image_message`, and `states.update_capacity_streak` still calls capacity a reset “second signal” even though its caller now uses it only for acceleration/logging.
- `requirements.txt` still pins `keyboard`, but runtime hotkeys intentionally use `GetAsyncKeyState`; do not reintroduce the `keyboard` library without a new real-game validation.

## STRUCTURE

```text
miningbot/                  importable package (32 Python modules)
  main.py                   Bot orchestration, all runtime state/subflows
  config.py                 Config/Region and DEFAULT; coordinates/thresholds/modes
  states.py                 top-level FSM and small state-policy functions
  harvester.py              harvest decisions, pitch/sweep/verify/give-up plans
  vision.py / ocr.py        detector and OCR logic + engine adapters
  audio.py                  chill scoring, edge/spike detection, loopback capture
  game_data.py              9-world events/ores/classification/keep-list formatting
  reentry*.py               automatic and Discord-remote re-entry pure logic
  remote_aim.py             Discord-assisted harvest targeting/alignment
  roblox_menu.py            menu OCR decisions
  sampler.py                R-key manual calibration UI and sample writing
  notify.py                 Discord HTTP API, embeds, reactions, grouped images
  diagnostics.py            split logging, snapshots, retention
  preflight.py              pure startup warning policy
  __main__.py               splash entrypoint used by pythonw/batch launcher
tests/                      651 collected tests; synthetic + tracked real fixtures
assets/                     tracked JSON datasets + local/gitignored machine assets
docs/                       incidents, mechanics, manual, specs/plans, stale handoffs
logs/                       gitignored runtime evidence and diagnostic scripts
*.mcr                       original human-recorded Roblox macro sequences
啟動挖礦bot.bat             pythonw -m miningbot (preferred no-console launcher)
```

`assets/ores_all.json`, `assets/rare_ores.json`, and `assets/README.md` are tracked. Most PNG/WAV runtime assets are ignored even when present locally. Never assume an asset visible on this machine will exist in a fresh checkout.

## WHERE TO LOOK

| Task | Read first | Then inspect |
|---|---|---|
| Runtime lifecycle/startup | `CLAUDE.md`, `main.Bot.run` | `Bot._on_enter`, `_tick`, `_focus_roblox`, `miningbot/__main__.py` |
| Top-level state behavior | `states.py` + `tests/test_states.py` | `main.observe`, `resolve_state_transition`, direct `self.state =` sites |
| Coordinates/thresholds/modes/hotkeys | `config.py` | fixture tests that bracket the value; relevant H incident |
| Rare-ore harvesting | CLAUDE harvest section + latest H incidents | `main._sweep_for_tracker`, `_tick_harvest`, `_harvest_success`; `harvester.py` |
| Tracker detection | H039/H040 + `tests/test_vision.py` | `vision.find_tracker`, `find_tracker_near`; real crops in local `assets/markers/` |
| Chat verification/OCR | H014/H020/H032/H041 | `ocr.ChatLedger`, `read_text_multi`, `_verify_chat_ocr`; OCR fixture tests |
| Chill/reset audio | CLAUDE audio/reset sections | `audio.py`, `main._on_audio_*`, `tests/test_audio.py` |
| Mine reset | 2026-07-12 capacity addendum | `states.py`, `main._banner_ocr_loop`, `_update_reset_complete` |
| Re-entry | latest remote-reentry/reentry-zoom specs | `reentry.py`, `reentry_remote.py`, `main._tick_reentry*`, config `reentry_*` |
| Discord remote aim | latest remote-aim spec | `remote_aim.py`, `main._handle_aim_reply`, `_tick_remote_aim` |
| Discord commands/control panel | `main._poll_discord`, `_handle_discord_command` | `notify.py`, `tests/test_notify.py` |
| D4/world/ore data | `game_data.py` | `fetch_ores.py`, tracked JSON datasets, `test_game_data.py` |
| Startup UI/menu checks | CLAUDE startup section | `roblox_menu.py`, `main._ensure_*`, `preflight.py` |
| R-key calibration | `docs/manual-sampling.md` | `sampler.py`, `calibrate_surface.py`, `status_hud.py` |
| Logs/snapshots | CLAUDE “實機排錯” | `diagnostics.py`, `logs/preflight_alerts.md`, categorized snapshots |

See `miningbot/AGENTS.md` for the current package map and `tests/AGENTS.md` for test rules.

## NON-NEGOTIABLE RUNTIME RULES

These are condensed guardrails; read CLAUDE/incidents before changing the related code.

1. Use `SW_MAXIMIZE`, never `SW_RESTORE`; call DPI awareness before the first screenshot/GUI.
2. Runtime coordinates are calibrated for a maximized 1920×1080 capture with the Windows taskbar visible. The taskbar shift invalidated several old y-coordinates; calibrate from real frames instead of “fixing” them by eye.
3. Tool keys toggle equipment. Never press D1 blindly. Current D1 detection is `vision.slot_selected` over `d1_slot_region`; the old `slot_pixel/slot_color` is retained only for calibration history.
4. Camera yaw uses `,`/`.` and must go through verified rotation. Fine pitch/aim uses right-button drag with settle and frame-diff validation. Plain `moveRel` does not rotate REX.
5. D3 is always `2 → 0.15s → 3 → 0.3s → hold-click 0.4s → 0.5s`; a tap or repeated bare `3` is unsafe because equipment toggles.
6. Harvest success requires new rare/special chat evidence. Tracker disappearance alone means RESWEEP, not success. Preserve episode `ChatLedger` and late-confirm paths.
7. Capacity reaching 100% must **never** enter `RESET_WAIT`; only the reset banner can stop mining. Capacity only accelerates banner polling and emits a one-time informational log.
8. Tracker color masks stay per-range; center-color confirmation is hue-independent. Real in-game crops, not wiki alpha icons, are shape templates. The shape ROI is currently 320 because real frames reach 207×208 px. Full-frame shape matching is prohibited in the sweep.
9. Discord polling/background workers may set pending flags or caches; game input is consumed on the main loop. Never send game input directly from the polling thread.
10. Tk widgets must not contain astral emoji (`> U+FFFF`) on this Tcl/Tk 8.6 machine; it can silently freeze the event loop. Use `_bmp_safe` and BMP symbols.
11. Global hotkeys are `GetAsyncKeyState`: Ctrl+Q pause-only, Q pause/resume/clear/skip startup, F12 quit, R sampler. Do not use the `keyboard` library. Never press Esc during manual game driving.
12. `reentry_mode` is a three-way switch: `off`, `remote`, `auto`. `remote` is the current default; `auto` is gated by calibrated surface templates. Preserve bounded failure → `NEEDS_HUMAN` behavior and restore pitch/zoom before finalizing.

## DEVELOPMENT WORKFLOW

- Start every task with `git status --short` and inspect overlapping user changes. The local `.claude/` directory is currently untracked user/tool state; do not add, delete, or normalize it unless explicitly asked.
- Use symbol search (`rg`) rather than stale line numbers. `main.py` changes rapidly.
- Pure decisions should be extracted and tested first. I/O shells can be tested with injected callables or narrowly scoped `monkeypatch`; real devices/game/network are never required for the default suite.
- Visual/OCR threshold changes require real fixtures and a two-sided bracket: true positive still passes and the relevant negative still rejects. Cite the H incident in the regression test.
- All coordinates and thresholds belong in `Config`; do not add hardcoded runtime coordinates in call sites.
- Preserve Chinese calibration comments: they are provenance, not decoration.
- Do not commit, switch branches, push, delete runtime evidence, or mutate Roblox/Discord unless the user asks. When a commit is requested, first follow the branch/co-author conventions currently documented in `CLAUDE.md`.
- `CLAUDE.md` currently asks that nontrivial code implementation be delegated through `opencode run`, with the primary agent owning specification, diff review, and verification. Treat that as active until the user explicitly retires it; docs/assets and one-line config tuning are listed exceptions.

## COMMANDS

```powershell
# exact suite inventory (fastest reliable documentation check)
python -m pytest --collect-only -q

# complete suite; OCR/real-fixture tests can take several minutes
python -m pytest -q

# normal console run
python -m miningbot.main

# preferred splash/no-console route used by 啟動挖礦bot.bat
pythonw -m miningbot

# asset/data/calibration tools
python -m miningbot.convert_audio chill.mp3
python -m miningbot.add_chill_ref --scan
python -m miningbot.fetch_trackers
python -m miningbot.fetch_ores
python -m miningbot.capture_template boost
python -m miningbot.calibrate
python -m miningbot.calibrate_surface --import NNN
```

On this managed Windows workspace, sandboxed `python.exe` may fail with “系統無法存取該檔案”; that is an execution-permission failure, not a pytest failure. Re-run through the approved Python/pytest path before diagnosing project code. PowerShell/OneDrive startup can also take 10–15 seconds, so give read-only inventory commands a realistic timeout.

## CURRENT RISK AREAS

- `main.py` is the dominant complexity hotspot and still has several intentional direct state assignments outside the central commit path. Search all `self.state =` sites when adding/changing a state.
- Remote aim/re-entry and zoom are new (2026-07-12) and need more live-game evidence than their pure tests provide.
- `scan_confirm_mode` is `off` and its region is not calibrated for the taskbar-visible layout; do not enable enforcement by assumption.
- Machine-local PNG/WAV assets are necessary for best runtime behavior but mostly absent from git. Preflight warnings and `assets/README.md` must be checked on a fresh machine.
- `docs/HANDOFF.md` §9 is actively dangerous as a current backlog; H040 and later code reverse several recommendations there.
