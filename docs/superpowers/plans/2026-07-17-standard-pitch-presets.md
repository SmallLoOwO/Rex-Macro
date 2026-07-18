# 兩套具名標準俯角 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立「挖礦標準角」歸位（bot 啟動＋回礦成功收尾），重用既有 mid 層 config 欄位，並提供礦內校準 CLI。

**Architecture:** 全部依附既有 `pitch_reset`（夾限飽和→回拉＝絕對定位）機制。新增一個純決策
（`harvester.mining_pitch_home_enabled`）、一個 Bot 共用 I/O 方法（`_pitch_home_mining`，
被吃只警告不擋流程）、三個接線點（`run()` 啟動、`_rr_success`、auto `CLICK_VERIFY`）、
一個校準 CLI（`calibrate_pitch`）。回礦標準角（`reentry_pitch_back_px`）零程式變更——
只需實機重校準寫回 config。

**Tech Stack:** Python 3.11+／Windows、pytest、既有 `input_control`／`config`／`harvester` 模組。

**Spec:** `docs/superpowers/specs/2026-07-17-standard-pitch-presets-design.md`

## Global Constraints

- **不 commit**：本分支已有未 commit 的 079 快照修復（同樣改 `main.py`）待實機驗證；
  per-task commit 會把無關修改掃進去。每 task 以「該檔測試綠」收尾，最終由使用者
  驗證 diff 後統一 commit。**這條覆蓋下方所有 task 的收尾步驟。**
- **不新增 Config 欄位、不改任何既有數值**：重用 `sweep_pitch_clamp_px`／
  `sweep_pitch_center_back_px`（挖礦標準角）與 `reentry_pitch_clamp_px`／
  `reentry_pitch_back_px`（回礦標準角）。
- **不動既有 pitch 回歸測試**（pitch_eaten、probe_frozen、plan_pitch_layers 等全保留）。
- 專案慣例：決策純函式可單測、I/O 收在 `main.Bot`；`<=0`＝未校準＝停用
  （與 `plan_pitch_layers` 同語意），缺校準不靜默改變行為。
- 執行模型：**Sonnet 5 子代理**（Agent tool `model: "sonnet"`），主 session 負責派工與審查。
- 驗證命令一律 `uv run pytest ... -q`、`uv run ruff check . --no-cache`。

---

### Task 1: 純決策 `mining_pitch_home_enabled`

**Files:**
- Modify: `miningbot/harvester.py`（緊接 `plan_pitch_layers` 之後，約 line 47）
- Test: `tests/test_harvester.py`（檔尾追加）

**Interfaces:**
- Produces: `harvester.mining_pitch_home_enabled(center_back_px: int) -> bool`
  （Task 2 的 `_pitch_home_mining` 用它當執行閘）

- [ ] **Step 1: Write the failing test**

在 `tests/test_harvester.py` 檔尾追加（檔案已有 `from miningbot import harvester`）：

```python
def test_mining_pitch_home_enabled_requires_calibration():
    # <=0＝未校準＝停用（與 plan_pitch_layers 同慣例）；>0＝已校準
    assert harvester.mining_pitch_home_enabled(0) is False
    assert harvester.mining_pitch_home_enabled(-40) is False
    assert harvester.mining_pitch_home_enabled(300) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_harvester.py::test_mining_pitch_home_enabled_requires_calibration -q`
Expected: FAIL — `AttributeError: module 'miningbot.harvester' has no attribute 'mining_pitch_home_enabled'`

- [ ] **Step 3: Write minimal implementation**

在 `miningbot/harvester.py` 的 `plan_pitch_layers` 函式之後加：

```python
def mining_pitch_home_enabled(center_back_px: int) -> bool:
    """挖礦標準角歸位是否啟用（純函式；spec 2026-07-17 兩套具名標準俯角）。

    與 plan_pitch_layers 同慣例：center_back_px <= 0＝未校準＝停用——缺校準
    不靜默改變行為（維持現狀角度，呼叫端記警告）。
    """
    return center_back_px > 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_harvester.py -q`
Expected: 全數 PASS（含既有測試）

---

### Task 2: Bot 共用方法 `_pitch_home_mining`＋`_pitch_restore_if_touched` 重用

**Files:**
- Modify: `miningbot/main.py`（`_pitch_restore_if_touched` 附近，約 line 4760）
- Test: `tests/test_main_pitch_home.py`（新檔）

