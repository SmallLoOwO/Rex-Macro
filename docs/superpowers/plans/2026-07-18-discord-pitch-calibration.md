# Discord 俯仰校準遙控 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **執行代理**：每個任務派 **Sonnet 5** 子代理（Agent `model=sonnet`）實作（2026-07-18 使用者指定）。

**Goal:** 把俯仰校準搬進 Discord：`校準 挖礦|回礦` 指令 → 校準 embed 卡（emoji 反應調角度、幅度 1/5/10/50 循環、每步自動截圖）→ 💾 自動寫回 `config.py`。

**Architecture:** 校準是 paused 底下的 session 旗標（不動 states.py）。Discord 輪詢執行緒只驗收指令/反應並寫 pending；聚焦、拖曳（`_pitch_drag_verified`）、截圖、寫檔全在主迴圈消費。embed 用既有 `send_embed`/`delete_message`+repost（DM 無法清他人反應）路徑。純決策（解析、記帳、embed 組字、config 改寫）全在 `calibrate_pitch.py` 當純函式。

**Tech Stack:** Python 3.11、stdlib urllib（notify.py 既有 Discord REST 封裝）、pytest、ruff。

**Spec:** `docs/superpowers/specs/2026-07-18-discord-pitch-calibration-design.md`

## Global Constraints

- **不執行任何 git commit/branch/push**（專案慣例：完成後由使用者驗收再 commit；本計畫所有「commit」步驟以「跑測試確認綠」取代）。
- Discord 背景執行緒**只能**解析、回覆訊息、寫 pending 旗標；`input_control`、寫檔、`_pause`/`_resume` 只在主迴圈。
- 不引入任何新依賴（不得用 discord.py / websocket）。
- 不動 `states.py`；不動任何既有 pitch 回歸測試（`test_calibrate_pitch.py` 既有測試、pitch_eaten、probe_frozen、sweep_pitch 全保留，只能新增）。
- 幅度循環固定 `(1, 5, 10, 50)`；session 初始幅度 **5**。
- 校準目標角欄位映射：`mining → (sweep_pitch_center_back_px, sweep_pitch_clamp_px)`、`reentry → (reentry_pitch_back_px, reentry_pitch_clamp_px)`（`miningbot/config.py:303-335`）。
- 反應 emoji 固定：`⬆️ ⬇️ 🔁 🧭 📷 💾 ❌` ↔ `up down step home snap save exit`。
- 每個任務結束跑 `uv run pytest -q`（全綠）與 `uv run ruff check . --no-cache`（無新違規）。
- 註解風格比照現行 main.py／calibrate_pitch.py：繁中、講「為什麼／約束」，不講「這行做什麼」。

---

### Task 1: 指令解析與接受閘（純函式）

**Files:**
- Modify: `miningbot/discord_commands.py`（COMMAND_NAMES 加 `校準`/`calib`）
- Modify: `miningbot/calibrate_pitch.py`（加 `parse_calib_target`、`can_accept_calibration`）
- Test: `tests/test_discord_commands.py`、`tests/test_calibrate_pitch.py`

**Interfaces:**
- Consumes: `discord_commands.parse_command`（既有）。
- Produces: `parse_calib_target(args: tuple) -> str | None`（`"mining"`/`"reentry"`/None；空 args 預設 `"mining"`）；`can_accept_calibration(reentry_active: bool, already_calibrating: bool) -> tuple[bool, str]`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_discord_commands.py` 末尾加：

```python
def test_parse_command_accepts_calibration():
    assert parse_command("校準").name == "校準"
    command = parse_command("calib mining")
    assert command.name == "calib"
    assert command.args == ("mining",)
```

`tests/test_calibrate_pitch.py` 末尾加：

```python
from miningbot.calibrate_pitch import parse_calib_target, can_accept_calibration


def test_parse_calib_target_defaults_and_aliases():
    assert parse_calib_target(()) == "mining"            # 無參數預設挖礦（spec 第 1 節）
    assert parse_calib_target(("挖礦",)) == "mining"
    assert parse_calib_target(("MINING",)) == "mining"   # 大小寫不敏感
    assert parse_calib_target(("回礦",)) == "reentry"
    assert parse_calib_target(("reentry",)) == "reentry"
    assert parse_calib_target(("garbage",)) is None      # 寧可不動不誤動


def test_can_accept_calibration_gates():
    ok, _ = can_accept_calibration(False, False)
    assert ok
    ok, reason = can_accept_calibration(True, False)
    assert not ok and "回礦" in reason                    # episode 進行中拒絕
    ok, reason = can_accept_calibration(False, True)
    assert not ok and "校準" in reason                    # 已在校準中拒絕
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_discord_commands.py tests/test_calibrate_pitch.py -q`
Expected: FAIL（`校準` 不在 COMMAND_NAMES；ImportError parse_calib_target）

- [ ] **Step 3: 最小實作**

`miningbot/discord_commands.py` 的 COMMAND_NAMES 改為：

```python
COMMAND_NAMES = frozenset({
    "list", "keep", "unkeep", "clear", "pause", "resume", "status", "help", "shot",
    "ability", "回礦", "reenter", "校準", "calib",
})
```

`miningbot/calibrate_pitch.py` 加（放在 `apply_calib_step` 之後）：

```python
def parse_calib_target(args: tuple):
    """`校準 [挖礦|回礦]` 目標角解析（純函式）。無參數預設挖礦；解析不出回 None。"""
    if not args:
        return "mining"
    a = args[0].lower()
    if a in ("挖礦", "mining"):
        return "mining"
    if a in ("回礦", "reentry"):
        return "reentry"
    return None


