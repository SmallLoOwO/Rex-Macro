# 手動回礦指令＋H044 探測式開場 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修 H044（REENTRY 在客戶端凍結中誤跑＋覆蓋視窗假傳送）＋新增手動回礦觸發（Discord `回礦` 指令與 STUCK 警告 🏠 反應鈕）。

**Architecture:** 傳送驗證從全幀改量 `reentry_game_region` 遊戲區（雙訊號 mean/frac OR）；開場點擊改探測式重試（點擊當探針，凍結中每 ~20s 重探、預算 300s 用盡才通知）；手動觸發走 `states.decide_transition` 純函式新旗標 `manual_reentry`。設計全文：`docs/superpowers/specs/2026-07-14-manual-reentry-and-freeze-gate-design.md`。

**Tech Stack:** Python、OpenCV（幀差）、pytest、Discord REST（stdlib urllib）。

## Global Constraints

- **程式實作任務（Task 2-4）依專案慣例委派 opencode**（GLM 5.2，無視覺）：執行時把該任務全文＋本節做成自足規格書丟給 `opencode run`；**opencode 不 commit、不讀任何圖片**。Task 1/5/6 由 Claude 親自做（視覺/文件/驗證）。
- TDD：每個任務先寫失敗測試再實作；完成標準 `python -m pytest -q` 全綠。
- 座標/門檻只進 `miningbot/config.py`，不散落。
- 執行緒鐵律：Discord 輪詢執行緒只寫旗標/回覆，**絕不碰 input_control**；輸入全在主迴圈。
- 布林旗標跨執行緒指定在 GIL 下為原子（比照 `human_cleared`/`_pending_ability`），不需鎖。
- 兩側夾數據（Task 1 固化，測試必須鎖住）：真傳送 mean **57.73**/frac **0.9966**；活著靜止 mean **≤0.09**/frac **≤0.0004**；凍結 **0.00**/0.0000。門檻 `reentry_teleport_diff=12.0`、`reentry_teleport_frac=0.05`。

---

### Task 1: H044 fixture 固化（Claude 親自——需讀圖）

**Files:**
- Create: `tests/fixtures/reentry/h044_frozen_a.png`, `h044_frozen_b.png`（凍結對，5s 間隔，逐位元相同）
- Create: `tests/fixtures/reentry/h044_alive_static_a.png`, `h044_alive_static_b.png`（活著靜止對，0.35s）
- Create: `tests/fixtures/reentry/h044_teleport_a.png`, `h044_teleport_b.png`（礦內→地表真傳送對）
- Create: `tests/test_reentry_fixtures.py`

**Interfaces:**
- Produces: 6 張 690×650 裁圖 fixture＋`tests/test_reentry_fixtures.py`（Task 2 的 config 門檻由此測試鎖定；先寫成引用 `config.DEFAULT.reentry_teleport_diff/reentry_teleport_frac`，Task 2 加欄位前此測試會 AttributeError＝紅燈，Task 2 完成即綠）

- [ ] **Step 1: 裁圖**

```python
# scratchpad/crop_h044.py — 跑一次即可
import cv2, os
REG = (1100, 200, 690, 650)   # 與 config reentry_game_region 一致
def crop(p):
    im = cv2.imread(p); x, y, w, h = REG
    return im[y:y+h, x:x+w]
S = 'logs/snapshots'
OUT = 'tests/fixtures/reentry'
os.makedirs(OUT, exist_ok=True)
pairs = {
  'h044_frozen_a.png':       S+'/reentry/20260714_182641_reentry_ep3_dir0.png',
  'h044_frozen_b.png':       S+'/reentry/20260714_182646_reentry_ep3_dir1.png',
  'h044_alive_static_a.png': S+'/trace/20260712_195521_pitch_eaten_before.png',
  'h044_alive_static_b.png': S+'/trace/20260712_195521_pitch_eaten_after.png',
  'h044_teleport_a.png':     S+'/trace/20260714_182543_mine_reset.png',
  'h044_teleport_b.png':     S+'/reentry/20260714_182836_reentry_ep3_dir0.png',
}
for name, src in pairs.items():
    cv2.imwrite(os.path.join(OUT, name), crop(src))
print('done')
```

- [ ] **Step 2: 寫 fixture 測試（先紅——config 欄位尚不存在）**

