# 失敗路徑俯仰掃描（Pitch Sweep）實作計畫

> **For agentic workers:** 本 repo 慣例：程式實作委派 opencode（`opencode run`，GLM 無視覺、勿讀圖）；本計畫即 opencode 規格書的本體。Claude 負責 Task 5 校準與最終驗證。Steps 用 checkbox 追蹤。

**Goal:** 標準俯仰 8 方位全空（本來要 giveup）時，加掃上、下兩個俯仰層再交人工。

**Architecture:** 層規劃／失敗分流／快照命名＝`harvester.py` 純函式（TDD）；拖曳 I/O＝`Bot`，沿用既有 `_pitch_drag_verified` 幀差驗證。層間轉換一律「`pitch_reset` 絕對基準 → `pitch_nudge`」，拖曳被吃整組重來一次、再失敗跳層。收尾統一歸位「置中標準角」。

**Tech Stack:** Python、pytest、pydirectinput（經 `input_control`）。

**Spec:** `docs/superpowers/specs/2026-07-11-pitch-sweep-design.md`（改動前先讀）

## Global Constraints

- TDD：先寫失敗測試再實作；完成標準 `python -m pytest -q` 全綠。
- **opencode 不 commit**（留人工審）；不動 `assets/`、不讀任何圖片。
- 純邏輯進 `miningbot/harvester.py`＋`tests/test_harvester.py`；I/O 只進 `miningbot/main.py`；座標/門檻只進 `miningbot/config.py`。
- 既有測試一個都不能改壞（尤其 `decide_sweep_failure` 的 H019 兩分支）。
- config 新鍵預設值＝**停用**（`sweep_pitch_enabled=False`、兩個校準量 0）；校準完成（Task 5）前不得改成啟用。

---

### Task 1: config 鍵＋`plan_pitch_layers` 層規劃純函式

**Files:**
- Modify: `miningbot/config.py`（`reentry_pitch_back_px` 那段附近，約 :199-215）
- Modify: `miningbot/harvester.py`（`HarvestState` dataclass 下方）
- Test: `tests/test_harvester.py`

**Interfaces:**
- Produces: `PitchLayer(name: str, nudge_px: int)`（frozen dataclass）；`plan_pitch_layers(enabled: bool, step_px: int, center_back_px: int) -> list[PitchLayer]`；config 鍵 `sweep_pitch_enabled / sweep_pitch_step_px / sweep_pitch_clamp_px / sweep_pitch_center_back_px`

- [ ] **Step 1: 失敗測試**

```python
# tests/test_harvester.py 新增
class TestPlanPitchLayers:
    """失敗路徑俯仰掃描的層規劃（2026-07-11 spec）：未校準/停用回空；啟用回上→下兩層。"""

    def test_disabled_returns_empty(self):
        assert harvester.plan_pitch_layers(False, 300, 400) == []

    def test_uncalibrated_step_returns_empty(self):
        assert harvester.plan_pitch_layers(True, 0, 400) == []

    def test_uncalibrated_center_back_returns_empty(self):
        assert harvester.plan_pitch_layers(True, 300, 0) == []

    def test_enabled_yields_up_then_down(self):
        layers = harvester.plan_pitch_layers(True, 300, 400)
        assert [l.name for l in layers] == ["up", "down"]
        assert [l.nudge_px for l in layers] == [-300, 300]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_harvester.py -q -k PlanPitchLayers`
Expected: FAIL（`plan_pitch_layers` 不存在）

- [ ] **Step 3: 實作**

`miningbot/config.py`（照既有註解風格，放 `reentry_*` 區塊之後）：

```python
    # --- 失敗路徑俯仰掃描（2026-07-11 spec：標準層 8 方位全空才掃上/下層）---
    sweep_pitch_enabled: bool = False           # 校準完成前保持 False（比照 reentry 慣例）
    sweep_pitch_step_px: int = 0                # 一層 nudge 拖曳量（R 視窗校準；0=未校準＝停用；
                                                #   正=向下拖。遊戲拖曳方向若相反，校準時設負值即可）
    sweep_pitch_clamp_px: int = 1500            # pitch_reset 飽和拖曳量（沿用 reentry 初值；礦內校準可調）
    sweep_pitch_center_back_px: int = 0         # 夾限→「置中視角」回拉量（R 視窗校準；0=未校準＝停用）
```

