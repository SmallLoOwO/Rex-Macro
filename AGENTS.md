# AGENTS.md — PROJECT KNOWLEDGE BASE

This is the repository-wide operating contract. Keep it current and focused on
decisions that are unsafe to rediscover. Volatile inventories such as test totals,
file lengths, and ore counts belong in command output, not guidance.

## HOW TO USE THIS FILE

- **Applies to every coding agent and human working in this repo** — Claude Code,
  Codex, Cursor, aider, or a person with an editor. Nothing here is tool-specific.
- **Nearest file wins.** `miningbot/AGENTS.md` and `tests/AGENTS.md` add local rules
  for their directories; this root file covers everything else.
- `CLAUDE.md` is a thin Claude Code entrypoint that imports this file. Runtime truth
  lives here and in the code — never add a second copy that can drift.
- A direct instruction from the user in the current session overrides this file. If
  it also contradicts a NON-NEGOTIABLE RUNTIME RULE below, say so before acting.
- Write code and comments to match the surrounding file. Commit messages and
  user-facing prose are in Chinese; identifiers, log keys, and error strings stay
  verbatim.

## OVERVIEW

Windows-only Python 3.11+ automation bot for Roblox REX. It mines, maintains D5
boost, rerolls or keeps D4 events, detects rare-ore chill audio, aims and fires D3,
verifies success from chat, exposes Discord controls, and handles mine reset through
manual, remote, or calibration-gated automatic re-entry.

`miningbot/main.py` is the I/O orchestrator around a state machine and bounded
subflows. Search current symbols; do not rely on historical line numbers, test
counts, or completed plan checkboxes.

## SOURCE OF TRUTH

When sources disagree, use this order:

1. Current code, tests, and `miningbot/config.py` defaults.
2. The non-negotiable rules here plus evidence in `docs/incidents.md`.
3. Current references: `docs/game-mechanics.md`, `docs/manual-sampling.md`, and
   `assets/README.md`.
4. A design or plan only when implementing tests/code confirm it shipped.
5. `docs/HANDOFF*.md`, `docs/superpowers/**`, and the retired delegation manual as
   historical context only. See `docs/README.md`.

`CLAUDE.md` is a thin compatibility entrypoint to this contract, not another copy
of runtime truth.

## STRUCTURE

```text
miningbot/
  main.py                   Bot orchestration and runtime state
  config.py                 Config/Region and DEFAULT (incl. `detection_disabled_tiers`, panel hues, all coordinates/thresholds)
  states.py                 top-level FSM and transition policies
  harvester.py              harvest decisions and D2/D3 wrappers
  vision.py / ocr.py        detector and OCR logic plus adapters
  audio.py                  chill/reset scoring and loopback capture
  game_data.py              active-world events/ores/classification, detection tier gate (`TIER_HUES`, `set_detection_disabled_tiers`, `classify_found_ore` per-tier gate, `format_detection_status`)
  reentry*.py               automatic and remote re-entry decisions
  teleport_board.py         re-entry teleport board detector (suggest only, never auto-click)
  corpus.py                 re-entry corpus folder outside snapshot retention
  build_reentry_dataset.py  offline: ledger rescue, dataset.jsonl, --eval report
  remote_aim.py             Discord-assisted harvest alignment
  roblox_menu.py            menu OCR decisions
  sampler.py                numbered manual-sample writing (R-key Tk UI retired 2026-07-17)
  measure_tier_hues.py      offline/live: panel row-colour tier hues; the fixed sampling protocol for `TIER_HUES` (D13)
  notify.py                 Discord HTTP API and async notifications
  discord_commands.py       pure Discord command parsing
  web_protocol.py           WebSocket message dataclasses, parsers, coord validation
  web_ipc.py                race routing key, PendingReplies, FallbackState
  web_server.py             FastAPI app, WebSocket endpoint, WebIPCThread, HTTP routes
  web_sink.py               EventLog → WebSocket broadcast sink
  web_config_whitelist.py   player-editable Config field whitelist (4 fields)
  web_config_persistence.py config_overrides.json load/save/apply
  web_static.py             HTML renderers (player settings, intervention, history, annotate)
  web_annotation.py         annotation schema + symptom/rarity helpers
  web_history.py            episode/snapshot/annotation three-tier loaders
  diagnostics.py            logging, snapshots, retention
  metrics.py                bounded latency percentiles
  preflight.py              pure startup warning policy
  __main__.py               splash entrypoint for pythonw/batch launch
tests/                      unit, synthetic, and tracked fixture regressions
assets/                     tracked JSON plus machine-local runtime assets
docs/                       current references, incidents, historical designs
logs/                       gitignored runtime evidence and diagnostics
*.mcr                       original human-recorded Roblox macros
啟動挖礦bot.bat             preferred no-console launcher
```

