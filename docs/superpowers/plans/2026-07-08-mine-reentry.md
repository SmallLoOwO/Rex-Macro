# 礦坑重置自動重新進礦（Auto Re-entry）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 礦坑重置後自動「回到地表 → 找傳送面板 → click-to-move 走近 → OCR 點目標層按鈕 → 回礦開挖」，失敗 reroll、用盡交 NEEDS_HUMAN。

**Architecture:** 依 `docs/superpowers/specs/2026-07-08-mine-reentry-design.md`（**實作前先整份讀完**）。新增 `State.REENTRY`；決策全在純函式模組 `miningbot/reentry.py`（比照 `harvester.py`），I/O 由 `Bot._tick_reentry` 執行。偵測只有兩種：面板邊緣模板比對（沿用 `vision._best_edge_match` pipeline）與 RapidOCR 文字框（新介面 `ocr.read_text_boxes`）。另有 R 鍵手動取樣視窗與 `calibrate_surface` 校準 CLI。

**Tech Stack:** Python、OpenCV、RapidOCR（已在用）、pydirectinput、Tkinter（比照 `status_hud`）、pytest。

## Global Constraints

- 純邏輯一律 TDD：先寫失敗測試 → 跑紅 → 實作 → 跑綠 → commit。測試指令 `python -m pytest -q`，改完必須全綠。
- 所有座標/門檻/秒數放 `miningbot/config.py` 的 `Config`，不寫死在邏輯裡。
- 「寧漏勿誤」：低信心寧可 reroll 也不亂點（傳錯層貴、reroll 便宜）。
- commit 訊息結尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`；在 feature 分支工作（現有 `feature/optimization-roadmap` 或新開）。
- `auto_reenter` 預設 **False**：程式碼全部落地後行為與今日完全相同，實機校準完才開。
- 註解風格比照現有程式碼：中文、講「為什麼/踩過什麼坑」，不覆述程式行為。

---

### Task 1: `states.py` 新增 REENTRY 狀態與轉換

**Files:**
- Modify: `miningbot/states.py`
- Test: `tests/test_states.py`（既有檔，附加測試）

**Interfaces:**
- Produces: `State.REENTRY`；`Observation` 新欄位 `reset_complete: bool = False`、`reentry_done: bool = False`、`reentry_failed: bool = False`、`auto_reenter: bool = False`。後續 Task 8 的 `decide_transition` 呼叫點依賴這些欄位名。

- [ ] **Step 1: 寫失敗測試**（附加到 `tests/test_states.py`）

```python
from miningbot.states import State, Observation, decide_transition

def _obs(**kw):
    base = dict(chill_audio=False, chill_text=False, harvest_done=False,
                harvest_failed=False, human_cleared=False)
    base.update(kw)
    return Observation(**base)

class TestReentryTransitions:
    def test_reset_wait_auto_reenter_off_stays(self):
        o = _obs(reset_complete=True, auto_reenter=False)
        assert decide_transition(State.RESET_WAIT, o) is State.RESET_WAIT

    def test_reset_wait_enters_reentry_when_reset_complete(self):
        o = _obs(reset_complete=True, auto_reenter=True)
        assert decide_transition(State.RESET_WAIT, o) is State.REENTRY

    def test_reset_wait_human_q_wins_over_auto(self):
        # 使用者按 Q＝明確接手，優先於自動路徑
        o = _obs(reset_complete=True, auto_reenter=True, human_cleared=True)
        assert decide_transition(State.RESET_WAIT, o) is State.MINING

    def test_reset_wait_not_complete_waits(self):
        o = _obs(auto_reenter=True)
        assert decide_transition(State.RESET_WAIT, o) is State.RESET_WAIT

    def test_reentry_done_to_mining(self):
        assert decide_transition(State.REENTRY, _obs(reentry_done=True)) is State.MINING

    def test_reentry_failed_to_needs_human(self):
        assert decide_transition(State.REENTRY, _obs(reentry_failed=True)) is State.NEEDS_HUMAN

    def test_reentry_failed_wins_over_done(self):
        o = _obs(reentry_done=True, reentry_failed=True)
        assert decide_transition(State.REENTRY, o) is State.NEEDS_HUMAN

    def test_reentry_otherwise_stays(self):
        assert decide_transition(State.REENTRY, _obs()) is State.REENTRY
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_states.py -q`
Expected: FAIL（`REENTRY` 不存在 / Observation 無此欄位）

- [ ] **Step 3: 最小實作**

`State` 加一行：

```python
    REENTRY = "REENTRY"            # 重置後自動回礦：回地表→找面板→點層級按鈕（失敗 reroll）
```

`Observation` 加欄位：

```python
    reset_complete: bool = False   # RESET_WAIT 中 banner reset 字樣已消失＋沉澱夠久
    reentry_done: bool = False     # _tick_reentry 回報成功（已回礦內）
    reentry_failed: bool = False   # reroll 用盡（→ NEEDS_HUMAN）
    auto_reenter: bool = False     # config 開關（關＝RESET_WAIT 維持今日等人工行為）
```

`decide_transition` 的 `RESET_WAIT` 分支改為（human_cleared 先判＝人工接手優先）、並加 `REENTRY` 分支：

```python
    if state is State.RESET_WAIT:
        if o.chill_audio and o.chill_text:   # 例外：重置期間意外出現稀有 → 強制採集
            return State.HARVESTING
        if o.human_cleared:                  # 使用者重新定位後按 Q
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_states.py -q`
Expected: PASS（既有測試也不能壞）

- [ ] **Step 5: Commit**

```bash
git add miningbot/states.py tests/test_states.py
git commit -m "feat(reentry): REENTRY 狀態與 RESET_WAIT 自動轉換（auto_reenter 守門）"
```

---

### Task 2: `reentry.py` 純決策模組

**Files:**
- Create: `miningbot/reentry.py`
- Test: `tests/test_reentry.py`

**Interfaces:**
- Produces（Task 8 依賴，簽名固定）:
  - 階段常數：`SURFACE_WAIT / PITCH_RESET / SWEEP / NAVIGATE / READ_PANEL / CLICK_VERIFY`（str）
  - `ReentryState`（dataclass：`attempts: int = 0`、`phase: str = SURFACE_WAIT`、`occlusion_tried: tuple = ()`、`phase_started: float = 0.0`、`attempt_started: float = 0.0`）
  - `pick_panel_direction(scores, threshold) -> tuple | None`
  - `movement_status(diffs, moving_thresh, stable_ticks) -> str`
  - `next_occlusion_action(tried) -> str`
  - `should_giveup(attempts, max_attempts) -> bool`
  - `pick_layer_button(records, target_name, decoy_names, min_ratio) -> tuple | None`

- [ ] **Step 1: 寫失敗測試**（`tests/test_reentry.py`）

```python
from miningbot import reentry