```python
# tests/test_reentry_fixtures.py
"""H044 fixture 回歸：傳送驗證區域化的兩側夾（2026-07-14 實錄裁圖）。

fixture 已是 reentry_game_region(1100,200,690,650) 的 690×650 裁圖；
若日後改 region 座標，fixture 必須從 logs/snapshots 原幀重裁。
量測紀錄：真傳送 mean 57.73/frac 0.9966；活著靜止 mean 0.09/frac 0.0004；凍結 0.00。
"""
import os
import cv2
import pytest
from miningbot import vision
from miningbot.config import DEFAULT as cfg

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "reentry")


def _pair(a, b):
    ia = cv2.imread(os.path.join(FIX, a))
    ib = cv2.imread(os.path.join(FIX, b))
    assert ia is not None and ib is not None
    return ia, ib


def test_frozen_pair_below_both_thresholds():
    a, b = _pair("h044_frozen_a.png", "h044_frozen_b.png")
    assert vision.frame_mean_diff(a, b) < cfg.reentry_teleport_diff
    assert vision.frames_changed_frac(a, b) < cfg.reentry_teleport_frac
    # 凍結＝逐位元相同（H044 核心事實）
    assert vision.frame_mean_diff(a, b) == pytest.approx(0.0, abs=0.01)


def test_alive_static_pair_below_both_thresholds():
    a, b = _pair("h044_alive_static_a.png", "h044_alive_static_b.png")
    assert vision.frame_mean_diff(a, b) < cfg.reentry_teleport_diff
    assert vision.frames_changed_frac(a, b) < cfg.reentry_teleport_frac


def test_teleport_pair_above_both_thresholds():
    a, b = _pair("h044_teleport_a.png", "h044_teleport_b.png")
    assert vision.frame_mean_diff(a, b) >= cfg.reentry_teleport_diff
    assert vision.frames_changed_frac(a, b) >= cfg.reentry_teleport_frac
```

- [ ] **Step 3: 確認紅燈**

Run: `python -m pytest tests/test_reentry_fixtures.py -q`
Expected: ERROR/FAIL（`AttributeError: reentry_teleport_frac`——Task 2 加 config 後轉綠）

- [ ] **Step 4: Commit fixtures＋測試**

```bash
git add tests/fixtures/reentry tests/test_reentry_fixtures.py
git commit -m "test(h044): 固化凍結/活著靜止/真傳送三組 fixture＋傳送門檻兩側夾回歸（暫紅，Task 2 config 補上即綠）"
```

---

### Task 2: config＋reentry_remote 純函式（opencode）

**Files:**
- Modify: `miningbot/config.py`（reentry 區塊，`reentry_click_retries` 之後）
- Modify: `miningbot/reentry_remote.py`
- Test: `tests/test_reentry_remote.py`（新增區塊）

**Interfaces:**
- Consumes: Task 1 的 `tests/test_reentry_fixtures.py`（config 欄位補上後轉綠）
- Produces:
  - `cfg.reentry_game_region: Region`、`cfg.reentry_teleport_frac: float`、`cfg.reentry_open_retry_wait_s: float`、`cfg.reentry_open_budget_s: float`
  - `reentry_remote.plan_open_retry(first_open_ts: float, now: float, wait_s: float, budget_s: float, last_probe_ts: float) -> str`（回 `"probe" | "wait" | "give_up"`）
  - `RemoteReentryContext.trigger: str = "reset"`；`ledger_entry(...)` 輸出多 `"trigger"` 鍵；`build_reentry_embed(...)` footer 手動時前綴「手動觸發｜」

- [ ] **Step 1: 寫失敗測試（tests/test_reentry_remote.py 末尾新增）**

```python
# ===== H044：開場探測節奏＋手動觸發記帳 =====
def test_plan_open_retry_probe_when_interval_elapsed():
    assert reentry_remote.plan_open_retry(0.0, 25.0, 20.0, 300.0, 0.0) == "probe"

def test_plan_open_retry_wait_before_interval():
    assert reentry_remote.plan_open_retry(0.0, 10.0, 20.0, 300.0, 0.0) == "wait"

def test_plan_open_retry_give_up_at_budget():
    assert reentry_remote.plan_open_retry(0.0, 300.0, 20.0, 300.0, 250.0) == "give_up"

def test_plan_open_retry_budget_wins_over_interval():
    # 預算已盡且間隔也到：give_up 優先（不再多點一擊）
    assert reentry_remote.plan_open_retry(0.0, 400.0, 20.0, 300.0, 0.0) == "give_up"

def test_ctx_trigger_default_reset_and_ledger_records_it():
    ctx = reentry_remote.RemoteReentryContext(episode_id=9, created_at=0.0,
                                              sticky_layer="Mantle Layer")
    assert ctx.trigger == "reset"
    entry = reentry_remote.ledger_entry(ctx, "success", "Aesteria", 12.3)
    assert entry["trigger"] == "reset"

def test_embed_footer_marks_manual_trigger():
    ctx = reentry_remote.RemoteReentryContext(episode_id=9, created_at=0.0,
                                              sticky_layer="Mantle Layer",
                                              trigger="manual")
    embed = reentry_remote.build_reentry_embed(ctx, "Mantle Layer", 60.0, False)
    assert embed["footer"]["text"].startswith("手動觸發｜")
    ctx.trigger = "reset"
    embed = reentry_remote.build_reentry_embed(ctx, "Mantle Layer", 60.0, False)
    assert "手動觸發" not in embed["footer"]["text"]
```

