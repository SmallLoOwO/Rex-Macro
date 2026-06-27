# miningbot/ — package internals

Per-module map for the importable bot package. Read `../AGENTS.md` for project overview, `../CLAUDE.md` for hard rules. This file is the module-level dependency + responsibility guide.

## OVERVIEW

22 Python modules. One orchestrator (`main.py`), 6 pure-logic modules with full TDD coverage, 6 thin I/O wrappers (untested by design), 4 CLI utilities, 5 supporting modules (config/events/diagnostics/notify/status_hud).

## STRUCTURE (by role)

```
miningbot/
├── main.py            # ⭐ Bot orchestrator (528 lines — largest module)
├── config.py          # Config dataclass + DEFAULT singleton (~110 fields)
│
├── ── pure logic (full TDD coverage) ──
├── states.py          # State enum + decide_transition (sole FSM decision fn)
├── geometry.py        # aim_decision (FIRE/ROTATE/MOUSE_AIM/HUMAN picker)
├── miner.py           # dispatch_event + cooldown_ready + D1-D5 I/O macros + resume_mining + use_activity_keep
├── harvester.py       # next_harvest_step + HarvestState + D2/D3 I/O macros
├── ocr.py             # contains_phrase/count_found/has_new_found (pure matchers)
├── events.py          # EventLog + EventRecord + make_file_sink (observer)
├── game_data.py       # REX 事件資料庫（16 事件）+ match_event/is_kept/fuzzy_match_ore (pure)
│
├── ── thin I/O wrappers (no tests; hold all hardware calls) ──
├── capture.py         # mss grab() + crop()
├── audio.py           # WASAPI LoopbackCapture + ChillListener + match_score
├── vision.py          # OpenCV find_tracker + find_template_edges + helpers
├── input_control.py   # pydirectinput wrappers (key/mouse/click_at/rotate_*)
├── window.py          # Win32 query_window + displacement_reason (pure)
│
├── ── supporting ──
├── diagnostics.py     # setup_logging（子 logger 分檔：heartbeat/actions/harvest/discord）+ save_snapshot
├── notify.py          # Discord Bot API：send_message/send_image_message(multipart)/fetch_messages/send_embed
├── status_hud.py      # tkinter always-on-top status window
│
└── ── CLI utilities (python -m miningbot.<name>) ──
    ├── convert_audio.py   # ffmpeg → chill_reference.wav
    ├── fetch_trackers.py  # download wiki tracker PNGs → assets/markers/
    ├── capture_template.py# interactive ROI capture → assets/*.png
    └── calibrate.py       # prints Region(...) literals for config.py
```

## WHERE TO LOOK

| Need | Go to |
|---|---|
| Where does state X transition? | `states.py:19` `decide_transition` (pure); **but** `_tick_mining` (`main.py:348`) and `_tick_harvest` (`main.py:394,440`) ALSO write `self.state` directly — pure FSM is partial |
| What runs every frame? | `main.py:272-285` `run()` loop body — 50ms tick |
| How does audio get to the FSM? | `LoopbackCapture` thread → `ChillListener.feed()` → `latest_score()` polled in `observe()` |
| How are events fanned out? | `Bot.__init__` (`main.py:19-30`) wires 3 sinks to `EventLog`: file, Discord (lazy), logger |
| Where is the D3 sequence? | `main.py:415-417` — `key_press("3") → sleep(0.6) → click_at(cx,cy,hold=0.4)` |
| Where is the D2 scan? | `harvester.py:49-55` `start_scan` — `key_press("2") → sleep(0.3) → click_at(center) → sleep(1.5)` |
| Where are tracker HSV ranges? | `vision.py:93-103` `_TRACKER_COLORS` (4 ranges; never merge) |
| Where are hotkeys polled? | `main.py:470-493` `_check_hotkeys` — `GetAsyncKeyState` (NOT `keyboard` lib) |

## INTER-MODULE DEPENDENCIES

Import graph (relative imports, `from . import`):

