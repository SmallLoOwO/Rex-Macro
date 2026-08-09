# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files under `.scratch/`. This
matches the convention already in use across `pitch-relative-nudge`,
`prechill-rescue-reconcile`, `sweep-pitch-enable`, `web-agent-tuning-loop`.

`.scratch/` is untracked (gitignored) working state, not committed history.
Once a feature ships, its narrative belongs in `docs/incidents.md` (if it's a
live-run fix) or a `docs/superpowers/specs/*.md` design doc (if it's a
forward design) — not in `.scratch/`.

## Conventions (as observed, not the skill's generic default)

- One feature per directory: `.scratch/<feature-slug>/`
- Implementation issues are one file per ticket at
  `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- No `spec.md` inside `.scratch/`. The design/spec lives at
  `docs/superpowers/specs/<date>-<feature>-design.md` and the issue file
  links to it directly.
- Each issue file: title line, `**What to build:**` prose, explicit
  behavior-boundary bullets ("都要照舊，不可退步"), `**Blocked by:**` line,
  `**Status:**` line, then a checklist of externally observable acceptance
  criteria (not internal call/parameter checks).
- Status strings seen: `ready-for-agent` (see `triage-labels.md` if the
  `triage` skill is installed — it wasn't at last setup, so this is
  informational only).

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/issues/`, creating the
directory if needed. If the feature needs a design doc first, write it to
`docs/superpowers/specs/` and link it from the issue instead of duplicating
it into `.scratch/`.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path
or the issue number directly.

## PRs as a request surface

Off. Do not treat GitHub PRs on `SmallLoOwO/Rex-Macro` as an issue-intake
surface for triage-style skills.