def can_accept_calibration(reentry_active: bool, already_calibrating: bool):
    """校準接受閘（純函式）。回礦 episode 進行中／已在校準中一律拒絕（spec 第 1 節）。"""
    if already_calibrating:
        return False, "已在校準中（校準卡按 ❌ 可離開）"
    if reentry_active:
        return False, "回礦 episode 進行中——結束後再校準"
    return True, ""
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_discord_commands.py tests/test_calibrate_pitch.py -q`
Expected: PASS

- [ ] **Step 5: 全量驗證**

Run: `uv run pytest -q; uv run ruff check . --no-cache`
Expected: 全綠、無新違規

---

### Task 2: 校準 session 與 embed 純函式核心

**Files:**
- Modify: `miningbot/calibrate_pitch.py`
- Test: `tests/test_calibrate_pitch.py`

**Interfaces:**
- Produces（後續任務全靠這些名字）：
  - `CALIB_TITLE = "🎯 俯仰校準"`（跨重啟辨識殘留卡用，之後不可改字）
  - `CALIB_STEPS = (1, 5, 10, 50)`；`next_step(cur: int) -> int`（循環；非法現值回 1）
  - `CALIB_EMOJIS: tuple[str, ...]`＝`("⬆️", "⬇️", "🔁", "🧭", "📷", "💾", "❌")`
  - `CALIB_ACTIONS: dict[str, str]`＝emoji→`"up"/"down"/"step"/"home"/"snap"/"save"/"exit"`
  - `calib_field_names(target: str) -> tuple[str, str]`＝(back_px 欄名, clamp 欄名)
  - `@dataclass CalibSession`：`target: str`、`offset: int`、`step: int = 5`、`prev_paused: bool = False`、`message_id: str | None = None`、`reactions_seen: dict = field(default_factory=dict)`
  - `build_calib_embed(target, offset, config_value, step, warn="") -> dict`

- [ ] **Step 1: 寫失敗測試**

`tests/test_calibrate_pitch.py` 末尾加：

```python
from miningbot.calibrate_pitch import (
    CALIB_TITLE, CALIB_STEPS, CALIB_EMOJIS, CALIB_ACTIONS, CalibSession,
    next_step, calib_field_names, build_calib_embed)


def test_next_step_cycles_and_recovers():
    assert next_step(1) == 5
    assert next_step(5) == 10
    assert next_step(10) == 50
    assert next_step(50) == 1                 # 循環回頭
    assert next_step(999) == 1                # 非法現值回 1（防記帳壞掉卡死）


def test_calib_field_names_mapping():
    assert calib_field_names("mining") == (
        "sweep_pitch_center_back_px", "sweep_pitch_clamp_px")
    assert calib_field_names("reentry") == (
        "reentry_pitch_back_px", "reentry_pitch_clamp_px")


def test_calib_session_defaults():
    sess = CalibSession(target="mining", offset=300)
    assert sess.step == 5                     # 初始幅度 5（計畫 Global Constraints）
    assert sess.prev_paused is False
    assert sess.message_id is None
    assert sess.reactions_seen == {}


def test_calib_actions_cover_all_emojis():
    assert set(CALIB_ACTIONS) == set(CALIB_EMOJIS)
    assert set(CALIB_ACTIONS.values()) == {
        "up", "down", "step", "home", "snap", "save", "exit"}