Only JSON datasets and documentation under `assets/` are guaranteed to be tracked.
Most runtime PNG/WAV files are machine-local. Fresh-checkout tests must use tracked
`tests/fixtures/` data or generate synthetic input.

## WHERE TO LOOK

| Task | Read first | Then inspect |
|---|---|---|
| Runtime/startup | `main.Bot.run`, `Bot._on_enter`, `Bot._tick` | `miningbot/__main__.py`, preflight tests |
| Top-level state | `states.py`, `tests/test_states.py` | every direct `self.state =` site |
| Coordinates/modes/hotkeys | `config.py` | config and incident regressions |
| Rare-ore harvest | rules below, latest matching H incident | `harvester.py`, `_sweep_for_tracker`, `_tick_harvest`, `_harvest_success` |
| D3 / scan sequences | `harvester.py`, the original root `.mcr` recordings | equipment toggles, settle calls, fixed key and hold timing |
| D4 keep/reroll | H049, `miner.plan_d4` | cache must be newer than the last action; unknown text needs two-sample confirmation |
| Tracker detection | H039/H040/H057, `tests/test_vision.py` | `vision.find_tracker`, `find_tracker_near`; bracket true positives against equipment/UI negatives; H057 blob rescue and re-anchor |
| Chat verification | H014/H020/H032/H041/H054/H055 | `ocr.ChatLedger`, `read_text_multi`, `_verify_chat_ocr`, `ocr.baseline_saw_found_history`, `ocr._strip_ui_residue` |
| Chill/reset audio | `audio.py`, `tests/test_audio.py` | `main._on_audio_*` |
| Mine reset | reset/capacity incident evidence | `states.py`, `_banner_ocr_loop`, `_update_reset_complete` |
| Re-entry | newest implemented re-entry specs | `reentry.py`, `reentry_remote.py`, `_tick_reentry*`; every path bounded, ledger written, pitch/zoom restored |
| Discord controls | command/parser tests | `main._poll_discord`, `notify.py`; incl. `重開`/`restart` (`_schedule_restart`, `_consume_pending_restart`, paused-only gate) |
| Web UI / WebSocket IPC | `docs/superpowers/specs/2026-07-26-web-ui-design.md`, `miningbot/AGENTS.md` Web UI layer | `web_*` modules, `main._web_*`, `Bot._execute_remote_fire_from_web`, `Bot._rr_click_from_web` |
| Re-entry corpus / dataset | `corpus.py`, `build_reentry_dataset.py` | `Bot._rr_save_corpus`, `<log_dir>/corpus/reentry/`, `dataset.jsonl`, `--eval`; MSIX dual-path resolution lives only in `build_reentry_dataset` |
| Teleport board prediction | `teleport_board.py` docstring (HSV percentile table) | `Bot._predict_teleport_board`, `reentry_predict_min_score`; suggestion only, never auto-click |
| World/ore data | `game_data.py`, `tests/test_game_data.py` | `fetch_ores.py`, tracked JSON datasets; active registry, low/high tier conflicts, JSON sync |
| Panel tier hues (`TIER_HUES`, `panel_*_hues`) | `docs/open-detection-issues.md` D13, `tests/fixtures/panel_tiers/README.md` | `measure_tier_hues.py` (fixed sampling protocol — **per-row median, never mean**), `tests/test_panel_tier_hues.py`; gradient is V-only so H is position-independent, but grey rows (Common/Layer) have no hue at all |
| Manual sampling / calibration | `docs/manual-sampling.md` | `sampler.py`, `calibrate_surface.py` (capture via remote-control 📷; the R-key window is gone) |
| Logs/snapshots | `diagnostics.py`, `docs/incidents.md` | categorized runtime snapshots |

Read `miningbot/AGENTS.md` for package-local rules and `tests/AGENTS.md` for test
conventions.