`miningbot/harvester.py`：

```python
@dataclass(frozen=True)
class PitchLayer:
    """失敗路徑俯仰掃描的一層（純資料）。nudge_px＝pitch_reset 置中後的拖曳量（正=向下拖）。"""
    name: str       # "up" / "down"（快照 label、log 用）
    nudge_px: int


def plan_pitch_layers(enabled: bool, step_px: int, center_back_px: int) -> list:
    """回失敗路徑要補掃的俯仰層序列（不含已掃過的標準層；純函式）。

    未校準（step=0 或 center_back<=0）視同停用——與 reentry「無模板視同關閉」同慣例。
    順序固定上→下：實機經驗礦多在壁上高處，H026 證實下方也會漏，兩層都掃。
    """
    if not enabled or step_px == 0 or center_back_px <= 0:
        return []
    return [PitchLayer("up", -step_px), PitchLayer("down", step_px)]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_harvester.py -q`
Expected: 全 PASS

---

### Task 2: `decide_sweep_failure` 加 NEXT_LAYER 分支

**Files:**
- Modify: `miningbot/harvester.py:95-110`（`decide_sweep_failure`）
- Test: `tests/test_harvester.py`

**Interfaces:**
- Produces: `decide_sweep_failure(had_candidates, resweeps_done, max_resweeps=1, pitch_layers_left=0) -> "RESWEEP" | "NEXT_LAYER" | "HUMAN"`（既有呼叫端不帶新參數時行為完全不變）

- [ ] **Step 1: 失敗測試**

```python
class TestDecideSweepFailurePitchLayers:
    """全空且尚有俯仰層 → NEXT_LAYER；其餘維持 H019 既有分流。"""

    def test_all_empty_with_layers_left(self):
        assert harvester.decide_sweep_failure(False, 0, pitch_layers_left=2) == "NEXT_LAYER"

    def test_all_empty_layers_exhausted(self):
        assert harvester.decide_sweep_failure(False, 0, pitch_layers_left=0) == "HUMAN"

    def test_resweep_takes_priority_over_layers(self):
        # 看過穩定框＝框在「這一層」，先在本層重掃（H019），不跳層
        assert harvester.decide_sweep_failure(True, 0, pitch_layers_left=2) == "RESWEEP"

    def test_had_candidates_resweeps_exhausted_goes_human(self):
        # spec：俯仰層只掛「全空」分支——verify 反覆失敗是 FOV 位移問題，跳層無益
        assert harvester.decide_sweep_failure(True, 1, pitch_layers_left=2) == "HUMAN"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_harvester.py -q -k PitchLayers`
Expected: 新測試 FAIL（TypeError: unexpected keyword）

- [ ] **Step 3: 實作**

```python
def decide_sweep_failure(had_candidates: bool, resweeps_done: int,
                         max_resweeps: int = 1, pitch_layers_left: int = 0) -> str:
    """sweep 失敗分流（純函式）。回 "RESWEEP" / "NEXT_LAYER" / "HUMAN"。

    - 看到過穩定框、轉回後 verify 失敗 → RESWEEP（H019；框在本層，重掃上限 max_resweeps）。
    - 全空 ∧ 尚有俯仰層未掃 → NEXT_LAYER（2026-07-11 spec：yaw 只改 x 不改 y，
      標準層看不到的框換俯仰層才有機會；只掛全空分支，verify 失敗跳層無益）。
    - 其餘 → HUMAN（偵測已準，2026-06-29 決策）。
    """
    if had_candidates and resweeps_done < max_resweeps:
        return "RESWEEP"
    if not had_candidates and pitch_layers_left > 0:
        return "NEXT_LAYER"
    return "HUMAN"
```

（保留原 docstring 的 H019 敘事重點，可合併改寫。）

- [ ] **Step 4: 跑測試確認通過（含既有 decide_sweep_failure 舊測試）**

Run: `python -m pytest tests/test_harvester.py -q`
Expected: 全 PASS

---

### Task 3: `HarvestState` 層欄位＋快照 label 純函式