def test_build_calib_embed_shows_state():
    embed = build_calib_embed("mining", 435, 0, 10)
    assert embed["title"] == CALIB_TITLE
    d = embed["description"]
    assert "sweep_pitch_center_back_px" in d
    assert "435" in d and "10" in d           # offset 與幅度都要看得到
    assert "挖礦標準角" in d
    assert "⚠" not in d
    warned = build_calib_embed("reentry", 400, 400, 5, warn="拖曳疑似被吃")
    assert "⚠" in warned["description"] and "回礦標準角" in warned["description"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_calibrate_pitch.py -q`
Expected: FAIL（ImportError）

- [ ] **Step 3: 最小實作**

`miningbot/calibrate_pitch.py`：檔頭 `import time` 下加 `from dataclasses import dataclass, field`；模組尾（`_focus_and_settle` 之前）加：

```python
# ---- Discord 遠端校準（2026-07-18 spec）：純決策，I/O 全在 main ----
CALIB_TITLE = "🎯 俯仰校準"       # 跨重啟掃頻道辨識殘留卡用——不可改字（比照 _REMOTE_TITLE）
CALIB_STEPS = (1, 5, 10, 50)
CALIB_EMOJIS = ("⬆️", "⬇️", "🔁", "🧭", "📷", "💾", "❌")
CALIB_ACTIONS = dict(zip(CALIB_EMOJIS,
                         ("up", "down", "step", "home", "snap", "save", "exit")))


@dataclass
class CalibSession:
    """校準 session 記帳（主迴圈持有；輪詢執行緒只讀 message_id/reactions_seen）。"""
    target: str                              # "mining" | "reentry"
    offset: int                              # 夾限上 px（絕對記帳，pitch_reset 基準）
    step: int = 5
    prev_paused: bool = False                # 進場前 paused；❌ 離開時恢復
    message_id: str | None = None
    reactions_seen: dict = field(default_factory=dict)


def next_step(cur: int) -> int:
    """幅度循環 1→5→10→50→1；非法現值回 1（防壞記帳卡死切換）。"""
    if cur not in CALIB_STEPS:
        return CALIB_STEPS[0]
    return CALIB_STEPS[(CALIB_STEPS.index(cur) + 1) % len(CALIB_STEPS)]


def calib_field_names(target: str) -> tuple[str, str]:
    """目標角 → (back_px 欄名, clamp 欄名)。spec 第 0 節映射表。"""
    if target == "mining":
        return "sweep_pitch_center_back_px", "sweep_pitch_clamp_px"
    return "reentry_pitch_back_px", "reentry_pitch_clamp_px"


def build_calib_embed(target: str, offset: int, config_value: int,
                      step: int, warn: str = "") -> dict:
    """校準卡 embed（純函式）。所有可變狀態（offset/幅度/現值）都進 description。"""
    name = "挖礦標準角" if target == "mining" else "回礦標準角"
    fld, _ = calib_field_names(target)
    desc = (
        (f"⚠ {warn}\n\n" if warn else "")
        + f"**目標角**：{name}（`{fld}`）\n"
        + f"**目前**：夾限上 {offset}px（config 現值 {config_value}px）\n"
        + f"**幅度**：{step}px（🔁 循環 1→5→10→50）\n\n"
        + "⬆️ 上調　⬇️ 下調（夾限飽和記帳夾 0）　🧭 歸位到夾限\n"
        + "📷 截圖　💾 寫回 config　❌ 離開\n"
    )
    return {"title": CALIB_TITLE, "description": desc, "color": 0x5865F2,
            "footer": {"text": "每次調整會重貼此卡（反應歸零可再點）並附新截圖"}}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_calibrate_pitch.py -q`
Expected: PASS

- [ ] **Step 5: 全量驗證**

Run: `uv run pytest -q; uv run ruff check . --no-cache`
Expected: 全綠

---

### Task 3: config.py 文字改寫純函式

**Files:**
- Modify: `miningbot/calibrate_pitch.py`
- Test: `tests/test_calibrate_pitch.py`

**Interfaces:**
- Produces: `rewrite_config_value(text: str, field: str, new_value: int) -> str | None`——錨點 `<field>: int = <數字>` 恰一次才改寫，否則 None；保留該行註解與其他所有行。

- [ ] **Step 1: 寫失敗測試**

`tests/test_calibrate_pitch.py` 末尾加：

```python
from miningbot.calibrate_pitch import rewrite_config_value

_CONFIG_SNIPPET = (
    "    reentry_pitch_clamp_px: int = 1500          # 俯仰歸位夾限\n"
    "    reentry_pitch_back_px: int = 400            # 回拉量（校準寫回這裡）\n"
    "    sweep_pitch_center_back_px: int = 0         # 0=未校準＝停用\n"
)


def test_rewrite_config_value_changes_only_target_line():
    out = rewrite_config_value(_CONFIG_SNIPPET, "sweep_pitch_center_back_px", 435)
    assert "sweep_pitch_center_back_px: int = 435         # 0=未校準＝停用" in out
    # 其他行 byte-level 不變（含 clamp 行與另一欄位）
    assert "reentry_pitch_clamp_px: int = 1500          # 俯仰歸位夾限" in out
    assert "reentry_pitch_back_px: int = 400            # 回拉量（校準寫回這裡）" in out


def test_rewrite_config_value_two_fields_independent():
    out = rewrite_config_value(_CONFIG_SNIPPET, "reentry_pitch_back_px", 380)
    assert "reentry_pitch_back_px: int = 380            # 回拉量（校準寫回這裡）" in out
    assert "sweep_pitch_center_back_px: int = 0" in out


def test_rewrite_config_value_idempotent_same_value():
    # 值已相同仍回改寫文（冪等；spec 第 3 節）——呼叫端不必特判
    out = rewrite_config_value(_CONFIG_SNIPPET, "reentry_pitch_back_px", 400)
    assert out is not None and "reentry_pitch_back_px: int = 400" in out


def test_rewrite_config_value_missing_or_ambiguous_anchor():
    assert rewrite_config_value(_CONFIG_SNIPPET, "no_such_field", 1) is None
    doubled = _CONFIG_SNIPPET + "    reentry_pitch_back_px: int = 999\n"
    assert rewrite_config_value(doubled, "reentry_pitch_back_px", 1) is None  # 錨點不唯一不硬寫
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_calibrate_pitch.py -q`
Expected: FAIL（ImportError rewrite_config_value）

- [ ] **Step 3: 最小實作**

`miningbot/calibrate_pitch.py`：檔頭加 `import re`；`build_calib_embed` 後加：

```python
def rewrite_config_value(text: str, field_name: str, new_value: int):
    """把 config.py 內 `<field>: int = <數字>` 這一行的數字換成 new_value（純函式）。

    錨點必須恰好出現一次，否則回 None（不硬寫；spec 第 3 節——寫錯 config 比不寫
    更糟）。只動數字本身，行首縮排與行尾註解 byte-level 保留。
    """
    pattern = re.compile(
        rf"(?m)^(?P<head>\s*{re.escape(field_name)}: int = )(?P<val>\d+)(?P<tail>.*)$")
    if len(pattern.findall(text)) != 1:
        return None
    return pattern.sub(
        lambda m: f"{m.group('head')}{new_value}{m.group('tail')}", text)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_calibrate_pitch.py -q`
Expected: PASS

- [ ] **Step 5: 全量驗證**

Run: `uv run pytest -q; uv run ruff check . --no-cache`
Expected: 全綠

---

### Task 4: main 接線——進場／離場與指令 dispatch

**Files:**
- Modify: `miningbot/main.py`
  - `from . import sampler, reentry, ...` 那行（main.py:21）加 `calibrate_pitch`
  - `Bot.__init__`（`self._pending_reentry = None` 附近，main.py:219）加 session 屬性
  - `_handle_discord_command`（main.py:1541 起）加 `校準`/`calib` 分支
  - `run()` 主迴圈 `while self._running:`（main.py:1888）頂部加 pending start 消費
  - `_resume`（main.py:4714）頂部加校準守門
  - 新方法 `_calib_start`、`_calib_exit`（放在 `_pitch_home_mining` 附近，main.py:4821 前後）
- Test: `tests/test_main_calibration.py`（新檔）

**Interfaces:**
- Consumes: Task 1-2 的 `parse_calib_target`、`can_accept_calibration`、`CalibSession`、`calib_field_names`；既有 `_pause`/`_resume`/`_sampler_pitch_prepare`/`_pitch_drag_verified`、`ic.pitch_reset`、`notify.send_message`/`delete_message`。
- Produces: `Bot._calib_session: CalibSession | None`、`Bot._pending_calib_start: str | None`、`Bot._pending_calib_action: str | None`、`Bot._calib_start(target: str)`、`Bot._calib_exit(sess)`。Task 6 的 `_tick_calibration` 會呼叫 `_calib_exit`；`_calib_start` 會呼叫 Task 6 的 `_post_calib_embed`/`_calib_snapshot`（本任務先以方法存在為前提寫好呼叫，測試用 stub——Task 6 補實作）。

- [ ] **Step 1: 寫失敗測試**

新檔 `tests/test_main_calibration.py`：

```python
from miningbot import main, calibrate_pitch
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


def _calib_bot(monkeypatch, paused=False):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot.log_discord = _LogRecorder()
    bot.paused = paused
    bot._calib_session = None
    bot._pending_calib_start = None
    bot._pending_calib_action = None
    bot._pitch_offset_px = 0
    bot._pause = lambda: setattr(bot, "paused", True)
    bot._sampler_pitch_prepare = lambda: None
    bot._post_calib_embed = lambda warn="": None
    bot._calib_snapshot = lambda: None
    monkeypatch.setattr(main.cfg, "sweep_pitch_center_back_px", 300)
    monkeypatch.setattr(main.cfg, "sweep_pitch_clamp_px", 1500)
    monkeypatch.setattr(main.cfg, "reentry_pitch_back_px", 400)
    monkeypatch.setattr(main.cfg, "reentry_pitch_clamp_px", 1500)
    return bot


def test_calib_start_records_prev_paused_then_pauses(monkeypatch):
    bot = _calib_bot(monkeypatch, paused=False)
    resets = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: resets.append((down, back)))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._calib_start("mining")
    sess = bot._calib_session
    assert sess.prev_paused is False          # 在 _pause() 之前捕捉
    assert bot.paused is True                 # 進場即強制暫停
    assert sess.target == "mining"
    assert sess.offset == 300                 # 從 config 現值起算（不歸零）
    assert resets == [(1500, 300)]
    assert bot._pitch_offset_px == 300