class TestPickPanelDirection:
    def test_best_above_threshold(self):
        scores = [(0, 0.30, (100, 200)), (3, 0.62, (500, 300)), (5, 0.50, (700, 100))]
        assert reentry.pick_panel_direction(scores, 0.45) == (3, 0.62, (500, 300))

    def test_all_below_threshold_none(self):
        # 寧漏勿誤：低信心回 None（呼叫端 reroll），不取「矮子裡的高個」
        assert reentry.pick_panel_direction([(0, 0.44, (1, 1))], 0.45) is None

    def test_empty_none(self):
        assert reentry.pick_panel_direction([], 0.45) is None

class TestMovementStatus:
    def test_still_moving(self):
        assert reentry.movement_status([9.0, 8.0, 7.0], 2.0, 3) == "moving"

    def test_stopped_after_stable_ticks(self):
        assert reentry.movement_status([9.0, 1.0, 0.5, 0.8], 2.0, 3) == "stopped"

    def test_not_enough_history_is_moving(self):
        # 剛點完 click-to-move，樣本不足時不可誤判停下
        assert reentry.movement_status([0.5], 2.0, 3) == "moving"

class TestOcclusionLadder:
    def test_ladder_order(self):
        assert reentry.next_occlusion_action(()) == "orbit"
        assert reentry.next_occlusion_action(("orbit",)) == "renavigate"
        assert reentry.next_occlusion_action(("orbit", "renavigate")) == "reroll"

class TestGiveup:
    def test_below_max_continues(self):
        assert reentry.should_giveup(4, 5) is False

    def test_at_max_gives_up(self):
        assert reentry.should_giveup(5, 5) is True

class TestPickLayerButton:
    DECOYS = ("Back to pre-reset location", "Basalt Layer",
              "Diorite Layer", "Obsidian Layer", "Core Layer")

    def _rec(self, text, center=(0, 0)):
        return {"text": text, "score": 0.9, "center": center}

    def test_exact_hit(self):
        recs = [self._rec("Diorite Layer", (10, 10)),
                self._rec("Mantle Layer", (300, 240)),
                self._rec("Back to pre-reset location", (300, 120))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.75) == (300, 240)

    def test_ocr_noise_still_hits(self):
        # 遊戲字型 i/l 同形（H033）：Mantie 仍應命中，因對 target 分數嚴格高於任一 decoy
        recs = [self._rec("Mantie Layer", (300, 240))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.75) == (300, 240)

    def test_decoy_never_picked(self):
        recs = [self._rec("Core Layer", (300, 300))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.75) is None

    def test_ambiguous_returns_none(self):
        # 對 target 與 decoy 分數打平＝分不清 → 不點（寧漏勿誤）
        recs = [self._rec("Layer", (300, 300))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.10) is None

    def test_below_min_ratio_none(self):
        recs = [self._rec("xxxxx", (300, 300))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.75) is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_reentry.py -q`
Expected: FAIL（模組不存在）

- [ ] **Step 3: 實作 `miningbot/reentry.py`**

```python
"""重置後自動回礦（REENTRY）的純決策邏輯。

設計：docs/superpowers/specs/2026-07-08-mine-reentry-design.md。
比照 harvester：這裡只有可單測的純函式與狀態資料，所有 I/O 在 main._tick_reentry。
核心原則「寧漏勿誤」：低信心寧可 reroll（按回到地表換重生點，幾十秒）也不亂點
（點錯層級按鈕＝傳錯層，浪費一整輪還可能沒發現）。
"""
from dataclasses import dataclass
from difflib import SequenceMatcher

# 單輪 attempt 內的階段（str 比照 harvester 的輕量風格）
SURFACE_WAIT = "surface_wait"    # 已按回到地表，等傳送完成（幀差大變化）
PITCH_RESET = "pitch_reset"      # 俯仰歸位（拖到底夾限→回拉校準量）
SWEEP = "sweep"                  # 八方位掃面板
NAVIGATE = "navigate"            # 右鍵 click-to-move 走向面板
READ_PANEL = "read_panel"        # OCR 找目標層文字框（含遮擋階梯）
CLICK_VERIFY = "click_verify"    # 已點層級按鈕，等傳送＋礦內驗證


@dataclass
class ReentryState:
    attempts: int = 0            # 已失敗的 reroll 輪數
    phase: str = SURFACE_WAIT
    occlusion_tried: tuple = ()  # 本輪已試過的遮擋手段
    phase_started: float = 0.0   # time.time()，I/O 端維護
    attempt_started: float = 0.0


def pick_panel_direction(scores, threshold):
    """八方位掃描結果選方向。scores: [(dir_idx, score, center_xy)]。

    取最高分且 >= threshold；全部低於門檻回 None（呼叫端 reroll）——
    不取「矮子裡的高個」：門檻以下的匹配點下去多半不是面板。
    """
    best = None
    for item in scores:
        if item[1] >= threshold and (best is None or item[1] > best[1]):
            best = item
    return best


def movement_status(diffs, moving_thresh, stable_ticks):
    """click-to-move 途中判斷角色停了沒。diffs＝連續幀平均差序列。

    連續 stable_ticks 筆都低於 moving_thresh ＝ 停下（到位或卡住，交 OCR 分辨）；
    樣本不足一律 "moving"——剛點完就判停會提早進 OCR、把走到一半的模糊幀當遮擋。
    """
    if len(diffs) < stable_ticks:
        return "moving"
    recent = diffs[-stable_ticks:]
    return "stopped" if all(d <= moving_thresh for d in recent) else "moving"


