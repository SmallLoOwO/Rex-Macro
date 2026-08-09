**English** | [繁體中文](README.zh-TW.md)

# 🪦 Boring Mining Game — REx: Reincarnated Full Auto-Miner

> **This game held my Roblox window hostage.**
>
> REx: Reincarnated is a mining game. Technically there's a Roblox bug that
> lets you idle-mine — hold W and walk away, your character keeps swinging.
> But boost? That doesn't press itself. Without someone actively refreshing
> the boost, you're mining at base speed with zero bonus yield. The bug gives
> you the swing, not the payoff. And rare ores still need manual scanning,
> aiming, and firing — step away for too long and a rare ore despawns while
> you're gone. You can't play anything else while it runs. Want to jump into
> Grow a Garden? Can't — REx is still holding your window. Want to hang out
> in Brookhaven with friends? Can't — the ore isn't done yet.
>
> And the crafting system? Late-game items demand materials that take **tens to
> hundreds of hours** of continuous, non-stop mining to gather. A single endgame
> craft — one item — can mean weeks of nothing but holding W and clicking. That's
> not a game anymore. That's a second job you don't get paid for.
>
> So I thought: what if it mines itself, maintains itself, and pings me when
> something goes wrong? What if I could just tap a button on my phone via Discord
> and be done with it?
>
> **That's this project.** You leave the bot running on this PC. It mines, it
> refreshes boosts, it hunts rare ores — when it hears the **chill** cue (the
> distinct sound the game plays when a rare ore spawns nearby) it scans all
> eight directions, fires the harvester tool, captures the ore, screenshots the
> proof, and sends it to your Discord. You can even tap the screen directly from
> your phone's browser to fire or click the teleport board.
>
> And then you go play something else. Because Roblox only lets you open one
> window — but who says the ore in that window has to be mined by *you*?
>
> And let's be honest — by the time you've sunk hundreds of hours into REx,
> there's nothing left to do but mine. The quests are done, the progression
> is flat, the excitement is gone, and the only thing that still matters is
> squeezing out a few more rare ores while you stare at the wall. This bot
> is for that player. The one who's already seen everything the game has to
> offer and just wants the ore without the soul-crushing grind.
>
> ⚠ **I am no longer maintaining this project.** The code is here for everyone
> who's been held hostage by REx. Fork it, modify it, make it yours. The
> coordinates are calibrated for 1920×1080 fullscreen — if your resolution
> differs you'll need to recalibrate, but at least the logic is all here.
>
> ⚠⚠ **This project is unfinished.** It has known bugs, untested edge cases,
> and features that were still in development when I stopped. Some detection
> logic is fragile, some flows degrade to "ping the human" more often than
> they should, and some things I never got to validate in a real live run.
> Read `docs/incidents.md` and `docs/open-detection-issues.md` for the full
> list of known problems. **Use it as a starting point, not a finished product.**

---

## At a Glance

| Question | Answer |
|---|---|
| **Can I sleep with this running?** | **No.** This is an assistant, not a full autopilot. It lets you step away from the keyboard, but you should check in every 20–30 minutes. |
| **How often does it need me?** | Every 20–30 minutes — to verify harvests, handle mine resets, and catch anything unexpected. |
| **What happens when something goes wrong?** | It logs everything, screenshots the evidence, and pings your Discord. Worst case it pauses and waits for you. |
| **Do I need to be a programmer?** | **Depends.** If your setup matches the original author's, it works out of the box. If you need different items, coordinates, or behavior, you'll need to edit Python code. |

<!-- TODO: Add screenshots — bot mining, Discord harvest notification, web UI intervention panel -->

---

## What Is This