def test_calib_start_from_reentry_target_uses_reentry_fields(monkeypatch):
    bot = _calib_bot(monkeypatch, paused=True)
    resets = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: resets.append((down, back)))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._calib_start("reentry")
    assert bot._calib_session.prev_paused is True
    assert bot._calib_session.offset == 400
    assert resets == [(1500, 400)]


def test_calib_exit_restores_prev_paused_and_reports_unsaved(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch, paused=True)
    sent = []
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    monkeypatch.setattr(notify_mod, "delete_message",
                        lambda token, ch, mid, **kw: (True, "ok"))
    resumed = []
    bot._resume = lambda: resumed.append(1)
    sess = calibrate_pitch.CalibSession(target="mining", offset=435,
                                        prev_paused=False, message_id="m1")
    bot._calib_session = sess
    bot._calib_exit(sess)
    assert bot._calib_session is None
    assert resumed == [1]                     # 原本沒暫停 → 離場恢復挖礦
    assert any("未存檔" in m and "435" in m for m in sent)   # offset≠config 現值(300)


def test_calib_exit_stays_paused_when_prev_paused(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch, paused=True)
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: (True, "ok"))
    resumed = []
    bot._resume = lambda: resumed.append(1)
    sess = calibrate_pitch.CalibSession(target="mining", offset=300,
                                        prev_paused=True, message_id=None)
    bot._calib_session = sess
    bot._calib_exit(sess)
    assert resumed == []                      # 原本就暫停 → 維持暫停


def test_resume_guarded_during_calibration(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._calib_session = calibrate_pitch.CalibSession(target="mining", offset=0)
    bot._resume()                             # 不炸、不動 paused（守門直接 return）
    assert any("校準中" in r for r in bot.logger.records)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_main_calibration.py -q`
Expected: FAIL（`_calib_start` 不存在）

- [ ] **Step 3: 實作**

3a. main.py:21 的 import 行加 `calibrate_pitch`：

```python
from . import sampler, reentry, roblox_menu, remote_aim, reentry_remote, discord_commands
from . import calibrate_pitch
```

3b. `Bot.__init__`（`self._pending_reentry = None` 之後）加：

```python
# Discord 俯仰校準（2026-07-18 spec）：輪詢執行緒只寫 pending，進場/動作/寫檔全在
# 主迴圈。session 活著＝強制暫停中（paused 底下的旗標，不是 states.py 新狀態）。
self._calib_session = None                # calibrate_pitch.CalibSession | None
self._pending_calib_start = None          # "mining"/"reentry"：指令驗收後待主迴圈進場
self._pending_calib_action = None         # "up"/…/"exit"：反應輪詢待主迴圈消費
```

3c. `_handle_discord_command` 加分支（放在 `elif cmd == "shot":` 之前）：

```python
elif cmd in ("校準", "calib"):
    # 俯仰校準（2026-07-18 spec）：此處在輪詢執行緒——只驗收＋寫 pending 旗標，
    # 暫停/pitch_reset/發卡全由主迴圈 _calib_start 執行（遊戲輸入鐵律）。
    target = calibrate_pitch.parse_calib_target(args)
    if target is None:
        notify.send_message(token, ch, "用法：`校準 挖礦`（預設）或 `校準 回礦`")
    else:
        ok_c, reason = calibrate_pitch.can_accept_calibration(
            self.state is State.REENTRY, self._calib_session is not None)
        if not ok_c:
            notify.send_message(token, ch, f"❌ 校準未接受：{reason}")
        else:
            self._pending_calib_start = target
            notify.send_message(token, ch,
                "🎯 校準已排入 → 將暫停挖礦、歸位到 config 現值並發校準卡")
    self.log_discord.info("CMD 校準 -> target=%s state=%s", target, self.state.value)
```

3d. `run()` 主迴圈（main.py:1888 `while self._running:` 內、`if self.paused:` 之前）加：

```python
if self._pending_calib_start is not None:
    target, self._pending_calib_start = self._pending_calib_start, None
    self._calib_start(target)
```

3e. `_resume`（main.py:4714）方法體最前面加守門：

```python
if self._calib_session is not None:
    # 校準中不准恢復挖礦（▶️/resume 只記離場後意圖；_calib_exit 先清 session 再呼叫
    # _resume 所以離場路徑不受此擋）。
    self.logger.info("RESUMED 被忽略：校準中（校準卡 ❌ 離開後才恢復）")
    return
```

3f. 新方法（放在 `_pitch_home_mining` 之前）：

```python
# ---- Discord 俯仰校準 session（2026-07-18 spec；paused 底下的旗標模式）----
def _calib_start(self, target: str):
    """進校準模式（主迴圈）：記原 paused → 強制暫停 → 歸位到 config 現值 → 發卡＋首圖。

    從現值起算（不從夾限歸零）：微調通常是「現值附近找更好」，歸零反而每次重校。
    進場歸位被吃只在卡上警告不擋（🧭 可重新絕對定位；比照 H046 慣例）。
    """
    fld, clamp_fld = calibrate_pitch.calib_field_names(target)
    cur = getattr(cfg, fld)
    sess = calibrate_pitch.CalibSession(target=target, offset=cur,
                                        prev_paused=self.paused)
    self._pause()                             # idempotent；放開 W/左鍵
    self._calib_session = sess
    self._sampler_pitch_prepare()
    warn = ""
    if not self._pitch_drag_verified(
            f"[校準] 進場歸位 {fld}={cur}",
            lambda: ic.pitch_reset(getattr(cfg, clamp_fld), cur)):
        warn = "進場歸位疑似被吃——🧭 可重新絕對定位"
    self._pitch_offset_px = cur
    self._post_calib_embed(warn)
    self._calib_snapshot()
    self.logger.info("校準開始 target=%s 現值=%d prev_paused=%s",
                     target, cur, sess.prev_paused)

def _calib_exit(self, sess):
    """❌ 離場：不寫檔；有未存變更附最終值供手抄；恢復進場前 paused 狀態。

    先清 session 再 _resume——_resume 的校準守門靠 session 判斷，順序反了會被擋。
    """
    from . import notify
    fld, _ = calibrate_pitch.calib_field_names(sess.target)
    unsaved = sess.offset != getattr(cfg, fld)
    if sess.message_id:
        notify.delete_message(cfg.discord_bot_token, cfg.discord_channel_id,
                              sess.message_id)
    self._calib_session = None
    self._pending_calib_action = None
    msg = "🏁 校準結束"
    if unsaved:
        msg += f"（⚠ 未存檔：最終 夾限上 {sess.offset}px；要保留請手動改 `{fld}`）"
    if not sess.prev_paused:
        msg += "｜恢復挖礦"
        self._resume()
    else:
        msg += "｜維持暫停（進場前即暫停）"
    notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id, msg)
    self.logger.info("校準結束 unsaved=%s prev_paused=%s", unsaved, sess.prev_paused)