## NON-NEGOTIABLE RUNTIME RULES

1. Use `SW_MAXIMIZE`, never `SW_RESTORE`; set DPI awareness before the first
   screenshot or GUI operation.
2. Coordinates are calibrated for **Roblox in fullscreen** on a 1920×1080 screen
   (client rect `0,0-1920,1080`, so screen coordinates equal client coordinates;
   recalibrated 2026-07-28). The previous baseline was a maximized window with the
   Windows taskbar visible (client `1920×1001` at origin `0,29`). Switching between
   the two is a pure translation, no scaling: top-anchored UI moves by ∓29px,
   bottom-anchored UI by ±50px, horizontal unchanged; centred overlays such as the
   Esc menu re-lay-out and must be re-measured, not translated. Recalibrate from
   real frames instead of adjusting by eye.
3. Tool keys toggle equipment. Never press D1 blindly; use `vision.slot_selected`
   over `d1_slot_region`.
4. Camera yaw uses `,`/`.` through verified rotation. Fine pitch/aim uses right-button
   drag with settle and frame-diff validation. Plain `moveRel` does not rotate REX.
5. D3 is always `2 → 0.15s → 3 → 0.3s → hold-click 0.4s → 0.5s`.
6. Harvest success requires new rare/special chat evidence. Tracker disappearance
   alone means `RESWEEP`, never success. Preserve episode `ChatLedger` and late
   confirmation. Count-difference signals are void when the baseline OCR saw no
   has-found history: chat auto-hides after ~15s idle, and old lines re-displayed
   by a later message are not this shot's evidence (H054). `chat_region` overlaps
   the persistent ore panel, so every chat OCR ends with panel text; strip trailing
   UI residue at the comparison entry point (`ocr._chat_lines`) or the anchor-based
   signals are dead by construction. Do not shorten the region instead — the panel
   is drawn *over* the newest chat line, not below it (H055). An empty baseline
   confirms nothing through the last-line or tail signals.
7. Capacity at 100% never enters `RESET_WAIT`; only the reset banner may stop mining.
8. Tracker masks remain per HSV range and center confirmation is hue-independent.
   Use real in-game crops, keep the configured candidate ROI, and never run
   full-frame shape matching inside the sweep.
9. Background workers publish pending flags or caches. Game input is consumed only
   on the main loop.
10. Tk text must not contain astral emoji (`> U+FFFF`) on this Tcl/Tk 8.6 machine;
    pass UI text through `_bmp_safe` and use BMP symbols.
11. Global hotkeys use `GetAsyncKeyState`: Ctrl+Q pause-only, Q
    pause/resume/clear/skip startup, F12 quit. The R sampler window was retired on
    2026-07-17 (screenshots via the remote-control 📷, pitch via the re-entry `仰角`
    command); do not reintroduce a hotkey for it. Do not use `keyboard` and never send
    Esc during manual driving.
12. `reentry_mode` is `off`, `remote`, or `auto`; the default comes from `Config`.
    Automatic mode is calibration gated. Every path is bounded, falls back to
    `NEEDS_HUMAN`, and restores pitch/zoom before finalization.
13. The web UI (`web_*` modules, `Bot._web_*` integration) exposes only the
    fields in `WEB_CONFIGURABLE_FIELDS` to players; thresholds, ROI, and detection
    params are AI-agent-only via direct `config.py` edits — **exception**:
    `detection_disabled_tiers` (2026-08-02, user-specified: changes frequently during
    play, controls which ore tiers count as "rare" for all detection systems). WebSocket IPC uses
    routing-key first-wins (`flow:episode_id`; second reply for the same key is
    dropped). **Connection count never gates a push** (2026-07-31, user-specified):
    every intervention flow pushes its frames into the registry replay buffer
    regardless of `is_fallback()`, posts the URL on Discord, and hands over to Discord
    only when the player presses 🔀 — the player is summoned *by* that Discord message,
    so nobody is ever connected at push time. `web_fallback_grace_s` now only colours
    the PING wording, never a routing decision.
    Player taps restore to native coords **client-side** (`web_static.sendClick`);
    the server only thin-validates `x ∈ [0,1920)`, `y ∈ [0,1080)` (`parse_fire_at_payload`).
    Auto-collected fixtures (`_save_auto_fixture`) are best-effort: write failures
    log and swallow, never break the main loop.