**Interfaces:**
- Consumes: `harvester.mining_pitch_home_enabled`（Task 1）、既有
  `self._pitch_drag_verified(label, drag) -> bool`、`self._sampler_pitch_prepare()`、
  `ic.pitch_reset(down_px, back_px)`
- Produces: `Bot._pitch_home_mining(label: str) -> bool`（Task 3 三個接線點呼叫；
  True＝已歸位，False＝未校準或兩輪被吃——呼叫端**不得**因 False 中斷流程）

- [ ] **Step 1: Write the failing tests**

新檔 `tests/test_main_pitch_home.py`：

```python
from miningbot import main
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


def _bot(monkeypatch, center_back_px):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._pitch_offset_px = 0
    bot._sampler_pitch_prepare = lambda: None
    monkeypatch.setattr(main.cfg, "sweep_pitch_center_back_px", center_back_px)
    monkeypatch.setattr(main.cfg, "sweep_pitch_clamp_px", 1500)
    return bot


def test_pitch_home_mining_skips_when_uncalibrated(monkeypatch):
    bot = _bot(monkeypatch, 0)
    calls = []
    bot._pitch_drag_verified = lambda label, drag: calls.append(label) or True
    assert bot._pitch_home_mining("啟動") is False
    assert calls == []                       # 未校準：一次拖曳都不准送
    assert any("未校準" in r for r in bot.logger.records)


def test_pitch_home_mining_success_sets_offset(monkeypatch):
    bot = _bot(monkeypatch, 300)
    drags = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: drags.append((down, back)))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    assert bot._pitch_home_mining("啟動") is True
    assert drags == [(1500, 300)]
    assert bot._pitch_offset_px == 300       # 記帳與 _rr_pitch 同語意（距夾限偏移）


def test_pitch_home_mining_two_eaten_warns_not_blocks(monkeypatch):
    bot = _bot(monkeypatch, 300)
    attempts = []
    bot._pitch_drag_verified = lambda label, drag: attempts.append(label) or False
    assert bot._pitch_home_mining("啟動") is False
    assert len(attempts) == 2                # 重試一次即止
    assert any("兩輪皆疑似被吃" in r for r in bot.logger.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_main_pitch_home.py -q`
Expected: 3 FAIL — `AttributeError: 'Bot' object has no attribute '_pitch_home_mining'`

- [ ] **Step 3: Implement `_pitch_home_mining`＋改寫 `_pitch_restore_if_touched`**

在 `miningbot/main.py` 的 `_pitch_restore_if_touched` 前面加新方法：

```python
    def _pitch_home_mining(self, label: str) -> bool:
        """歸位到挖礦標準角（sweep_pitch_center_back_px；spec 2026-07-17 兩套具名標準俯角）。

        未校準（<=0）跳過並警告、維持現狀角度（「未校準＝停用」慣例，缺校準不
        靜默改變行為）；被吃重試一次後只警告不擋流程（比照 H046「俯仰被吃不擋
        拍照」——歸位失敗頂多回到「角度不受控」的現狀，不值得為它擋掛機）。
        """
        if not harvester.mining_pitch_home_enabled(cfg.sweep_pitch_center_back_px):
            self.logger.warning(
                "%s：挖礦標準角未校準（sweep_pitch_center_back_px<=0）——跳過歸位", label)
            return False
        self._sampler_pitch_prepare()
        for attempt in (1, 2):
            if self._pitch_drag_verified(
                    f"{label} 挖礦標準角歸位(attempt {attempt})",
                    lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                           cfg.sweep_pitch_center_back_px)):
                self._pitch_offset_px = cfg.sweep_pitch_center_back_px
                return True
            self._sampler_pitch_prepare()
        self.logger.warning("%s：挖礦標準角歸位兩輪皆疑似被吃——視角可能非標準角，人工留意",
                            label)
        return False
```

把 `_pitch_restore_if_touched` 整個函式改成（docstring 保留原文前兩段語意）：

```python
    def _pitch_restore_if_touched(self):
        """採集收尾俯仰歸位：動過俯仰層（含轉換失敗——reset 可能已改角度）才歸位到置中標準角。

        使用者挖礦視角習慣＝置中（2026-07-11 確認），center_back_px 即校準成置中 → 歸位＝
        回到平常挖礦角度。沒動過（絕大多數採集）零成本零風險。重試/警告收斂進
        _pitch_home_mining（pitch_touched 只在 sweep_pitch 已校準時可能為 True，
        歸位閘在此路徑必過）。
        """
        if not self.harvest.pitch_touched:
            return
        self._pitch_home_mining(f"[{self.harvest.harvest_id}] 收尾")
```

