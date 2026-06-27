# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-27
**Commit:** `bc7a622`
**Branch:** `feature/window-discord-controls`

## OVERVIEW

Windows-only Python 3.11+ bot that idles the Roblox game "REX" (rex-3 wiki): auto-mines common ore, drinks boosters (D5), rerolls events (D4), and harvests rare ore when the "chill" audio cue fires. Stops for human on mine reset. State-machine driven, 50 ms tick, pure-logic TDD core.

## STRUCTURE

```
無聊的挖礦遊戲/
├── miningbot/        # importable package — Bot orchestrator + I/O wrappers + pure logic + 4 CLI tools
├── tests/            # 87 pytest tests — pure-logic only (no Roblox, no audio device needed)
├── docs/             # HANDOFF.md (live status), game-mechanics.md (REX rules), superpowers/{specs,plans}/ (frozen 2026-06-23 design)
├── assets/           # gitignored binaries — chill_reference.wav, boost_active.png, d4_cooldown.png, markers/*.png
├── logs/             # runtime (gitignored) — miningbot.log, events.log, snapshots/*.png
├── *.mcr             # Roblox macro recordings (NOT Python — human-recorded hotkey sequences, original source for sequences in miner.py)
├── CLAUDE.md         # ⭐ SOURCE OF TRUTH — operating manual with hard-won rules
└── README.md         # user-facing install + run guide
```

## WHERE TO LOOK

| Task | Read first | Then |
|---|---|---|
| **Understand what the bot does** | `CLAUDE.md` (top), `docs/game-mechanics.md` | `miningbot/main.py:245` `Bot.run()` loop |
| **Tweak a coordinate / threshold / hotkey** | `miningbot/config.py` (`Config` dataclass, ~110 fields) | No call-site edits — all consumers read `cfg` |
| **Change state-machine logic** | `miningbot/states.py:19` `decide_transition` + `tests/test_states.py` | TDD: failing test first |
| **Fix tracker detection** | `miningbot/vision.py:105` `find_tracker` + `tests/test_vision.py` | Read CLAUDE.md "稀有礦追蹤框偵測" hard rules first |
| **Change D3 harvest timing** | `miningbot/main.py:415` + `miningbot/input_control.py:49` `click_at` | CLAUDE.md "D3 採集" rule (0.6s + 0.4s hold) |
| **Tune chill audio threshold** | `miningbot/config.py:52` `audio_match_threshold=0.30` | `miningbot/audio.py:25` `ChillListener` |
| **Change hotkeys** | `miningbot/config.py:101` + `miningbot/main.py:470` `_check_hotkeys` | CLAUDE.md says NEVER use `keyboard` lib |
| **Setup Discord notifications** | `.env.example` → `.env` with `DISCORD_BOT_TOKEN`/`DISCORD_CHANNEL_ID` | `miningbot/notify.py` |
| **What's currently broken** | `docs/HANDOFF.md` §3 | Has ready-to-implement fixes in §4 |
| **Source-of-truth hierarchy for docs** | `CLAUDE.md` > `docs/HANDOFF.md` > `docs/game-mechanics.md` > `docs/superpowers/*` (historical, partially stale) | See ANTI-PATTERNS below |
| **Per-module map / inter-module deps** | `miningbot/AGENTS.md` | — |
| **How to write / find tests** | `tests/AGENTS.md` | — |

## CODE MAP (top symbols by reference centrality)