14. Reentry web intervention runs **after** the eight-direction sweep, never before:
    the teleport board is almost never in the opening view, so a single current frame
    gives the player nothing to click. `_rr_sweep_capture` runs once and feeds both
    paths (web push and Discord images) — never sweep twice for the web. A web
    `reentry_click` carrying `dir` (1-8) must rotate to that direction before
    clicking; if rotation is eaten, abandon the click rather than clicking blind.
    Panel buttons (`sweep`/`reroll`/`skip`) are picked up inside the wait loop, not
    by `_consume_web_pending` — the main loop is blocked there. The wait is
    **unbounded** (2026-07-30, user-specified): no join grace, no budget. The only
    switch back to Discord is the 🔀 reaction on the "網頁在等你點" ping
    (`_arm_web_escalate_reaction`); every fixed window from 120s to 900s just moved
    the same race later — RR#34 pushed at 18:28:23, the 120s grace expired at
    18:30:23 and wiped the replay buffer, the player opened the page at 18:41:45 and
    saw a blank panel. Because it never times out, the abort conditions in
    `_await_web_action` are load-bearing: `_mine_resetting` (stale frames)
    and `_running`/`paused` (F12 must be able to stop the bot).
    A non-`descended` click does **not** re-sweep unless the frame actually moved
    (`_rr_last_click_moved`, 2026-08-01): a missed or eaten click leaves the player
    standing in the same spot, so the previous eight frames are still valid and
    re-sweeping only costs 8 rotations / ~25s. `moved_unconfirmed` hands over to
    `awaiting_confirm` instead of retrying — that branch already pushed the confirm
    panel. `awaiting_confirm` itself pushes the marker/landing evidence frames to the
    web with `mode="confirm"`; its summary must quote the **measured**
    `depth_m`/`layer_seen` (`reentry_remote.format_landing_evidence`), not the
    declared `sticky_layer`, and must not offer `重骰` as the answer to doubt —
    rerolling returns to the surface and restarts the whole episode while the player
    is already inside the mine. Broadcast the result **before** pushing those frames:
    `_broadcast_intervention_result` ends the replay buffer.
15. The same shape now governs the two harvest intervention flows (2026-07-31):
    - **Giveup candidate list** — `_push_web_aim_candidates` pushes unconditionally;
      the Discord candidate overlays are **held** in `_web_held_aim` and only sent by
      `_release_web_held_aim(send=True)` when the player presses 🔀 on the NEEDS_HUMAN
      PING (picked up in `_consume_web_pending`, which is where NEEDS_HUMAN ticks).
      The chat/backpack before-after crops still go out immediately: they are the
      evidence for *why* it gave up and have no web equivalent.
    - **Manual survey (`手動`)** — D2 rescan and the direction capture run **first**,
      then the raw frames go to the web and the grid overlays are held for Discord.
      The web click queues `_pending_aim` (kind `point`) so it goes through
      `_execute_remote_fire`'s realign → rescan → refind sequence; it must not borrow
      `_handle_web_aim_click`, which drops replies while `_aim_busy` is set.
      It captures **mid + up + down** (24 frames) whenever pitch is calibrated,
      gated on `plan_pitch_layers(True, …)` and deliberately **not** on
      `sweep_pitch_enabled` — that flag governs the automatic failure path, while
      `手動` is an explicit player request (harvest 144: the ore sat above near-miss
      candidate ⑨, and a mid-only handoff made it unreachable). `_handle_aim_reply`
      accepts `5U`/`5D` under the same calibration-only gate, or the images would be
      sent to a syntax that answers 看不懂. Per-layer: re-press D2 (a full layer takes
      ~30s and trackers expire), budget restarts after the rescan, an eaten drag skips
      that layer, and the survey ends with `_pitch_goto_layer(…, 0)` so
      `ctx.pose_pitch_layer` is honest for the next `plan_alignment`.
    Both use the routing key `harvest:<harvest_id>`, so a later push replaces the
    earlier panel — release the held images before pushing a new batch.
