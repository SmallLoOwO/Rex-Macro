# tests/ — TEST GUIDE

Read `../AGENTS.md` for project-wide behavior and `../miningbot/AGENTS.md` for module
ownership.

## BASELINE

Use fresh command output instead of storing totals or timing snapshots in guidance:

```powershell
uv run pytest --collect-only -q
uv run pytest -q --durations=10
```

Report exact pass/fail/skip totals from the current worktree. Tests do not require
Roblox, live screen/input, an audio device, or Discord. Optional real OCR engines may
be conditionally skipped; a skip is not end-to-end proof.

## TEST SHAPES

- Pure decision and value-object tests.
- Synthetic numpy image/audio tests.
- Tracked real screenshot/OCR incident regressions.
- Filesystem tests using `tmp_path`.
- Narrow I/O wrapper tests using injected functions or local `monkeypatch`.
- Optional engine tests guarded with `pytest.mark.skipif`.

Use `rg -n subject_or_incident tests` instead of maintaining a duplicated per-file
inventory.

## CONVENTIONS

- Name the invariant: `test_<subject>_<expected>`.
- Cite the H incident or observed failure beside real regressions.
- Prefer the smallest pure decision surface. Inject a narrow external action when
  orchestration is otherwise difficult to test.
- Keep `monkeypatch` local and assert exact calls/arguments; do not build a fake
  Roblox runtime.
- Use `tmp_path` for retention, refs, logs, and tessdata discovery.
- Synthetic thresholds normally come from `DEFAULT`; use a custom `Config` only for
  the boundary under test.
- Visual/OCR fixtures bracket both sides: target passes and the relevant
  false-positive/false-negative counterpart behaves correctly.
- Keep incident fixtures immutable; add a new named fixture for new evidence.

## WHAT NOT TO DO

1. Do not capture a live screen, send real input, open Roblox, access Discord, or
   require physical audio hardware in the default suite.
2. Do not delete or relax an incident regression merely to make a new approach green.
3. Do not hardcode obsolete coordinates or copied production defaults.
4. Do not cross-compare OCR preprocess passes as one stream.
5. Do not treat an optional-engine skip as a passing integration result.
6. Do not use broad `Bot` mocks to claim runtime coverage.

## FIXTURE RULES

- Regression fixtures live under `tests/fixtures/`; selected tracked datasets live
  under `assets/*.json`.
- Machine-local PNG/WAV files under `assets/` are runtime inputs, not test fixtures.
  A fresh-checkout test must not depend on them.
- OCR fixture tests may load real engines and dominate runtime. Iterate on focused
  tests, then run collection and the complete suite.
- Runtime tracker templates belong to local `assets/markers/`; intentionally tracked
  incident scenes belong under `tests/fixtures/`.

## COMMANDS

```powershell
uv run pytest -q tests/test_states.py
uv run pytest -q tests/test_harvester.py tests/test_vision.py
uv run pytest -q tests/test_ocr.py tests/test_ocr_fixtures.py
uv run pytest -q tests/test_reentry.py tests/test_reentry_remote.py tests/test_remote_aim.py
uv run pytest -q
```

Always state whether a verification command completed. No output before a timeout is
inconclusive.
