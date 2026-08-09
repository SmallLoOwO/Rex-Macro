# Domain Docs

How the engineering skills should consume this repo's domain documentation
when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, if it exists.
- **`docs/adr/`**, if it exists — read ADRs that touch the area you're about
  to work in.

Neither exists yet in this repo. **Proceed silently** — don't flag their
absence, don't suggest creating them upfront. The `/domain-modeling` skill
creates them lazily when terms or decisions actually get resolved.

## This repo's existing decision record

This repo already has an equivalent to an ADR log:
[`docs/incidents.md`](../incidents.md) (live-run incident findings, cited as
`Hxxx` throughout `AGENTS.md`) and one-off design docs under
`docs/superpowers/specs/`. Treat these as authoritative prior decisions —
check them before proposing something that contradicts an already-diagnosed
incident, same as you'd check an ADR.

`AGENTS.md` at the repo root remains the primary operating contract (source
of truth order, non-negotiable runtime rules); this file only governs how
domain-modeling-style skills should layer `CONTEXT.md`/ADR conventions on
top of it once those files start getting created.

## File structure

Single-context repo (this repo — one Python package, no monorepo signals):

```
/
├── CONTEXT.md            (not yet created)
├── docs/adr/             (not yet created)
├── docs/incidents.md     (existing decision/incident record)
└── miningbot/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor
proposal, a hypothesis, a test name), use the term as defined in
`CONTEXT.md` once it exists. Until then, match the terminology already used
in `AGENTS.md` and `docs/incidents.md` (e.g. `harvest`, `reentry`, `sweep`,
`chill`) rather than inventing synonyms.

## Flag ADR conflicts

If your output contradicts an existing incident finding in
`docs/incidents.md` or a shipped design in `docs/superpowers/specs/`,
surface it explicitly rather than silently overriding.