16. **One session, one worktree.** Before the first edit of any session, open
    or create a git worktree on a dedicated branch (`EnterWorktree`, or
    `git worktree add ../<repo>-<task> -b <task>`). The primary working
    directory is shared between sessions; editing it in parallel means the last
    commit silently overwrites the other's work. Evidence: the orphan worktree
    `sad-proskuriakova-705b24` at detached `408069b` held the only copy of the
    H055 fix for three days (2026-07-22); `git fsck --lost-found` lists two
    dangling commits (`7082eaeb`, `3c857eea`) of unrecoverable session work.
    A `SessionStart` hook (`.claude/hooks/worktree-enforce.ps1`) injects a
    warning when the primary tree is dirty and a sibling worktree exists; the
    hook is silent inside a linked worktree. Merge protocol: tests green
    inside the worktree → commit there → merge into the integration branch →
    remove the worktree (`ExitWorktree` / `git worktree remove`). `.claude/
    worktrees/**` is already gitignored, so the Grep tool cannot see inside
    worktrees — when checking "is this fix already done elsewhere" also run
    `git worktree list` and scan dangling commits (`git fsck --lost-found`).

## DEVELOPMENT WORKFLOW

- Start with `git status --short`. If another session is active (unrelated
  changes you did not write, or a sibling worktree exists), open a new
  worktree before editing — see NON-NEGOTIABLE RUNTIME RULE 16.
- Use `rg` and symbol names rather than stale line numbers.
- Test pure decisions first. Default tests must not require Roblox, devices, or live
  Discord.
- Visual/OCR threshold changes require real fixtures and a two-sided bracket. Cite
  the relevant H incident.
- Put every runtime coordinate, threshold, interval, and mode in `Config`.
- Preserve Chinese calibration comments; they record provenance.
- Every completed task must end with a commit: run the full test suite green
  first, stage only the files the task touched, and write a Chinese commit
  message describing the change (cite the H incident id when applicable).
- **Every new feature, fix, or behavioural change must include logging** that lets
  a future agent diagnose failures from logs alone — without re-reading the code to
  guess what happened. At minimum: log the decision point (what was chosen and why),
  the key variables that drove it, and the outcome. Log the fallback/early-exit path
  too, not just the happy path — "it fell back to single ref" is more important to
  trace than "8 refs captured." Use `self.log_harvest` for episode-scoped events
  (keyed by `harvest_id`) and `self.logger` for one-off warnings. When in doubt,
  over-log: a redundant line costs nothing; a missing line costs a full re-investigation.
- **Keep docs in sync.** When a task adds or changes a runtime rule, Discord
  command, web-configurable field, config parameter, or detection/decision path,
  update the relevant doc files **in the same commit**. Stale docs are worse than
  no docs — the next agent trusts them and builds on wrong assumptions. Checklist
  by change type:

  | Changed | Update these files |
  |---|---|
  | Discord command / remote button | `AGENTS.md` WHERE TO LOOK, `docs/web-ui-guide.md` command tables, `main.py` help text |
  | Web-configurable field (WEB_CONFIGURABLE_FIELDS) | `AGENTS.md` rule 13 + STRUCTURE, `miningbot/AGENTS.md` invariant 11, `docs/web-ui-guide.md` settings section |
  | Config parameter (config.py) | `AGENTS.md` WHERE TO LOOK "Coordinates/modes/hotkeys" row + STRUCTURE |
  | Detection / classification logic | `AGENTS.md` WHERE TO LOOK + NON-NEGOTIABLE RULES, `miningbot/AGENTS.md`, `docs/game-mechanics.md` |
  | Runtime rule (safety/correctness) | `AGENTS.md` NON-NEGOTIABLE RUNTIME RULES + CURRENT RISK AREAS |
  | Incident / threshold tuning | `docs/incidents.md` (new H entry) or `docs/open-detection-issues.md` (new D entry) |
  | Panel hue / tier data | `game_data.py` TIER_HUES comment table, `config.py` panel_*_hues, `harvester.py` + `vision.py` hue comments |
- Do not push, switch branches, delete runtime evidence, or mutate
  Roblox/Discord unless the user explicitly requests it.
- The primary agent owns integration, diff review, and verification. Delegate to a
  subagent only when the work splits cleanly and cannot collide on shared files —
  `main.py` and `config.py` are touched by almost every task, so parallel work there
  is a merge fight, not a speedup. This holds for whichever agent tool you are
  (there is no mandated delegation flow any more; the retired opencode manual in
  `docs/` is historical).