**Files:**
- Modify: `miningbot/harvester.py:8-16`（`HarvestState`）
- Test: `tests/test_harvester.py`

**Interfaces:**
- Produces: `HarvestState.pitch_layer: str = "mid"`、`HarvestState.pitch_layers_left: list`（default_factory=list）、`HarvestState.pitch_touched: bool = False`；`sweep_snapshot_label(pitch_layer: str, dir_idx: int) -> str`
- Consumes: 無（`dataclasses.field` 需 import）

- [ ] **Step 1: 失敗測試**

```python
class TestSweepSnapshotLabel:
    def test_mid_keeps_legacy_name(self):
        # 標準層維持舊檔名——logs/_diag_tracker.py 與文件的 `*sweep_empty*` glob 兩者都吃，
        # 但既有排錯習慣搜 sweep_empty_dirN，不無故改名
        assert harvester.sweep_snapshot_label("mid", 3) == "sweep_empty_dir3"

    def test_pitch_layer_tagged(self):
        assert harvester.sweep_snapshot_label("up", 0) == "sweep_empty_up_dir0"
        assert harvester.sweep_snapshot_label("down", 7) == "sweep_empty_down_dir7"


def test_harvest_state_pitch_defaults():
    st = harvester.HarvestState(rotations=0, elapsed_s=0.0)
    assert st.pitch_layer == "mid"
    assert st.pitch_layers_left == []
    assert st.pitch_touched is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_harvester.py -q -k "SnapshotLabel or pitch_defaults"`
Expected: FAIL

- [ ] **Step 3: 實作**

```python
from dataclasses import dataclass, field   # 檔頂既有 import 改這行

@dataclass
class HarvestState:
    rotations: int          # （既有欄位照舊）
    elapsed_s: float
    net_rotations: int = 0
    d3_attempts: int = 0
    harvest_id: str = ""
    verify_fail_resweeps: int = 0
    pitch_layer: str = "mid"        # 目前俯仰層（"mid"/"up"/"down"；快照 label／log 用）
    pitch_layers_left: list = field(default_factory=list)  # 尚未掃的 PitchLayer（失敗路徑逐層 pop）
    pitch_touched: bool = False     # 任一層轉換「嘗試過」（含失敗）→ 收尾必須 pitch_reset 歸位


def sweep_snapshot_label(pitch_layer: str, dir_idx: int) -> str:
    """sweep 全空診斷快照 label（純函式）。標準層維持舊名 sweep_empty_dirN（排錯習慣不變），
    俯仰層加層標記 sweep_empty_<layer>_dirN。"""
    if pitch_layer == "mid":
        return "sweep_empty_dir%d" % dir_idx
    return "sweep_empty_%s_dir%d" % (pitch_layer, dir_idx)
```

