# tests/ — pure-logic TDD suite

Conventions for the 87-test pytest suite. Read `../AGENTS.md` for project commands, `../miningbot/AGENTS.md` for what each module does. This file is the test-writing guide.

## OVERVIEW

87 pytest tests covering **pure logic only** — no Roblox, no audio device, no screen. All green at `bc7a622`. Runs in ~8s.

## STRUCTURE

```
tests/
├── __init__.py            # package marker (empty)
├── test_states.py     (9) # decide_transition — full 4-state FSM
├── test_geometry.py   (5) # aim_decision — FIRE/ROTATE/MOUSE_AIM/HUMAN
├── test_miner.py      (8) # dispatch_event priority + cooldown_ready
├── test_harvester.py  (8) # next_harvest_step + restore_actions
├── test_events.py     (2) # EventLog sink fan-out
├── test_ocr.py       (11) # contains/count/has_new_found (diff semantics)
├── test_vision.py    (19) # find_tracker ranking + template helpers (synthetic numpy)
├── test_window.py     (9) # displacement_reason priority + WindowState
├── test_audio.py      (6) # match_score + loudest_window (synthetic signals)
├── test_notify.py     (7) # format_message (Chinese templates)
└── test_diagnostics.py(3) # setup_logging + save_snapshot (tmp_path)
```

## WHERE TO LOOK

| Need | Go to |
|---|---|
| Find the test for a state transition | `test_states.py` — names like `test_chill_takes_priority_over_reset` |
| Find the test for tracker ranking | `test_vision.py:81` `test_find_tracker_prefers_higher_colored_over_larger_area` |
| Find the test that locks the OCR stale-chat bug | `test_ocr.py:39` — comment `# ★ 核心bug：D3 前就有舊訊息...` |
| Find the helper that builds an Observation | `test_states.py:3` `def obs(**kw)` |
| Find the helper that builds a synthetic tracker image | `test_vision.py:14` `_draw_tracker(scene, cx, cy, size, color)` |
| Find the test for window DPI scaling | `test_window.py:5` `BASELINE` — 1536×864 (not 1920×1080) |

## CONVENTIONS (this test suite only)

- **Pure-function TDD.** Every test exercises a pure function or pure method. I/O is never invoked. The 6 I/O wrappers (`capture`, `input_control`, `audio.LoopbackCapture`, `vision` OpenCV parts, `ocr.read_text`, `window.query_window`) are untested by design — `CLAUDE.md` rule.
- **No `conftest.py`, no shared fixtures.** Each test file builds its own minimal helpers inline. Duplication beats indirection at this scale.
- **No `parametrize`, no `mock`, no `monkeypatch`.** Verified by grep. Only the built-in `tmp_path` fixture is used (in `test_diagnostics.py`).
- **Inline constructor helpers** per file:
  - `obs(**kw)` → `Observation` with safe defaults (`test_states.py:3`)
  - `flags(**kw)` → `EventFlags` (`test_miner.py:3`)
  - `cur(**kw)` + `BASELINE`/`POS_TOL`/`SIZE_TOL` module consts → `WindowState` (`test_window.py:5-17`)
  - `rec(t, **meta)` → `EventRecord` (`test_notify.py:7`)
  - `_scene_with_patch`, `_draw_tracker`, `_framed_box`, `_ring` → synthetic numpy arrays (`test_vision.py`)
- **Tests inject `cfg=DEFAULT`** instead of hardcoding thresholds — `test_harvester.py` passes `cfg=DEFAULT` to `next_harvest_step`. Keeps tests aligned with `config.py` automatically.
- **Test name = invariant**: `test_<subject>_<expected>` (e.g. `test_find_tracker_ignores_dark_panel_without_colored_center`). Read the name to know what's locked down.
- **Regression tests cite the bug in a comment**: `# 對應 HANDOFF「修 2」`, `# ★ 核心bug：D3 前就有舊訊息...`. These are executable bug reports — don't strip the citation when editing.
- **AAA in ~4-5 lines, no comments** unless it's a regression-cite. No `# arrange`, no `# act`, no `# assert` decoration.

## ANTI-PATTERNS (in this suite)

1. **NEVER add a test that imports `mss`, `pydirectinput`, `pyaudiowpatch`, or `pytesseract`** — those are I/O deps and break CI without hardware. Pure logic + numpy only.
2. **NEVER hardcode a threshold in a test.** Read from `from miningbot.config import DEFAULT` and pass `cfg=DEFAULT`. If you need a non-default value, construct a `Config(...)` instance locally.
3. **NEVER use `unittest.mock` or `monkeypatch`** to fake I/O. The codebase pattern is to refactor the pure decision out (see `decide_transition`, `dispatch_event`, `next_harvest_step`) and test that. If you find yourself reaching for mock, the production code needs refactoring instead.
4. **NEVER delete a failing test to make the suite green.** Read the comment — it's a regression lock. Either fix the production code or update the test with a justification comment.
5. **NEVER add a `conftest.py`** — the no-shared-fixture style is intentional. Helpers stay local to the file that needs them.

## NOTES

- **Coverage matrix** (what's tested vs not):
  - Fully tested: `states`, `geometry`, `events`, `window` (pure parts), `diagnostics`
  - Partially tested: `miner` (only `dispatch_event`/`cooldown_ready` — not the I/O macros), `harvester` (only `next_harvest_step`/`restore_actions` — not `start_scan`/`fire_d3`), `ocr` (matchers yes, `read_text` no), `audio` (`match_score`/`loudest_window` yes, `ChillListener`/`LoopbackCapture` no), `notify` (`format_message` yes, HTTP no), `vision` (all pure helpers yes, `load_template` no)
  - Untested by design: `capture`, `input_control`, `main.Bot`
- **Highest-leverage gaps** (pure logic, TDD-able): `miner._ensure_pickaxe` (locks the D1-toggle rule), `harvester.fire_d3` (locks 0.6s+0.4s timing), `audio.ChillListener.feed/score` (locks ~0.4 threshold behavior). All would need a thin injectable interface or `monkeypatch.setattr` on `ic`.
- **Run command**: `python -m pytest -q` from project root. `pytest.ini` only sets `testpaths = tests`.
- **Collection time**: ~5.6s (dominated by OpenCV/numpy import in `test_vision.py`). Actual test execution ~2.6s.
- **The 1536×864 baseline in `test_window.py`** is NOT a bug — it encodes the 125% DPI scaling on the dev machine. Don't "fix" it to 1920×1080.
