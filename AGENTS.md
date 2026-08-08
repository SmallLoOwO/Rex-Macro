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
  web_config_whitelist.py   player-editable Config field whitelist (3 fields)
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
    play, controls which ore tiers count as "rare" for all detection systems).
    `sweep_pitch_enabled` was removed from the whitelist on 2026-08-05 (pitch-layer
    scanning disabled — see rule 15); the config field remains in `config.py` but is
    vestigial and has no effect. WebSocket IPC uses
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
      It captures **mid only** (8 frames) — pitch-layer scanning was disabled on
      2026-08-05 (user request: "多移動多錯又花多時間"), so `plan_pitch_layers`
      always returns `[]` and the survey no longer adds up/down layers.
      `_handle_aim_reply` no longer accepts `5U`/`5D` (the layer list is `("mid",)`
      only). Per-survey: re-press D2 (tracker expires after ~30s), budget restarts
      after the rescan.
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
    inside the worktree → commit there → merge into the integration branch
    (`feature/optimization-roadmap` — the branch the bot actually runs from)
    → remove the worktree (`ExitWorktree` / `git worktree remove`). **An
    unmerged worktree branch is invisible to the running bot** — the commit
    exists in git but the bot executes whatever is checked out in the primary
    working tree, so a fix left on a branch is a fix that doesn't exist.
    `.claude/ worktrees/**` is already gitignored, so the Grep tool cannot
    see inside worktrees — when checking "is this fix already done elsewhere"
    also run `git worktree list` and scan dangling commits
    (`git fsck --lost-found`).

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
- **After committing, merge into `feature/optimization-roadmap`.** The bot
  runs from this branch; a commit on a worktree branch that hasn't been
  merged is invisible to the running program. Before finishing a session,
  also check for other unmerged branches: `git for-each-ref --format='%(refname:short)
  %(committerdate:short)' refs/heads/ | while read b _; do n=$(git rev-list --count
  feature/optimization-roadmap..$b 2>/dev/null); [ "$n" -gt 0 ] && echo "$b: $n unmerged";
  done` — cherry-pick or merge any that belong, then delete stale branches
  (`git branch -d <name>` for merged, `git branch -D <name>` for orphaned).
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
- **STUCK 卡住偵測被 D4/D5/D2 冷卻動作掩蓋**（H082，2026-08-08）。使用者回報「W 有時
  中斷、角色卡原地，但 D4/D5/D1 都正常運作」——`_tick_mining` 舊版把「這幀有沒有
  執行任何動作」跟「角色有沒有在移動」畫等號（`action is not None` 就重置卡住計時
  器），D4/D5/D2 是冷卻到了就按、跟移動無關，卻持續把 60s 無進度的通報切碎/延後。
  實機 2026-08-01 01:15-01:53 抓到乾淨重現：D5 每隔數分鐘正常觸發，同時 STUCK 連
  跳 8 次，最後靠礦坑重置轉 REENTRY 才解除（STUCK 本身純通知，不會重按 W）。已改
  `miner.counts_as_progress`（只認 REFOCUS）＋`_on_enter(MINING)` 歸零
  `_last_boost`/`_last_progress`/`_stuck_notified`/`_boost_stall_notified`/
  `_prev_frame`（原本沿用進場前的舊時間戳，讓 `_check_boost_stall` 兩週內 132 筆
  警報幾乎全是假警報）。純決策修復、不動視覺門檻。同日已加 OS 層直接核對：
  `input_control.w_should_be_down()`/`w_actually_down()`（`GetAsyncKeyState`；
  注意 `restype` 要明講 `c_short`，不然預設 `c_int` 會讓「按著」判斷恆假）＋
  `Bot._check_w_os_state`，bot 認為 W 該按著但 OS 說沒按著就記 `[w-dropped]`。
  **需實機驗證**：下次角色卡住時 STUCK 應更快在接近真正卡住的時間點觸發、不再被
  D4/D5 節奏切碎；若同時出現 `[w-dropped]`，才是「鍵被外力放掉」第一次的 OS 層
  直接證據；若卡住但這條沒出現，代表問題不在鍵被吃，方向要往回打。見
  `docs/incidents.md` H082。
