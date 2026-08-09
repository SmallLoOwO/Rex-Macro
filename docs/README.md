# Documentation map

Use this index to distinguish current guidance from point-in-time evidence. Current
code, tests, and `miningbot/config.py` still outrank every document.

## Current references

| File | Purpose |
|---|---|
| `../AGENTS.md` | repository-wide operating contract and hard runtime rules |
| `game-mechanics.md` | game-domain observations that affect automation decisions |
| `manual-sampling.md` | manual sampling and re-entry calibration procedure (the R-key window was retired 2026-07-17; capture via the remote-control 📷) |
| `web-ui-guide.md` | web intervention/settings/history UI: Tailscale setup, operator walkthrough, troubleshooting |
| `data-collection-pipeline.md` | data collection workflow for training and calibration assets |
| `../assets/README.md` | tracked datasets versus machine-local runtime assets |
| `../tests/fixtures/README.md` | live-capture fixture library index; each subdirectory has its own README with thresholds and two-sided brackets |
| `incidents.md` | append-only H-series runtime evidence, causes, and regressions |
| `open-detection-issues.md` | measured-but-unfixed detection/aim gaps (D-series); move an entry into `incidents.md` once it ships |

## Maintenance rule

- Put new runtime rules in `AGENTS.md` only when violating them can damage safety or
  correctness.
- Put detailed failure evidence in `incidents.md`, not in `AGENTS.md`.
- Keep volatile totals, timings, file lengths, and generated inventories out of
  guidance; obtain them from fresh commands.
- When a current reference becomes obsolete, move or label it historical instead of
  leaving contradictory prose in place.