```
main.py
  ├── config.DEFAULT          (everything reads cfg)
  ├── events.EventLog         (sink fan-out)
  ├── states.{State, Observation, decide_transition}
  ├── capture.{grab, crop}    (I/O)
  ├── vision.{load_template, find_template_edges, find_tracker, frame_mean_diff}
  ├── ocr.{read_text, contains_any, count_found, has_new_found}
  ├── audio.{load_reference, ChillListener, LoopbackCapture}
  ├── miner.{EventFlags, dispatch_event, init_mining_sequence, use_boost, use_activity}
  ├── harvester.{HarvestState, next_harvest_step, start_scan, fire_d3, restore_view}
  ├── diagnostics.{setup_logging, save_snapshot}
  ├── window.{query_window, displacement_reason}
  ├── input_control as ic    (key/mouse primitives)
  └── notify (LAZY — only if cfg.discord_bot_token+channel_id set)

miner.py
  ├── config.DEFAULT
  ├── input_control as ic
  ├── capture (LAZY inside _ensure_pickaxe — style violation)
  └── vision (LAZY inside _ensure_pickaxe — style violation)

harvester.py
  ├── config.DEFAULT
  ├── geometry.aim_decision
  └── input_control as ic

ocr.py / audio.py / vision.py / capture.py / window.py / input_control.py
  └── (stdlib + 3rd-party only; no intra-package imports)
```

**Critical edges** (high blast radius if changed):
- `Config` is imported by ~every module. Adding/removing a field ripples everywhere.
- `decide_transition` signature change → also update `_tick_*` direct writes (see ANTI-PATTERNS).
- `ic.*` (input_control) used by `miner`, `harvester`, `main` directly. Cannot be renamed/repurposed trivially.

## CONVENTIONS (intra-package)

- **All thresholds/coords/hotkeys in `config.py:Config`** — single source. Callers do `from .config import DEFAULT as cfg` then `cfg.<field>`. Tests inject `cfg=DEFAULT`.
- **Relative imports only** (`from . import X`, `from .X import Y`). Never `from miningbot.X import Y` — package is run via `python -m miningbot.<entry>`.
- **Pure functions return data; I/O functions return `None`** (side-effect). `dispatch_event` returns action string; `use_boost` performs the action and returns `None`.
- **`@dataclass` for value objects** — `Config`, `Region`, `Observation`, `HarvestState`, `EventFlags`, `EventRecord`, `WindowState`. Mutable state lives on `Bot` instance attrs.
- **Type hints on pure functions only** — I/O wrappers are untyped (they wrap untyped C extensions).
- **Lazy imports for hardware/optional deps**: `notify` (Discord env check), `pydirectinput` (focus-fallback only), `tkinter` (HUD only).
- **Chinese inline comments are the norm** — calibration provenance, real-hardware reasoning, bug-cite comments. Don't strip them when editing.

## ANTI-PATTERNS (intra-package)

1. **NEVER add business logic to `main.py` outside `Bot` class methods.** `_read_chat` and `_snapshot_crop` (`main.py:455-467`) are exceptions that belong in `harvester.py` — don't proliferate them.
2. **NEVER rely solely on `decide_transition` for transitions.** `_tick_mining` (REFOCUS→NEEDS_HUMAN at `:348`) and `_tick_harvest` (timeout/success at `:394,440`) write `self.state` directly. If you add a new state, update both paths.
3. **NEVER import `capture`/`vision` inline (function-body)** — only `miner._ensure_pickaxe` does this (`miner.py:51-52`); it's a style violation. Move imports to module top.
4. **NEVER instantiate `Bot` without testing focus first.** `run()` calls `_focus_roblox()` and aborts if it returns False. Constructing `Bot` does NOT start the loop — `bot.run()` does.
5. **NEVER call `audio.LoopbackCapture.start()` outside `Bot.__init__`** — single audio device, single thread. `main.py:36-40` owns the lifecycle.
6. **NEVER bypass `cfg` and hardcode a coordinate.** Even in tests, pass `cfg=DEFAULT` rather than literals.
7. **NEVER use `audio.detect` (defined `audio.py:21`)** — likely dead; `ChillListener` uses its own internal logic. Verify before extending.

## NOTES

- **`main.py` is 528 lines** — the single complexity hotspot. The Bot class is the entire orchestrator; the only module-level functions are `_set_dpi_aware()` and `main()`.
- **Dead init line**: `main.py:41` `self.harvest = HarvestState(...)` is overwritten at `:309` on first HARVESTING entry. Could be `None` and lazily created.
- **Unused I/O surface** (intentional per CLAUDE.md): `input_control.aim_move`, `input_control.mouse_move_rel` — declared for future vertical-tracker support, never called.
- **Redundant `import ctypes`**: `main.py` imports it at top (`:3`) AND inside 3 functions (`:219, 475, 535`). Harmless (cached), but noisy.
- **`status_hud.py` runs on a daemon thread** while `bot.run` runs on main. Don't add HUD updates from inside the loop thread — use the existing `_check_status_window` polling pattern.
- **`_focus_roblox` is the most fragile function** — Win32 focus APIs behave inconsistently across Windows versions. If focus issues appear, the fallback `pydirectinput.click()` at center (`main.py:234-236`) is the recovery path.