A Windows-only Python 3.11+ automation bot for [REx: Reincarnated](https://www.roblox.com/games/8549934015/REx-Reincarnated).
It handles mining, boost maintenance, rare-ore detection and harvesting, Discord
remote control, and mine re-entry after resets.

## Required In-Game Items (Late-Game Only)

**This bot is designed for late-game players.** What does "late-game" mean here?
You should already:

- Know what the **chill** sound is — the distinct audio cue the game plays when a
  rare ore spawns nearby
- Have crafted a **Tier 6 pickaxe**
- Have enough materials to **craft** all four tools below (or already own them)
- Understand the game's boost, scanner, and event mechanics

If you're still early-game, this bot won't help you — come back when you've
progressed far enough to craft all four.

### Key Bindings — This Is Important

The original author placed these four items on **hotkeys 2, 3, 4, 5** in-game.
The bot presses these number keys directly. **You must set up your hotkeys the
same way**, or change the key mappings in `miningbot/config.py` to match yours.

| Slot | Item | What It Does | Wiki |
|---|---|---|---|
| **Key 2** | Cybernetium Radar | Scans for rare-ore trackers within range | [Wiki](https://rex-reincarnated.fandom.com/wiki/Cybernetium_Radar) |
| **Key 3** | Laser Scope | Aims and fires at detected trackers to harvest rare ore | [Wiki](https://rex-reincarnated.fandom.com/wiki/Laser_Scope) |
| **Key 4** | Lucidium Locator | Event radar — the bot uses it to decide keep/reroll on random events | [Wiki](https://rex-reincarnated.fandom.com/wiki/Lucidium_Locator) |
| **Key 5** | Bucket of Sealed Whispers | Mining boost — the bot auto-refreshes it when it expires | [Wiki](https://rex-reincarnated.fandom.com/wiki/Bucket_of_Sealed_Whispers) |

None of these can be bought — every single one is a craft recipe requiring
materials from deep-layer mining and rare drops. That's the whole point: by
the time you have all four, the game has nothing left to offer except more
mining, and that's exactly the part this bot takes off your hands.

> **Want to use different items, or remove some entirely?** The code is yours
> to modify. You can strip out any subsystem you don't need (e.g. remove the
> event keep/reroll logic if you don't have a Lucidium Locator), or swap in
> weaker alternatives. For example, the Bucket of Sealed Whispers
> ([Wiki](https://rex-reincarnated.fandom.com/wiki/Bucket_of_Sealed_Whispers))
> can be replaced with the weaker [Reaper Bucket](https://rex-reincarnated.fandom.com/wiki/Reaper_Bucket)
> — you'd just need to adjust the boost cooldown and duration parameters in
> `config.py` and `miner.py`. **But the default code assumes all four are
> equipped on keys 2–5**, so removing or swapping an item means finding and
> updating the relevant logic in `miningbot/`.

## ⚠ The UI Is in Chinese

**All in-game interaction text, Discord messages, web UI labels, log entries, and
status notifications are written in Traditional Chinese (繁體中文).**

If you want English (or any other language), you'll need to find and replace the
Chinese strings yourself. The code logic and identifiers are in English — only
user-facing text is Chinese. See the [Developer Guide](#developer-guide) below
for which files to edit.

---

# Player Guide

## Installation

> ⚠ **This is not a one-click app.** You need Python 3.11+ and basic
> command-line familiarity. If you've never used a terminal, the setup will
> be painful.

1. Install **Python 3.11+** and **Tesseract OCR**. Run Roblox at **1920×1080
   fullscreen**.
2. Install [uv](https://docs.astral.sh/uv/), then run:

   ```powershell
   uv sync --locked
   ```

3. Copy `.env.example` to `.env`. Fill in your Discord token and channel ID.
   Leave empty if you don't use Discord.
4. Set up your in-game hotkeys — place the four items on **keys 2, 3, 4, 5**
   (see [Key Bindings](#key-bindings--this-is-important) above).
5. Prepare chill audio references and game templates:

   ```powershell
   uv run python -m miningbot.convert_audio "your_chill.mp3"
   uv run python -m miningbot.fetch_trackers
   uv run python -m miningbot.calibrate
   ```

6. Launch: double-click `啟動挖礦bot.bat`, or run `uv run python -m miningbot`.

## Hotkeys (Bot Control)

- **Ctrl+Q**: Pause and release all held keys.
- **Q**: Pause / resume.
- **F12**: Quit.

## Discord Commands

The bot responds to Discord messages in your configured channel:

- `pause` / `resume` — control mining
- `status` — check what the bot is doing
- `shot` — take a screenshot
- `list` / `keep` / `unkeep` — manage your ore keep-list
- `clear` — clear the backpack filter
- `回礦` / `reenter` — re-enter the mine after a reset

Mine re-entry has three modes: `off` (do nothing), `remote` (wait for your
Discord command, default), or `auto` (automatically re-enter, requires
calibration).

## Web UI

The bot includes a web interface for remote control — tap the screen to fire,
click teleport boards, adjust settings, all from your phone browser.

It binds to your machine's Tailscale IP (falls back to `127.0.0.1` if Tailscale
isn't running). If no one is connected, it falls back to Discord buttons
automatically. See [`docs/web-ui-guide.md`](docs/web-ui-guide.md) for setup.

⚠ The web UI needs `fastapi`, `uvicorn`, and `websockets` installed in the
**same Python that runs the bot**. If missing, the bot still mines fine —
just without the web interface.

---

# Developer Guide

> This section is for anyone who wants to modify the bot — change items,
> coordinates, thresholds, or behavior. If the default setup works for you,
> you can skip this entirely.

## Project Structure

```
miningbot/
  main.py          Bot orchestration and runtime state
  config.py        All coordinates, thresholds, key mappings, and modes
  states.py        Top-level state machine
  harvester.py     Harvest decisions and tool wrappers
  miner.py         Mining loop, boost (D5) maintenance
  vision.py        Tracker detection and shape arbitration
  ocr.py           Chat verification and OCR logic
  audio.py         Chill/reset audio scoring
  game_data.py     Ore classification, tier gate, world data
  reentry*.py      Mine re-entry logic (automatic and remote)
  remote_aim.py    Discord-assisted harvest alignment
  web_*.py         Web UI: FastAPI server, WebSocket IPC, HTML renderers
tests/             Unit tests + tracked fixture regressions
assets/            JSON datasets + documentation
docs/              Reference docs, incident records
```

Start with `config.py` — every coordinate, threshold, interval, key mapping,
and mode lives there. Read `AGENTS.md` for operating conventions and
non-negotiable runtime rules.

## Changing Key Bindings

The bot sends raw key presses via `pydirectinput`. To change which keys trigger
which items, edit the key constants in `config.py` (search for the slot/tool
key definitions). Remember: Roblox tool keys are **toggles** — pressing a key
that's already equipped will unequip it, so the bot includes logic to verify
the correct slot is selected before acting.

## Changing the UI Language

All user-facing Chinese text lives in:

| Area | Files |
|---|---|
| Discord messages | `notify.py`, `reentry_remote.py`, `remote_aim.py` |
| Web UI HTML | `web_static.py` |
| Log text | throughout `miningbot/*.py` (search for CJK characters) |
| Help text | `main.py` (`_poll_discord` command help) |

## Development

```powershell
uv run ruff check .
uv run pytest -q
```

OCR, coordinate, or visual threshold changes require two-sided regression with
real fixtures — default tests never operate Roblox, Discord, or physical audio
devices.

## Logs

Runtime data defaults to `%LOCALAPPDATA%\RexMacro\logs`. Override with
`REX_MININGBOT_LOG_DIR` in `.env`.

- `miningbot.log` — state transitions, warnings, milestones
- `actions.log` / `harvest.log` / `discord.log` — subsystem detail
- `heartbeat.log` — latency percentiles (p50/p95/p99)
- `snapshots/` — categorized diagnostic screenshots

## Credits

Built with [FastAPI](https://github.com/fastapi/fastapi), [OpenCV](https://github.com/opencv/opencv-python),
[RapidOCR](https://github.com/RapidAI/RapidOCR), [Tesseract](https://github.com/tesseract-ocr/tesseract),
[NumPy](https://github.com/numpy/numpy), [SciPy](https://github.com/scipy/scipy),
[mss](https://github.com/BoboTiG/python-mss), [pydirectinput](https://github.com/learncodebygaming/pydirectinput),
[PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch), and other open-source libraries.

## License

This project is for educational and personal use only. Roblox automation may
violate the game's Terms of Service — use at your own risk.
