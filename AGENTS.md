# PROJECT KNOWLEDGE BASE

This is the repository-wide operating contract. Keep it current and focused on
decisions that are unsafe to rediscover. Volatile inventories such as test totals,
file lengths, and ore counts belong in command output, not guidance.

## OVERVIEW

Windows-only Python 3.11+ automation bot for Roblox REX. It mines, maintains D5
boost, rerolls or keeps D4 events, detects rare-ore chill audio, aims and fires D3,
verifies success from chat, exposes Discord controls, and handles mine reset through
manual, remote, or calibration-gated automatic re-entry.

`miningbot/main.py` is the I/O orchestrator around a state machine and bounded
subflows. Search current symbols; do not rely on historical line numbers, test
counts, or completed plan checkboxes.

## SOURCE OF TRUTH

When sources disagree, use this order:

1. Current code, tests, and `miningbot/config.py` defaults.
2. The non-negotiable rules here plus evidence in `docs/incidents.md`.
3. Current references: `docs/game-mechanics.md`, `docs/manual-sampling.md`, and
   `assets/README.md`.
4. A design or plan only when implementing tests/code confirm it shipped.
5. `docs/HANDOFF*.md`, `docs/superpowers/**`, and the retired delegation manual as
   historical context only. See `docs/README.md`.

`CLAUDE.md` is a thin compatibility entrypoint to this contract, not another copy
of runtime truth.

## STRUCTURE

```text
miningbot/
  main.py                   Bot orchestration and runtime state
  config.py                 Config/Region and DEFAULT
  states.py                 top-level FSM and transition policies
  harvester.py              harvest decisions and D2/D3 wrappers
  vision.py / ocr.py        detector and OCR logic plus adapters
  audio.py                  chill/reset scoring and loopback capture
  game_data.py              active-world events/ores/classification
  reentry*.py               automatic and remote re-entry decisions
  remote_aim.py             Discord-assisted harvest alignment
  roblox_menu.py            menu OCR decisions
  sampler.py                R-key calibration UI and sample writing
  notify.py                 Discord HTTP API and async notifications
  discord_commands.py       pure Discord command parsing
  diagnostics.py            logging, snapshots, retention
  metrics.py                bounded latency percentiles
  preflight.py              pure startup warning policy
  __main__.py               splash entrypoint for pythonw/batch launch
tests/                      unit, synthetic, and tracked fixture regressions
assets/                     tracked JSON plus machine-local runtime assets
docs/                       current references, incidents, historical designs
logs/                       gitignored runtime evidence and diagnostics
*.mcr                       original human-recorded Roblox macros
啟動挖礦bot.bat             preferred no-console launcher
```

Only JSON datasets and documentation under `assets/` are guaranteed to be tracked.
Most runtime PNG/WAV files are machine-local. Fresh-checkout tests must use tracked
`tests/fixtures/` data or generate synthetic input.

## WHERE TO LOOK

| Task | Read first | Then inspect |
|---|---|---|
| Runtime/startup | `main.Bot.run`, `Bot._on_enter`, `Bot._tick` | `miningbot/__main__.py`, preflight tests |
| Top-level state | `states.py`, `tests/test_states.py` | every direct `self.state =` site |
| Coordinates/modes/hotkeys | `config.py` | config and incident regressions |
| Rare-ore harvest | rules below, latest matching H incident | `harvester.py`, `_sweep_for_tracker`, `_tick_harvest`, `_harvest_success` |
| Tracker detection | H039/H040/H057, `tests/test_vision.py` | `vision.find_tracker`, `find_tracker_near` |
| Chat verification | H014/H020/H032/H041/H054/H055 | `ocr.ChatLedger`, `read_text_multi`, `_verify_chat_ocr`, `ocr.baseline_saw_found_history`, `ocr._strip_ui_residue` |
| Chill/reset audio | `audio.py`, `tests/test_audio.py` | `main._on_audio_*` |
| Mine reset | reset/capacity incident evidence | `states.py`, `_banner_ocr_loop`, `_update_reset_complete` |
| Re-entry | newest implemented re-entry specs | `reentry.py`, `reentry_remote.py`, `_tick_reentry*` |
| Discord controls | command/parser tests | `main._poll_discord`, `notify.py` |
| World/ore data | `game_data.py`, `tests/test_game_data.py` | `fetch_ores.py`, tracked JSON datasets |
| R-key calibration | `docs/manual-sampling.md` | `sampler.py`, `calibrate_surface.py` |
| Logs/snapshots | `diagnostics.py`, `docs/incidents.md` | categorized runtime snapshots |