_OCCLUSION_LADDER = ("orbit", "renavigate")


def next_occlusion_action(tried):
    """OCR 找不到目標層文字時的遮擋處理階梯（便宜→貴）：
    orbit（, 轉 45°，角色離開面板與鏡頭之間）→ renavigate（再右鍵重導航一次，
    實測有時能讓角色站到側邊）→ reroll。
    """
    for a in _OCCLUSION_LADDER:
        if a not in tried:
            return a
    return "reroll"


def should_giveup(attempts, max_attempts):
    return attempts >= max_attempts


def _norm(s):
    return " ".join(s.lower().split())


def pick_layer_button(records, target_name, decoy_names, min_ratio):
    """從 OCR 文字框挑目標層按鈕，回 center 座標或 None。

    records: ocr.read_text_boxes 輸出 [{'text','score','center',...}]。
    命中條件（寧漏勿誤，比照 rare vs common 雙向最近鄰）：
    對 target 的相似度 >= min_ratio 且 **嚴格大於** 對任一 decoy（其他按鈕含
    Back to pre-reset location）的相似度——打平＝分不清＝不點。
    """
    tgt = _norm(target_name)
    decoys = [_norm(d) for d in decoy_names]
    best = None
    for r in records:
        t = _norm(r["text"])
        tr = SequenceMatcher(None, t, tgt).ratio()
        if tr < min_ratio:
            continue
        dr = max((SequenceMatcher(None, t, d).ratio() for d in decoys), default=0.0)
        if tr > dr and (best is None or tr > best[0]):
            best = (tr, r["center"])
    return best[1] if best else None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_reentry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add miningbot/reentry.py tests/test_reentry.py
