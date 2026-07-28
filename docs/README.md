# Documentation map

Use this index to distinguish current guidance from point-in-time evidence. Current
code, tests, and `miningbot/config.py` still outrank every document.

## Current references

| File | Purpose |
|---|---|
| `../AGENTS.md` | repository-wide operating contract and hard runtime rules |
| `../CLAUDE.md` | thin compatibility entrypoint to `AGENTS.md` |
| `game-mechanics.md` | game-domain observations that affect automation decisions |
| `manual-sampling.md` | manual sampling and re-entry calibration procedure (the R-key window was retired 2026-07-17; capture via the remote-control 📷) |
| `web-ui-guide.md` | web intervention/settings/history UI: Tailscale setup, operator walkthrough, troubleshooting, agent notes |
| `../assets/README.md` | tracked datasets versus machine-local runtime assets |
| `../tests/fixtures/README.md` | live-capture fixture library index; each subdirectory has its own README with thresholds and two-sided brackets |
| `incidents.md` | append-only H-series runtime evidence, causes, and regressions |
| `open-detection-issues.md` | measured-but-unfixed detection/aim gaps (D-series); move an entry into `incidents.md` once it ships |

## Historical documents

The following files preserve design intent or old investigation context. They are
not current behavior specifications and must not override code or tests:

- `HANDOFF.md`
- `HANDOFF_false_positives.md`
- `opencode-delegation-manual.md`
- `superpowers/plans/**`
- `superpowers/specs/**`（唯一例外：`superpowers/specs/2026-07-26-web-ui-design.md`
  對應已落地的網頁 UI 程式碼，是現行設計參考；仍以 `AGENTS.md` 與程式為準）
- `superpowers/handoffs/**` — 進行中的交接文件，**結案後即為歷史**。
  `2026-07-26-h061-web-ui-startup-hang.md` 的根因判定（import lock 死結）**已被推翻**，
  正確版本見 `incidents.md` H061。

A completed checkbox is evidence that work was planned, not proof that it shipped.
Use the implementing diff and regression tests when reconstructing history.

## Maintenance rule

- Put new runtime rules in `AGENTS.md` only when violating them can damage safety or
  correctness.
- Put detailed failure evidence in `incidents.md`, not in `AGENTS.md` or `CLAUDE.md`.
- Keep volatile totals, timings, file lengths, and generated inventories out of
  guidance; obtain them from fresh commands.
- When a current reference becomes obsolete, move or label it historical instead of
  leaving contradictory prose in place.