- Another session may be editing the same files. Re-check `git status --short` before
  staging; if the diff contains hunks you did not write, stage only your own
  (`git diff -U3 -- <file>` → filter hunks → `git apply --cached`) instead of
  committing someone else's unfinished work.

## COMMANDS

```powershell
uv sync --locked
uv run pytest --collect-only -q
uv run pytest -q
uv run ruff check . --no-cache
uv lock --check

uv run python -m miningbot.main
pythonw -m miningbot
uv run python -m miningbot.fetch_ores
uv run python -m miningbot.fetch_trackers
uv run python -m miningbot.capture_template boost
uv run python -m miningbot.measure_tier_hues            # 面板階級色相（D13；抓當下畫面或給 PNG）
uv run python -m miningbot.calibrate_surface --import NNN
uv run python -m miningbot.calibrate_pitch
uv run python -m miningbot.build_reentry_dataset --rescue
uv run python -m miningbot.build_reentry_dataset --eval
```

Sandboxed `python.exe` may fail with an execution-permission error on this managed
Windows workspace. Re-run through the approved `uv` path before diagnosing code.

## LIVE-RUN TROUBLESHOOTING

- Resolve the log root from `Config.log_dir`; do not assume the repo `logs/`.
- ⚠ `pythonw -m miningbot` (the `.bat` launcher) runs the Microsoft Store / MSIX
  Python, so writes to `%LOCALAPPDATA%\RexMacro\logs` are virtualized to
  `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\Local\RexMacro\logs`.
  The path printed inside the log will not exist as written; live evidence is in the
  LocalCache copy. A `uv run` start is unaffected. That interpreter is also a
  different environment from `.venv` — H061 was exactly this (see `docs/incidents.md`).
- ⚠ The LocalCache copy's **directory metadata goes stale**: `Get-ChildItem` can show
  an mtime/size hours behind the real content. Always judge "how far did the last run
  get" from `Get-Content -Tail` timestamps, never from directory times, and never
  conclude "nothing after T" from a narrow time-window grep.
- Read `miningbot.log` first, then `actions.log`, `harvest.log`, `discord.log`, and
  the categorized snapshots. Harvest evidence is filed under the **numeric**
  `harvest_id` (`118`), which is a different namespace from the `Hxxx` incident ids.
- Adjust a threshold or coordinate only from real frames/crops plus the matching H
  incident. Never loosen a conservative verdict or delete an incident regression to
  make one failing fixture pass.

## CURRENT RISK AREAS

- `main.py` remains the main complexity hotspot and has intentional direct state
  assignments outside the central transition path.
- Remote aim/re-entry and zoom need more live-game evidence than pure tests provide.
- `scan_confirm_mode` is now `enforce` (H073, 2026-08-02). harvest 168 實機：
  進場 D2 click 被吃、掃描沒觸發，但 `scan_confirm_mode` 原為 `off` 使
  `_confirm_scan` 永遠 return True → bot 無法分辨「沒稀有礦」與「掃描沒觸發」→
  白掃 8 方位全空 → giveup。現改成 enforce + `_harvest_scan_guard`（比照
  `_harvest_boost_guard` 的 self-heal 模式）：進場 `_confirm_scan` 偵測 badge
  缺失時自動 retry；sweep 每方位的 `_harvest_scan_guard` 持續檢查效果列 Local
  徽章，缺了就補掃再繼續（不交人工）。**需實機驗證**：下一輪 log 預期看到
  `[scan-confirm] enter ok=True/False` 及 `scan guard: 無 Local 徽章 -> 補掃 D2`。
  另修復 `_boost_needs_refresh` 偽陽性：全螢幕校準後使用次數 icon 的 edge match
  score 從 0.19 升到 0.42（剛過舊門檻 0.40），boost guard 以為 D5 還在而不補。
  `boost_edge_threshold` 0.40→0.55（true boost 0.77+ vs 次數 icon 0.42-）。
- **`giveup_rescue_observe` is on (observation mode) and needs a human decision to
  leave it.** Path B of the give-up rescue judges "this ore was already banked" but
  still hands over to the human; every hit is appended to
  `<log_dir>/rescue_observed.json`. **When that file reaches
  `giveup_rescue_observe_target` (10) entries, lay the records out for the user and
  ask whether to switch to automatic** (`giveup_rescue_observe = False`). Two bugs
  found on 2026-07-31 both pointed the same way — claiming "already banked" when it
  was not, which silently abandons a real rare ore — and both slipped past the tests,
  hence the observation period. Do not flip it without showing the evidence first;
  `scan_confirm_mode` above is what happens when nobody is reminded.