（既有欄位的原註解保留，勿刪。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_harvester.py -q`
Expected: 全 PASS

---

### Task 4: Bot 接線（層轉換、失敗分流消費、收尾歸位、快照 label）

**Files:**
- Modify: `miningbot/main.py`（四個點，見下）

純 I/O 接線、無新純邏輯 → 無新單元測試；完成標準＝全測試套件仍綠＋Task 5 實機驗證。

**Interfaces:**
- Consumes: Task 1-3 全部；既有 `self._pitch_drag_verified(label, drag)`（main.py:3142）、`ic.pitch_reset/pitch_nudge`、`self._mine_resetting`、`self._focus_roblox()`

- [ ] **Step 1: HARVESTING 進場初始化層清單**

`_on_enter` 建 `HarvestState` 處（搜 `HarvestState(`），建構後加：

```python
        self.harvest.pitch_layers_left = harvester.plan_pitch_layers(
            cfg.sweep_pitch_enabled, cfg.sweep_pitch_step_px,
            cfg.sweep_pitch_center_back_px)
```

- [ ] **Step 2: 新增 `_pitch_layer_transition`＋`_pitch_restore_if_touched`（放 `_pitch_drag_verified` 附近）**

```python
    def _pitch_layer_transition(self) -> bool:
        """失敗路徑俯仰層轉換：pitch_reset 絕對基準 → nudge 到下一層（2026-07-11 spec）。

        回 True＝已切到新層（呼叫端 return，下個 tick 在新層重跑 8 方位）；False＝層用盡
        或礦坑重置中（呼叫端走 giveup）。拖曳被吃 → 整組（reset→nudge）重來一次——reset
        冪等（飽和→回拉）使重試安全、nudge 單獨重送會過量（sampler 微調不重送的教訓）；
        再失敗跳過該層試下一層（寧可少掃一層，不可角度不明硬掃——45° 斜角事故同族）。
        """
        hid = self.harvest.harvest_id
        while self.harvest.pitch_layers_left:
            if self._mine_resetting:
                self.logger.info("[%s] 俯仰層轉換前偵測到礦坑重置 -> 放棄掃層", hid)
                return False
            layer = self.harvest.pitch_layers_left.pop(0)
            self.harvest.pitch_touched = True
            for attempt in (1, 2):
                ok = self._pitch_drag_verified(
                    f"[{hid}] 俯仰層 {layer.name} 歸位(attempt {attempt})",
                    lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                           cfg.sweep_pitch_center_back_px))
                if ok:
                    ok = self._pitch_drag_verified(
                        f"[{hid}] 俯仰層 {layer.name} nudge {layer.nudge_px}px(attempt {attempt})",
                        lambda: ic.pitch_nudge(layer.nudge_px))
                if ok:
                    break
                self._focus_roblox()
                ic.settle(cfg.sampler_pitch_focus_settle_s)
            if not ok:
                self.logger.warning("[%s] 俯仰層 %s 拖曳兩輪皆疑似被吃 -> 跳過該層",
                                    hid, layer.name)
                continue
            self.harvest.pitch_layer = layer.name
            self._harvest_start = time.time()   # 每層獨立 sweep_timeout_s 預算（比照 sweep 完成後重置）
            self.logger.info("[%s] 俯仰層切換 -> %s（重新 8 方位掃描）", hid, layer.name)
            return True
        return False

    def _pitch_restore_if_touched(self):
        """採集收尾俯仰歸位：動過俯仰層（含轉換失敗——reset 可能已改角度）才歸位到置中標準角。

        使用者挖礦視角習慣＝置中（2026-07-11 確認），center_back_px 即校準成置中 → 歸位＝
        回到平常挖礦角度。沒動過（絕大多數採集）零成本零風險。
        """
        if not self.harvest.pitch_touched:
            return
        for attempt in (1, 2):
            if self._pitch_drag_verified(
                    f"[{self.harvest.harvest_id}] 收尾俯仰歸位(attempt {attempt})",
                    lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                           cfg.sweep_pitch_center_back_px)):
                return
            self._focus_roblox()
            ic.settle(cfg.sampler_pitch_focus_settle_s)
        self.logger.warning("[%s] 收尾俯仰歸位兩輪皆疑似被吃——視角可能非置中，人工留意",
                            self.harvest.harvest_id)
```

- [ ] **Step 3: `_tick_harvest` 全空分支消費 NEXT_LAYER（main.py:2334 附近）**

把既有：

```python
                if harvester.decide_sweep_failure(had_candidates,
                                                  self.harvest.verify_fail_resweeps) == "RESWEEP":
                    self.harvest.verify_fail_resweeps += 1
                    self.logger.info(...)
                    self._reharvest_sweep()
                    return
                self.logger.info("[%s] sweep 未找到追蹤框（環繞一次）-> 人工", hid)
                self._harvest_giveup("全方位掃描未找到追蹤框（礦可能已被挖走），請手動處理")
                return