行為差異（皆為改善、記入 PR 說明）：收尾歸位現在會先 `_sampler_pitch_prepare()`
（游標保證在遊戲內）、並維護 `_pitch_offset_px` 記帳（原本沒有；與 `_rr_pitch` 對齊）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_main_pitch_home.py tests/test_harvester.py -q`
Expected: 全數 PASS

---

### Task 3: 三個接線點（啟動／`_rr_success`／auto `CLICK_VERIFY`）＋順序測試

**Files:**
- Modify: `miningbot/main.py:1837`（`run()` 內 `self._startup_phase = False` 之後）
- Modify: `miningbot/main.py:4215`（`_rr_success`）
- Modify: `miningbot/main.py:4417`（auto `CLICK_VERIFY` 成功分支）
- Test: `tests/test_main_pitch_home.py`（追加）

**Interfaces:**
- Consumes: `Bot._pitch_home_mining(label) -> bool`（Task 2）

- [ ] **Step 1: Write the failing tests**

在 `tests/test_main_pitch_home.py` 檔尾追加：

```python
from miningbot import reentry_remote


def _rr_bot(monkeypatch, order):
    bot = Bot.__new__(Bot)
    monkeypatch.setattr(main.cfg, "movement_mode_mining", "Default (Keyboard)")
    bot._set_movement_mode = lambda target: order.append("movement") or True
    bot._pitch_home_mining = lambda label: order.append("home") or True
    bot._rr_finalize = lambda outcome: order.append("finalize")
    bot._rr_notify = lambda msg, **kw: None
    return bot


def test_rr_success_order_movement_home_finalize(monkeypatch):
    # spec 第 4 節：movement mode 復原 → 歸位 → ledger → 回 MINING
    order = []
    bot = _rr_bot(monkeypatch, order)
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="mid")
    ctx.walked = True
    bot._rr_success(ctx, "success")
    assert order == ["movement", "home", "finalize"]
    assert bot._reentry_done is True


def test_rr_success_without_walk_still_homes(monkeypatch):
    order = []
    bot = _rr_bot(monkeypatch, order)
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=8, created_at=0.0, sticky_layer="mid")
    bot._rr_success(ctx, "confirmed_by_user")
    assert order == ["home", "finalize"]
    assert bot._reentry_done is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_main_pitch_home.py -q`
Expected: 新增 2 筆 FAIL——`order` 缺 `"home"`（`_rr_success` 尚未呼叫歸位）

- [ ] **Step 3: 接線 `_rr_success`**

`miningbot/main.py` `_rr_success` 改為：

```python
    def _rr_success(self, ctx, outcome):
        """成功收尾：movement mode 復原（若走過位）→ 挖礦標準角歸位 → ledger → 回 MINING。"""
        if ctx.walked:
            self._set_movement_mode(cfg.movement_mode_mining)
        self._pitch_home_mining(f"[RR#{ctx.episode_id}] 回礦收尾")
        self._rr_finalize(outcome)
        self._reentry_done = True                 # decide_transition → MINING → init 序列
        self._rr_notify("⛏ 回礦完成，開挖")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_main_pitch_home.py -q`
Expected: 全數 PASS

- [ ] **Step 5: 接線 auto `CLICK_VERIFY` 成功分支**

`miningbot/main.py` auto 版（`_tick_reentry` 的 `CLICK_VERIFY` 段，約 line 4411-4417）：
在 `_set_movement_mode` 成功之後、`self._reentry_done = True` 之前插一行：

```python
                    if not self._set_movement_mode(cfg.movement_mode_mining):
                        self.logger.warning("REENTRY 進礦成功但切回 Movement Mode 失敗 -> NEEDS_HUMAN")
                        self._human_reason = "自動回礦成功但無法切回 Default (Keyboard)，請手動確認設定後按 Q"
                        self.state = State.NEEDS_HUMAN
                        self._on_enter(State.NEEDS_HUMAN, frame)
                        return
                    self._pitch_home_mining("REENTRY(auto) 回礦收尾")
                    self._reentry_done = True