```

注意：main.py 慣例是在方法內 `from . import notify`（區域名綁的是模組物件），因此測試一律 monkeypatch `miningbot.notify` 模組屬性（上面測試碼的 `notify_mod` 寫法）——打 `main.notify` 打不到。

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_main_calibration.py -q`
Expected: PASS

- [ ] **Step 5: 全量驗證**

Run: `uv run pytest -q; uv run ruff check . --no-cache`
Expected: 全綠

---

### Task 5: main 接線——存檔（💾 寫回 config.py）

**Files:**
- Modify: `miningbot/main.py`（新方法 `_calib_save`，放在 `_calib_exit` 之後）
- Test: `tests/test_main_calibration.py`

**Interfaces:**
- Consumes: Task 3 `rewrite_config_value`、Task 2 `calib_field_names`。
- Produces: `Bot._calib_save(sess, path: str | None = None) -> bool`——`path=None` 用 `miningbot/config.py` 實檔（`config` 模組 `__file__`）；測試傳 tmp 檔。成功＝寫檔＋`setattr(cfg, fld, offset)`＋回報舊→新；失敗＝不寫檔、不動 cfg、回報手抄值。

- [ ] **Step 1: 寫失敗測試**

`tests/test_main_calibration.py` 末尾加：

```python
_CFG_TEXT = (
    "    sweep_pitch_clamp_px: int = 1500            # 飽和拖曳量\n"
    "    sweep_pitch_center_back_px: int = 0         # 0=未校準＝停用\n"
)


def _save_bot(monkeypatch, tmp_path, sent):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    p = tmp_path / "config.py"
    p.write_text(_CFG_TEXT, encoding="utf-8")
    return bot, p


def test_calib_save_writes_file_and_syncs_cfg(monkeypatch, tmp_path):
    sent = []
    bot, p = _save_bot(monkeypatch, tmp_path, sent)
    sess = calibrate_pitch.CalibSession(target="mining", offset=435)
    assert bot._calib_save(sess, path=str(p)) is True
    assert "sweep_pitch_center_back_px: int = 435" in p.read_text(encoding="utf-8")
    assert main.cfg.sweep_pitch_center_back_px == 435   # 記憶體同步：本次執行立即生效
    assert any("300 → 435" in m for m in sent)   # 舊值＝記憶體 cfg 現值（_calib_bot 設 300），非檔案裡的 0


def test_calib_save_missing_anchor_keeps_cfg_untouched(monkeypatch, tmp_path):
    sent = []
    bot, p = _save_bot(monkeypatch, tmp_path, sent)
    p.write_text("nothing here\n", encoding="utf-8")
    sess = calibrate_pitch.CalibSession(target="mining", offset=435)
    assert bot._calib_save(sess, path=str(p)) is False
    assert main.cfg.sweep_pitch_center_back_px == 300   # 檔案與記憶體不分岔：cfg 不動
    assert p.read_text(encoding="utf-8") == "nothing here\n"
    assert any("435" in m and "手抄" in m for m in sent)


def test_calib_save_oserror_reports_value(monkeypatch, tmp_path):
    sent = []
    bot, _ = _save_bot(monkeypatch, tmp_path, sent)
    sess = calibrate_pitch.CalibSession(target="mining", offset=435)
    assert bot._calib_save(sess, path=str(tmp_path / "no_dir" / "x.py")) is False
    assert main.cfg.sweep_pitch_center_back_px == 300
    assert any("手抄" in m for m in sent)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_main_calibration.py -q`
Expected: FAIL（`_calib_save` 不存在）

- [ ] **Step 3: 實作**

`miningbot/main.py`（`_calib_exit` 之後）：

```python
def _calib_save(self, sess, path: str | None = None) -> bool:
    """💾 寫回 config.py＋記憶體 cfg（spec 第 3 節）。

    錨點恰一次才寫（rewrite_config_value 回 None＝不硬寫）；任何失敗都不動記憶體
    cfg——檔案與記憶體不分岔。成功後挖礦標準角本次執行立即生效（>0 解鎖啟動歸位
    /mid 層），回礦標準角下次 episode 生效。
    """
    from . import notify
    from . import config as config_module
    fld, _ = calibrate_pitch.calib_field_names(sess.target)
    token, ch = cfg.discord_bot_token, cfg.discord_channel_id
    path = path or config_module.__file__
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new_text = calibrate_pitch.rewrite_config_value(text, fld, sess.offset)
        if new_text is None:
            notify.send_message(token, ch,
                f"❌ 寫檔失敗：config.py 找不到唯一 `{fld}` 錨點——"
                f"請手抄 `{fld} = {sess.offset}`")
            return False
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
    except OSError as e:
        notify.send_message(token, ch,
            f"❌ 寫檔失敗：{e}——請手抄 `{fld} = {sess.offset}`")
        return False
    old = getattr(cfg, fld)
    setattr(cfg, fld, sess.offset)
    notify.send_message(token, ch,
        f"💾 已寫回 `{fld}`：{old} → {sess.offset}（記憶體同步，本次執行立即生效）")
    self.logger.info("校準存檔 %s: %d -> %d", fld, old, sess.offset)
    return True
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_main_calibration.py -q`
Expected: PASS

- [ ] **Step 5: 全量驗證**

Run: `uv run pytest -q; uv run ruff check . --no-cache`
Expected: 全綠

---

### Task 6: main 接線——校準卡貼卡／輪詢／動作消費／截圖

**Files:**
- Modify: `miningbot/main.py`
  - 新方法 `_post_calib_embed`、`_repost_calib_embed`、`_poll_calib_reactions`、`_tick_calibration`、`_calib_snapshot`（放在 `_calib_save` 之後）
  - `_poll_discord`（main.py:1277 `if self._remote_message_id:` 之後）加校準卡輪詢 hook
  - `run()` 主迴圈 paused 分支（main.py:1889-1892）加 `_tick_calibration` 消費
- Test: `tests/test_main_calibration.py`

