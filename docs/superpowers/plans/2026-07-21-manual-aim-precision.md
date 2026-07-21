# 手動瞄準精定位 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手動瞄準選粗格後，限縮該格用特徵偵測器找追蹤框真正中心自動開火（綠色框已驗證 0px 命中）；抓不到退回放大手選細格；裁格/放大圖落 log 養其他色系素材。

**Architecture:** 純函式（`remote_aim.grid_cell_region`／`fov_state_consistent`）＋新偵測器（`vision.detect_tracker_core`，限縮區域內「亮飽和色方塊＋黑邊」）＋改 `main._execute_remote_fire`（限縮偵測→命中自動開火；None→退路＋落 log）＋放大手選退路（awaiting_fine 子狀態，借回礦純函式）。

**Tech Stack:** Python 3.11、opencv (cv2)、numpy、既有 miningbot 模組（vision/remote_aim/reentry_remote/main）、pytest、ruff、uv。

## Global Constraints

- 座標／門檻／間隔只放 `miningbot/config.py`；純函式不做 I/O。
- 方位訊息面 1-8、內部 dir_idx 0-based（前一 commit 落地，勿回退）。
- 追蹤框場景 fixture 入 `assets/*_scene.png`；不目視讀圖，斷言用 `cv2.imread` 計算。
- 每任務完成必 commit：`uv run pytest -q` 全綠＋`uv run ruff check . --no-cache`，只 stage 該任務檔案，中文訊息，結尾 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 借回礦（`reentry_remote`）純函式可用，但**不共用其狀態機**（兩流程刻意分離）。
- 非綠色框無 fixture → 偵測回 None → 退路兜底，**永不誤射未驗證色系**。

---

### Task 1: remote_aim 純函式（粗格區域＋FOV 狀態比對）

**Files:**
- Modify: `miningbot/remote_aim.py`（加 2 函式，接在 `grid_cell_of` 附近）
- Test: `tests/test_remote_aim.py`

**Interfaces:**
- Produces:
  - `grid_cell_region(cell: str, margin_frac: float = 0.0, w=1920, h=1080, cols=6, rows=4) -> tuple|None`（回 (x,y,w,h) 原幀子區域，含對稱餘裕＋clamp；非法回 None）
  - `fov_state_consistent(s0: bool, s1: bool) -> bool`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_remote_aim.py（TestGridCellRegion / TestFovStateConsistent 新增）
from miningbot.remote_aim import grid_cell_region, fov_state_consistent

class TestGridCellRegion:
    def test_c1_no_margin(self):
        assert grid_cell_region("C1") == (640, 0, 320, 270)

    def test_c1_margin_clamps_top(self):
        # margin 0.15：mx=48,my=40；C1 貼頂 y0 clamp 0、右不出界
        assert grid_cell_region("C1", 0.15) == (592, 0, 416, 310)

    def test_f4_margin_clamps_right_bottom(self):
        # F4 貼右下角，x1/y1 clamp 到 1920/1080
        x, y, w, h = grid_cell_region("F4", 0.15)
        assert x == 1600 - 48 and y == 810 - 40
        assert x + w == 1920 and y + h == 1080

    def test_invalid(self):
        for bad in ("", "C", "G1", "C5", "c1c"):
            assert grid_cell_region(bad) is None