- [ ] **Step 2: 跑測試確認紅**

Run: `python -m pytest tests/test_reentry_remote.py -q`
Expected: FAIL（`plan_open_retry` 不存在、`trigger` 非法欄位）

- [ ] **Step 3: config.py 新增欄位（`reentry_click_retries` 之後）**

```python
    reentry_game_region: Region = field(default_factory=lambda: Region(1100, 200, 690, 650))
    # ↑ H044 遊戲專屬觀測區（右側場景帶 x1100-1790/y200-850）：避開頂部橫幅、左側聊天/NORMAL
    #   面板、右側按鈕欄（x≥1800）、左下 HUD，也避開使用者常放覆蓋視窗的中央區。傳送驗證量此區。
    #   ⚠ 此區必須保持無覆蓋視窗；改座標須重裁 tests/fixtures/reentry/h044_*.png。
    reentry_teleport_frac: float = 0.05         # 傳送雙訊號之二（frames_changed_frac ≥ 此值＝傳送）。
    #   兩側夾（H044）：真傳送 0.9966 / 活著靜止 ≤0.0004 / 凍結 0.0000。mean 會被夜空大片黑稀釋，
    #   frac 補位；與 reentry_teleport_diff 取 OR。
    reentry_open_retry_wait_s: float = 20.0     # 開場探測：判「未傳送」後隔多久再點一次（H044 凍結中
    #   點擊無反應，點擊本身就是探針；被動凍結偵測已被量測否決——活著靜止畫面與凍結像素不可分）
    reentry_open_budget_s: float = 300.0        # 開場探測總預算（自 episode 首擊起算；實測凍結 1~2.5
    #   分鐘，300s 蓋過最壞觀測 2 倍）。用盡→通知一次附截圖，等 重骰/跳過/回礦
```

- [ ] **Step 4: reentry_remote.py 實作**

`RemoteReentryContext` 加欄位（`net_zoom` 之後）：

```python
    trigger: str = "reset"       # 本 episode 觸發來源：reset（礦坑重置）/ manual（回礦 指令、🏠）
```

`ledger_entry` 的 dict 加一鍵（`"duration_s"` 之前同層）：

```python
            "trigger": ctx.trigger,
```

新純函式（放在 `next_episode_id` 附近）：

```python
def plan_open_retry(first_open_ts: float, now: float, wait_s: float,
                    budget_s: float, last_probe_ts: float) -> str:
    """開場探測節奏（H044）：上一擊判「未傳送」後的下一步。

    "probe"＝間隔已到且預算未盡（再點一次「回到地表」當探針）；
    "wait"＝間隔未到（主迴圈下 tick 再問）；"give_up"＝預算用盡（通知一次、等人工）。
    預算從 episode 第一擊（first_open_ts）起算——凍結 1~2.5 分鐘是常態，探測本身無害
    （點了沒反應＝什麼都沒發生），預算只是「該告訴人類了」的收口。
    """
    if now - first_open_ts >= budget_s:
        return "give_up"
    if now - last_probe_ts >= wait_s:
        return "probe"
    return "wait"
```

`build_reentry_embed` 的 footer 行改成：

```python
        "footer": {"text": ("手動觸發｜" if ctx.trigger == "manual" else "")
                           + "照片訊息在上方；此卡會隨進度原地更新"},
```

- [ ] **Step 5: 跑測試確認綠（含 Task 1 fixture 測試轉綠）**

Run: `python -m pytest tests/test_reentry_remote.py tests/test_reentry_fixtures.py -q`
Expected: PASS 全綠

---

### Task 3: states 手動旗標＋notify 訊息 id（opencode）

**Files:**
- Modify: `miningbot/states.py`
- Modify: `miningbot/notify.py`
- Test: `tests/test_states.py`、`tests/test_notify.py`（新增/調整）