git commit -m "feat(reentry): 純決策模組——方位選擇/移動停判/遮擋階梯/層按鈕模糊匹配"
```

---

### Task 3: `ocr.read_text_boxes`（RapidOCR 文字框介面）

**Files:**
- Modify: `miningbot/ocr.py`（附加在 `pass_labels` 之後）
- Test: `tests/test_ocr.py`（附加）

**Interfaces:**
- Consumes: 既有 `_get_rapid_engine()`（rapid 輸出物件有 `.boxes`（4 點多邊形陣列）、`.txts`、`.scores`）。
- Produces: `parse_rapid_boxes(boxes, txts, scores) -> list[dict]`（純函式）與 `read_text_boxes(image_bgr, region_offset=(0,0)) -> list[dict]`；dict 鍵＝`text`/`score`/`center`。Task 8 依賴 `read_text_boxes`。

- [ ] **Step 1: 寫失敗測試**（附加到 `tests/test_ocr.py`）

```python
class TestParseRapidBoxes:
    def test_basic(self):
        boxes = [[(100, 200), (200, 200), (200, 240), (100, 240)]]
        recs = ocr.parse_rapid_boxes(boxes, ["Mantle Layer"], [0.95])
        assert recs == [{"text": "Mantle Layer", "score": 0.95,
                         "center": (150, 220)}]

    def test_none_inputs_empty(self):
        # rapid 對空圖可能回 None 欄位（與 _read_text_rapid 同款防禦）
        assert ocr.parse_rapid_boxes(None, None, None) == []

    def test_missing_scores_default_zero(self):
        boxes = [[(0, 0), (10, 0), (10, 10), (0, 10)]]
        recs = ocr.parse_rapid_boxes(boxes, ["x"], None)
        assert recs[0]["score"] == 0.0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_ocr.py -q -k ParseRapidBoxes`
Expected: FAIL（函式不存在）

- [ ] **Step 3: 實作**（`miningbot/ocr.py` 末尾附加）

```python
def parse_rapid_boxes(boxes, txts, scores) -> list:
    """RapidOCR 輸出三陣列 → [{'text','score','center'}]（純函式，可單測）。

    center＝四點多邊形頂點平均（int）。給 reentry.pick_layer_button 挑層級按鈕用：
    文字框中心＝可直接點擊的螢幕座標（再加 region 偏移）。
    """
    boxes = list(boxes) if boxes is not None else []
    txts = list(txts) if txts else []
    scores = list(scores) if scores else [0.0] * len(txts)
    recs = []
    for b, t, s in zip(boxes, txts, scores):
        xs = [int(p[0]) for p in b]
        ys = [int(p[1]) for p in b]
        recs.append({"text": t, "score": float(s),
                     "center": (sum(xs) // len(xs), sum(ys) // len(ys))})
    return recs


def read_text_boxes(image_bgr: np.ndarray, region_offset=(0, 0)) -> list:
    """OCR 並回每行文字的框中心（螢幕座標＝crop 座標＋region_offset）。

    只有 rapidocr 路徑有框資訊；不可用回 []——呼叫端（reentry）據此走
    遮擋階梯/reroll，不做 tesseract 後備（無框＝無從點擊，硬湊必亂點）。
    """
    eng = _get_rapid_engine()
    if eng is None:
        return []
    out = eng(image_bgr, use_cls=False)
    recs = parse_rapid_boxes(out.boxes, out.txts, out.scores)
    ox, oy = region_offset
    for r in recs:
        r["center"] = (r["center"][0] + ox, r["center"][1] + oy)
    return recs
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_ocr.py -q`
Expected: PASS（既有測試不壞）

- [ ] **Step 5: Commit**

```bash
git add miningbot/ocr.py tests/test_ocr.py
git commit -m "feat(ocr): read_text_boxes——RapidOCR 文字框中心座標（reentry 按鈕點擊用）"
```

---

### Task 4: `vision.best_template_match_scored`（帶分數的多模板比對）

**Files:**
- Modify: `miningbot/vision.py`（`find_best_marker` 之後附加）
- Test: `tests/test_vision.py`（既有檔附加；若無此檔則建立）

**Interfaces:**
- Consumes: 既有 `_canny`、`_best_edge_match(scene_e, sh, sw, template_bgr, scales) -> (best_val, best_center)`。
- Produces: `best_template_match_scored(scene_bgr, templates: list, scales) -> (score: float, center | None)`——與 `find_template_edges` 差在**回分數**（sweep 要跨方位比大小）且吃模板 list。

- [ ] **Step 1: 寫失敗測試**

```python
import numpy as np
from miningbot import vision

def _panel_scene(cx=200, cy=150):
    scene = np.zeros((300, 400, 3), dtype=np.uint8)
    cv2.rectangle(scene, (cx - 40, cy - 25), (cx + 40, cy + 25), (200, 80, 200), 3)
    return scene

def test_best_template_match_scored_finds_rect():
    import cv2
    scene = np.zeros((300, 400, 3), dtype=np.uint8)
    cv2.rectangle(scene, (160, 125), (240, 175), (200, 80, 200), 3)
    tmpl = scene[115:185, 150:250].copy()
    score, center = vision.best_template_match_scored(scene, [tmpl], scales=(1.0,))
    assert score > 0.8
    assert abs(center[0] - 200) < 10 and abs(center[1] - 150) < 10

def test_best_template_match_scored_empty_templates():
    scene = np.zeros((100, 100, 3), dtype=np.uint8)
    assert vision.best_template_match_scored(scene, [], scales=(1.0,)) == (-1.0, None)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_vision.py -q -k best_template_match_scored`
Expected: FAIL

- [ ] **Step 3: 實作**

```python
def best_template_match_scored(scene_bgr, templates: list, scales=(1.0,)):
    """多模板取最佳 (score, center)；找不到回 (-1.0, None)。

    與 find_template_edges 的差別：回分數不設門檻——reentry sweep 要跨 8 方位
    比大小、由呼叫端用 config 門檻決定「夠不夠信心」（寧漏勿誤在決策層做）。
    """
    scene_e = _canny(scene_bgr)
    sh, sw = scene_e.shape[:2]
    best_val, best_loc = -1.0, None
    for t in templates:
        v, loc = _best_edge_match(scene_e, sh, sw, t, scales)
        if loc is not None and v > best_val:
            best_val, best_loc = v, loc
    return best_val, best_loc
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_vision.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add miningbot/vision.py tests/test_vision.py
git commit -m "feat(vision): best_template_match_scored——sweep 跨方位比分數用"
```

---

### Task 5: config 參數＋`input_control` 俯仰/右鍵原語

**Files:**
- Modify: `miningbot/config.py`（`Config` 內、`# 熱鍵` 區塊前附加）
- Modify: `miningbot/input_control.py`（末尾附加）
- Test: 無（薄 I/O＋純資料；`python -m pytest -q` 確認 import 不壞即可）

**Interfaces:**
- Produces: 下列 config 欄位（Task 6/7/8 依賴，名稱固定）；`input_control.pitch_reset(down_px, back_px)`、`input_control.pitch_nudge(dy)`。

- [ ] **Step 1: config 附加**

```python
    # 重置自動回礦（auto re-entry；docs/superpowers/specs/2026-07-08-mine-reentry-design.md）
    auto_reenter: bool = False                  # 校準完成前預設關：關＝RESET_WAIT 等人工（今日行為）
    reentry_surface_button_xy: tuple = (0, 0)   # 右下「回到地表」UI 按鈕座標（實機校準後填）
    reentry_reset_settle_s: float = 5.0         # banner reset 字樣消失後沉澱多久才開始
    reentry_max_attempts: int = 5               # reroll 上限，用盡 → NEEDS_HUMAN
    reentry_attempt_timeout_s: float = 60.0     # 單輪（按回到地表→點擊驗證）時限
    reentry_teleport_wait_s: float = 6.0        # 按回到地表/層按鈕後等場景切換上限
    reentry_teleport_diff: float = 25.0         # 幀平均差超過此值＝傳送發生（校準時調）
    reentry_pitch_clamp_px: int = 1500          # 俯仰歸位：向下拖到夾限的量（過量無妨，飽和即可）
    reentry_pitch_back_px: int = 400            # 回拉量（R 視窗校準出、寫回這裡）
    reentry_panel_dir: str = "assets/surface"   # 面板偵測模板資料夾（實機裁圖）
    reentry_panel_threshold: float = 0.45       # 面板邊緣比對門檻（高信心才進下一步）
    reentry_panel_scales: tuple = (0.5, 0.7, 1.0, 1.4, 2.0)  # 距離變化大→尺度比 marker 寬
    reentry_target_layer: str = "Mantle Layer"  # 目標層按鈕文字（校準時依實際要挖的層改）
    reentry_decoy_buttons: tuple = ("Back to pre-reset location", "Basalt Layer",
                                    "Diorite Layer", "Obsidian Layer", "Core Layer")
    reentry_button_min_ratio: float = 0.75      # 層按鈕模糊比對下限（且須嚴格贏過 decoy）
    reentry_nav_timeout_s: float = 15.0         # click-to-move 單段到位上限
    reentry_move_stable_ticks: int = 3          # 連續 N tick 幀差近零＝角色停下
    reentry_move_diff: float = 2.0              # 「近零」門檻（與 stuck/chat 同尺度）
    reentry_mine_max_brightness: float = 60.0   # 礦內判定：stuck_region 平均亮度上限（校準時定）
    # R 鍵手動取樣（校準素材收集；也可用於裁追蹤框模板/補 OCR fixture）
    hotkey_sample: str = "r"
    manual_snapshot_dir: str = "logs/snapshots/manual"
    sample_pitch_step_px: int = 40              # R 視窗上/下微調一次的拖曳量
```

- [ ] **Step 2: `input_control` 附加**

```python
def _drag_vertical(total_px: int, chunk: int = 180):
    """右鍵按住的垂直拖曳，拆 chunk 段送（單次過大會被遊戲的滑鼠加速/取樣吃掉）。"""
    sign = 1 if total_px >= 0 else -1
    remaining = abs(total_px)
    pydirectinput.mouseDown(button="right")
    time.sleep(0.04)
    while remaining > 0:
        step = min(chunk, remaining)
        pydirectinput.moveRel(0, sign * step, relative=True)
        time.sleep(0.03)
        remaining -= step
    pydirectinput.mouseUp(button="right")
    time.sleep(_STEP)

def pitch_reset(down_px: int, back_px: int):
    """俯仰歸位：先向下拖到夾限（飽和，量多無妨）、再回拉固定量。

    俯仰角沒有絕對讀數（挖礦中途人工抬頭後回不去），但夾限是硬邊界——
    飽和之後「回拉多少」就是可重現的絕對角度。down/back 方向若與遊戲相反
    （拖下=抬頭），校準時把兩個參數對調正負驗證，勿改此函式。
    """
    _drag_vertical(down_px)
    settle()
    _drag_vertical(-back_px)
    settle()

def pitch_nudge(dy: int):
    """俯仰微調一步（R 取樣視窗的上/下鈕用）。dy>0 向下拖。"""
    _drag_vertical(dy)
```

- [ ] **Step 3: 全測試確認不壞**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add miningbot/config.py miningbot/input_control.py
git commit -m "feat(reentry): config 參數＋俯仰歸位原語（夾限飽和→回拉固定量）"
```

---

### Task 6: R 鍵手動取樣視窗

**Files:**
- Create: `miningbot/sampler.py`
- Modify: `miningbot/main.py`（`_HotkeyController` 加 R；`Bot.__init__` 掛 callback）
- Test: `tests/test_sampler.py`

**Interfaces:**
- Consumes: `config` 的 `manual_snapshot_dir`/`sample_pitch_step_px`/`reentry_pitch_*`；`capture.grab()`；`input_control.pitch_reset`/`pitch_nudge`。
- Produces: `sampler.next_manual_index(existing_names: list[str]) -> int`（純函式）；`sampler.save_sample(frame_bgr, out_dir, pitch_offset_px) -> str`（回檔名 stem 如 `"007"`）；`sampler.SamplerWindow(on_capture, on_pitch_reset, on_pitch_nudge)`（Tkinter，比照 `status_hud` 的執行緒模式——**先讀 `miningbot/status_hud.py` 照抄其視窗生命週期寫法**）。`_HotkeyController` 建構子新增 `on_sample=None` 參數。

- [ ] **Step 1: 寫失敗測試**（`tests/test_sampler.py`）

```python
from miningbot.sampler import next_manual_index
from miningbot.main import _HotkeyController

class TestNextManualIndex:
    def test_empty_starts_at_1(self):
        assert next_manual_index([]) == 1

    def test_continues_from_max(self):
        assert next_manual_index(["001.png", "002.png", "007.png"]) == 8

    def test_ignores_non_matching(self):
        # sidecar json 與雜檔不干擾編號
        assert next_manual_index(["001.png", "001.json", "readme.txt"]) == 2

class TestHotkeyR:
    def _mk(self, down):
        calls = []
        hk = _HotkeyController(down, on_stop=lambda: None, on_toggle=lambda: None,
                               on_quit=lambda: None, on_sample=lambda: calls.append(1))
        return hk, calls

    def test_r_edge_triggers_once(self):
        pressed = {0x52}
        hk, calls = self._mk(lambda vk: vk in pressed)
        hk.tick(); hk.tick()          # 按住兩 tick 只觸發一次（邊緣觸發）
        assert calls == [1]
        pressed.clear(); hk.tick()
        pressed.add(0x52); hk.tick()  # 放開再按 → 再觸發
        assert calls == [1, 1]

    def test_no_callback_no_crash(self):
        hk = _HotkeyController(lambda vk: vk == 0x52, lambda: None,
                               lambda: None, lambda: None)
        hk.tick()   # on_sample 未掛也不能炸（既有呼叫端不傳此參數）
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_sampler.py -q`
Expected: FAIL

- [ ] **Step 3: 實作**

`miningbot/main.py` 的 `_HotkeyController`：`__init__` 加參數 `on_sample=None`，存 `self._on_sample = on_sample`、`self._prev_r = False`；`tick()` 末尾（f12 判斷前）加：

```python
        r = self._down(0x52)                   # 'R'：手動取樣視窗
        if r and not self._prev_r and self._on_sample:
            self._on_sample()
        self._prev_r = r
```

`miningbot/sampler.py`：

```python
"""R 鍵手動取樣：編號截圖＋俯仰校準小視窗。

用途：使用者在遊戲裡看到「值得當樣本的畫面」（傳送面板視角、漏抓的追蹤框、
新背景的聊天框）按 R 留檔，之後直接以編號指名「用 007 當模板」。
sidecar json 記俯仰偏移量——這讓「合適的仰角」變成可重現的數字（寫回 config）。
視窗生命週期比照 status_hud（Tk 在自己的執行緒；按鈕 callback 轉交主程式執行，
不在 Tk 執行緒直接送 pydirectinput——送鍵前要 _focus_roblox，焦點在小視窗上）。
"""
import json
import os
import re
import time

_NUM_RE = re.compile(r"^(\d{3})\.png$")


def next_manual_index(existing_names) -> int:
    nums = [int(m.group(1)) for n in existing_names for m in [_NUM_RE.match(n)] if m]
    return max(nums, default=0) + 1


def save_sample(frame_bgr, out_dir: str, pitch_offset_px: int) -> str:
    """存編號截圖＋sidecar。回傳編號字串（如 "007"）。"""
    import cv2
    os.makedirs(out_dir, exist_ok=True)
    stem = f"{next_manual_index(os.listdir(out_dir)):03d}"
    cv2.imwrite(os.path.join(out_dir, f"{stem}.png"), frame_bgr)
    with open(os.path.join(out_dir, f"{stem}.json"), "w", encoding="utf-8") as f:
        json.dump({"pitch_offset_px": pitch_offset_px,
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)
    return stem
```

`SamplerWindow`（同檔）：**先讀 `miningbot/status_hud.py`**，照它的 Tk 執行緒/生命週期模式寫一個小視窗，含四顆按鈕與一個目前俯仰偏移量 label：
- 「俯仰歸位」→ callback `on_pitch_reset()`（主程式：`_focus_roblox()` → `ic.pitch_reset(cfg.reentry_pitch_clamp_px, cfg.reentry_pitch_back_px)` → 偏移計數歸 `cfg.reentry_pitch_back_px`）
- 「▲ 上」「▼ 下」→ `on_pitch_nudge(±cfg.sample_pitch_step_px)`（聚焦後 `ic.pitch_nudge`，並更新偏移計數）
- 「📸 截圖」→ `on_capture()`（主程式：`capture.grab()` → `save_sample(...)` → log `📸 手動截圖 #NNN pitch=NNN`）
- 再按 R 或關閉視窗 → 收掉。

`Bot.__init__` 建 `_HotkeyController` 處加 `on_sample=self._toggle_sampler`；`Bot._toggle_sampler` 開/關視窗並掛上述 callback（callback 內動作以 `self.paused or self.state in (State.NEEDS_HUMAN, State.RESET_WAIT)` 之外時先自動 `_pause()`——取樣時不能跟挖礦輸入互搶）。

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_sampler.py -q`（再跑 `python -m pytest -q` 全綠）
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add miningbot/sampler.py miningbot/main.py tests/test_sampler.py
git commit -m "feat(sampler): R 鍵取樣視窗——編號截圖＋俯仰偏移 sidecar＋熱鍵邊緣觸發"
```

---

### Task 7: `calibrate_surface` 校準 CLI

**Files:**
- Create: `miningbot/calibrate_surface.py`
- Test: `tests/test_calibrate_surface.py`（只測純 helper）

**Interfaces:**
- Consumes: `manual_snapshot_dir` 的編號截圖；`vision.load_template`。
- Produces: `assets/surface/panel_<NNN>.png` 模板；`clamp_roi(roi, w, h) -> (x, y, rw, rh)` 純函式。

- [ ] **Step 1: 寫失敗測試**

```python
from miningbot.calibrate_surface import clamp_roi

def test_clamp_roi_inside_unchanged():
    assert clamp_roi((10, 20, 50, 40), 200, 100) == (10, 20, 50, 40)

def test_clamp_roi_clipped_to_frame():
    assert clamp_roi((-5, 90, 300, 40), 200, 100) == (0, 90, 200, 10)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_calibrate_surface.py -q`
Expected: FAIL

- [ ] **Step 3: 實作**

```python
"""校準 CLI：把 R 鍵手動截圖變成 re-entry 需要的資產。

用法：
  python -m miningbot.calibrate_surface --import 007
      開 007.png，cv2.selectROI 框出面板 → 存 assets/surface/panel_007.png
  python -m miningbot.calibrate_surface --brightness 007
      印該圖 stuck_region 的平均亮度（收集「礦內 vs 地表」兩組樣本、
      人工取中間值填 config.reentry_mine_max_brightness）
"""
import argparse
import os

import cv2
import numpy as np

from .config import DEFAULT as cfg


def clamp_roi(roi, w, h):
    """selectROI 拖出框可能超出圖框，夾回合法範圍（純函式）。"""
    x, y, rw, rh = roi
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    rw = max(1, min(int(rw), w - x))
    rh = max(1, min(int(rh), h - y))
    return (x, y, rw, rh)


def _load(stem: str):
    path = os.path.join(cfg.manual_snapshot_dir, f"{stem}.png")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"找不到 {path}（先用 R 鍵截圖）")
    return img


def _import(stem: str):
    img = _load(stem)
    roi = cv2.selectROI("框出傳送面板（Enter 確認、c 取消）", img, showCrosshair=True)
    cv2.destroyAllWindows()
    if roi[2] == 0 or roi[3] == 0:
        raise SystemExit("已取消")
    x, y, w, h = clamp_roi(roi, img.shape[1], img.shape[0])
    os.makedirs(cfg.reentry_panel_dir, exist_ok=True)
    out = os.path.join(cfg.reentry_panel_dir, f"panel_{stem}.png")
    cv2.imwrite(out, img[y:y + h, x:x + w])
    print(f"模板已存 {out}（{w}x{h}）")


def _brightness(stem: str):
    img = _load(stem)
    r = cfg.stuck_region
    crop = img[r.y:r.y + r.h, r.x:r.x + r.w]
    print(f"{stem}: stuck_region 平均亮度 = {float(np.mean(crop)):.1f}"
          f"（礦內樣本應遠低於地表；中間值填 reentry_mine_max_brightness）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="imp", metavar="NNN")
    ap.add_argument("--brightness", metavar="NNN")
    a = ap.parse_args()
    if a.imp:
        _import(a.imp)
    elif a.brightness:
        _brightness(a.brightness)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_calibrate_surface.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add miningbot/calibrate_surface.py tests/test_calibrate_surface.py
git commit -m "feat(reentry): calibrate_surface CLI——手動截圖裁面板模板＋亮度簽名"
```

---

### Task 8: `main.Bot` 接線（`_tick_reentry`＋觸發＋通知）

**Files:**
- Modify: `miningbot/main.py`
- Modify: `miningbot/notify.py`（`_TEMPLATES` 加兩行）
- Modify: `miningbot/status_hud.py`（狀態名對照加一行）
- Modify: `miningbot/diagnostics.py`（`snapshot_subdir` 加 reentry 分流）
- Test: 純邏輯已在 Task 1/2 覆蓋；本 task 靠 `python -m pytest -q` 不壞＋Task 9 實機驗證

**Interfaces:**
- Consumes: Task 1–5 全部產出。
- Produces: `Bot._tick_reentry(frame)`、`Bot._reentry`（ReentryState）、`Bot._reentry_done/_reentry_failed` 旗標。

- [ ] **Step 1: 觸發鏈**（逐點改，每點都先讀該處現有程式再動手）

1. **banner worker 擴到 RESET_WAIT**：`_banner_ocr_loop` 現在只在 `state is MINING` 時跑（CLAUDE.md：RESET_WAIT 期間快取凍在 True）。條件改成 `state is MINING or (cfg.auto_reenter and state is State.RESET_WAIT)`——否則 `_mine_resetting` 永遠不會變 False、`reset_complete` 永遠不成立。
2. **reset_complete 追蹤**：`Bot.__init__` 加 `self._reset_clear_since = 0.0`。主迴圈 RESET_WAIT 分支：`_mine_resetting` 為 True → 歸 0；為 False 且 `_reset_clear_since == 0` → 設 now；`now - _reset_clear_since >= cfg.reentry_reset_settle_s` → `reset_complete=True`。
3. **Observation 傳入**：`decide_transition` 呼叫點的 `Observation(...)` 加 `mine_resetting=...` 同款的三個新參數：`reset_complete=...`、`reentry_done=self._reentry_done`、`reentry_failed=self._reentry_failed`、`auto_reenter=cfg.auto_reenter`。
4. **`_on_enter` 加 REENTRY**：`_focus_roblox()`（失敗回 `State.NEEDS_HUMAN` 降級，比照 MINING 入口）→ `self._reentry = reentry.ReentryState(phase_started=time.time(), attempt_started=time.time())`、旗標歸 False、放開 W/左鍵（`ic.key_up("w"); ic.mouse_up()`）、按「回到地表」`ic.click_at(*cfg.reentry_surface_button_xy)`、log `REENTRY_START`。
5. **MINING 入口清理**：`_on_enter(MINING)` 內「從 NEEDS_HUMAN/RESET_WAIT/HARVESTING 回 MINING」的重聚焦/清 `_mine_resetting` 條件把 `REENTRY` 加進清單。
6. **`_tick` 分派**：`self.state is State.REENTRY` → `self._tick_reentry(frame)`。

- [ ] **Step 2: `_tick_reentry` 實作**（放 `_tick_harvest` 之後；每 tick 進來一次、內部依 phase 做一小步，與主迴圈節奏相容）

```python
    def _tick_reentry(self, frame):
        """REENTRY 每 tick 一步。決策純函式在 reentry.py，這裡只做 I/O。

        任一步失敗統一走 _reentry_reroll（按回到地表換重生點）；
        attempts 用盡 → _reentry_failed=True（decide_transition → NEEDS_HUMAN）。
        """
        st = self._reentry
        now = time.time()
        if now - st.attempt_started > cfg.reentry_attempt_timeout_s:
            self._reentry_reroll("attempt timeout"); return

        if st.phase == reentry.SURFACE_WAIT:
            # 等傳送完成：與按下瞬間的參考幀比，大變化＝到地表了
            if self._reentry_ref is None:
                self._reentry_ref = frame.copy(); return
            if vision.frame_mean_diff(self._reentry_ref, frame) >= cfg.reentry_teleport_diff:
                self._set_phase(reentry.PITCH_RESET)
            elif now - st.phase_started > cfg.reentry_teleport_wait_s:
                self._reentry_reroll("teleport not detected")
            return

        if st.phase == reentry.PITCH_RESET:
            ic.pitch_reset(cfg.reentry_pitch_clamp_px, cfg.reentry_pitch_back_px)
            self._set_phase(reentry.SWEEP)
            return

        if st.phase == reentry.SWEEP:
            # 8 方位一次掃完（同 _sweep_for_tracker 的旋轉節奏，非逐 tick）
            scores = []
            for i in range(8):
                f = capture.grab()
                v, loc = vision.best_template_match_scored(
                    f, self._panel_templates, cfg.reentry_panel_scales)
                scores.append((i, v, loc))
                self.log_act.debug("reentry sweep dir=%d score=%.3f", i, v)
                if i < 7:
                    self._rotate_verified(+1)
            self._rotate_verified(+1)      # 第 8 轉回原位（8×45°=360°）
            best = reentry.pick_panel_direction(scores, cfg.reentry_panel_threshold)
            if best is None:
                self._reentry_reroll("panel not found in sweep"); return
            for _ in range(harvester.plan_return_rotations(0, best[0])):
                self._rotate_verified(+1)
            self._reentry_panel_xy = best[2]
            self._set_phase(reentry.NAVIGATE)
            self._nav_click()
            return

        if st.phase == reentry.NAVIGATE:
            self._move_diffs.append(
                vision.frame_mean_diff(self._last_nav_frame, frame)
                if self._last_nav_frame is not None else 99.0)
            self._last_nav_frame = frame.copy()
            status = reentry.movement_status(
                self._move_diffs, cfg.reentry_move_diff, cfg.reentry_move_stable_ticks)
            if status == "stopped":
                self._set_phase(reentry.READ_PANEL)
            elif now - st.phase_started > cfg.reentry_nav_timeout_s:
                self._set_phase(reentry.READ_PANEL)   # 超時也去讀——可能早就到了
            return

        if st.phase == reentry.READ_PANEL:
            recs = ocr.read_text_boxes(frame)
            target = reentry.pick_layer_button(
                recs, cfg.reentry_target_layer, cfg.reentry_decoy_buttons,
                cfg.reentry_button_min_ratio)
            if target is not None:
                self._snapshot(frame, "reentry_click")
                self._reentry_ref = frame.copy()
                ic.click_at(*target)
                self._set_phase(reentry.CLICK_VERIFY)
                return
            act = reentry.next_occlusion_action(st.occlusion_tried)
            st.occlusion_tried += (act,)
            self.log_act.info("reentry 遮擋階梯: %s（OCR %d 行無目標）", act, len(recs))
            if act == "orbit":
                self._rotate_verified(-1)
            elif act == "renavigate":
                self._nav_click()
                self._set_phase(reentry.NAVIGATE)
            else:
                self._reentry_reroll("panel text unreadable")
            return

        if st.phase == reentry.CLICK_VERIFY:
            if vision.frame_mean_diff(self._reentry_ref, frame) >= cfg.reentry_teleport_diff:
                r = cfg.stuck_region
                crop = frame[r.y:r.y + r.h, r.x:r.x + r.w]
                if float(np.mean(crop)) <= cfg.reentry_mine_max_brightness:
                    self._reentry_done = True
                    self._snapshot(frame, "reentry_success")
                    self.log.log("REENTRY_SUCCESS",
                                 {"attempts": st.attempts + 1})
                    return
            if now - st.phase_started > cfg.reentry_teleport_wait_s:
                self._reentry_reroll("click did not teleport into mine")
```

輔助（同 class）：

```python
    def _set_phase(self, phase):
        self._reentry.phase = phase
        self._reentry.phase_started = time.time()
        self._move_diffs = []
        self._last_nav_frame = None

    def _nav_click(self):
        ic.click_at(*self._reentry_panel_xy, button="right")   # click-to-move

    def _reentry_reroll(self, reason: str):
        st = self._reentry
        st.attempts += 1
        self.log_act.info("reentry reroll #%d：%s", st.attempts, reason)
        if reentry.should_giveup(st.attempts, cfg.reentry_max_attempts):
            self._reentry_failed = True
            self._snapshot(capture.grab(), "reentry_giveup")
            self.log.log("NEEDS_HUMAN", {"reason": f"自動回礦失敗×{st.attempts}（{reason}）"})
            return
        self._reentry = reentry.ReentryState(
            attempts=st.attempts, phase_started=time.time(), attempt_started=time.time())
        self._reentry_ref = None
        self._focus_roblox()
        ic.click_at(*cfg.reentry_surface_button_xy)             # 再按回到地表
```

`Bot.__init__` 補：`self._reentry = None`、`self._reentry_ref = None`、`self._reentry_done = False`、`self._reentry_failed = False`、`self._reentry_panel_xy = None`、`self._move_diffs = []`、`self._last_nav_frame = None`、`self._panel_templates = []`（`run()` 啟動時從 `cfg.reentry_panel_dir` 用 `vision.load_template` 載入全部 png；空清單＋`auto_reenter=True` → 啟動 WARNING 並視同 `auto_reenter=False`）。

- [ ] **Step 3: 通知/HUD/快照分流**

`notify.py` `_TEMPLATES` 加：

```python
    "REENTRY_START":   lambda m: "⛏️ 礦坑已重置，開始自動回礦…",
    "REENTRY_SUCCESS": lambda m: f"✅ 自動回礦成功（第 {m.get('attempts', '?')} 輪），恢復挖礦",
```

`status_hud.py` 狀態對照加 `"REENTRY": "重置·自動回礦"`。
`diagnostics.snapshot_subdir` 在既有分流前加：`if label.startswith("reentry"): return "reentry"`。

- [ ] **Step 4: 全測試**

Run: `python -m pytest -q`
Expected: PASS（全綠）

- [ ] **Step 5: Commit**

```bash
git add miningbot/main.py miningbot/notify.py miningbot/status_hud.py miningbot/diagnostics.py
git commit -m "feat(reentry): Bot._tick_reentry 接線——觸發鏈/六階段執行/通知與快照分流"
```

---

### Task 9: 文件更新

**Files:**
- Modify: `CLAUDE.md`（架構段狀態清單加 `REENTRY`；硬規則區加一小節「重置自動回礦」3–5 行：指向 spec、強調 `auto_reenter` 預設關、R 鍵取樣、寧漏勿誤點擊）
- Modify: `docs/HANDOFF.md`（若有接手微調段落，加 reentry 校準參數清單）

- [ ] **Step 1: 更新文件**（內容從 spec 摘要，不重複細節，指向 `docs/superpowers/specs/2026-07-08-mine-reentry-design.md`）
- [ ] **Step 2: 全測試 `python -m pytest -q` 綠 → Commit**

```bash
git add CLAUDE.md docs/HANDOFF.md
git commit -m "docs(reentry): CLAUDE.md/HANDOFF 補自動回礦摘要與校準指引"
```

---

### Task 10: 實機校準與驗證（人工＋agent 協作，程式碼完成後）

> 這一 task 不寫程式；是把 spec 的「校準時必須實機確認清單」跑完、把量到的值填回 config。**每一項都要留證據（log/截圖）再打勾。**

- [ ] 量「回到地表」按鈕座標 → `reentry_surface_button_xy`（截圖＋Read 量座標）
- [ ] R 鍵視窗：俯仰歸位穩定性（連按 3 次歸位、截圖比對視角一致）→ 校準 `reentry_pitch_back_px`（面板入畫的仰角）；確認拖曳方向正負
- [ ] `,`/`.` 在地表是否照常 45°（用 R 視窗截圖驗證）
- [ ] 右鍵「短點」click-to-move vs「按住拖」轉鏡頭：遊戲是否區分；**確認 Movement Mode 需求**；確認挖礦「按住 W＋左鍵」不受影響（衝突→改為只在 REENTRY 期間切換模式，回 MINING 前切回）
- [ ] 用 R 鍵收 5–10 張不同重生點截圖 → `calibrate_surface --import` 裁 2–3 張面板模板 → 跑 `_diag` 式離線比對確認 `reentry_panel_threshold` 有 gap
- [ ] `--brightness` 收礦內/地表各 3 張 → 定 `reentry_mine_max_brightness`
- [ ] 確認目標層按鈕全名拼字 → `reentry_target_layer`／`reentry_decoy_buttons`（照面板實際文字）；點按鈕有無確認彈窗、扣費與餘額不足行為
- [ ] 乾跑：`auto_reenter=True`、手動觸發一次重置流程全程盯梢（Q 隨時可接手）；成功 2–3 次後才留開
- [ ] 把使用者提供的 4 張對話截圖（近距正面/遠距/橋對面/貼臉遮擋）存進 `tests/fixtures/surface/`，補 `best_template_match_scored` 對真實幀的回歸測試

---

## 自我檢查紀錄

- Spec 覆蓋：狀態機（Task 1/8）、R 視窗（Task 6）、校準工具與確認清單（Task 7/10）、A/B/C 三階段與遮擋階梯（Task 2/8）、reroll 邊界（Task 2/8）、通知/HUD/快照（Task 8）、fixtures（Task 10）。spec 內「明確不做」清單無對應 task＝正確。
- 型別一致：`pick_panel_direction` 吃/回 `(dir, score, center)` tuple；`read_text_boxes` 回 dict list 與 `pick_layer_button` 的 `records` 一致；`ReentryState` 欄位與 `_tick_reentry` 使用處一致。
- 佔位符掃描：無 TBD/TODO；所有 code step 附完整程式碼。