**Interfaces:**
- Consumes: Task 2 `CALIB_EMOJIS`/`CALIB_ACTIONS`/`build_calib_embed`/`next_step`、`calibrate_pitch.apply_calib_step`（既有：up=+px、down=max(0,−px)、reset=0）、Task 4 `_calib_exit`、Task 5 `_calib_save`；既有 `notify.send_embed`/`add_reaction`/`fetch_message`/`find_reaction_increments`/`delete_message`/`send_images_message`、`capture.grab`、`sampler.save_sample`、`ic.pitch_nudge`/`pitch_reset`。
- Produces: 完整可用的校準迴圈；`_poll_calib_reactions` 只在 Discord 執行緒跑、只寫 `_pending_calib_action`；`_tick_calibration` 只在主迴圈 paused 分支跑。

- [ ] **Step 1: 寫失敗測試**

`tests/test_main_calibration.py` 末尾加：

```python
def _tick_bot(monkeypatch):
    bot = _calib_bot(monkeypatch)
    bot.paused = True
    bot._calib_session = calibrate_pitch.CalibSession(
        target="mining", offset=300, message_id="m1")
    bot._repost_calib_embed = lambda warn="": bot._reposts.append(warn)
    bot._reposts = []
    bot._snaps = []
    bot._calib_snapshot = lambda: bot._snaps.append(1)
    return bot


def test_tick_calibration_up_down_accounting(monkeypatch):
    bot = _tick_bot(monkeypatch)
    nudges = []
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: nudges.append(dy))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._pending_calib_action = "up"
    bot._tick_calibration()
    assert nudges == [-5]                     # 上＝dy<0（沿用取樣視窗語意）；初始幅度 5
    assert bot._calib_session.offset == 305
    assert bot._pitch_offset_px == 305
    assert bot._snaps == [1]                  # 調完自動截圖
    bot._pending_calib_action = "down"
    bot._tick_calibration()
    assert nudges == [-5, 5]
    assert bot._calib_session.offset == 300


def test_tick_calibration_down_saturates_at_zero(monkeypatch):
    bot = _tick_bot(monkeypatch)
    bot._calib_session.offset = 3
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: None)
    bot._pitch_drag_verified = lambda label, drag: True
    bot._pending_calib_action = "down"
    bot._tick_calibration()
    assert bot._calib_session.offset == 0     # 夾限飽和記帳夾 0（apply_calib_step 語意）


def test_tick_calibration_step_cycles_without_game_input(monkeypatch):
    bot = _tick_bot(monkeypatch)
    called = []
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: called.append(dy))
    monkeypatch.setattr(main.ic, "pitch_reset", lambda d, b: called.append((d, b)))
    bot._pending_calib_action = "step"
    bot._tick_calibration()
    assert bot._calib_session.step == 10      # 5 → 10
    assert called == []                       # 🔁 不碰遊戲
    assert bot._snaps == []                   # 也不截圖


def test_tick_calibration_home_resets_offset(monkeypatch):
    bot = _tick_bot(monkeypatch)
    resets = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: resets.append((down, back)))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._pending_calib_action = "home"
    bot._tick_calibration()
    assert resets == [(1500, 0)]              # 歸位到夾限（絕對重定位）
    assert bot._calib_session.offset == 0
    assert bot._pitch_offset_px == 0


def test_tick_calibration_eaten_warns_but_accounts(monkeypatch):
    bot = _tick_bot(monkeypatch)
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: None)
    bot._pitch_drag_verified = lambda label, drag: False   # 被吃
    bot._pending_calib_action = "up"
    bot._tick_calibration()
    assert bot._calib_session.offset == 305   # 記帳照調（比照 仰角 慣例）
    assert any("被吃" in w for w in bot._reposts)


def test_tick_calibration_noop_without_pending(monkeypatch):
    bot = _tick_bot(monkeypatch)
    bot._pending_calib_action = None
    bot._tick_calibration()                   # 不炸、不動任何東西
    assert bot._calib_session.offset == 300


def test_poll_calib_reactions_only_sets_pending(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    bot._calib_session = calibrate_pitch.CalibSession(
        target="mining", offset=300, message_id="m1",
        reactions_seen={e: 1 for e in calibrate_pitch.CALIB_EMOJIS})
    monkeypatch.setattr(notify_mod, "fetch_message",
                        lambda token, ch, mid, **kw: {"reactions": [
                            {"emoji": {"name": "⬆️"}, "count": 2}]})
    bot._poll_calib_reactions()
    assert bot._pending_calib_action == "up"
    # pending 佔用中不覆蓋（一次一動作）
    monkeypatch.setattr(notify_mod, "fetch_message",
                        lambda token, ch, mid, **kw: {"reactions": [
                            {"emoji": {"name": "❌"}, "count": 2}]})
    bot._poll_calib_reactions()
    assert bot._pending_calib_action == "up"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_main_calibration.py -q`
Expected: FAIL（`_tick_calibration`/`_poll_calib_reactions` 不存在）

- [ ] **Step 3: 實作**

3a. 新方法（`_calib_save` 之後）：