class TestFovStateConsistent:
    def test_equal_states_true(self):
        assert fov_state_consistent(True, True) is True
        assert fov_state_consistent(False, False) is True

    def test_differing_states_false(self):
        assert fov_state_consistent(True, False) is False
        assert fov_state_consistent(False, True) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_remote_aim.py::TestGridCellRegion tests/test_remote_aim.py::TestFovStateConsistent -q`
Expected: FAIL（`ImportError` / `AttributeError: grid_cell_region`）

- [ ] **Step 3: 實作**

```python
# miningbot/remote_aim.py（接在 grid_cell_of 之後）
def grid_cell_region(cell: str, margin_frac: float = 0.0,
                     w: int = 1920, h: int = 1080,
                     cols: int = 6, rows: int = 4):
    """粗格代碼 → 原幀子區域 (x, y, w, h)，含對稱邊界餘裕＋clamp 到畫面內；非法回 None。

    餘裕防框貼格線被裁；限縮偵測用（vision.detect_tracker_core 只掃這塊）。
    """
    cell = (cell or "").strip().upper()
    if len(cell) != 2 or cell[0] not in GRID_COLS[:cols] or cell[1] not in GRID_ROWS[:rows]:
        return None
    cw, ch = w // cols, h // rows
    cx = GRID_COLS.index(cell[0]) * cw
    cy = GRID_ROWS.index(cell[1]) * ch
    mx, my = int(cw * margin_frac), int(ch * margin_frac)
    x0, y0 = max(0, cx - mx), max(0, cy - my)
    x1, y1 = min(w, cx + cw + mx), min(h, cy + ch + my)
    return (x0, y0, x1 - x0, y1 - y0)


def fov_state_consistent(s0: bool, s1: bool) -> bool:
    """偵測幀與開火前的 boost 狀態相等 → True（可開火）；不等 → False（作廢重來）。"""
    return s0 == s1
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_remote_aim.py -q`
Expected: PASS（含既有測試）

- [ ] **Step 5: commit**

```bash
git add miningbot/remote_aim.py tests/test_remote_aim.py
git commit -m "feat(remote_aim): 加 grid_cell_region 粗格區域＋fov_state_consistent 純函式（手動瞄準精定位 §7）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: vision.detect_tracker_core 限縮偵測器＋綠色 fixture

**Files:**
- Create: `assets/aim_tracker_core_green_scene.png`（由 101 review 快照複製）
- Modify: `miningbot/vision.py`（加 `detect_tracker_core`）
- Test: `tests/test_vision.py`

**Interfaces:**
- Consumes: 無（吃 ndarray）
- Produces: `detect_tracker_core(region_bgr, profiles, *, min_area=80, ar_lo=0.6, ar_hi=1.7, extent_min=0.6, border_margin=6, border_dark_max=70, border_dark_frac_min=0.15) -> tuple|None`
  - `profiles`: `[(name, hsv_lo, hsv_hi), ...]`
  - 回 `(cx, cy, profile_name, border_frac)`（座標相對 `region_bgr` 左上）｜`None`

- [ ] **Step 1: 建 fixture**

```bash
# 由 101 開火幀（綠框、boost 到期態）原樣入庫
cp "$LOCALAPPDATA/Packages/PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0/LocalCache/Local/RexMacro/logs/snapshots/review/20260721_134803_262217600_000030_101_aim_fire_800x135.png" assets/aim_tracker_core_green_scene.png
```
（若該路徑已清，改用任何含綠色追蹤框的實機全幀，並更新下方 C1 真值座標——但預設沿用 (851,189)。）

- [ ] **Step 2: 寫失敗測試**