Read `miningbot/AGENTS.md` for package-local rules and `tests/AGENTS.md` for test
conventions.

## NON-NEGOTIABLE RUNTIME RULES

1. Use `SW_MAXIMIZE`, never `SW_RESTORE`; set DPI awareness before the first
   screenshot or GUI operation.
2. Coordinates are calibrated for a maximized 1920×1080 capture with the Windows
   taskbar visible. Recalibrate from real frames instead of adjusting by eye.
3. Tool keys toggle equipment. Never press D1 blindly; use `vision.slot_selected`
   over `d1_slot_region`.
4. Camera yaw uses `,`/`.` through verified rotation. Fine pitch/aim uses right-button
   drag with settle and frame-diff validation. Plain `moveRel` does not rotate REX.
5. D3 is always `2 → 0.15s → 3 → 0.3s → hold-click 0.4s → 0.5s`.
6. Harvest success requires new rare/special chat evidence. Tracker disappearance
   alone means `RESWEEP`, never success. Preserve episode `ChatLedger` and late
   confirmation. Count-difference signals are void when the baseline OCR saw no
   has-found history: chat auto-hides after ~15s idle, and old lines re-displayed
   by a later message are not this shot's evidence (H054). `chat_region` overlaps
   the persistent ore panel, so every chat OCR ends with panel text; strip trailing
   UI residue at the comparison entry point (`ocr._chat_lines`) or the anchor-based
   signals are dead by construction. Do not shorten the region instead — the panel
   is drawn *over* the newest chat line, not below it (H055). An empty baseline
   confirms nothing through the last-line or tail signals.
7. Capacity at 100% never enters `RESET_WAIT`; only the reset banner may stop mining.
8. Tracker masks remain per HSV range and center confirmation is hue-independent.
   Use real in-game crops, keep the configured candidate ROI, and never run
   full-frame shape matching inside the sweep.
9. Background workers publish pending flags or caches. Game input is consumed only
   on the main loop.
10. Tk text must not contain astral emoji (`> U+FFFF`) on this Tcl/Tk 8.6 machine;
    pass UI text through `_bmp_safe` and use BMP symbols.
11. Global hotkeys use `GetAsyncKeyState`: Ctrl+Q pause-only, Q
    pause/resume/clear/skip startup, F12 quit, R sampler. Do not use `keyboard` and
    never send Esc during manual driving.
12. `reentry_mode` is `off`, `remote`, or `auto`; the default comes from `Config`.
    Automatic mode is calibration gated. Every path is bounded, falls back to
    `NEEDS_HUMAN`, and restores pitch/zoom before finalization.

## DEVELOPMENT WORKFLOW

- Start with `git status --short` and preserve unrelated user/tool changes.
- Use `rg` and symbol names rather than stale line numbers.
- Test pure decisions first. Default tests must not require Roblox, devices, or live
  Discord.
- Visual/OCR threshold changes require real fixtures and a two-sided bracket. Cite
  the relevant H incident.
- Put every runtime coordinate, threshold, interval, and mode in `Config`.
- Preserve Chinese calibration comments; they record provenance.
- Every completed task must end with a commit: run the full test suite green
  first, stage only the files the task touched, and write a Chinese commit
  message describing the change (cite the H incident id when applicable).
- Do not push, switch branches, delete runtime evidence, or mutate
  Roblox/Discord unless the user explicitly requests it.
- The primary agent owns integration, diff review, and verification.

## COMMANDS

```powershell
uv run pytest --collect-only -q
uv run pytest -q
uv run ruff check . --no-cache
uv lock --check

uv run python -m miningbot.main
pythonw -m miningbot
uv run python -m miningbot.fetch_ores
uv run python -m miningbot.fetch_trackers
uv run python -m miningbot.capture_template boost
uv run python -m miningbot.calibrate_surface --import NNN
uv run python -m miningbot.calibrate_pitch
```

Sandboxed `python.exe` may fail with an execution-permission error on this managed
Windows workspace. Re-run through the approved `uv` path before diagnosing code.

## CURRENT RISK AREAS

- `main.py` remains the main complexity hotspot and has intentional direct state
  assignments outside the central transition path.
- Remote aim/re-entry and zoom need more live-game evidence than pure tests provide.
- `scan_confirm_mode` is still off. Its region was calibrated on 2026-07-25 to the
  bottom-right effect row (the earlier bottom-left value read the ore panel instead),
  but the mode has not yet run in `observe` against a live session.
- Machine-local PNG/WAV assets are not guaranteed in a fresh checkout; preflight
  must warn explicitly.
- Historical HANDOFF/design files are evidence, not a current backlog.