**Interfaces:**
- Produces:
  - `Observation.manual_reentry: bool = False`
  - `decide_transition`：MINING/NEEDS_HUMAN/RESET_WAIT＋`manual_reentry and auto_reenter` → REENTRY（判序見程式碼）
  - `states.can_accept_manual_reentry(state: State, reentry_active: bool) -> tuple[bool, str]`
  - `notify.send_message_with_id(token, channel_id, content, timeout=10.0) -> (ok: bool, detail: str, message_id: str | None)`；`send_message` 委派它（回傳簽名不變）
  - `notify._TEMPLATES` 移除 `"STUCK"`（改走 Bot 專屬路徑掛 🏠，避免雙發）

- [ ] **Step 1: 寫失敗測試**

`tests/test_states.py` 新增（import 沿用該檔既有寫法）：

```python
# ===== H044 spec 第 3 節：手動回礦觸發 =====
def _obs_manual(**kw):
    base = dict(chill_audio=False, chill_text=False, harvest_done=False,
                harvest_failed=False, human_cleared=False,
                manual_reentry=True, auto_reenter=True)
    base.update(kw)
    return Observation(**base)

def test_manual_reentry_from_mining():
    assert decide_transition(State.MINING, _obs_manual()) is State.REENTRY

def test_manual_reentry_from_needs_human_beats_human_cleared():
    o = _obs_manual(human_cleared=True)
    assert decide_transition(State.NEEDS_HUMAN, o) is State.REENTRY

def test_manual_reentry_from_reset_wait_bypasses_reset_complete():
    o = _obs_manual(mine_resetting=True, reset_complete=False)
    assert decide_transition(State.RESET_WAIT, o) is State.REENTRY

def test_manual_reentry_ignored_without_auto_reenter():
    o = _obs_manual(auto_reenter=False)
    assert decide_transition(State.MINING, o) is State.MINING

def test_manual_reentry_mining_loses_to_chill_and_reset():
    o = _obs_manual(chill_audio=True, chill_text=True)
    assert decide_transition(State.MINING, o) is State.HARVESTING
    o = _obs_manual(mine_resetting=True)
    assert decide_transition(State.MINING, o) is State.RESET_WAIT

def test_manual_reentry_does_not_touch_harvesting():
    assert decide_transition(State.HARVESTING, _obs_manual()) is State.HARVESTING

def test_can_accept_manual_reentry_matrix():
    ok, _ = can_accept_manual_reentry(State.MINING, True)
    assert ok
    ok, _ = can_accept_manual_reentry(State.RESET_WAIT, True)
    assert ok
    ok, reason = can_accept_manual_reentry(State.HARVESTING, True)
    assert not ok and "採集" in reason
    ok, reason = can_accept_manual_reentry(State.REENTRY, True)
    assert not ok and "回礦" in reason
    ok, reason = can_accept_manual_reentry(State.MINING, False)
    assert not ok and "未啟用" in reason
```

`tests/test_notify.py` 調整：既有 `test_stuck_includes_reason`（第 68 行）改為：

```python
def test_stuck_no_longer_templated():
    # H044 起 STUCK 走 Bot._notify_stuck 專屬路徑（送出後掛 🏠），事件模板移除避免雙發
    assert format_message(rec("STUCK", reason="60s 無進度")) is None


def test_send_message_with_id_requires_credentials():
    ok, detail, mid = notify.send_message_with_id("", "", "hi")
    assert ok is False and mid is None
```

（`notify` 若該檔尚未整模組 import，比照檔內既有寫法引入。）

- [ ] **Step 2: 跑測試確認紅**

Run: `python -m pytest tests/test_states.py tests/test_notify.py -q`
Expected: FAIL（`manual_reentry` 非法欄位、`can_accept_manual_reentry` 不存在、STUCK 仍有模板）

- [ ] **Step 3: states.py 實作**

`Observation` 加欄位（`auto_reenter` 之後）：

```python
    manual_reentry: bool = False   # Discord `回礦` 指令/STUCK 🏠 反應：手動觸發回礦（H044 spec 第 3 節）
```

`decide_transition` 改為：

