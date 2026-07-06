# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-27 · **Updated:** 2026-06-28 (log 分檔/Discord 圖片+命令/game_data/harvest 修復包/chill 延遲修復/pythonw)
**Branch:** `feature/window-discord-controls`（`python -m pytest -q` → 123 passed）

## OVERVIEW

Windows-only Python 3.11+ bot that idles the Roblox game "REX" (rex-3 wiki): auto-mines common ore, drinks boosters (D5), rerolls events (D4), and harvests rare ore when the "chill" audio cue fires. Stops for human on mine reset. State-machine driven, 50 ms tick, pure-logic TDD core.

## STRUCTURE

```
無聊的挖礦遊戲/
├── miningbot/        # importable package — Bot orchestrator + I/O wrappers + pure logic + 4 CLI tools
├── tests/            # 131 pytest tests — pure-logic only (no Roblox, no audio device needed)
├── docs/             # incidents.md (H 系列實機事故錄：症狀/根因/對策/fixture/commit), HANDOFF.md (live status), game-mechanics.md (REX rules), superpowers/{specs,plans}/ (frozen 2026-06-23 design)
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
| **Fix tracker detection** | `miningbot/vision.py` `find_tracker` (hybrid HSV + shape) + `tests/test_vision.py` | Read CLAUDE.md "追蹤框偵測" + ANTI-PATTERNS 6-9; **門檻來歷/漏抓事故見 `docs/incidents.md`**; needs REAL frames (see NOTES) |
| **Change D3 harvest timing** | `miningbot/main.py` `_tick_harvest` D3 fire section + `config.py` `sweep_timeout_s`/`harvest_verify_timeout_s` | CLAUDE.md "D3 採集" rule (0.3s equip + 0.4s hold + 0.5s server); **改門檻前先讀 `docs/incidents.md` 對應 Hxxx** |
| **D4 事件保留/刷新** | `miningbot/game_data.py` `EVENTS` + `match_event`/`is_kept` | `main.py` USE_D4 分支；Discord `!keep`/`!list` 命令 |
| **Discord 通知/命令** | `miningbot/notify.py` `send_image_message`/`fetch_messages` | `main.py` `_discord_poll_loop`/`_handle_discord_command` |
| **Chill 音訊偵測** | `miningbot/audio.py` `ChillListener`（節流 `score_interval_s`）| `config.py` `audio_match_threshold`/`audio_score_interval_s` |
| **Log 分檔** | `miningbot/diagnostics.py` `setup_logging`（子 logger `_SUBLOGGERS`）| `main.py` log 路由（`log_hb`/`log_act`/`log_harvest`/`log_discord`）|
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
| `find_tracker` | fn | `miningbot/vision.py` | Rare-ore detection — **hybrid (2026-06-28)**: HSV per-range locate (hue-independent colored) + small-ROI real-crop outline confirm (`shape_templates`) |
| `find_marker` / `best_outline_score` | fn | `miningbot/vision.py` | Color-independent outline (Canny) shape match; alpha-outline for transparent wiki PNGs via `template_outline_edges` |
| `ChillListener` | class | `miningbot/audio.py:25` | Rolling buffer + cross-correlation score（**節流**：每 `score_interval_s` 算一次，非每 chunk）|
| `LoopbackCapture` | class | `miningbot/audio.py:47` | WASAPI speaker-loopback thread feeding `ChillListener` |
| `displacement_reason` | pure fn | `miningbot/window.py:30` | Window-drift verdict: missing > unfocused > moved > resized |
| `EventLog` | class | `miningbot/events.py` | Observer sink fan-out (file + Discord image/text + logger) |
| `match_event` / `is_kept` | pure fn | `miningbot/game_data.py` | REX 事件 OCR 比對 + D4 keep/reroll 判斷（16 事件資料庫）|
| `resume_mining` | fn | `miningbot/miner.py` | 採集成功後恢復挖 礦（直接按 1+W，取代 init_mining_sequence）|
| `send_image_message` | fn | `miningbot/notify.py` | Discord multipart 圖片上傳（stdlib urllib）|

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
6. **NEVER merge `_TRACKER_COLORS` HSV masks** — range3 (H=153-179) overlaps red mine background (H≈168); per-range `frame_fill` only (`vision.py`).
7. **NEVER hue-restrict the `colored` confirm in `find_tracker`** — the old `(S>90)&(V>90)&((H<35)|(H>95))` excluded H35-95 (yellow-green), silently dropping yellow/green-centered ores (e.g. Ionized). MUST be hue-independent `(S>90)&(V>90)` (2026-06-28 fix; root cause of "ore on screen but not detected"). Tier center color is arbitrary.
8. **NEVER use wiki PNGs as detection templates** — they are transparent outline-only icons; even matched correctly via the alpha outline (`template_outline_edges`), the vector edges DON'T match the in-game anti-aliased render at realistic scale (empirically all-miss; only noise-hits at scale 0.2). Use **real in-game crops** (`assets/markers/*_tracker_real.png`, no alpha → auto-selected into the shape-confirm set). One real crop generalizes across tiers (shape is color-independent). Real crops require real frames — see NOTES.
9. **NEVER run full-frame shape/template matching in the sweep** — 5.7s (2 templates) to 23.5s (9) per frame at 1080p. Shape confirm runs ONLY in a small ROI around each HSV candidate (`shape_roi_px`, ~65ms).
10. **NEVER make D3 a tap-click** — must be hold-click 0.4s after equip delay (`main.py`; equip wait 0.3s per 2026-06-28 HANDOFF, was 0.6s).
11. **NEVER cite `docs/superpowers/spec|plans/*` for thresholds/hotkeys/APIs without cross-checking code** — these are 2026-06-23 frozen designs; many values superseded (audio thr 0.55→0.30, hotkeys F8/F9/F12→Ctrl+Q/Q/F12, 3 states→4, Discord "deferred"→shipped, `contains_any` success→diff-based `has_new_found`).
12. **NEVER press Esc when driving the game manually** (computer-use sessions) — opens Roblox menu. Use only game keys: 1-5, `,`/`.`, W, ←/→.

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

- **Tracker detection needs REAL game frames** (wiki PNGs are insufficient — see ANTI-PATTERN 8). Real in-game captures live in **`C:\Users\puppy\OneDrive\Pictures\Roblox`** (Roblox screenshot key; files `RobloxScreenShot<YYYYMMDD_HHMMSS>.png`, ~1080p). Workflow to add a tier's template or tune thresholds: search that folder for the matching frame (by time / event banner text / ore color) → load with cv2 → run `find_tracker` / `best_outline_score` to confirm → crop the frame to `assets/markers/<tier>_tracker_real.png` (no alpha → auto-joins the shape-confirm set). Irrelevant screenshots there may be deleted to reduce clutter (verify contents before deleting). Cross-tier shape generalization (one crop covering all tiers) is UNVERIFIED — low-res video frames suggest tier frame shapes may differ (yellow starburst vs blue diamond vs red flower); confirm with full-res real frames.
- **Reference frame on disk**: `assets/very_rare.png` is a real Transcendent-tier frame (Ionized, red cave, blue diamond frame + lime center) with the tracker at ~(1230,643) — used by `tests/test_vision.py::test_find_tracker_hybrid_detects_real_marker`.
- **Log streams**: 分檔（propagate=False 隔離）—`miningbot.log`(主敘事), `heartbeat.log`(心跳+RMS), `actions.log`(boost/D4), `harvest.log`(sweep/D3細節), `discord.log`(通知+命令), `events.log`(TSV), `snapshots/*.png`+`chill_audio_*.wav`. Flip `cfg.log_level="DEBUG"` for per-frame detail.
- **SSH Session 0 Isolation**: bot must run on local desktop, not via SSH — audio loopback and Win32 foreground APIs don't work in Session 0 (`docs/HANDOFF.md` §6.1).
- **Tesseract path** is hardcoded to `C:\Program Files\Tesseract-OCR\tesseract.exe` (UB-Mannheim build) in `config.py:81`.
- **DPI scaling note**: this machine runs 125% DPI → `GetWindowRect` reports 1536×864, not 1920×1080. `tests/test_window.py` baseline reflects this. The bot uses **baseline-relative** comparison, not absolute pixels.
- **3 known limitations** (per `docs/HANDOFF.md` §7): (A) `find_tracker` false-positive on red chat text inside `chat_region`; (B) 「 礦已被自動挖走」無法自動偵測（聊天只顯示 礦名不帶 tier）；(C) D3 階段超時檢查有 blocking 問題（sleep 序列阻塞主迴圈）。
- **123 tests green** (2026-06-28). game_data 新增 18 測試（event match/fuzzy/embed/is_kept）；vision template matching 加 8 測試。