- **Reentry click-eaten detection** (2026-08-05). 礦坑重置後遊戲把玩家送到隨機地表
  （遠離傳送板），「Go to surface」按鈕傳送到傳送板附近。`_click_surface_verified`
  偵測不到傳送＝點擊被吃，但舊版無視此信號繼續走狀態錨（只看 Depth=Surface，不分
  正確/錯誤地表位置）→ 八方位掃描必空 → 每次要重骰。現 trigger=reset 且
  `teleported=False` 時跳過掃描直接重探（`_rr_click_eaten` 旗標 → probe loop 用
  `reentry_click_retry_wait_s`=3s 而非 20s）。trigger=manual 不受影響（H046(b)：
  人可能已在傳送板附近）。**需實機驗證**：log 應見 `[RR#] 開場：回到地表 ×N 皆未
  偵測傳送——點擊可能被吃` 後 3s 重探，而非 20s 後或白掃八方位。
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
  **H079/H080 (2026-08-08, user-confirmed root cause): the NORMAL panel re-sorts/
  re-renders itself continuously, independent of the search filter or any bot input —
  "cleared" is a one-frame snapshot, not a durable state.** 5 periodic backpack
  screenshots 30s apart, zero bot interaction between them, show a different row order
  every single time; `_panel_zeroed_at` from a verified `殘留 0 列：空` clear does not
  mean the panel stays that way — a permanently-held Exotic+ ore (Clovara, growing via
  passive pickaxe: 8→10 across one day) cycled back into the visible top rows within
  ≤4 minutes of a verified clear, re-triggering `harvest_entry_panel_check`'s
  short-circuit on essentially every chill for the same static ore. **User direction:
  the presence-check threshold/logic in `_episode_panel_gains` stays as-is** — the fix
  belongs on the "does `_panel_zeroed_at` still reflect reality right now" side, not
  the check itself. Same finding also puts H079's "TextBox lost interaction" conclusion
  in doubt: 8 retries ~7-13s apart sampling a panel that naturally doesn't repaint for
  tens of seconds to minutes can look identical to a genuinely stuck box at this
  sampling rate — don't trust the H079 log signal alone until the panel's own
  repaint trigger/period is known. See `docs/incidents.md` H080 before touching
  `_episode_panel_gains`, `_clear_panel_filter`, or `_panel_zeroed_at` freshness.
  **H081 fix (2026-08-08, needs live validation): `_clear_panel_filter_once` now
  calls `ic.center_crosshair()` right before clicking the filter box.** The
  NEEDS_HUMAN→MINING resume path (`toggle_pause_action` → `'clear_human'` →
  `decide_transition` → `_on_enter(MINING)`) never called it, unlike `_resume()`
  (the *paused*→resume Q-handler, `main.py:10318`) which already has this exact
  fix for "user tabbed to Discord and back, cursor drifted" — the scenario
  NEEDS_HUMAN exists to create. The two paths that always succeeded (normal
  harvest-success resume, fresh boot) both already exercise a real mouse/keyboard
  action affecting cursor state before reaching the clear (`prepare_scan()` or
  `pitch_reset`); the short-circuit path never does. Two competing explanations
  (H080's panel-repaint theory vs. this cursor-recenter gap) aren't yet mutually
  excluded — this fix targets the one with a concrete code-level gap.
- **H216 (2026-08-07, harvest 216): panel-clear retry loop went blind to a mine reset
  that started mid-loop.** `_resume_mining_tail` only checks `_mine_resetting` once at
  entry (H051); the panel-clear retry loop that runs right after (up to 8 attempts,
  ~55s observed) never re-checks it, so a reset banner appearing partway through (the
  countdown is only 24s) went unnoticed until retries exhausted, then unconditionally
  downgraded to NEEDS_HUMAN with a "please clear it manually" message that was already
  moot — the mine was resetting/cleared by then and the RESET_WAIT→REENTRY chain never
  got a chance to take over. **Fix (queue, don't abort — user-specified 2026-08-07):**
  the panel-clear sequence is treated as an atomic action that always runs to its
  natural end (success or retries exhausted) — it is never cut short mid-loop, since
  stopping partway leaves the UI in an undefined state. `_resume_mining_tail` re-checks
  `_mine_resetting` right after `_clear_panel_filter()` returns (success or failure
  alike — a reset pending means don't resume mining either way) and routes to
  RESET_WAIT instead of continuing/NEEDS_HUMAN when true. `decide_transition`'s
  NEEDS_HUMAN branch got the same treatment: if the reset flag is set by the time the
  player clears human (`human_cleared`), go to RESET_WAIT instead of MINING — MINING's
  `_on_enter` would otherwise fire key/mouse input immediately and clear the reset
  flag itself, decapitating the reset→reentry chain. **Needs live-game validation**:
  a harvest whose panel-clear retries overlap a reset should run the full retry
  sequence uninterrupted, then log "採集收尾：面板歸零跑完但礦坑重置 pending -> 回
  RESET_WAIT" (success or failure) instead of "降級 NEEDS_HUMAN".
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
- **H187 (2026-08-04, harvest 187): give-up rescue was structurally blind to
  ionized/spectral variant ores, and a separate anchor-drift bug disabled chat
  rescue on top of that.** Chat baseline showed `an ionized Fortuitous` as
  evidence, but sweep still gave up to human. Two independent bugs found:
  (1) `_episode_chill_at` — the anchor `_prechill_ref` needs to look backward
  from — was being set twice: once at the true chill moment (`_on_enter`
  HARVESTING, H072 panel-check code) and again ~10-30s later after reference
  capture/D2 cooldown finished. The second write pushed the anchor outside the
  prechill ring buffer's frozen window (buffer stops sampling once HARVESTING
  starts), so `pick_prechill_ref` always returned None — chat rescue (Route A)
  was silently disabled whenever entry setup took longer than
  `prechill_min_age_s`. **Fixed**: removed the redundant second assignment;
  the anchor is now set exactly once, at the true chill trigger.
  (2) Route B (`_panel_rare_ores`) only ever reads whichever backpack tab is
  showing (assumed NORMAL) — the 2026-07-31 panel-zero-rescue design explicitly
  deferred IONIZED/SPECTRAL tab support as "add once observed live"
  (`docs/superpowers/specs/2026-07-31-panel-zero-rescue-design.md`, Out of
  Scope). H187 is that observation. **Added Route C** (`_panel_variant_tab_scan`):
  when routes A/B both find nothing and the panel is zeroed, click the panel
  header (`panel_header_xy`, confirmed by the player to cycle
  NORMAL→IONIZED→SPECTRAL→NORMAL) and OCR each tab. The click is verified via
  `harvester.next_panel_tab` after every step — an unexpected header means the
  click was eaten, and the scan stops immediately rather than retrying blind
  (this button has zero live-fire history, unlike the filter-box click). The
  `finally` block always attempts a verified return to NORMAL (bounded to 3
  attempts) so a stuck tab self-heals via the next MINING entry's existing
  header gate (`panel_expected_header`) even when recovery fails.
  **`giveup_rescue_variant_observe` is its own observation flag** (default on),
  independent of `giveup_rescue_observe` — even accounts that have already
  graduated chat/panel rescue to automatic still get a fresh observation
  period for this specific interaction, because raw tab existence has an
  unverified assumption baked in (whether IONIZED/SPECTRAL tabs are actually
  zeroed per-episode the same way NORMAL is, or whether the filter is shared
  across tabs at all — nobody has confirmed this live). Hits are appended to
  `<log_dir>/variant_tab_observed.json`. **When that file reaches
  `giveup_rescue_variant_observe_target` (10) entries, lay the records out for
  the user and ask whether to switch to automatic**
  (`giveup_rescue_variant_observe = False`). **The header click itself is
  live-verified** (2026-08-08, player idle at Surface, no bot running): 3
  real clicks at `panel_header_xy` cycled NORMAL→IONIZED→SPECTRAL→NORMAL,
  `harvester.panel_header` OCR matched `harvester.next_panel_tab`'s prediction
  at every step, and the panel round-tripped back to the exact original
  NORMAL row list. **Still unverified**: whether IONIZED/SPECTRAL actually
  get zeroed per-episode the same way NORMAL does (the live probe only
  confirmed the click/cycle mechanics, not the zero-point assumption behind
  a real rescue hit) — that's what `giveup_rescue_variant_observe` is still
  guarding against.
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