```python
def _post_calib_embed(self, warn: str = ""):
    """貼校準卡＋全套反應、記 count 基線（照抄 _post_remote_control 模式）。"""
    from . import notify
    sess = self._calib_session
    fld, _ = calibrate_pitch.calib_field_names(sess.target)
    embed = calibrate_pitch.build_calib_embed(
        sess.target, sess.offset, getattr(cfg, fld), sess.step, warn)
    token, ch = cfg.discord_bot_token, cfg.discord_channel_id
    ok, detail, mid = notify.send_embed(token, ch, embed)
    if not (ok and mid):
        self.log_discord.info("calib post FAIL -> %s", detail)
        return
    seen = {}
    for em in calibrate_pitch.CALIB_EMOJIS:
        added, _ = notify.add_reaction(token, ch, mid, em)
        seen[em] = 1 if added else 0
    sess.message_id = mid
    sess.reactions_seen = seen

def _repost_calib_embed(self, warn: str = ""):
    """刪舊卡貼新卡：DM 無法清他人反應（HTTP 403 code 50003），repost 讓反應歸零
    可立即再點（與遙控器同一條已驗證路徑）。"""
    from . import notify
    old = self._calib_session.message_id
    if old:
        notify.delete_message(cfg.discord_bot_token, cfg.discord_channel_id, old)
    self._post_calib_embed(warn)

def _poll_calib_reactions(self):
    """輪詢校準卡反應（**Discord 輪詢執行緒**）：只寫 _pending_calib_action。

    pending 佔用中不覆蓋（一次一動作；主迴圈消費完才收下一個）——快速連點不會
    疊加成失控的連環拖曳。
    """
    from . import notify
    sess = self._calib_session
    if sess is None or not sess.message_id or self._pending_calib_action is not None:
        return
    message = notify.fetch_message(cfg.discord_bot_token, cfg.discord_channel_id,
                                   sess.message_id)
    if message is None:
        return
    sess.reactions_seen, increments = notify.find_reaction_increments(
        message, sess.reactions_seen, calibrate_pitch.CALIB_EMOJIS)
    for emoji, delta in increments:
        self._pending_calib_action = calibrate_pitch.CALIB_ACTIONS[emoji]
        self.log_discord.info("calib %s -> action=%s (+%d)",
                              emoji, self._pending_calib_action, delta)
        break                                 # 一次輪詢只收一個動作

def _tick_calibration(self):
    """消費校準動作（主迴圈、paused 分支）。⬆️⬇️🧭 執行後重貼卡＋附新截圖。"""
    if self._pending_calib_action is None:
        return
    action, self._pending_calib_action = self._pending_calib_action, None
    sess = self._calib_session
    _, clamp_fld = calibrate_pitch.calib_field_names(sess.target)
    if action == "step":
        sess.step = calibrate_pitch.next_step(sess.step)
        self._repost_calib_embed()
    elif action in ("up", "down"):
        self._sampler_pitch_prepare()
        dy = -sess.step if action == "up" else sess.step   # 上＝dy<0（取樣視窗語意）
        ok = self._pitch_drag_verified(f"[校準] {action} {sess.step}px",
                                       lambda: ic.pitch_nudge(dy))
        sess.offset = calibrate_pitch.apply_calib_step(sess.offset, action, sess.step)
        self._pitch_offset_px = sess.offset
        self._repost_calib_embed(
            "" if ok else "拖曳疑似被吃（記帳照調；懷疑沒動就 🧭 重新絕對定位）")
        self._calib_snapshot()
    elif action == "home":
        self._sampler_pitch_prepare()
        ok = self._pitch_drag_verified(
            "[校準] 歸位到夾限",
            lambda: ic.pitch_reset(getattr(cfg, clamp_fld), 0))
        sess.offset = 0
        self._pitch_offset_px = 0
        self._repost_calib_embed("" if ok else "歸位疑似被吃——再按一次 🧭")
        self._calib_snapshot()
    elif action == "snap":
        self._calib_snapshot()
    elif action == "save":
        self._calib_save(sess)
        self._repost_calib_embed()
    elif action == "exit":
        self._calib_exit(sess)

def _calib_snapshot(self):
    """校準截圖：落編號樣本（sidecar 記俯仰偏移）＋回傳 Discord（含 offset/幅度標註）。"""
    from . import notify
    sess = self._calib_session
    frame = capture.grab()
    stem = sampler.save_sample(frame, cfg.manual_snapshot_dir, self._pitch_offset_px)
    path = os.path.join(cfg.manual_snapshot_dir, f"{stem}.png")
    ok, detail = notify.send_images_message(
        cfg.discord_bot_token, cfg.discord_channel_id,
        f"🎯 校準 #{stem}｜夾限上 {sess.offset}px｜幅度 {sess.step}px", [path])
    self.log_discord.info("calib snapshot #%s -> %s", stem, detail)
```

3b. `_poll_discord`（main.py:1277-1278 `if self._remote_message_id: self._poll_remote_reactions()` 之後）加：

```python
if self._calib_session is not None:
    self._poll_calib_reactions()
```

3c. `run()` paused 分支（main.py:1889-1892）改為：

```python
if self.paused:
    if self._calib_session is not None:
        self._tick_calibration()          # 校準動作只在 paused 分支消費（session 活著＝必暫停）
    # 防掛機踢除：暫停中每 antiafk_interval_s 按一次 Space
    self._antiafk_tick("暫停")
    time.sleep(0.05); continue
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_main_calibration.py -q`
Expected: PASS

- [ ] **Step 5: 全量驗證**

Run: `uv run pytest -q; uv run ruff check . --no-cache`
Expected: 全綠

---

### Task 7: 校準中互動守門＋help 文案＋啟動殘留卡清理

**Files:**
- Modify: `miningbot/main.py`
  - `_handle_discord_command` 方法頂部（`cmd`/`args` 賦值後）加校準中守門
  - `_poll_remote_reactions` for 迴圈頂部加校準中守門
  - `cmd == "help"` 分支加 `校準` 一行（用 `rg -n '"help"' miningbot/main.py` 定位）
  - 新方法 `_ensure_no_stale_calib`；在 `run()` 呼叫 `self._ensure_remote_control()`（main.py:1882）之後呼叫
- Test: `tests/test_main_calibration.py`

**Interfaces:**
- Consumes: Task 2 `CALIB_TITLE`、既有 `notify.fetch_messages`/`find_remote_messages`/`delete_message`。
- Produces: 校準中 `pause`/`resume`（指令與 ▶️⏸️）只改 `sess.prev_paused` 不解除校準；`ability`/`回礦`/`reenter` 拒絕回覆「校準中」；📷 照常。啟動時殘留校準卡一律刪除（不認領）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_main_calibration.py` 末尾加：

```python
from miningbot import discord_commands
from miningbot.states import State


def _guard_bot(monkeypatch, sent):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    bot.state = State.MINING
    bot._calib_session = calibrate_pitch.CalibSession(
        target="mining", offset=300, prev_paused=False)
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    monkeypatch.setattr(main.cfg, "discord_bot_token", "t")
    monkeypatch.setattr(main.cfg, "discord_channel_id", "c")
    return bot


def test_pause_resume_during_calib_records_intent_only(monkeypatch):
    sent = []
    bot = _guard_bot(monkeypatch, sent)
    bot._handle_discord_command(discord_commands.DiscordCommand("pause", ()))
    assert bot._calib_session.prev_paused is True     # 只記離場後意圖
    assert bot._calib_session is not None             # 不解除校準
    bot._handle_discord_command(discord_commands.DiscordCommand("resume", ()))
    assert bot._calib_session.prev_paused is False
    assert all("校準中" in m for m in sent)


def test_game_input_commands_rejected_during_calib(monkeypatch):
    sent = []
    bot = _guard_bot(monkeypatch, sent)
    bot._handle_discord_command(discord_commands.DiscordCommand("回礦", ()))
    bot._handle_discord_command(discord_commands.DiscordCommand("ability", ()))
    assert len(sent) == 2 and all("校準中" in m for m in sent)
    assert getattr(bot, "_manual_reentry", False) is False