```

改為：

```python
                verdict = harvester.decide_sweep_failure(
                    had_candidates, self.harvest.verify_fail_resweeps,
                    pitch_layers_left=len(self.harvest.pitch_layers_left))
                if verdict == "RESWEEP":
                    self.harvest.verify_fail_resweeps += 1
                    self.logger.info("[%s] sweep 看過穩定框但 verify 失敗（FOV 位移/邊緣裁切）"
                                     "-> 重掃一次 (%d/1)", hid, self.harvest.verify_fail_resweeps)
                    self._reharvest_sweep()
                    return
                if verdict == "NEXT_LAYER":
                    # yaw 只改 x 不改 y（H026）：標準層看不到的框，換俯仰層才有機會。
                    # 只在本來就要 giveup 的案例多花 ~30-40s，換少一次遠端介入。
                    self.last_action = "俯仰層掃描"
                    if self._pitch_layer_transition():
                        return          # 下個 tick 在新層重跑 8 方位（sweep 計時已重置）
                    # 層全部被吃/重置中 → 落到 giveup
                self.logger.info("[%s] sweep 未找到追蹤框（俯仰層剩 %d）-> 人工",
                                 hid, len(self.harvest.pitch_layers_left))
                self._harvest_giveup("全方位掃描未找到追蹤框（礦可能已被挖走），請手動處理")
                return
```

- [ ] **Step 4: 快照 label 帶層（main.py:2197 `_sweep_for_tracker` 全空落盤）**

```python
                for di, fr in sweep_frames:
                    self._hsnap(fr, harvester.sweep_snapshot_label(self.harvest.pitch_layer, di))
```

- [ ] **Step 5: 收尾歸位接線**

- `_harvest_success`（main.py:2535 起）：在呼叫 `restore_view` 的同一段、restore 之前加 `self._pitch_restore_if_touched()`（先俯仰後 yaw，兩者獨立、順序只求固定）。
- `_harvest_giveup`（main.py:2208 起）：`plan.restore_view` 為真（face_tracker=False）的分支裡、既有 restore_view 呼叫之前加 `self._pitch_restore_if_touched()`；face_tracker=True 分支**不加**（保持面對框，spec 定案）。

- [ ] **Step 6: 全套測試**

Run: `python -m pytest -q`
Expected: 全綠

---

### Task 5: 實機校準＋啟用（Claude/人工，不委派 opencode）

**Files:**
- Modify: `miningbot/config.py`（填校準值、翻 `sweep_pitch_enabled=True`）
- Modify: `CLAUDE.md`（採集流程段補一行俯仰層敘述）、`docs/manual-sampling.md`（校準步驟）

- [ ] **Step 1: 礦內 R 視窗校準 `sweep_pitch_center_back_px`**：俯仰歸位 → 微調到「置中視角」（平常挖礦角度），讀偏移量寫入 config。若礦內夾限行為與地表不同，同步調 `sweep_pitch_clamp_px`。
- [ ] **Step 2: 校準 `sweep_pitch_step_px`**：從置中 nudge 一步、截圖對比，調整到「一步 ≈ 半個垂直視野」（三層銜接不留縫也不重複過多）；確認正負方向（正=向下拖是否符合遊戲）。
- [ ] **Step 3: 啟用＋實機端到端**：`sweep_pitch_enabled=True`；人為造「標準層看不到框」情境（或等自然案例），確認 log 出現層切換、上/下層能撈到框且就地開火、收尾視角回置中；三層全空時 `snapshots/trace/` 有 `sweep_empty_up_dir*`/`sweep_empty_down_dir*`。
- [ ] **Step 4: 文件補記＋commit**（含 Task 1-4 的 code；commit 訊息照慣例附 Co-Authored-By）。

## Self-Review 紀錄

- Spec 覆蓋：層順序上→下（Task 1）、NEXT_LAYER 只掛全空分支（Task 2）、每層獨立 timeout（Task 4 Step 2 重置 `_harvest_start`）、快照層標記（Task 3/4）、收尾歸位含 face_tracker 例外（Task 4 Step 5）、重置守門（Task 4 Step 2 `_mine_resetting`）、boost guard 無需改動（層內 8 方位迴圈沿用既有 `_sweep_for_tracker`）、校準前停用（Global Constraints＋Task 1 預設值）——全數有任務對應。
- `_reharvest_sweep` 留在當前層：已核實（main.py:2834）它只改 `d3_attempts`/`_target_marker`/計時器、**不重建 HarvestState** → 層欄位天然存活，自然滿足 spec「RESWEEP 只重掃當前層」，無需改碼。
- 型別/命名一致性：`PitchLayer.nudge_px`、`pitch_layers_left`（list of PitchLayer；decide 收 `len()`）、`sweep_snapshot_label` 各任務用名一致。
