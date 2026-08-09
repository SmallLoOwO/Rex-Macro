**English** | [繁體中文](README.zh-TW.md)

# 🪦 Boring Mining Game — Roblox REX Full Auto-Miner

> **This game held my Roblox window hostage.**
>
> REX is a fully manual mining game. There is no auto-mine, no idle mode, no
> AFK progress. Every ore, every swing — that's your finger on the button. You
> can't play anything else while it runs. Want to jump into Blade Ball? Can't —
> REX is still mining. Want to hang out in Brookhaven? Can't — the ore isn't
> done yet. You leave it mining, you can't play anything else. Step away for a
> bathroom break? Zero yield while you're gone — the game doesn't mine for you.
> Walk away for 20 minutes? Roblox kicks you for inactivity. Come back and your
> character is stuck, the boost expired, the rare ore despawned — hours wasted
> for nothing.
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
> refreshes boosts, it hunts rare ores — when it hears the chill audio cue it
> scans all eight directions, fires D3, captures the ore, screenshots the proof,
> and sends it to your Discord. You can even tap the screen directly from your
> phone's browser to fire or click the teleport board.
>
> And then you go play something else. Because Roblox only lets you open one
> window — but who says the ore in that window has to be mined by *you*?
>
> And let's be honest — by the time you've sunk hundreds of hours into REX,
> there's nothing left to do but mine. The quests are done, the progression
> is flat, the excitement is gone, and the only thing that still matters is
> squeezing out a few more rare ores while you stare at the wall. This bot
> is for that player. The one who's already seen everything the game has to
> offer and just wants the ore without the soul-crushing grind.
>
> ⚠ **I am no longer maintaining this project.** The code is here for everyone
> who's been held hostage by REX. Fork it, modify it, make it yours. The
> coordinates are calibrated for 1920×1080 fullscreen — if your resolution
> differs you'll need to recalibrate, but at least the logic is all here.

---

## What Is This

A Windows-only Python 3.11+ automation bot for Roblox REX. Core pipeline: mining,
D5 boost maintenance, D4 event keep/reroll, chill audio detection, rare-ore
sweep/aim/harvest, chat verification, Discord remote control, and manual / remote /
experimental automatic mine re-entry.

`miningbot/main.py` is the state machine and I/O orchestration core; pure decision
logic is split across `states.py`, `harvester.py`, `miner.py`, `game_data.py`, and
related modules.

## Required In-Game Items (Late-Game Only)

**This bot is designed for late-game players.** The tools it automates — D2
through D5 — are not starter gear. They are endgame items that must be
**crafted** from rare materials you'll only obtain after significant
progression. If you're still early-game, this bot won't help you — come back
when you've crafted all four.

You need these equipped on hotkeys D2–D5 before the bot can function:

| Key | Item | What It Does | Wiki |
|---|---|---|---|
| **D2** | Cybernetium Radar | Scans for rare-ore trackers within range | [Wiki](https://rex-reincarnated.fandom.com/wiki/Cybernetium_Radar) |
| **D3** | Laser Scope | Aims and fires at detected trackers to harvest rare ore | [Wiki](https://rex-reincarnated.fandom.com/wiki/Laser_Scope) |
| **D4** | Lucidium Locator | Event radar — the bot uses it to decide keep/reroll on random events | [Wiki](https://rex-reincarnated.fandom.com/wiki/Lucidium_Locator) |
| **D5** | Bucket of Sealed Whispers | Mining boost — increases speed and FOV; the bot auto-refreshes it on cooldown | [Wiki](https://rex-reincarnated.fandom.com/wiki/Bucket_of_Sealed_Whispers) |

None of these can be bought — every single one is a craft recipe requiring
materials from deep-layer mining and rare drops. That's the whole point: by
the time you have all four, the game has nothing left to offer except more
mining, and that's exactly the part this bot takes off your hands.

> **Want to use different items, or remove some entirely?** The code is yours
> to modify. You can strip out any D2–D5 subsystem you don't need (e.g. remove
> the D4 keep/reroll logic if you don't have a Lucidium Locator), or swap in
> weaker alternatives. For example, D5 ([Bucket of Sealed Whispers](https://rex-reincarnated.fandom.com/wiki/Bucket_of_Sealed_Whispers))
> can be replaced with the weaker [Reaper Bucket](https://rex-reincarnated.fandom.com/wiki/Reaper_Bucket)
> — you'd just need to adjust the boost cooldown and duration parameters in
> `config.py` and `miner.py`. The bot is modular enough to run without any
> subset of these. **But the default code assumes all four are equipped**, so
> removing or swapping an item means finding and updating the relevant logic
> in `miningbot/` — it's not just a config flip.

## ⚠ The UI Is in Chinese

**All in-game interaction text, Discord messages, web UI labels, log entries, and
status notifications are written in Traditional Chinese (繁體中文).** This includes:

- Discord command responses and embed cards
- Web UI buttons, labels, and status text
- Log messages and warning text
- Help text and player-facing instructions

If you want to use this bot with English (or any other language) UI, you will need
to find and replace the Chinese strings yourself. The relevant files are:

| Area | Files to edit |
|---|---|
| Discord messages | `miningbot/notify.py`, `miningbot/reentry_remote.py`, `miningbot/remote_aim.py` |
| Web UI HTML | `miningbot/web_static.py` |
| Log text | throughout `miningbot/*.py` (search for Chinese characters) |
| Help text | `miningbot/main.py` (`_poll_discord` command help) |
| Config comments | `miningbot/config.py` |

The **code logic, identifiers, and log keys are in English** — only user-facing
text is Chinese.

## Installation

1. Install Python 3.11+, Tesseract OCR, and run Roblox at **1920×1080 fullscreen**
   (coordinate baseline since 2026-07-28; the old baseline was a maximized window
   with the taskbar visible — switching between them is a 29px top / 50px bottom
   translation that requires recalibrating detection regions).
2. Install [uv](https://docs.astral.sh/uv/), then in the project root:

   ```powershell
   uv sync --locked
   ```

   The `ocr-native` group installs a hash-locked Windows/Python 3.11 tesserocr
   wheel; if unavailable, the program falls back to pytesseract. Legacy
   `pip install -r requirements.txt` covers runtime deps only; the fully
   reproducible environment is `pyproject.toml + uv.lock`.
3. Copy `.env.example` to `.env`, fill in your Discord token/channel. Leave empty
   if you don't use Discord.
4. Prepare chill audio references and local templates:

   ```powershell
   uv run python -m miningbot.convert_audio "your_chill.mp3"
   uv run python -m miningbot.fetch_trackers
   uv run python -m miningbot.calibrate
   ```

5. Launch: double-click `啟動挖礦bot.bat`, or run `uv run python -m miningbot`.
   For console output: `uv run python -m miningbot.main`.

## Hotkeys

- **Ctrl+Q**: Pause and release all held keys.
- **Q**: Pause / resume; during startup checks = skip current check.
- **F12**: Quit.

(The R-key sampler window was retired 2026-07-17 — screenshots via the remote 📷
button, pitch via the re-entry `仰角` command.)

## Discord & Re-entry

Supports `pause`, `resume`, `status`, `shot`, `ability`, `list`, `keep`, `unkeep`,
`clear`, `回礦` / `reenter`, and more. `reentry_mode` can be `off`, `remote`, or
`auto`; defaults to `remote`. `auto` requires a local surface template
calibration to be completed first.

## Web UI

Built-in web interface (`web_server_enabled`, on by default; binds to
`web_server_host` = this machine's Tailscale IP, auto-falls back to `127.0.0.1`
if Tailscale is down). Four pages: `/intervention` (live intervention: 5-button
remote + persistent status + pinch-zoom tap-to-fire / tap-teleport-board), `/`
(player settings: whitelisted config fields + keep-list + D2 toggle), `/history`,
`/annotate`.

When no one is connected to the web UI (or disconnected beyond
`web_fallback_grace_s`), it auto-falls back to the existing Discord reaction
button flow — whichever responds first wins. See
[`docs/web-ui-guide.md`](docs/web-ui-guide.md) for setup and troubleshooting.

⚠ The web UI requires `fastapi` / `uvicorn` / `websockets` installed in **the
same Python interpreter that launches the bot** (`啟動挖礦bot.bat` uses `pythonw`
= Microsoft Store Python, which is a separate environment from `.venv`). If
missing, the bot still mines normally — it just disables the web UI and notes it
in `miningbot.log` and the Discord startup message.

## Logging & Debugging

New installs default runtime data to `%LOCALAPPDATA%\RexMacro\logs` to avoid
OneDrive syncing large PNGs. Override with `REX_MININGBOT_LOG_DIR` in `.env`.

- `miningbot.log`: state transitions, warnings, milestones.
- `actions.log` / `harvest.log` / `discord.log`: subsystem detail.
- `heartbeat.log`: heartbeat + capture/observe/tick/loop p50/p95/p99.
- `snapshots/`: categorized by trace/review/events/reentry/trackers.

Sampling profiler for real sessions:

```powershell
uv run py-spy record -o profile.svg -- python -m miningbot.main
```

## Development

```powershell
uv run ruff check .
uv run pytest -q
```

GitHub Actions runs the same locked checks on `windows-latest + Python 3.11`.
OCR, coordinate, or visual threshold changes require two-sided regression with
real fixtures; default tests never operate Roblox, Discord, or physical audio
devices.

Read `AGENTS.md` for operating conventions and runtime rules.

## Project Structure

```
miningbot/        Core code (state machine, harvest, vision, audio, re-entry, web UI)
tests/            Unit tests + tracked fixture regressions
assets/           JSON datasets + documentation
docs/             Reference docs, incident records
```

## Credits — Open Source Projects

This project stands on the shoulders of these excellent open-source libraries:

| Library | Role |
|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | Web UI backend & WebSocket server |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI server |
| [OpenCV](https://github.com/opencv/opencv-python) | Computer vision — tracker detection, shape arbitration, color masks |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Primary OCR engine for chat verification |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) / [pytesseract](https://github.com/madmaze/pytesseract) / [tesserocr](https://github.com/sirfz/tesserocr) | OCR fallback & boost count reading |
| [NumPy](https://github.com/numpy/numpy) | Numerical computing throughout |
| [SciPy](https://github.com/scipy/scipy) | Audio spectral analysis & signal processing |
| [mss](https://github.com/BoboTiG/python-mss) | Fast screen capture |
| [pydirectinput](https://github.com/learncodebygaming/pydirectinput) | DirectInput key/mouse simulation for Roblox |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) | WASAPI loopback audio capture for chill detection |
| [python-dotenv](https://github.com/motdotla/dotenv) | Environment variable management |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | ML model inference |
| [websockets](https://github.com/python-websockets/websockets) | WebSocket protocol implementation |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | FFmpeg binaries for video encoding |
| [pytest](https://github.com/pytest-dev/pytest) | Testing framework |
| [ruff](https://github.com/astral-sh/ruff) | Linting |
| [py-spy](https://github.com/benfred/py-spy) | Sampling profiler |

## License

This project is for educational and personal use only. Roblox automation may
violate the game's Terms of Service — use at your own risk.