| Symbol | Type | Location | Role |
|---|---|---|---|
| `Bot` | class | `miningbot/main.py:13` | Orchestrator: holds state machine thread, wires all I/O, owns 50 ms loop |
| `Config` / `DEFAULT` | dataclass | `miningbot/config.py:18` / `:110` | All coords/thresholds/hotkeys/secrets — single source |
| `State` | enum | `miningbot/states.py:4` | `MINING / HARVESTING / NEEDS_HUMAN / RESET_WAIT` |
| `decide_transition` | pure fn | `miningbot/states.py:19` | Sole pure state-machine decision (chill beats reset) |
| `Observation` | dataclass | `miningbot/states.py:11` | Per-frame observation (chill/harvest/reset/human flags) |
| `dispatch_event` | pure fn | `miningbot/miner.py:12` | MINING action picker: priority REFOCUS > USE_D5 > USE_D4 |
| `next_harvest_step` | pure fn | `miningbot/harvester.py:20` | HARVESTING step generator: WAIT/ROTATE/MOUSE_AIM/FIRE_D3/HUMAN |
| `find_tracker` | fn | `miningbot/vision.py:105` | Rare-ore detection — per-HSV-range frame_fill + colored_frac rank |
| `ChillListener` | class | `miningbot/audio.py:25` | Rolling buffer + cross-correlation score against reference WAV |
| `LoopbackCapture` | class | `miningbot/audio.py:47` | WASAPI speaker-loopback thread feeding `ChillListener` |
| `displacement_reason` | pure fn | `miningbot/window.py:30` | Window-drift verdict: missing > unfocused > moved > resized |
| `EventLog` | class | `miningbot/events.py` | Observer sink fan-out (file + Discord + logger) |

## CONVENTIONS (deviations from standard Python)

- **Flat layout, no `src/`, no `pyproject.toml`, no `setup.py`.** Just `requirements.txt` (11 pinned deps) + `pytest.ini` (`testpaths = tests`).
- **Single-config hub.** Every coordinate/threshold/hotkey lives in `miningbot/config.py:Config`. Never hardcode in logic modules.
- **Pure-vs-I/O split is strict.** Pure (`states`, `geometry`, `miner` dispatch fns, `harvester` step fn, `ocr` matchers, `events`) has full type hints + unit tests. I/O wrappers (`capture`, `audio` device parts, `vision` OpenCV, `ocr` Tesseract, `input_control`, `window` Win32) hold all hardware calls and are untested by design.
- **`@dataclass` + `Enum` everywhere** for state carriers (`Config`, `Region`, `Observation`, `HarvestState`, `EventFlags`, `EventRecord`, `WindowState`).
- **CLI utilities are first-class modules**: `python -m miningbot.{main,convert_audio,fetch_trackers,capture_template,calibrate}`.
- **Windows-only.** DPI-aware, Win32 API, `pydirectinput`, WASAPI loopback. Cross-platform is not a goal.
- **Threaded, not async.** Main loop on main thread; audio capture, hotkey poll, HUD on background threads.
- **Lazy imports for optional deps**: `notify` (only if Discord env set, `main.py:24`), `pydirectinput` (only on focus-failure fallback, `main.py:234`), `tkinter` (only if HUD enabled).

## ANTI-PATTERNS (THIS PROJECT — read CLAUDE.md for the full list)

These are forbidden here, not generic Python advice:

1. **NEVER use `SW_RESTORE` to focus Roblox** — collapses maximized window, all coords break. Use `SW_MAXIMIZE=3` (`main.py:224`).
2. **NEVER skip `SetProcessDpiAwareness(2)` before first screenshot** — `mss` flips DPI-awareness on first grab; baseline captured before that then disagrees with runtime coords → false "resized" (`main.py:528-542`).
3. **NEVER use `keyboard` library for hotkeys** — fails to receive keys when Roblox has foreground. Use `GetAsyncKeyState` polling (`main.py:470`).
4. **NEVER press D1 unconditionally** — toggles pickaxe off if already equipped. Only press when `slot_pixel` matches "not holding" (`miner.py:49-58`).
5. **NEVER use `pydirectinput.moveRel` alone to rotate camera** — does nothing in REX. Use `,` / `.` (45° each) or right-click drag (`input_control.py:55`).
6. **NEVER merge `_TRACKER_COLORS` HSV masks** — range3 (H=153-179) overlaps red mine background (H≈168); per-range `frame_fill` only (`vision.py:118-120`).
7. **NEVER trust wiki edge templates for tracker detection** — center color varies per ore. Use color+frame_fill+colored_frac ranking (`vision.py:151`).
8. **NEVER make D3 a tap-click** — must be hold-click 0.4s after 0.6s equip delay (`main.py:415-417`).
9. **NEVER cite `docs/superpowers/spec|plans/*` for thresholds/hotkeys/APIs without cross-checking code** — these are 2026-06-23 frozen designs; many values superseded (audio thr 0.55→0.30, hotkeys F8/F9/F12→Ctrl+Q/Q/F12, 3 states→4, Discord "deferred"→shipped, `contains_any` success→diff-based `has_new_found`).
10. **NEVER press Esc when driving the game manually** (computer-use sessions) — opens Roblox menu. Use only game keys: 1-5, `,`/`.`, W, ←/→.

