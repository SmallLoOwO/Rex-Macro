# tests/ — TEST GUIDE

Read `../AGENTS.md` for project-wide source priority and `../miningbot/AGENTS.md` for module ownership.

## BASELINE

As of 2026-07-13:

- `python -m pytest --collect-only -q` → **651 tests collected** in about 39 seconds on this machine.
- The complete suite includes real OCR/image fixtures and can exceed 3 minutes. Do not document a full “passed” count unless the command actually completes in the current worktree.
- Tests do not require Roblox, a live screen, an audio device, or Discord, but some real-engine fixture tests are conditionally skipped when tesseract/RapidOCR is unavailable.

The suite is no longer “pure logic only.” It contains:

- pure decision/value tests;
- synthetic numpy image/audio tests;
- tracked real screenshot/OCR fixture regressions;
- filesystem tests using `tmp_path`;
- narrow I/O-wrapper tests using injected functions or `monkeypatch`;
- engine-dependent tests guarded with `pytest.mark.skipif`.

## FILE MAP

| Area | Test files |
|---|---|
| FSM/policies/hotkeys | `test_states.py`, `test_hotkeys.py` |
| Harvest/aim/vision | `test_harvester.py`, `test_geometry.py`, `test_vision.py`, boost/slot/pitch fixture files |
| Chat/OCR/UI | `test_ocr.py`, `test_ocr_fixtures.py`, capacity/chat/player/menu fixture files, `test_roblox_menu.py` |
| Audio/chill refs | `test_audio.py`, `test_add_chill_ref.py` |
| Worlds/events/ore sync | `test_game_data.py`, `test_fetch_ores.py` |
| Re-entry/remote | `test_reentry.py`, `test_reentry_remote.py`, `test_remote_aim.py` |
| Discord/events | `test_notify.py`, `test_events.py` |
| Platform/ops/UI | `test_capture.py`, `test_input_control.py`, `test_window.py`, `test_diagnostics.py`, `test_preflight.py`, `test_sampler.py`, `test_status_hud.py` |

Use `rg -n subject_or_incident tests` instead of relying on stale per-file test counts.

## CONVENTIONS

- Test name states the invariant: `test_<subject>_<expected>`; class grouping is used for coherent feature families.
- Real regressions cite H incident IDs or the observed failure in a nearby comment/docstring. Preserve those references.
- Prefer the smallest pure decision surface. If orchestration is hard to test, extract a pure function or inject the narrow external action.
- `monkeypatch` is allowed for thin platform wrappers and engine fallback selection. Keep it local and assert exact calls/arguments; do not build a fake Roblox runtime.
- `tmp_path` is used wherever file retention, refs, logs, or tessdata discovery is under test.
- `pytest.mark.skipif` is correct for optional real OCR engines. A skip is not proof that the engine path works; report skips in verification results.
- Synthetic thresholds should normally come from `DEFAULT`. A custom `Config` is appropriate when the test specifically exercises a non-default mode/boundary.
- Real fixture tests should bracket both sides: the target frame passes and the incident’s false-positive/false-negative counterpart behaves correctly.
- Keep fixtures immutable. Add a new named fixture for new evidence instead of overwriting old incident evidence.

## WHAT NOT TO DO

1. Do not invoke live screen capture, send real input, open Roblox, access Discord, or require a physical audio device in the default suite.
2. Do not delete/relax an incident regression merely to make a new approach green. Explain any deliberate semantic change and retain an equivalent safety test.
3. Do not hardcode obsolete coordinates or copied production thresholds when `DEFAULT` is the behavior under test.
4. Do not cross-compare OCR outputs from different preprocess passes as if they were one stream; pass self-consistency is part of the verifier design.
5. Do not treat an optional-engine skip as a passing end-to-end OCR validation.
6. Do not use broad mocks of `Bot` to claim runtime coverage. Test pure policies, and reserve live validation for explicit desktop sessions.

## FIXTURE RULES

- Tracked fixtures live under `tests/fixtures/` and selected tracked datasets under `assets/*.json`.
- Local PNG/WAV files under `assets/` are mostly gitignored even if present. A test intended for a fresh checkout must not silently depend on an untracked machine-local asset.
- OCR fixture tests may load real engines and dominate runtime. Run focused tests while iterating, then collection/full-suite checks before handoff.
- For new tracker evidence, keep the full scene when feasible and encode the incident/harvest ID in the test or fixture name. Cropped runtime templates belong to local `assets/markers/`; regression scenes belong in tracked test fixtures only when intentionally added.

## COMMANDS

```powershell
# inventory only
python -m pytest --collect-only -q

# focused iteration
python -m pytest -q tests/test_states.py
python -m pytest -q tests/test_harvester.py tests/test_vision.py
python -m pytest -q tests/test_ocr.py tests/test_ocr_fixtures.py
python -m pytest -q tests/test_reentry.py tests/test_reentry_remote.py tests/test_remote_aim.py

# complete verification (allow several minutes)
python -m pytest -q
```

When reporting verification, include the exact command, pass/fail/skip totals, and whether the command timed out. “No output before timeout” is inconclusive, not green or red.