def test_ensure_no_stale_calib_deletes_all(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    monkeypatch.setattr(main.cfg, "discord_bot_token", "t")
    monkeypatch.setattr(main.cfg, "discord_channel_id", "c")
    msgs = [
        {"id": "1", "author": {"bot": True},
         "embeds": [{"title": calibrate_pitch.CALIB_TITLE}]},
        {"id": "2", "author": {"bot": True},
         "embeds": [{"title": calibrate_pitch.CALIB_TITLE}]},
        {"id": "3", "author": {"bot": True}, "embeds": [{"title": "別的卡"}]},
    ]
    monkeypatch.setattr(notify_mod, "fetch_messages",
                        lambda token, ch, **kw: msgs)
    deleted = []
    monkeypatch.setattr(notify_mod, "delete_message",
                        lambda token, ch, mid, **kw: deleted.append(mid) or (True, "ok"))
    bot._ensure_no_stale_calib()
    assert sorted(deleted) == ["1", "2"]      # 殘留卡全刪不認領（session 不跨重啟）
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_main_calibration.py -q`
Expected: FAIL（守門不存在——pause 分支會直接 `self._pause()`；`_ensure_no_stale_calib` 不存在）

- [ ] **Step 3: 實作**

3a. `_handle_discord_command`（`cmd = command.name` / `args = command.args` 之後）加：

```python
if self._calib_session is not None and cmd in (
        "pause", "resume", "回礦", "reenter", "ability"):
    # 校準中（2026-07-18 spec 第 1 節）：pause/resume 只記離場後意圖不解除校準；
    # 其餘遊戲輸入指令一律拒絕不排隊。📷/shot/status 等唯讀不在此列、照常。
    if cmd in ("pause", "resume"):
        self._calib_session.prev_paused = (cmd == "pause")
        notify.send_message(token, ch,
            f"🎯 校準中——已記下：離開校準後將"
            f"{'保持暫停' if cmd == 'pause' else '恢復挖礦'}")
    else:
        notify.send_message(token, ch, "❌ 校準中——先按校準卡 ❌ 離開再操作")
    self.log_discord.info("CMD %s during calib -> intent/reject", cmd)
    return
```

3b. `_poll_remote_reactions` for 迴圈內（`action_taken = action` 之後、既有 dispatch 之前）加：

```python
if self._calib_session is not None and action != "snap":
    # 校準中：▶️/⏸️ 只記離場後意圖；⚡/🏠 拒絕。📷 唯讀照常（fall through）。
    if action in ("resume", "pause"):
        self._calib_session.prev_paused = (action == "pause")
        notify.send_message(token, ch,
            f"🎯 校準中——離開校準後將"
            f"{'保持暫停' if action == 'pause' else '恢復挖礦'}")
    else:
        notify.send_message(token, ch, "❌ 校準中——先按校準卡 ❌ 離開再操作")
    self.log_discord.info("remote %s during calib -> intent/reject", action)
    break
```

3c. `cmd == "help"` 分支的說明文字加一行（放在 `回礦` 說明附近）：

```
`校準 [挖礦|回礦]`：進俯仰校準卡（⬆️⬇️ 調角、🔁 幅度 1/5/10/50、💾 寫回 config）
```

3d. 新方法（`_ensure_remote_control` 之後）＋呼叫點：

```python
def _ensure_no_stale_calib(self):
    """啟動清跨重啟殘留校準卡：session 不跨重啟，殘留卡一律作廢刪除（spec 第 2 節）。

    復用 find_remote_messages 的「bot 作者＋embed 標題」匹配；newest 也不認領——
    殘留卡的 session 記帳已丟失，認領只會做出角度與記帳脫鉤的卡。
    """
    from . import notify
    token, ch = cfg.discord_bot_token, cfg.discord_channel_id
    msgs = notify.fetch_messages(token, ch, limit=20)
    newest, stale = notify.find_remote_messages(msgs, calibrate_pitch.CALIB_TITLE)
    for mid in ([newest] if newest else []) + stale:
        ok, detail = notify.delete_message(token, ch, mid)
        self.log_discord.info("stale calib card mid=%s deleted -> %s", mid, detail)
```

`run()` 內 `self._ensure_remote_control()`（main.py:1882）下一行加：

```python
self._ensure_no_stale_calib()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_main_calibration.py -q`
Expected: PASS

- [ ] **Step 5: 全量驗證**

Run: `uv run pytest -q; uv run ruff check . --no-cache`
Expected: 全綠

---

### Task 8: 全量驗證與文件收尾

**Files:**
- Modify: `docs/superpowers/specs/2026-07-18-discord-pitch-calibration-design.md`（狀態行改「已實作（2026-07-18）」）
- Modify: `CLAUDE.md` 常用命令段**不動**（校準 CLI 保留）。AGENTS.md：先跑 `rg -n "回礦|reenter|Discord 指令" AGENTS.md` 查證——若有列 Discord 指令清單的段落，在該處加一行 `校準 [挖礦|回礦]`；沒有此類段落就不改 AGENTS.md。

**Interfaces:**
- Consumes: Task 1-7 全部完成。

- [ ] **Step 1: 全量測試**

Run: `uv run pytest -q`
Expected: 全綠（含既有 768+ 測試與本計畫新增全部）

- [ ] **Step 2: Lint 與收集檢查**

Run: `uv run ruff check . --no-cache; uv run pytest --collect-only -q`
Expected: 無違規；collect 無錯誤

- [ ] **Step 3: 鐵律自查（人工核對清單）**

逐項確認並在回報中列出證據（檔案:行號）：
- `_poll_calib_reactions`、`_handle_discord_command` 校準分支**沒有**任何 `ic.` 呼叫、`_pause`/`_resume` 呼叫（守門分支只改 `sess.prev_paused` 布林，允許）。
- `_tick_calibration` 只被 `run()` paused 分支呼叫。
- `states.py` 零改動（`git diff --stat miningbot/states.py` 為空）。
- 既有測試檔只有新增、無修改既有 test 函式（`git diff tests/test_calibrate_pitch.py tests/test_discord_commands.py` 檢查）。

- [ ] **Step 4: spec 狀態更新**

`docs/superpowers/specs/2026-07-18-discord-pitch-calibration-design.md` 的
`狀態：設計定案，待實作計畫` 改為 `狀態：已實作（2026-07-18；計畫 docs/superpowers/plans/2026-07-18-discord-pitch-calibration.md）`。

- [ ] **Step 5: 回報**

不 commit。回報：新增/修改檔案清單、測試數量變化、鐵律自查證據、待使用者實機驗證項目（進場歸位、⬆️⬇️ 截圖迴圈、💾 寫回後重啟讀值、❌ 恢復挖礦）。