## UNIQUE STYLES

- **Test names encode the invariant**: `test_chill_takes_priority_over_reset`, `test_find_tracker_ignores_dark_panel_without_colored_center`. Read the test name to know what's locked down.
- **Regression tests cite the bug**: comments like `# 對應 HANDOFF「修 2」` or `# ★ 核心bug：D3 前就有舊訊息...` link the test to a real-world failure. Treat as executable bug reports.
- **Coordinates annotated with real-hardware reasoning**: e.g. `Region(360, 42, 1440, 52)  # 頂部事件列（chill/事件文字）實測`. Comments are calibration provenance, not decoration.
- **`.mcr` files at root are Roblox macro recordings** — the human-recorded originals that `miner.py`'s key sequences were transcribed from. Useful as ground truth if a sequence looks wrong.
- **`logs/_*.py` are diagnostic scripts** (e.g. `logs/_test_harvest.py`, `logs/_diag_tracker.py`) — ad-hoc one-shots for real-hardware debugging, NOT production code. Listed in `docs/HANDOFF.md` §6.

## COMMANDS

```bash
# Test (pure logic, no game needed) — must stay green
python -m pytest -q

# Start bot (Roblox must be open + maximized first)
python -m miningbot.main

# Asset prep (all output gitignored — user-generated)
python -m miningbot.convert_audio "chill.mp3"          # → assets/chill_reference.wav
python -m miningbot.fetch_trackers                     # → assets/markers/*.png (7 high-tier)
python -m miningbot.capture_template boost              # → assets/boost_active.png
python -m miningbot.capture_template d4cool             # → assets/d4_cooldown.png
python -m miningbot.calibrate                           # prints Region(...) for config.py

# Debug one-liner (screenshot — sets DPI-aware first)
python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab; cv2.imwrite('logs/x.png', grab())"
```

**Hotkeys at runtime** (polled globally, work even with Roblox foreground):
- **Ctrl+Q** — emergency stop (release all keys, wait for Q to resume)
- **Q** — toggle pause / resume
- **F12** — real exit

## NOTES

- **Log streams**: `logs/miningbot.log` (rotating, 2 MB × 5), `logs/events.log` (structured `EventLog`), `logs/snapshots/*.png` (key-moment frames). Flip `cfg.log_level="DEBUG"` for per-frame detail.
- **SSH Session 0 Isolation**: bot must run on local desktop, not via SSH — audio loopback and Win32 foreground APIs don't work in Session 0 (`docs/HANDOFF.md` §6.1).
- **Tesseract path** is hardcoded to `C:\Program Files\Tesseract-OCR\tesseract.exe` (UB-Mannheim build) in `config.py:81`.
- **DPI scaling note**: this machine runs 125% DPI → `GetWindowRect` reports 1536×864, not 1920×1080. `tests/test_window.py` baseline reflects this. The bot uses **baseline-relative** comparison, not absolute pixels.
- **3 known blocking bugs** (per `docs/HANDOFF.md` §3): (A) `find_tracker` false-positive on red chat text inside `chat_region`; (B) chill audio missed — needs raw-RMS diagnostic; (C) D3 click on chatbox edge clears chat history. §4 has code-ready fixes.
- **87 tests green** as of `bc7a622`. Last commit added 8 OCR diff-tests to lock down bug fix for stale-chat false-success.