```python
# tests/test_vision.py（TestDetectTrackerCore 新增）
import cv2
from miningbot.vision import detect_tracker_core

GREEN = [("green", (40, 150, 150), (85, 255, 255))]

def _scene():
    img = cv2.imread("assets/aim_tracker_core_green_scene.png")
    assert img is not None
    return img

class TestDetectTrackerCore:
    def test_hits_box_center_in_c1(self):
        # 限縮 C1 (640,0,320,270) → 框真正中心相對 (211,189)（絕對 851,189）
        crop = _scene()[0:270, 640:960]
        r = detect_tracker_core(crop, GREEN)
        assert r is not None
        cx, cy, name, bf = r
        assert abs(cx - 211) <= 15 and abs(cy - 189) <= 15
        assert name == "green" and bf >= 0.15

    def test_empty_neighbor_cell_none(self):
        # B1 (320,0,320,270) 無框 → None（負樣本兩側夾）
        crop = _scene()[0:270, 320:640]
        assert detect_tracker_core(crop, GREEN) is None

    def test_no_profiles_none(self):
        # 未覆蓋色系（空 profiles）→ None，永不誤射
        crop = _scene()[0:270, 640:960]
        assert detect_tracker_core(crop, []) is None
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `uv run pytest tests/test_vision.py::TestDetectTrackerCore -q`
Expected: FAIL（`ImportError: detect_tracker_core`）

- [ ] **Step 4: 實作**

```python
# miningbot/vision.py（新函式；檔內已 import cv2, numpy as np）
def detect_tracker_core(region_bgr, profiles, *, min_area=80, ar_lo=0.6, ar_hi=1.7,
                        extent_min=0.6, border_margin=6, border_dark_max=70,
                        border_dark_frac_min=0.15):
    """限縮區域內找追蹤框中心（亮飽和色方塊＋周圍黑邊）。回 (cx,cy,profile,border_frac)｜None。

    座標相對 region_bgr 左上。玩家已提供粗格＝無全幀干擾，故限縮偵測乾淨可靠。
    profiles=[(name,hsv_lo,hsv_hi)]；空清單或無命中回 None（未驗證色系不誤射）。
    多命中取面積最大。黑邊是跨色系判別鍵（綠地形無黑邊，框有）。
    """
    if region_bgr is None or region_bgr.size == 0 or not profiles:
        return None
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    rh, rw = region_bgr.shape[:2]
    best = None
    for name, lo, hi in profiles:
        mask = cv2.inRange(hsv, tuple(lo), tuple(hi))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            a = cv2.contourArea(c)
            if a < min_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if not (ar_lo < w / max(h, 1) < ar_hi and a / (w * h) > extent_min):
                continue
            m = border_margin
            x0, y0 = max(0, x - m), max(0, y - m)
            x1, y1 = min(rw, x + w + m), min(rh, y + h + m)
            ring = gray[y0:y1, x0:x1]
            inner = np.zeros(ring.shape, np.uint8)
            inner[y - y0:y - y0 + h, x - x0:x - x0 + w] = 1
            bp = ring[inner == 0]
            bf = float((bp < border_dark_max).mean()) if bp.size else 0.0
            if bf < border_dark_frac_min:
                continue
            if best is None or a > best[0]:
                best = (a, x + w // 2, y + h // 2, name, bf)
    return None if best is None else (best[1], best[2], best[3], best[4])
```

- [ ] **Step 5: 跑測試確認通過**

Run: `uv run pytest tests/test_vision.py::TestDetectTrackerCore -q`
Expected: PASS（3 則）。若命中測試 FAIL，只調 profile HSV/門檻對齊 §6 表、**不放寬到誤收 B1**。

- [ ] **Step 6: commit**

```bash
git add miningbot/vision.py tests/test_vision.py assets/aim_tracker_core_green_scene.png
git commit -m "feat(vision): detect_tracker_core 限縮區域特徵偵測（亮飽和色方塊＋黑邊）＋綠色 fixture

限縮玩家指定粗格內找框真正中心，無全幀干擾。綠色 101 實測 0px、空格 None。
其他色系 profile 待 fixture 補（空 profiles 回 None 不誤射）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: config 新增偵測器/放大門檻＋移除盲打常數

**Files:**
- Modify: `miningbot/config.py`

**Interfaces:**
- Produces（`Config` 欄位）：`tracker_core_profiles`、`tracker_core_min_area`、`tracker_core_ar_lo`、`tracker_core_ar_hi`、`tracker_core_extent_min`、`tracker_core_border_margin`、`tracker_core_border_dark_max`、`tracker_core_border_dark_frac_min`、`remote_aim_zoom_margin_frac`、`remote_aim_fine_grid`、`remote_aim_fov_recheck_max`

- [ ] **Step 1: 確認 refind 常數引用點**

Run: `rg remote_aim_refind_radius_px`
Expected: 僅 `config.py` 定義 + `main.py` 的 `_execute_remote_fire` step 3 引用（Task 4 會刪 main 那段）。若他處另有引用，先記錄、Task 4 一併處理。

- [ ] **Step 2: 加 config 欄位**

```python
# miningbot/config.py（remote_aim_* 群組附近）
tracker_core_profiles: tuple = (("green", (40, 150, 150), (85, 255, 255)),)  # 色系 HSV（漸進擴充）
tracker_core_min_area: int = 80
tracker_core_ar_lo: float = 0.6
tracker_core_ar_hi: float = 1.7
tracker_core_extent_min: float = 0.6
tracker_core_border_margin: int = 6
tracker_core_border_dark_max: int = 70
tracker_core_border_dark_frac_min: float = 0.15
remote_aim_zoom_margin_frac: float = 0.15
remote_aim_fine_grid: int = 6
remote_aim_fov_recheck_max: int = 2
```
（若 `Config` 用 dataclass，`tracker_core_profiles` 用 tuple-of-tuple 免 mutable default。）

- [ ] **Step 3: 移除 refind 常數**

刪 `remote_aim_refind_radius_px`（Task 4 一併刪 main.py 引用；本步先確認 Step 1 無他處引用才刪，否則保留到 Task 4）。

- [ ] **Step 4: 跑測試＋lint**

Run: `uv run pytest -q && uv run ruff check miningbot/config.py --no-cache`
Expected: PASS / All checks passed（此步不獨立 commit，隨 Task 4）

---

### Task 4: 接進 _execute_remote_fire——限縮偵測自動命中＋裁格 log

**Files:**
- Modify: `miningbot/main.py`（`_execute_remote_fire` step 3；`_tick_remote_aim` 傳 region）
- 依賴：Task 1 `grid_cell_region`、Task 2 `detect_tracker_core`、Task 3 config

**Interfaces:**
- Consumes: `remote_aim.grid_cell_region`、`vision.detect_tracker_core`、`remote_aim.fov_state_consistent`
- Produces: `_execute_remote_fire(ctx, tgt_layer, tgt_dir, prior, region)`（新增 `region` 參數＝限縮偵測區）

- [ ] **Step 1: 呼叫端算 region 傳入**（`_tick_remote_aim`，約 main.py:3332-3341）

把目前：
```python
        if reply.kind == "candidate":
            c = ctx.candidates[reply.number - 1]
            tgt_layer, tgt_dir, prior = c.layer, c.dir_idx, c.pos
        else:
            tgt_layer, tgt_dir = reply.layer, reply.dir_idx
            prior = remote_aim.grid_cell_center(reply.cell)
```
改為（多算 region；candidate 用其位置反推粗格）：
```python
        if reply.kind == "candidate":
            c = ctx.candidates[reply.number - 1]
            tgt_layer, tgt_dir, prior = c.layer, c.dir_idx, c.pos
            cell = remote_aim.grid_cell_of(c.pos) or "C2"
        else:
            tgt_layer, tgt_dir = reply.layer, reply.dir_idx
            prior = remote_aim.grid_cell_center(reply.cell)
            cell = reply.cell
        region = remote_aim.grid_cell_region(cell, cfg.remote_aim_zoom_margin_frac)
```
並把呼叫改為 `self._execute_remote_fire(ctx, tgt_layer, tgt_dir, prior, region)`。

- [ ] **Step 2: 改 _execute_remote_fire 簽名＋step 3**

簽名加 `region`。把目前 step 3（`# 3. ROI 放寬重找` 起到 `pos = (int(pos[0]), int(pos[1]))` 為止，約 main.py:3496-3517）整段換成限縮偵測：
```python
        # 3. 限縮偵測：玩家已提供粗格，只掃該格找框真正中心（無全幀干擾）。
        f_detect = capture.grab()
        state0 = self._boost_present
        rx, ry, rw, rh = region
        cell_crop = f_detect[ry:ry + rh, rx:rx + rw]
        self._hsnap(f_detect, "aim_cell_dir%d_%s" % (tgt_dir + 1, cell))   # 素材 log（§8）
        hit = vision.detect_tracker_core(
            cell_crop, cfg.tracker_core_profiles,
            min_area=cfg.tracker_core_min_area, ar_lo=cfg.tracker_core_ar_lo,
            ar_hi=cfg.tracker_core_ar_hi, extent_min=cfg.tracker_core_extent_min,
            border_margin=cfg.tracker_core_border_margin,
            border_dark_max=cfg.tracker_core_border_dark_max,
            border_dark_frac_min=cfg.tracker_core_border_dark_frac_min)
        if not hit:
            # 未覆蓋色系/框消失：標素材、回報退路（Task 5 升級為放大手選）
            self._hsnap(f_detect, "aim_core_miss_dir%d_%s" % (tgt_dir + 1, cell))
            self.logger.info("[%s] AIM 限縮偵測無框（region=%s）", hid, region)
            return False, "沒自動抓到框（可能非綠色框），`跳過` 或 `手動` 重掃"
        pos = (rx + hit[0], ry + hit[1])
        pos_score = hit[3]
        self.logger.info("[%s] AIM 限縮偵測命中 %s (%s bf=%.2f)", hid, pos, hit[2], hit[3])
        pos = (int(pos[0]), int(pos[1]))
```
（保留其後既有的 `# 4. 開火` 與 verify 尾不動；`cell` 已由簽名處可得——若 `_execute_remote_fire` 內無 `cell`，改用 `region` 命名 log：`"aim_cell_dir%d" % (tgt_dir + 1)`。）

- [ ] **Step 3: 刪盲打常數**

刪 `remote_aim_refind_radius_px`（config.py＋此處已無引用）。Run `rg remote_aim_refind_radius_px` 確認 0 命中。

- [ ] **Step 4: 全測試＋lint**

Run: `uv run pytest -q && uv run ruff check miningbot/ --no-cache`
Expected: PASS / All checks passed。
（`_execute_remote_fire` 是 I/O 編排、無單元 harness；正確性由 Task 1-2 純函式測＋全綠＋**下一輪實機綠框自動命中** log 驗證——見結案。）

- [ ] **Step 5: commit**

```bash
git add miningbot/main.py miningbot/config.py
git commit -m "feat(remote_aim/main): 手動瞄準改限縮單格特徵偵測自動命中＋裁格 log 養素材（spec §5/§8）

選粗格後只掃該格找框真正中心→命中自動開火（綠框 0px）；移除整幀重找＋盲打粗格心
（101 病灶 74px）。抓不到暫回報退路（Task 5 升級放大手選）。裁格/miss 圖落 log 當
其他色系 fixture 素材。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: 放大手選退路（awaiting_fine 子狀態＋連鎖放大）

**Files:**
- Modify: `miningbot/remote_aim.py`（`AimReply` 加 kind、`parse_reply` 加 awaiting_fine 分支）
- Modify: `miningbot/main.py`（`AimContext` 加 zoom 欄位；`_execute_remote_fire` None 分支改進 awaiting_fine；`_handle_aim_reply`／`_tick_remote_aim` 消費 fine/放大/退）
- 依賴：Task 4；借 `reentry_remote.fine_cell_subregion`／`magnify_scale`／`pop_zoom_layer`
- Test: `tests/test_remote_aim.py`

**Interfaces:**
- Consumes: Task 4 的 miss 分支；`reentry_remote` 三純函式
- Produces: `parse_reply(text, num_candidates, layers_available=("mid",), awaiting_fine=False)`（新增 `awaiting_fine`）；`AimReply` 新 kind `"fine"`／`"magnify"`／`"zoom_back"`

- [ ] **Step 1: 寫 parse_reply awaiting_fine 失敗測試**

```python
# tests/test_remote_aim.py::TestParseReply 續
    def test_awaiting_fine_bare_cell(self):
        r = parse_reply("B3", 0, awaiting_fine=True)
        assert r.kind == "fine" and r.cell == "B3"

    def test_awaiting_fine_magnify(self):
        r = parse_reply("放大 B3", 0, awaiting_fine=True)
        assert r.kind == "magnify" and r.cell == "B3"

    def test_awaiting_fine_back(self):
        assert parse_reply("退", 0, awaiting_fine=True).kind == "zoom_back"

    def test_bare_cell_rejected_when_not_awaiting_fine(self):
        # 非 awaiting_fine 時裸細格不解析（避免誤射）
        assert parse_reply("B3", 0) is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_remote_aim.py::TestParseReply -q`
Expected: FAIL（`parse_reply() got unexpected keyword 'awaiting_fine'`）

- [ ] **Step 3: 實作 parse_reply awaiting_fine 分支**

```python
# miningbot/remote_aim.py：parse_reply 簽名加 awaiting_fine=False；函式開頭處理
def parse_reply(text, num_candidates, layers_available=("mid",), awaiting_fine=False):
    ...
    t = (text or "").replace("　", " ").strip()
    if not t:
        return None
    low = t.lower()
    if low in ("skip", "跳過"):
        return AimReply("skip")
    if awaiting_fine:
        # 放大手選子狀態：裸細格／放大／退（借回礦 _FINE_CELL 同義：A-F1-6）
        parts_f = t.split()
        if len(parts_f) == 1 and re.fullmatch(r"[A-Fa-f][1-6]", parts_f[0]):
            return AimReply("fine", cell=parts_f[0].upper())
        if len(parts_f) == 2 and parts_f[0] in ("放大", "magnify") \
                and re.fullmatch(r"[A-Fa-f][1-6]", parts_f[1]):
            return AimReply("magnify", cell=parts_f[1].upper())
        if low in ("退", "back"):
            return AimReply("zoom_back")
        return None
    # ...（以下維持既有 manual/candidate/grid 分支不變）
```
`AimReply` 的 `kind` docstring 補 `"fine"/"magnify"/"zoom_back"`。

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_remote_aim.py -q`
Expected: PASS

- [ ] **Step 5: AimContext 加 zoom 欄位＋miss 分支進 awaiting_fine**

`AimContext`（remote_aim.py:48-55）加：`awaiting_fine: bool = False`、`zoom_region: tuple = ()`、`zoom_stack: list = field(default_factory=list)`、`zoom_boost_state: bool = False`、`zoom_dir: int = 0`、`zoom_layer: str = "mid"`。
Task 4 的 miss 分支（回報字串）改為：設 `ctx.awaiting_fine=True`、`ctx.zoom_region=region`、`ctx.zoom_boost_state=self._boost_present`、`zoom_dir/zoom_layer`，發放大圖（`reentry_remote.magnify_scale` 定倍率、`remote_aim.draw_grid` 疊 6×6），caption 見 spec §9，回 `(False, "已放大待手選")`（不算失敗回挖礦、保留 ctx 等回覆）。

- [ ] **Step 6: 消費 fine/magnify/zoom_back（_tick_remote_aim）**

`_tick_remote_aim` 加分支：
- `fine`：`sub = reentry_remote.fine_cell_subregion(ctx.zoom_region, reply.cell)`；`pos=(sub[0]+sub[2]//2, sub[1]+sub[3]//2)`；`state1=self._boost_present`；`remote_aim.fov_state_consistent(ctx.zoom_boost_state, state1)`？True→`self._fire_d3_at(*pos)`＋既有 verify 尾；False→重抓當下重發放大圖（`remote_aim_fov_recheck_max` 上限，耗盡回報「畫面反覆變動」）。
- `magnify`：`ctx.zoom_stack.append(ctx.zoom_region)`；`ctx.zoom_region=fine_cell_subregion(ctx.zoom_region, reply.cell)`；重放大重發。
- `zoom_back`：`phase, layer = reentry_remote.pop_zoom_layer(...)` 同義——這裡簡化：`ctx.zoom_region = ctx.zoom_stack.pop() if ctx.zoom_stack else <原粗格 region>`；重發。
`_handle_aim_reply`（輪詢執行緒）解析時傳 `awaiting_fine=ctx.awaiting_fine`。

- [ ] **Step 7: 玩家訊息＋help 同步**（spec §9）

更新 miss→退路 caption、FOV 作廢重發訊息、`MANUAL_SURVEY_HELP` 末句、aim `看不懂` 訊息（awaiting_fine 時列 `細格`／`放大`／`退`）。見 [[feedback_new_command_must_update_player_messages]]。

- [ ] **Step 8: 全測試＋lint**

Run: `uv run pytest -q && uv run ruff check miningbot/ --no-cache`
Expected: PASS / All checks passed。

- [ ] **Step 9: commit**

```bash
git add miningbot/remote_aim.py miningbot/main.py tests/test_remote_aim.py
git commit -m "feat(remote_aim/main): 手動瞄準抓不到框→放大手選退路（awaiting_fine＋連鎖放大＋FOV 閘，spec §5.5）

自動偵測 None 時進 awaiting_fine：發放大圖、玩家回細格/放大/退，借回礦 fine_cell_subregion
連鎖逼近；發圖記 boost 狀態、開火前重讀不一致即重發（不依賴 D5）。訊息/help 同步。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage：**
- §5 流程：Task 4（自動命中）＋Task 5（放大手選退路）✅
- §6 偵測器＋綠 profile：Task 2 ✅
- §7 元件（grid_cell_region/fov_state_consistent/detect_tracker_core）：Task 1、2 ✅
- §8 log 素材：Task 4 step 2（`aim_cell_*`／`aim_core_miss_*`）✅
- §9 訊息：Task 5 step 7 ✅
- §10 測試：各 Task 的 test step ✅
- §11 config：Task 3 ✅；移除 refind：Task 3/4 ✅
- §13 三階段：Task 1-2→3-4（自動命中，獨立實機驗證）→5（退路）✅

**2. Placeholder scan：** 純函式與偵測器有完整程式碼；I/O（Task 4/5）給實際替換碼與行號錨。Task 5 step 6 的 zoom_back 用簡化 pop（非直接套 reentry ctx），已標明——實作者照該邏輯即可，非佔位。

**3. Type consistency：** `detect_tracker_core` 回 `(cx,cy,name,bf)` 四元組——Task 2 測試與 Task 4 `hit[0..3]` 一致；`grid_cell_region` 回 `(x,y,w,h)`——Task 4 `rx,ry,rw,rh` 解包一致；`AimReply` 新 kind 三者 Task 5 parse 與消費一致。

**結案＝實機驗證（非測試綠）：** 下一輪掛機、手動瞄準綠框，`harvest.log` 應見
`AIM 限縮偵測命中 (x,y) (green bf=…)` 且該發 verify 確認；非綠框應見 `限縮偵測無框`→退路發圖。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-21-manual-aim-precision.md`.**

分階段：**Task 1-4 = 自動命中（修好 101 綠框、開始養素材，可獨立實機驗證）**；**Task 5 = 放大手選退路**。可只做到 Task 4 先上機、Task 5 後補。

兩種執行方式：
1. **Subagent-Driven（推薦）** — 每個 Task 派新 subagent、Task 間審查、快迭代。
2. **Inline Execution** — 本 session 內用 executing-plans、批次執行加檢查點。

哪一種？（或先只跑 Task 1-4？）