```

- [ ] **Step 6: 接線啟動歸位（`run()`）**

`miningbot/main.py` `run()` 內（line ~1837）：

```python
        self._startup_phase = False
        # 挖礦標準角歸位（spec 2026-07-17）：人啟動前留的角度不受控，進第一輪掃描前
        # 歸位；未校準（<=0）維持現狀只警告。不納入 Q 跳過——只要 2~3s，且跳過會讓
        # 「啟動角度不可靠」的動機靜默失效。
        self.last_action = "俯仰歸位（挖礦標準角）"
        self._pitch_home_mining("啟動")
        miner.init_mining_sequence(rotate=self._rotate_verified)
```

（`run()` 不可單測——由 Task 2 的單元測試＋實機驗證覆蓋；實機檢核點見 Task 5。）

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -q`
Expected: 全綠（基線 768 過＋本計畫新增測試）

---

### Task 4: 校準 CLI `calibrate_pitch`

**Files:**
- Create: `miningbot/calibrate_pitch.py`
- Test: `tests/test_calibrate_pitch.py`（新檔）

**Interfaces:**
- Consumes: `ic.pitch_reset(down_px, back_px)`、`ic.pitch_nudge(dy)`、`ic.move_to`、
  `ic.settle`、`cfg.sweep_pitch_clamp_px`／`sample_pitch_step_px`／
  `sampler_pitch_focus_settle_s`／`window_title`／`screen_w`／`screen_h`
- Produces: `parse_calib_command(text: str, default_step: int) -> tuple | None`
  （`("reset"|"quit", 0)` 或 `("up"|"down", px)`）、
  `apply_calib_step(offset: int, kind: str, px: int) -> int`

- [ ] **Step 1: Write the failing tests**

新檔 `tests/test_calibrate_pitch.py`：

```python
from miningbot.calibrate_pitch import apply_calib_step, parse_calib_command


def test_parse_defaults_and_explicit_px():
    assert parse_calib_command("r", 40) == ("reset", 0)
    assert parse_calib_command("q", 40) == ("quit", 0)
    assert parse_calib_command("u", 40) == ("up", 40)      # 未給 px 用預設步長
    assert parse_calib_command("d 60", 40) == ("down", 60)
    assert parse_calib_command("UP 25", 40) == ("up", 25)  # 大小寫不敏感


def test_parse_rejects_garbage():
    # 寧可不動不誤動：解析不出回 None（與 reentry_remote.parse_reply 同哲學）
    assert parse_calib_command("", 40) is None
    assert parse_calib_command("x", 40) is None
    assert parse_calib_command("u 0", 40) is None
    assert parse_calib_command("u -5", 40) is None
    assert parse_calib_command("u abc", 40) is None
    assert parse_calib_command("r 10", 40) is None


def test_apply_step_accounting_saturates_at_clamp():
    assert apply_calib_step(120, "reset", 0) == 0
    assert apply_calib_step(0, "up", 40) == 40
    assert apply_calib_step(40, "down", 25) == 15
    assert apply_calib_step(15, "down", 100) == 0   # 夾限飽和：不記負值
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_calibrate_pitch.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'miningbot.calibrate_pitch'`

- [ ] **Step 3: Write the CLI**

新檔 `miningbot/calibrate_pitch.py`：