```python
def decide_transition(state: State, o: Observation) -> State:
    if state is State.MINING:
        if o.chill_audio and o.chill_text:   # 稀有優先（雙重確認）
            return State.HARVESTING
        if o.mine_resetting:                 # 偵測到重置 → 暫停等定位（回礦由重置流程接手）
            return State.RESET_WAIT
        if o.manual_reentry and o.auto_reenter:   # 手動回礦（蒐集素材/卡死自救，用途不限）
            return State.REENTRY
        return State.MINING
    if state is State.HARVESTING:
        if o.harvest_failed:
            return State.NEEDS_HUMAN
        if o.harvest_done:
            return State.MINING
        return State.HARVESTING
    if state is State.NEEDS_HUMAN:
        if o.manual_reentry and o.auto_reenter:   # 手動優先於 human_cleared（更明確的意圖）
            return State.REENTRY
        return State.MINING if o.human_cleared else State.NEEDS_HUMAN
    if state is State.RESET_WAIT:
        if o.chill_audio and o.chill_text:   # 例外：重置期間意外出現稀有 → 強制採集
            return State.HARVESTING
        if o.manual_reentry and o.auto_reenter:   # 人工強制：繞過 reset_complete（凍結逃生口）
            return State.REENTRY
        if o.human_cleared:                  # 使用者重新定位後按 Q＝明確接手，優先於自動路徑
            return State.MINING
        if o.auto_reenter and o.reset_complete:
            return State.REENTRY
        return State.RESET_WAIT
    if state is State.REENTRY:
        if o.reentry_failed:                 # failed 先判：同 tick 兩旗標並存時保守交人工
            return State.NEEDS_HUMAN
        if o.reentry_done:
            return State.MINING
        return State.REENTRY
    return state
```

新純函式（`can_consume_ability` 附近）：

```python
def can_accept_manual_reentry(state: State, reentry_active: bool) -> tuple[bool, str]:
    """Discord `回礦` 指令／STUCK 🏠 的接收守門（純函式）。回 (可接受, 拒絕原因)。

    HARVESTING 拒收：採集有自己的超時/giveup 路徑，插入回礦會亂時序；也不排隊
    （比照 aim-reply「不排隊，避免舊指令補刀」）。REENTRY 拒收：已在流程中。
    """
    if not reentry_active:
        return False, "回礦模式未啟用（reentry_mode=off 或按鈕座標未校準）"
    if state is State.HARVESTING:
        return False, "採集進行中，稍後再送"
    if state is State.REENTRY:
        return False, "已在回礦流程中（用 重骰/跳過/📷 控制）"
    return True, ""
```

- [ ] **Step 4: notify.py 實作**

`send_message` 改寫＋新函式（原 92-113 行整段替換）：

```python
def send_message(token: str, channel_id: str, content: str, timeout: float = 10.0):
    """直接送一則純文字訊息到 Discord 頻道。回 (ok: bool, detail: str)。"""
    ok, detail, _ = send_message_with_id(token, channel_id, content, timeout)
    return ok, detail


def send_message_with_id(token: str, channel_id: str, content: str, timeout: float = 10.0):
    """送純文字訊息並回 (ok, detail, message_id)——需要對該訊息貼反應/編輯時用。

    message_id 取自 Discord 回應 JSON 的 "id"（比照 send_embed）；失敗時 None。
    STUCK 🏠 手動回礦鈕（H044）靠它拿 mid 貼反應。
    """
    if not token or not channel_id:
        return False, "缺少 token 或 channel_id", None
    url = API.format(channel_id=channel_id)
    data = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "miningbot (local automation, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                mid = json.loads(body).get("id")
            except (ValueError, AttributeError):
                mid = None
            return True, f"HTTP {resp.status}", mid
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {e.code}: {body}", None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None
```

`_TEMPLATES` 移除 `"STUCK"` 行，於 dict 上方註解補：`# STUCK 不在此：H044 起走 Bot._notify_stuck 專屬路徑（送出後掛 🏠 手動回礦反應鈕）`。

- [ ] **Step 5: 跑測試確認綠**

Run: `python -m pytest tests/test_states.py tests/test_notify.py -q`
Expected: PASS 全綠

---

### Task 4: Bot 接線（opencode）

**Files:**
- Modify: `miningbot/main.py`

**Interfaces:**
- Consumes: Task 2 `plan_open_retry`／config 四欄位／`ctx.trigger`；Task 3 `manual_reentry`／`can_accept_manual_reentry`／`send_message_with_id`
- Produces: 無（終端接線）；行為驗收見 Task 6

- [ ] **Step 1: import 與 `__init__` 狀態**

main.py 第 14 行的 states import 加 `can_accept_manual_reentry`。`__init__`（`_stuck_notified` 附近）新增：

```python
        self._manual_reentry = False           # Discord 回礦 指令/STUCK 🏠（輪詢執行緒寫、主迴圈消費）
        self._rr_trigger = "reset"             # 本輪 REENTRY 觸發來源（reset/manual；建 ctx 時寫入）
        self._stuck_alert_mid = None           # STUCK 警告訊息 id（🏠 反應輪詢；進度恢復即作廢）
        self._stuck_seen = set()               # 🏠 已見使用者基線（含 bot 自己貼的）
        self._rr_open_first_ts = 0.0           # H044 開場探測：episode 首擊時刻（0=非探測中）
        self._rr_open_last_ts = 0.0            # H044 開場探測：上一次探測時刻
```