- **`harvest_entry_panel_check` short-circuits to NEEDS_HUMAN** (2026-08-04).
  When chill triggers and the NORMAL panel already has a whitelisted (Exotic+) ore,
  the bot **skips the entire sweep flow** (prepare_scan / D2 cooldown / reference
  rotation / 8-direction sweep) and goes straight to NEEDS_HUMAN — saving ~87s on
  cases where the pickaxe already collected the ore before chill (harvest 184: 87s
  all-empty sweep). The short-circuit uses the correct `_on_enter` return-state pattern
  (same as REENTRY focus-fail degradation), NOT `_harvest_giveup` — the old short-circuit
  (pre-2026-08-02) called `_harvest_giveup` inside `_on_enter(HARVESTING)` which returned
  None → `resolve_state_transition` overrode it back to HARVESTING → state-commit bug
  (harvest 171). The 2026-08-02 fix removed the short-circuit entirely; the 2026-08-04
  fix restores it with the correct return pattern. Double-chill does not change the path
  (still short-circuits), only the notification text — sweep reliability is already
  compromised by D5 FOV drift during these episodes (184: found tracker dir=0 but verify
  failed, resweep + 3 layers all empty). Each hit is appended to
  `<log_dir>/panel_check_observed.json`.
  **When that file reaches `panel_check_observe_target` (10) entries, lay the records
  out for the user and ask whether to switch to automatic** (skip NEEDS_HUMAN, resume
  mining directly). Requires `_panel_zeroed_at` to be set — if the panel clear at MINING
  entry failed (H070/H071), the check is bypassed entirely. Panel clear now retries
  (`panel_clear_max_retries`, 2026-08-04: re-does the full click→type→verify sequence
  up to N times, matching `_rotate_verified`'s self-heal pattern; 2026-08-05 raised
  from 3→7 per user request "多增加點選的次數"). **When all retries are exhausted the
  bot degrades to NEEDS_HUMAN** (2026-08-05, user-specified: "無論如何都要把它清空…
  如果還是沒有清理成功，則直接轉交人工") — MINING entry, harvest-resume tail, and the
  manual `清空` command all hand off instead of silently continuing with an untrusted
  panel. The old "路 B 將跳過下一場" silent-skip behavior is removed: handing off
  rebuilds the trust basis (player clears manually → `_panel_zeroed_at` set next round).
- **Double-chill detection via banner color** (2026-08-02, threshold fixed 2026-08-04).
  Audio cannot count two near-simultaneous chills (1.5s rolling window merges them), but
  the top banner text is discrete with a unique random RGB per spawn message. During
  MINING, each tick samples the banner text hue (`vision.banner_text_hue`); hue jumps
  are timestamped into `_banner_color_changes`. At HARVESTING entry, **≥2 jumps within
  `double_chill_window_s`** sets `_double_chill_detected` — NOT `any()` (which fires for
  a single chill's 1 jump, blocking the panel-check short-circuit forever). Log validation
  (2026-08-04): 89 banner changes across one day, 9 clusters of ≥2 within 3s, 3 matched
  actual harvest entries (172/174/178, all sweep-empty → human). When the flag is set:
  (1) after harvesting the first ore, a bonus sweep is forced even with no visible
  tracker, and (2) if the bonus sweep is empty, the bot hands to human instead of
  resuming MINING. **Needs live-game validation**: verify that banner text hue is sampled
  correctly and that double-chill episodes trigger the expected bonus sweep + human
  handoff.
- Machine-local PNG/WAV assets are not guaranteed in a fresh checkout; preflight
  must warn explicitly.
- Historical HANDOFF/design files are evidence, not a current backlog.
- Web UI pinch-zoom + tap and WebSocket half-open detection need live-game
  validation before being trusted on long unattended runs; the regression suite
  covers the wire protocol and pure logic, not real mobile-browser behavior.

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature-slug>/issues/`, matching the
convention already in use. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root (neither created yet;
`docs/incidents.md` is the existing decision record). See
`docs/agents/domain.md`.