```python
"""校準 CLI：量出「挖礦標準角」sweep_pitch_center_back_px（spec 2026-07-17）。

用法（站在礦內、Roblox 開著；console 與遊戲來回切換）：
  uv run python -m miningbot.calibrate_pitch

互動指令（每步先自動聚焦回遊戲、游標移進畫面、沉澱後才拖曳）：
  r         歸位到夾限（累計回拉量歸 0；一切從絕對基準起算）
  u [px]    向上拉 px（預設 sample_pitch_step_px）
  d [px]    向下拉 px（已在夾限再往下只會飽和，記帳同步夾 0）
  q         結束並印最終值

畫面滿意時把印出的「累計回拉量」寫回 config.sweep_pitch_center_back_px。
"""
import time

from . import input_control as ic
from .config import DEFAULT as cfg


def parse_calib_command(text: str, default_step: int):
    """互動指令解析（純函式；寧可不動不誤動，解析不出回 None）。"""
    parts = (text or "").strip().lower().split()
    if not parts:
        return None
    head = parts[0]
    if head in ("q", "quit") and len(parts) == 1:
        return ("quit", 0)
    if head in ("r", "reset") and len(parts) == 1:
        return ("reset", 0)
    if head in ("u", "up", "d", "down"):
        kind = "up" if head in ("u", "up") else "down"
        if len(parts) == 1:
            return (kind, default_step)
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
            return (kind, int(parts[1]))
        return None
    return None


def apply_calib_step(offset: int, kind: str, px: int) -> int:
    """累計回拉量記帳（純函式）。reset＝回夾限（0）；up＝+px；down＝-px 但夾 0——
    物理事實：已在夾限再往下拖只會飽和，記負值＝記帳與實際角度脫鉤。"""
    if kind == "reset":
        return 0
    if kind == "up":
        return offset + px
    return max(0, offset - px)


def _focus_and_settle():
    """找 Roblox → 最大化 → 前景 → 游標移進畫面 → 沉澱（拖曳前必要沉澱：
    焦點剛切回就送右鍵拖曳會被吃，見 sampler_pitch_focus_settle_s 註解）。
    校準有人在場，聚焦失敗印提示請人手點一下即可——不搬 main._focus_roblox
    的 AttachThreadInput 補救，CLI 保持薄。"""
    import ctypes
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, cfg.window_title)
    if not hwnd:
        raise SystemExit(f"找不到 Roblox 視窗（title={cfg.window_title}）；先開好遊戲")
    u.ShowWindow(hwnd, 3)      # SW_MAXIMIZE（不可 SW_RESTORE——會縮窗座標全錯）
    time.sleep(0.3)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    if u.GetForegroundWindow() != hwnd:
        print("⚠ 未取得前景焦點——請手動點一下遊戲視窗後重送指令")
    ic.move_to(cfg.screen_w // 2, cfg.screen_h // 2)
    ic.settle(cfg.sampler_pitch_focus_settle_s)


def main():
    print(__doc__)
    offset = None                          # None＝尚未 r 歸位（無絕對基準不准微調）
    while True:
        try:
            line = input("calibrate-pitch> ").strip()
        except EOFError:
            break
        cmd = parse_calib_command(line, cfg.sample_pitch_step_px)
        if cmd is None:
            print("指令：r（歸位）/ u [px] / d [px] / q（結束）")
            continue
        kind, px = cmd
        if kind == "quit":
            break
        if kind != "reset" and offset is None:
            print("先 r 歸位到夾限（絕對基準），再微調")
            continue
        _focus_and_settle()
        if kind == "reset":
            ic.pitch_reset(cfg.sweep_pitch_clamp_px, 0)
            offset = 0
        else:
            ic.pitch_nudge(-px if kind == "up" else px)   # 上＝dy<0（沿用取樣視窗語意）
            offset = apply_calib_step(offset, kind, px)
        print(f"累計回拉量（夾限→現在）= {offset}px")
    if offset is not None:
        print(f"最終：sweep_pitch_center_back_px = {offset}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_calibrate_pitch.py -q`
Expected: 3 PASS

---

### Task 5: 文件同步＋全套驗證

**Files:**
- Modify: `AGENTS.md`（命令區塊，`calibrate_surface` 行之後，約 line 143）
- Modify: `CLAUDE.md`（「常用命令」區塊，`calibrate_surface` 行之後）

**Interfaces:** 無（純文件＋驗證）

- [ ] **Step 1: 命令清單補 `calibrate_pitch`**

兩份文件的命令區塊各加一行（放在 `calibrate_surface` 那行後面）：

```powershell
uv run python -m miningbot.calibrate_pitch
```

- [ ] **Step 2: Run full verification**

Run: `uv run pytest -q`
Expected: 全綠（基線＋新增 9 筆）
Run: `uv run ruff check . --no-cache`
Expected: 無違規

- [ ] **Step 3: 實機驗證檢核點（記入交付說明，執行由使用者掛機時進行）**

1. 未校準現狀（`sweep_pitch_center_back_px=0`）啟動：log 出現
   「啟動：挖礦標準角未校準……跳過歸位」warning，其餘行為與現狀完全相同。
2. 跑 `calibrate_pitch` 校準出值、寫回 config 後啟動：log 出現
   「啟動 挖礦標準角歸位(attempt 1)」且畫面歸到標準角。
3. 一次 remote 回礦成功收尾後：log 出現「[RR#N] 回礦收尾 挖礦標準角歸位」。
4. 回礦標準角重校準（零程式）：實機回礦 episode 中 `仰角 上/下 [px]`＋📷 迭代，
   從 log 讀 `_pitch_offset_px` 記帳值寫回 `reentry_pitch_back_px`。