- [ ] **Step 2: `_click_surface_verified` 區域化＋雙訊號**

`ref = capture.grab()` 改 `ref = capture.crop(capture.grab(), cfg.reentry_game_region)`；輪詢內：

```python
                cur = capture.crop(capture.grab(), cfg.reentry_game_region)
                d = vision.frame_mean_diff(ref, cur)
                fr = vision.frames_changed_frac(ref, cur) or 0.0
                if d > max_diff:
                    max_diff = d
                if d >= cfg.reentry_teleport_diff or fr >= cfg.reentry_teleport_frac:
```

docstring 補一句：「H044 起量 `reentry_game_region`（全幀會被覆蓋視窗重繪灌爆＝凍結中假傳送）；frac 雙訊號補『夜空大片黑稀釋 mean』的地表↔地表傳送。」log 行順帶輸出 `fr`。

- [ ] **Step 3: `_rr_open_episode` 探測化**

`teleported = self._click_surface_verified("開場")` 前後改為：

```python
        now = time.time()
        if self._rr_open_first_ts == 0.0:
            self._rr_open_first_ts = now         # 探測預算起算（episode 首擊）
        teleported = self._click_surface_verified("開場")
        self._rr_ensure_ctx(reroll)
        self._rr_open_last_ts = time.time()
        if not teleported:
            # H044 探測式開場：未傳送（凍結/虛空/按鈕失效）→ 不通知、不拍圖，排下一次探測；
            # 預算用盡才通知一次（_tick_reentry_remote 依 plan_open_retry 決策）。
            self.logger.info("[RR#%s] 開場點擊無反應（可能凍結/虛空）——%.0fs 後再探（預算剩 %.0fs）",
                             self._rr_ctx.episode_id, cfg.reentry_open_retry_wait_s,
                             max(0.0, cfg.reentry_open_budget_s
                                 - (time.time() - self._rr_open_first_ts)))
            self.last_action = "回礦開場探測中（畫面可能凍結）"
            return
        self._rr_open_first_ts = 0.0             # 傳送成功：清探測狀態
```

（原「⚠ 按回到地表畫面無變化」通知與截圖從此處**刪除**——搬到 Step 4 的 give_up 分支。）

- [ ] **Step 4: `_tick_reentry_remote` 探測消費**

`if self._rr_ctx is None:` 區塊之後、`if self._pending_reentry is not None:` 之前插入：

```python
        # H044 開場探測：上一擊未傳送（first_ts 非 0）→ 依節奏重探/放棄。使用者指令優先
        #（重骰/跳過照常走 pending 消費；重骰失敗會回到這裡繼續計預算）。
        if self._rr_open_first_ts and self._pending_reentry is None:
            act = reentry_remote.plan_open_retry(
                self._rr_open_first_ts, time.time(),
                cfg.reentry_open_retry_wait_s, cfg.reentry_open_budget_s,
                self._rr_open_last_ts)
            if act == "probe":
                self._rr_busy = True
                try:
                    self._rr_open_episode(reroll=True)
                finally:
                    self._rr_busy = False
                return
            if act == "give_up":
                self._rr_open_first_ts = 0.0
                snap = capture.grab()
                path = self._rr_sync_write(
                    snap, f"reentry_ep{self._rr_ctx.episode_id}_open_nochange")
                self._rr_notify(
                    f"⚠ 回礦 #{self._rr_ctx.episode_id}：「回到地表」點了 "
                    f"{int(cfg.reentry_open_budget_s)}s 畫面都無變化"
                    "（全黑＝虛空；有畫面＝凍結或按鈕失效）。回 `重骰` 重試或 `跳過`",
                    image_paths=[path])
                return
            # act == "wait" → 落到下方等待分支更新 HUD
```

等待分支（`else:` 內）的 last_action 改為：

```python
            if self._rr_open_first_ts:
                self.last_action = f"回礦開場探測中 #{ctx.episode_id}（畫面可能凍結，已 {mins} 分）"
            else:
                self.last_action = f"回礦等待指令 #{ctx.episode_id}（已等 {mins} 分）"
```

`_rr_finalize` 開頭加 `self._rr_open_first_ts = 0.0`（episode 收尾清探測狀態）。

- [ ] **Step 5: 手動旗標消費（observe＋run 迴圈）**

`observe()` 末段改為：

```python
        manual = self._manual_reentry
        if manual:
            self._manual_reentry = False        # 一次性消費：不留舊旗標補刀（比照 aim-reply 不排隊）
        return Observation(chill_audio=chill_audio, chill_text=chill_text,
                           harvest_done=False, harvest_failed=False,
                           human_cleared=self.human_cleared,
                           mine_resetting=mine_resetting,
                           reset_complete=self._update_reset_complete(),
                           reentry_done=self._reentry_done,
                           reentry_failed=self._reentry_failed,
                           auto_reenter=self._reentry_active(),
                           manual_reentry=manual)
```

run 迴圈 `decided = decide_transition(self.state, obs)` 之後插入：

```python
                if obs.manual_reentry:
                    if decided is State.REENTRY:
                        self._rr_trigger = "manual"
                        self._evac_done = False   # 手動觸發沒有撤離步驟，footer 不得沿用上輪殘值
                    else:   # 競態：指令到消費之間狀態變了（如 chill 搶轉）→ 明講不動作
                        self._rr_notify(f"ℹ️ 回礦指令已忽略（{self.state.value} 優先轉 {decided.value}）")
                elif decided is State.REENTRY and self.state is not State.REENTRY:
                    self._rr_trigger = "reset"
```

`_rr_ensure_ctx` 建新 ctx 處加 `trigger=self._rr_trigger`：

```python
        self._rr_ctx = reentry_remote.RemoteReentryContext(
            episode_id=reentry_remote.next_episode_id(last),
            created_at=time.time(), sticky_layer=self._rr_sticky_layer,
            trigger=self._rr_trigger)
```

- [ ] **Step 6: Discord `回礦`/`reenter` 指令**

`_DISCORD_COMMANDS` 加 `"回礦", "reenter"`。`_handle_discord_command` 在 `ability` 區塊後加：

```python
        elif cmd in ("回礦", "reenter"):
            # 手動觸發回礦（H044 spec 第 3 節；用途不限卡死——蒐集面板樣本等皆可）。
            # 輪詢執行緒只寫旗標；狀態守門走純函式 can_accept_manual_reentry。
            ok, reason = can_accept_manual_reentry(self.state, self._reentry_active())
            if not ok:
                notify.send_message(token, ch, f"❌ 回礦未接受：{reason}")
            else:
                self._manual_reentry = True
                unpause = ""
                if self.paused:
                    self.paused = False           # 比照 resume：手動回礦隱含「動起來」
                    self._antiafk_last = 0.0
                    unpause = "（已解除暫停）"
                notify.send_message(token, ch,
                    f"⛏ 手動回礦已排入{unpause}（狀態: {self.state.value}）→ 下個 tick 進 REENTRY")
            self.log_discord.info("CMD 回礦 -> accepted=%s state=%s", ok, self.state.value)
```

`help` 文案在 `ability` 行後加：

```python
                "`回礦` — 手動觸發回礦（卡死自救/蒐集面板樣本；同 `reenter`）\n"
```

注意：`_handle_discord_command` 取 cmd 的既有寫法（首詞 lower＋lstrip("!")）對中文詞無需改動。

- [ ] **Step 7: STUCK 警告 🏠 反應鈕**

`_tick_mining` 卡住分支 `self._alert("腳本可能卡住了")` 後加 `self._notify_stuck(f"{cfg.stuck_timeout_s:.0f}s 無進度")`；進度恢復處（`self._stuck_notified = False` 那行後）加 `self._stuck_alert_mid = None`。新方法：

```python
    def _notify_stuck(self, reason: str):
        """STUCK Discord 警告＋🏠 手動回礦反應鈕（H044 spec 第 3 節）。

        取代舊 STUCK 事件模板（notify._TEMPLATES 已移除，避免雙發）。回礦未啟用＝純文字。
        在主迴圈跑（與舊 sink 同步發送同成本）；失敗只記 log。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        active = self._reentry_active()
        text = f"⚠️ 腳本可能卡住：{reason}"
        if active:
            text += "\n點 🏠 或回 `回礦` ＝手動回礦自救（回地表→傳圖→你指揮）"
        ok, detail, mid = notify.send_message_with_id(token, ch, text)
        self.log_discord.info("STUCK alert -> %s (mid=%s)", detail, mid)
        if not (ok and mid and active):
            return
        notify.add_reaction(token, ch, mid, "🏠")
        users = notify.get_reactions(token, ch, mid, "🏠")
        self._stuck_alert_mid = mid
        self._stuck_seen = {u.get("id") for u in users if u.get("id")}   # 基線含 bot 自己
```

`_poll_discord` 的反應輪詢區（`_poll_rr_reactions` 之後）加：

```python
        if self._stuck_alert_mid and self.state is not State.MINING:
            self._stuck_alert_mid = None       # 離開 MINING＝卡住語境失效，🏠 作廢（訊息留著）
        elif self._stuck_alert_mid:
            self._poll_stuck_reaction()
```

新方法（照抄 `_poll_rr_reactions` 的同步守門語意）：

```python
    def _poll_stuck_reaction(self):
        """輪詢 STUCK 警告的 🏠：新點擊＝手動回礦（與 `回礦` 指令同一旗標）。

        Discord 輪詢執行緒：只寫旗標/回覆，絕不碰 input_control。
        fetch 失敗回空 list → 不同步 seen（照抄 _poll_remote_reactions 守門）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        mid = self._stuck_alert_mid
        if not mid:
            return
        users = notify.get_reactions(token, ch, mid, "🏠")
        if not users:
            return
        user_ids = {u.get("id") for u in users if u.get("id")}
        new_clickers = user_ids - self._stuck_seen
        self._stuck_seen = set(user_ids)
        if not new_clickers:
            return
        ok, reason = can_accept_manual_reentry(self.state, self._reentry_active())
        if not ok:
            notify.send_message(token, ch, f"❌ 回礦（🏠）未接受：{reason}")
            return
        self._manual_reentry = True
        if self.paused:
            self.paused = False
            self._antiafk_last = 0.0
        self._stuck_alert_mid = None       # 一次性：觸發後按鈕作廢（訊息留著）
        notify.send_message(token, ch, "⛏ 手動回礦已排入（🏠）→ 下個 tick 進 REENTRY")
        self.log_discord.info("STUCK 🏠 by %s -> manual_reentry", ",".join(sorted(new_clickers)))
```

- [ ] **Step 8: 全測試**

Run: `python -m pytest -q`
Expected: PASS 全綠（main.py 接線由既有純函式測試＋Task 6 實機驗證覆蓋）

---

### Task 5: 文件與 memory（Claude）

**Files:**
- Modify: `CLAUDE.md`（REENTRY 段落＋Discord 指令）
- Modify: `docs/incidents.md`（新增 H044）
- Modify: `C:\Users\puppy\.claude\projects\...\memory\project_reentry_void_fall.md`（補凍結事實）

- [ ] **Step 1: docs/incidents.md 新增 H044 條目**：症狀（18:25 時間線）、量測表（凍結 0.00／活著靜止 ≤0.0004／真傳送 0.9966；全幀被覆蓋視窗灌爆 11-13）、一句話根因、對策（探測式開場＋區域化雙訊號＋被動活性閘否決記錄）、fixture 路徑、commit。
- [ ] **Step 2: CLAUDE.md**：H043 段落後補 H044 一句話對策；指令清單/回礦流程補「`回礦` 手動觸發（不限卡死）＋STUCK 🏠」。
- [ ] **Step 3: memory 更新**：`project_reentry_void_fall.md` 補「礦坑重生＝客戶端分鐘級全凍結；被動活性偵測不可行（活著靜止畫面像素上與凍結不可分）；修法＝探測式開場」＋ MEMORY.md 索引行同步。
- [ ] **Step 4: Commit（文件與 memory 單獨一筆）**

---

### Task 6: 驗證與收尾（Claude）

- [ ] **Step 1: 審 opencode diff**（`git diff` 逐檔；重點：執行緒鐵律、探測迴圈的 return 路徑、`_rr_finalize` 清探測狀態）
- [ ] **Step 2: 紅燈驗證**：暫時 revert `decide_transition` 的 manual 分支 → `tests/test_states.py` 必紅；暫時把 `_click_surface_verified` 改回全幀 → fixture 測試不動（純函式測試不覆蓋 I/O）——改用人工檢查 diff 確認裁圖呼叫存在。復原。
- [ ] **Step 3: 全測試綠** `python -m pytest -q`
- [ ] **Step 4: Commit 實作**（feature branch、訊息含 H044、`Co-Authored-By: Claude ...`）
- [ ] **Step 5: 寫下實機驗證預期（結案條件）**：
  - 下一次礦坑重置：`miningbot.log` 應出現「開場點擊無反應（可能凍結/虛空）——20s 後再探」數則 → 解凍後「[RR] 開場 click attempt … -> teleported」→ 正常發 8 方位圖；**不得**出現凍結期間的 `pitch_eaten`/「旋轉鍵 . 疑似被吃」連發。
  - Discord 發 `回礦`：回覆「已排入」→ `STATE_CHANGE MINING→REENTRY`（events.log）→ embed footer 帶「手動觸發｜」→ ledger 尾行 `"trigger": "manual"`。
  - 卡住 60s：Discord 出現含 🏠 的警告；點 🏠 → 「已排入（🏠）」→ 進 REENTRY。
