# Discord 遠端瞄準（Remote Aim）實作計畫

> **For agentic workers:** 本 repo 慣例：程式實作委派 opencode（`opencode run`，GLM 無視覺、勿讀圖）；本計畫即 opencode 規格書的本體。分兩梯次委派：Phase A（Task A1-A3，附圖增強，獨立可用）先跑並人工審核，Phase B（Task B1-B3）再跑。Claude 負責最終驗證與 Task B4 實機端到端。Steps 用 checkbox 追蹤。

**Goal:** giveup 交人工時附「近失候選編號＋網格」圖，使用者在 Discord 回一般訊息（`2`／`5U C3`／`跳過`）即可指揮 bot 轉向、重掃、開火。

**Architecture:** 近失候選由 `vision.find_tracker` 外掛欄位外露（判定零改動）；編號表／網格座標／疊圖／回覆解析／對齊計畫全在新模組 `miningbot/remote_aim.py`（純函式，TDD）；Bot 負責 sweep 記錄、giveup 發圖、Discord 輪詢分支與 NEEDS_HUMAN tick 的 fire 執行。fire＝一發 D3＋一個 verify 窗口，不自動 RETRY/RESWEEP（要不要再射由使用者決定）。

**Tech Stack:** Python、pytest、OpenCV、Discord Bot API（經 `notify`）。

**Spec:** `docs/superpowers/specs/2026-07-11-discord-remote-aim-design.md`（改動前先讀）

## Global Constraints

- TDD：先寫失敗測試再實作；完成標準 `python -m pytest -q` 全綠。
- **opencode 不 commit**（留人工審）；不動 `assets/`、不讀任何圖片。
- 純邏輯進 `miningbot/remote_aim.py`＋`tests/test_remote_aim.py`；`vision.py` 只做純外掛（既有回傳/判定零改動，全部既有 vision 測試必須原樣通過）；I/O 只進 `miningbot/main.py`。
- 解析不出的訊息一律不動作（寧可不射不誤射）；`!` 前綴與既有命令行為完全不動。
- 執行緒安全：Discord 輪詢執行緒只寫單一 pending 欄位，輸入操作一律由主迴圈消費（比照 `_sampler_want` 旗標模式）。

---

## Phase A：giveup 附圖增強（獨立可用）

### Task A1: `vision.find_tracker` 近失候選外露

**Files:**
- Modify: `miningbot/vision.py:311-445`（`find_tracker`）
- Test: `tests/test_vision.py`

**Interfaces:**
- Produces: `find_tracker(..., collect_rejects=None)`——傳 list 進來時，把「值得人工看的被拒候選」append 成 dict：`{"pos": (cx, cy), "colored": float, "edge": float | None, "reason": str}`；reason ∈ `"margin"`（in_area False）/`"exclude"`/`"preexist"`/`"hard_rej"`/`"soft"`（borderline survivor 落選）。不傳（None）＝行為與現狀 byte-identical。

- [ ] **Step 1: 失敗測試**

```python
# tests/test_vision.py 新增（檔尾）
def _hollow_ring(img, cx, cy, size=40, color=(60, 220, 60), thick=6):
    """畫一個彩色空心方框（模擬追蹤框外框），回傳中心座標。"""
    h = size // 2
    cv2.rectangle(img, (cx - h, cy - h), (cx + h, cy + h), color, thick)
    return cx, cy


def test_collect_rejects_margin_band():
    """邊緣帶內的彩色環：現狀被拒（in_area=False）、collect_rejects 應收到 reason=margin。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _hollow_ring(img, 60, 540)          # x=60 落在 margin_frac=0.10 的左緣帶（<192）
    rejects = []
    loc = find_tracker(img, margin_frac=0.10, collect_rejects=rejects)
    assert loc is None
    assert any(r["reason"] == "margin" and abs(r["pos"][0] - 60) <= 5 for r in rejects), rejects


def test_collect_rejects_none_keeps_behavior():
    """不傳 collect_rejects：回傳值與傳了之後的回傳值完全一致（外掛零影響）。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _hollow_ring(img, 960, 540)
    a = find_tracker(img, margin_frac=0.10)
    b = find_tracker(img, margin_frac=0.10, collect_rejects=[])
    assert a == b


def test_collect_rejects_hard_rej_real_equipment():
    """真實資料：H040 紅緞帶裝備場景——現狀 hard_rej 拒收，collect_rejects 應把它外露。"""
    img_path = "assets/red_ribbon_equipment_scene.png"
    tmpls = _load_real_markers_h040()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    rejects = []
    loc = find_tracker(img, margin_frac=cfg.tracker_margin_frac,
                       shape_templates=tmpls,
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_hard_floor=cfg.tracker_shape_hard_floor,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px,
                       collect_rejects=rejects)
    assert loc is None                       # H040 回歸：裝備仍不誤收
    assert any(r["reason"] == "hard_rej" for r in rejects), rejects
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_vision.py -q -k collect_rejects`
Expected: FAIL（TypeError: unexpected keyword）

- [ ] **Step 3: 實作**

`find_tracker` 簽名加 `collect_rejects=None`。三個掛點（全部只在 `collect_rejects is not None` 時動作，且不改任何既有 control flow）：

1. **preexist 拒收處**（`if ref_fill > 0.15:` 區塊、`continue` 前）：先算 colored_frac（把既有 `bb_hsv`/`colored_frac` 計算搬到差分過濾**之前**——它只讀 hsv，搬動安全），colored_frac > 0.40 才 append `{"pos": (cx, cy), "colored": colored_frac, "edge": None, "reason": "preexist"}`。
2. **accept=False 處**（既有 `if accept:` 的 else 側）：colored_frac > 0.40 時依原因 append——`not in_area` → `"margin"`；`in_exclude` → `"exclude"`（兩者都成立取 margin）。colored 不過門檻的不收（垃圾）。
3. **形狀確認迴圈**：`hard_rej` verdict → append `{"pos": (cx, cy), "colored": cf, "edge": score, "reason": "hard_rej"}`；`soft` verdict → 同樣 append（reason `"soft"`）——survivor 之後可能贏（回傳非 None），呼叫端自行忽略「有回傳值時的 rejects」或照用（附圖仍有參考價值），vision 不做去重。

- [ ] **Step 4: 跑測試確認通過（含全部既有 vision 測試）**

Run: `python -m pytest tests/test_vision.py -q`
Expected: 全 PASS

---

### Task A2: `remote_aim.py` 資料結構＋編號表＋網格＋疊圖

**Files:**
- Create: `miningbot/remote_aim.py`
- Test: `tests/test_remote_aim.py`（新檔）

**Interfaces:**
- Produces:
  - `AimCandidate(number, layer, dir_idx, pos, score, reason)`（frozen dataclass）
  - `SweepShot(layer, dir_idx, snapshot_path, rejects)`（dataclass；rejects＝A1 的 dict list）
  - `AimContext(candidates, shots, pose_net_rotations, pose_pitch_layer, harvest_id, created_at)`（dataclass）
  - `build_aim_context(shots, pose_net_rotations, pose_pitch_layer, harvest_id, now, max_candidates=9) -> AimContext`
  - `grid_cell_center(cell, w=1920, h=1080, cols=6, rows=4) -> (x, y) | None`
  - `draw_overlay(frame_bgr, candidates, grid=True) -> new ndarray`（不改輸入）
  - `GRID_COLS = "ABCDEF"`、`GRID_ROWS = "1234"`

- [ ] **Step 1: 失敗測試**

```python
# tests/test_remote_aim.py（新檔）
import numpy as np
from miningbot import remote_aim
from miningbot.remote_aim import (AimCandidate, SweepShot, build_aim_context,
                                  grid_cell_center, draw_overlay, parse_reply)


def _shot(layer, d, rejects):
    return SweepShot(layer=layer, dir_idx=d, snapshot_path=f"snap_{layer}_{d}.png",
                     rejects=rejects)

def _rej(x, y, edge, reason="hard_rej", colored=0.8):
    return {"pos": (x, y), "colored": colored, "edge": edge, "reason": reason}


class TestBuildAimContext:
    def test_numbers_by_score_desc_across_shots(self):
        # 編號＝全域流水、依分數（edge 優先、無 edge 用 colored）降冪——最像框的排最前
        shots = [_shot("mid", 2, [_rej(100, 200, 0.30)]),
                 _shot("up", 5, [_rej(500, 400, 0.38), _rej(900, 300, None, "margin", 0.9)])]
        ctx = build_aim_context(shots, 0, "mid", "071", now=123.0)
        assert [c.number for c in ctx.candidates] == [1, 2, 3]
        assert ctx.candidates[0].pos == (500, 400)      # edge 0.38 最高
        assert ctx.candidates[0].layer == "up" and ctx.candidates[0].dir_idx == 5
        assert ctx.candidates[2].pos == (900, 300)      # 無 edge（margin）排 edge 之後
        assert ctx.pose_net_rotations == 0 and ctx.harvest_id == "071"

    def test_cap_max_candidates(self):
        shots = [_shot("mid", 0, [_rej(10 * i, 20, 0.2 + i * 0.01) for i in range(1, 15)])]
        ctx = build_aim_context(shots, 0, "mid", "072", now=0.0, max_candidates=9)
        assert len(ctx.candidates) == 9

    def test_empty_shots_gives_empty_candidates(self):
        ctx = build_aim_context([], 3, "up", "073", now=0.0)
        assert ctx.candidates == [] and ctx.pose_net_rotations == 3
        assert ctx.pose_pitch_layer == "up"


class TestGridCellCenter:
    def test_c3_center(self):
        # 6×4 網格、1920×1080：格寬 320、高 270。C=第3欄(idx2)、3=第3列(idx2)
        assert grid_cell_center("C3") == (2 * 320 + 160, 2 * 270 + 135)

    def test_a1_and_f4_corners(self):
        assert grid_cell_center("A1") == (160, 135)
        assert grid_cell_center("F4") == (5 * 320 + 160, 3 * 270 + 135)

    def test_case_insensitive(self):
        assert grid_cell_center("c3") == grid_cell_center("C3")

    def test_invalid_cells(self):
        for bad in ("G1", "A5", "AA", "3C", "", "C"):
            assert grid_cell_center(bad) is None


class TestDrawOverlay:
    def test_marks_candidate_and_keeps_input_intact(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cands = [AimCandidate(1, "mid", 2, (640, 400), 0.3, "hard_rej")]
        out = draw_overlay(frame, cands, grid=True)
        assert out.shape == frame.shape
        assert frame.sum() == 0                      # 輸入不被改
        assert out[400, 640 - 40:640 + 40].sum() > 0  # 候選框附近有畫東西
        assert out.sum() > 0

    def test_no_candidates_grid_only(self):
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        out = draw_overlay(frame, [], grid=True)
        assert out.sum() > 0                          # 網格線有畫
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_remote_aim.py -q`
Expected: FAIL（module 不存在）

- [ ] **Step 3: 實作**

```python
# miningbot/remote_aim.py
"""Discord 遠端瞄準（2026-07-11 spec）：giveup 附圖的近失候選編號／網格座標／
回覆解析／對齊計畫——全部純函式，I/O 在 main.Bot。"""
import re
from dataclasses import dataclass, field

GRID_COLS = "ABCDEF"
GRID_ROWS = "1234"


@dataclass(frozen=True)
class AimCandidate:
    number: int      # 全域流水編號（跨層跨方位，1 起）
    layer: str       # "mid"/"up"/"down"
    dir_idx: int     # 0-7（sweep 方位＝相對挖礦原視角的淨右轉數）
    pos: tuple       # (cx, cy) 拍攝當時的螢幕座標（位置先驗，非實彈座標）
    score: float     # 排序鍵（edge 優先；無 edge 用 colored-1.0 墊底排 edge 後）
    reason: str      # find_tracker 被拒原因（診斷顯示）


@dataclass
class SweepShot:
    layer: str
    dir_idx: int
    snapshot_path: str
    rejects: list    # vision.find_tracker collect_rejects 的 dict list


@dataclass
class AimContext:
    candidates: list          # [AimCandidate] 依 score 降冪、編號 1..n
    shots: list               # [SweepShot]
    pose_net_rotations: int   # giveup 收尾後的實際淨旋轉（絕對姿態；restore 過＝0）
    pose_pitch_layer: str     # giveup 收尾後俯仰層（歸位過＝"mid"）
    harvest_id: str
    created_at: float


def _rank_key(rej: dict) -> float:
    """排序鍵：有 edge 用 edge；無 edge（margin/exclude/preexist）用 colored-1.0
    墊底——形狀有分數的候選比純 HSV 近失更可信，一律排前面。"""
    if rej.get("edge") is not None:
        return float(rej["edge"])
    return float(rej.get("colored", 0.0)) - 1.0


def build_aim_context(shots, pose_net_rotations: int, pose_pitch_layer: str,
                      harvest_id: str, now: float, max_candidates: int = 9) -> AimContext:
    """把各 (層,方位) 的近失候選攤平、依分數降冪編號 1..n（上限 max_candidates 防洗版）。"""
    flat = []
    for s in shots:
        for r in s.rejects or []:
            flat.append((_rank_key(r), s.layer, s.dir_idx, r))
    flat.sort(key=lambda t: t[0], reverse=True)
    cands = [AimCandidate(number=i + 1, layer=layer, dir_idx=d,
                          pos=tuple(r["pos"]), score=key, reason=r["reason"])
             for i, (key, layer, d, r) in enumerate(flat[:max_candidates])]
    return AimContext(candidates=cands, shots=list(shots),
                      pose_net_rotations=pose_net_rotations,
                      pose_pitch_layer=pose_pitch_layer,
                      harvest_id=harvest_id, created_at=now)


def grid_cell_center(cell: str, w: int = 1920, h: int = 1080,
                     cols: int = 6, rows: int = 4):
    """網格代碼（如 "C3"）→ 格中心螢幕座標；不合法回 None。"""
    cell = (cell or "").strip().upper()
    if len(cell) != 2 or cell[0] not in GRID_COLS[:cols] or cell[1] not in GRID_ROWS[:rows]:
        return None
    ci = GRID_COLS.index(cell[0])
    ri = GRID_ROWS.index(cell[1])
    cw, ch = w // cols, h // rows
    return (ci * cw + cw // 2, ri * ch + ch // 2)


def draw_overlay(frame_bgr, candidates, grid: bool = True):
    """把候選框編號＋淡色網格疊到快照上（純函式，copy 後畫、不改輸入）。

    延遲 import cv2/np：解析/座標函式在無 OpenCV 環境也可測。
    """
    import cv2
    out = frame_bgr.copy()
    h, w = out.shape[:2]
    if grid:
        cols, rows = len(GRID_COLS), len(GRID_ROWS)
        cw, ch = w // cols, h // rows
        for i in range(1, cols):
            cv2.line(out, (i * cw, 0), (i * cw, h), (90, 90, 90), 1)
        for j in range(1, rows):
            cv2.line(out, (0, j * ch), (w, j * ch), (90, 90, 90), 1)
        for i in range(cols):
            for j in range(rows):
                cv2.putText(out, f"{GRID_COLS[i]}{GRID_ROWS[j]}",
                            (i * cw + 6, j * ch + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 140, 140), 1)
    for c in candidates:
        x, y = c.pos
        cv2.rectangle(out, (x - 36, y - 36), (x + 36, y + 36), (0, 215, 255), 3)
        cv2.putText(out, str(c.number), (x - 30, y - 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 215, 255), 3)
    return out
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_remote_aim.py -q -k "AimContext or Grid or Overlay"`
Expected: PASS（parse_reply 的 import 先留著會 ImportError——把 import 行拆開或先加 `def parse_reply(*a, **k): raise NotImplementedError`；Task B1 實作）
→ 更乾淨的做法：Step 1 測試檔先只 import 本 Task 的名字，B1 再加 parse_reply import。

- [ ] **Step 5: Commit 訊息建議**（人工審後）`feat(remote-aim): 近失候選外露＋編號表/網格/疊圖純函式`

---

### Task A3: Bot——sweep 記錄＋giveup 發圖＋context 生命週期

**Files:**
- Modify: `miningbot/main.py`（`_sweep_for_tracker`、`_find_tracker` 呼叫、`_harvest_giveup`、`_on_enter`）
- Modify: `miningbot/config.py`

純 I/O 接線；完成標準＝全套測試綠。

**Interfaces:**
- Consumes: A1 `collect_rejects`、A2 全部
- Produces: `Bot._aim_context: AimContext | None`、`Bot._sweep_shots: list[SweepShot]`（episode 級）；config `remote_aim_enabled: bool = True`、`remote_aim_max_candidates: int = 9`

- [ ] **Step 1: config 加鍵**（`sweep_pitch_*` 區塊後）

```python
    # --- Discord 遠端瞄準（2026-07-11 spec：giveup 附近失候選編號圖，回訊息即指揮）---
    remote_aim_enabled: bool = True             # 關掉＝giveup 附圖/回覆解析全部回到今天行為
    remote_aim_max_candidates: int = 9          # 附圖候選編號上限（防洗版）
```

- [ ] **Step 2: sweep 記錄近失候選**

`_sweep_for_tracker` 內：
- 迴圈前 `sweep_rejects_by_dir = {}`。
- 第一次偵測（`r1 = self._find_tracker(f, ...)`）改為先建 `rejs = [] if cfg.remote_aim_enabled else None`，把 `collect_rejects=rejs` 傳進 `self._find_tracker`（`_find_tracker` wrapper 需原樣轉傳 `collect_rejects` 給 `vision.find_tracker`——查 wrapper 簽名照樣式加 passthrough 參數）；`sweep_rejects_by_dir[i] = rejs or []`。第二幀（穩定確認）不收集。
- 全空落盤處（`for di, fr in sweep_frames:`）現在 `_hsnap` 回傳路徑：改成收集 `self._sweep_shots.append(remote_aim.SweepShot(layer=self.harvest.pitch_layer, dir_idx=di, snapshot_path=path or "", rejects=sweep_rejects_by_dir.get(di, [])))`（`path = self._hsnap(...)`）。
- `self._sweep_shots` 在 `_on_enter(HARVESTING)` 建 HarvestState 處重置為 `[]`（episode 級，跨層/跨 RESWEEP 累積）。
- 檔頂 `from . import remote_aim`。

- [ ] **Step 3: giveup 建 context＋發圖**

`_harvest_giveup` 中、`self.state = State.NEEDS_HUMAN` 之前：

```python
        # 遠端瞄準 context（2026-07-11 spec）：記「giveup 收尾後」的絕對姿態——
        # restore_view 路徑歸位完 net=0/mid；face_tracker 路徑保持面對框（net/層照舊）
        self._aim_context = None
        if cfg.remote_aim_enabled and self._sweep_shots:
            ctx = remote_aim.build_aim_context(
                self._sweep_shots, self.harvest.net_rotations,
                self.harvest.pitch_layer, self.harvest.harvest_id,
                now=time.time(), max_candidates=cfg.remote_aim_max_candidates)
            self._aim_context = ctx
            aim_paths = self._render_aim_shots(ctx)      # 疊圖＋落盤，回 [(caption, path)]
            if aim_paths:
                groups.insert(0, ("aim", [p for _, p in aim_paths[:4]]))
```

（`groups` 是既有 image_groups 組裝變數；`_REGION_CAPTIONS` 樣式的群標題加一個 `"aim": "🎯 近失候選（回編號射擊，如 `2`；或 `方位 格子` 如 `5 C3`；`跳過` 回挖礦）"`——照既有 caption 常數的定義處加。）

新 helper（放 `_harvest_giveup` 附近）：

```python
    def _render_aim_shots(self, ctx):
        """把有候選的 SweepShot 疊圖（候選編號＋網格）另存 trace/，回 [(caption, path)]。

        只發「有候選的方位」防洗版（spec）；讀快照→疊圖→寫檔都在 giveup 當下同步做
        （一次性、非熱路徑）。讀檔失敗跳過該張（快照是非同步寫檔，極端下可能還沒落盤）。
        """
        import cv2
        out = []
        by_shot = {}
        for c in ctx.candidates:
            by_shot.setdefault((c.layer, c.dir_idx), []).append(c)
        for shot in ctx.shots:
            key = (shot.layer, shot.dir_idx)
            if key not in by_shot or not shot.snapshot_path:
                continue
            img = cv2.imread(shot.snapshot_path)
            if img is None:
                continue
            overlaid = remote_aim.draw_overlay(img, by_shot[key], grid=True)
            path = shot.snapshot_path.replace(".png", "_aim.png")
            cv2.imwrite(path, overlaid)
            out.append((f"方位{shot.dir_idx}（層 {shot.layer}）", path))
        # 依「該方位最高分候選」排序，最像框的方位先發
        best = {k: max(c.score for c in v) for k, v in by_shot.items()}
        out.sort(key=lambda cp: -best.get(
            next(((s.layer, s.dir_idx) for s in ctx.shots
                  if f"方位{s.dir_idx}（層 {s.layer}）" == cp[0]), None), -9))
        return out
```

（排序那段若嫌繞，收集時直接帶 key 一起排——實作自行選較乾淨寫法，行為＝「候選最高分的方位排前、最多 4 張」。）

- [ ] **Step 4: context 作廢時機**

`_on_enter` 的 `State.MINING` 分支、`State.RESET_WAIT` 分支、與 HARVESTING 建 HarvestState 處：`self._aim_context = None`。`__init__` 初始化 `self._aim_context = None`、`self._sweep_shots = []`。

- [ ] **Step 5: 全套測試＋跑 `python -m pytest -q` 全綠**

---

## Phase B：回覆解析＋執行

### Task B1: `parse_reply` 回覆解析

**Files:**
- Modify: `miningbot/remote_aim.py`
- Test: `tests/test_remote_aim.py`

**Interfaces:**
- Produces: `AimReply(kind, number=0, dir_idx=0, layer="mid", cell="")`（frozen dataclass；kind ∈ `"candidate"`/`"grid"`/`"skip"`/`"all"`）；`parse_reply(text, num_candidates, layers_available=("mid",)) -> AimReply | None`

- [ ] **Step 1: 失敗測試**

```python
class TestParseReply:
    def test_candidate_number(self):
        r = parse_reply("2", 3)
        assert r.kind == "candidate" and r.number == 2

    def test_candidate_out_of_range(self):
        assert parse_reply("4", 3) is None
        assert parse_reply("0", 3) is None

    def test_grid_default_layer(self):
        r = parse_reply("5 C3", 0)
        assert (r.kind, r.dir_idx, r.layer, r.cell) == ("grid", 5, "mid", "C3")

    def test_grid_pitch_layers(self):
        r = parse_reply("5U c3", 0, layers_available=("mid", "up", "down"))
        assert (r.kind, r.dir_idx, r.layer, r.cell) == ("grid", 5, "up", "C3")
        r = parse_reply("0d A1", 0, layers_available=("mid", "up", "down"))
        assert (r.kind, r.dir_idx, r.layer) == ("grid", 0, "down")

    def test_grid_layer_unavailable(self):
        # 俯仰掃描未啟用（layers 只有 mid）→ U/D 不合法
        assert parse_reply("5U C3", 0, layers_available=("mid",)) is None

    def test_grid_invalid(self):
        assert parse_reply("8 C3", 0) is None       # 方位只有 0-7
        assert parse_reply("5 G1", 0) is None       # 格子不合法
        assert parse_reply("5", 0) is None           # 單數字但零候選

    def test_skip_and_all(self):
        assert parse_reply("跳過", 3).kind == "skip"
        assert parse_reply("SKIP", 3).kind == "skip"
        assert parse_reply("全部", 3).kind == "all"

    def test_fullwidth_space_and_noise(self):
        r = parse_reply("　5　C3　", 0)               # 全形空白
        assert r is not None and r.kind == "grid"
        assert parse_reply("哈哈這是聊天", 3) is None
        assert parse_reply("", 3) is None
```

- [ ] **Step 2: 跑紅** Run: `python -m pytest tests/test_remote_aim.py -q -k ParseReply` → FAIL

- [ ] **Step 3: 實作**

```python
@dataclass(frozen=True)
class AimReply:
    kind: str        # "candidate" / "grid" / "skip" / "all"
    number: int = 0
    dir_idx: int = 0
    layer: str = "mid"
    cell: str = ""


_LAYER_SUFFIX = {"U": "up", "D": "down"}


def parse_reply(text: str, num_candidates: int,
                layers_available=("mid",)):
    """NEEDS_HUMAN 待命時的一般訊息解析（無前綴；寧可不射不誤射，解析不出回 None）。

    - "2" → 候選編號（1..num_candidates 內才收）
    - "5 C3" / "5U C3" / "5d c3" → 網格（方位 0-7；U/D 需該層存在 layers_available）
    - "跳過"/"skip" → skip；"全部" → all（補發其餘方位快照）
    """
    t = (text or "").replace("　", " ").strip()
    if not t:
        return None
    low = t.lower()
    if low in ("skip", "跳過"):
        return AimReply("skip")
    if low in ("all", "全部"):
        return AimReply("all")
    parts = t.split()
    if len(parts) == 1 and parts[0].isdigit():
        n = int(parts[0])
        if 1 <= n <= num_candidates:
            return AimReply("candidate", number=n)
        return None
    if len(parts) == 2:
        m = re.fullmatch(r"([0-7])([UuDd]?)", parts[0])
        if not m:
            return None
        layer = _LAYER_SUFFIX.get(m.group(2).upper(), "mid") if m.group(2) else "mid"
        if layer not in layers_available:
            return None
        cell = parts[1].upper()
        if grid_cell_center(cell) is None:
            return None
        return AimReply("grid", dir_idx=int(m.group(1)), layer=layer, cell=cell)
    return None
```

- [ ] **Step 4: 跑綠** Run: `python -m pytest tests/test_remote_aim.py -q` → 全 PASS

---

### Task B2: 對齊計畫純函式

**Files:**
- Modify: `miningbot/remote_aim.py`
- Test: `tests/test_remote_aim.py`

**Interfaces:**
- Consumes: `harvester.plan_return_rotations(from_dir, to_dir, dirs=8)`（既有）
- Produces: `plan_alignment(cur_net_rotations, cur_layer, tgt_dir, tgt_layer) -> (rot_steps, pitch_change)`；`rot_steps`＝帶號最短步數（正=右轉）；`pitch_change`＝`None`（同層免動）或 `tgt_layer`（需 pitch_reset→nudge 到該層；含 tgt="mid" 時的純歸位）

- [ ] **Step 1: 失敗測試**

```python
from miningbot.remote_aim import plan_alignment

class TestPlanAlignment:
    def test_restored_pose_to_dir5(self):
        # giveup 已歸位（net=0, mid）→ 目標方位 5：最短路徑左轉 3（5-0=5 → -3）
        assert plan_alignment(0, "mid", 5, "mid") == (-3, None)

    def test_face_tracker_pose_same_dir(self):
        # face_tracker giveup 停在 dir3（net=3）→ 目標同方位：不轉
        assert plan_alignment(3, "mid", 3, "mid") == (0, None)

    def test_wrapped_net_rotations(self):
        # net=9（sweep 轉了超過一圈）≡ dir1 → 目標 0：左轉 1
        assert plan_alignment(9, "mid", 0, "mid") == (-1, None)

    def test_layer_change(self):
        steps, pitch = plan_alignment(0, "mid", 2, "up")
        assert steps == 2 and pitch == "up"

    def test_back_to_mid_from_up(self):
        # 目前在 up 層、目標 mid 層 → pitch_change="mid"（純歸位）
        assert plan_alignment(0, "up", 0, "mid") == (0, "mid")

    def test_same_layer_no_pitch(self):
        assert plan_alignment(0, "up", 0, "up") == (0, None)
```

- [ ] **Step 2: 跑紅** → FAIL

- [ ] **Step 3: 實作**

```python
def plan_alignment(cur_net_rotations: int, cur_layer: str,
                   tgt_dir: int, tgt_layer: str):
    """目前絕對姿態 →（目標方位, 目標層）的對齊計畫（純函式）。

    方位＝相對挖礦原視角的淨右轉數 mod 8（sweep dir 與 net_rotations 同一座標系）。
    回 (帶號最短旋轉步數, None|目標層)。層不同才動俯仰（Bot 端一律 pitch_reset→nudge，
    "mid" 層 nudge=0＝純歸位）。
    """
    from .harvester import plan_return_rotations
    steps = plan_return_rotations(cur_net_rotations % 8, tgt_dir % 8)
    pitch = None if cur_layer == tgt_layer else tgt_layer
    return steps, pitch
```

- [ ] **Step 4: 跑綠**

---

### Task B3: Bot 接線——輪詢分支、pending 消費、fire 執行

**Files:**
- Modify: `miningbot/main.py`（`_poll_discord`、`_tick`、新方法群）
- Modify: `miningbot/config.py`

**Interfaces:**
- Consumes: A3 `_aim_context`、B1 `parse_reply`/`AimReply`、B2 `plan_alignment`；既有 `_rotate_verified`、`_pitch_drag_verified`、`ic.pitch_reset/pitch_nudge`、`harvester.prepare_scan/execute_scan`、`vision.find_tracker_near`、`_verify_chat_ocr`、`ocr.ChatLedger`、`_harvest_boost_guard`、`_mine_resetting`、`miner.init_mining_sequence`
- Produces: `Bot._pending_aim: AimReply | None`（輪詢執行緒寫、主迴圈讀清）、`Bot._aim_busy: bool`

- [ ] **Step 1: config 加鍵**

```python
    remote_aim_refind_radius_px: int = 160      # fire 前重找 ROI 半徑（同 shape_roi 半徑量級）
    remote_aim_budget_s: float = 120.0          # 單次 fire 全流程預算（對齊+重掃+驗證）
```

- [ ] **Step 2: `_poll_discord` 加 aim 分支**（`if first.lstrip("!") in _DISCORD_COMMANDS:` 之後）

```python
            if first.lstrip("!") in _DISCORD_COMMANDS:
                self._handle_discord_command(content)
            elif self._aim_context is not None and self.state is State.NEEDS_HUMAN:
                self._handle_aim_reply(content)
```

新方法（放 `_handle_discord_command` 附近；**此方法只做解析/回覆/寫 pending，絕不碰 input_control**——輸入由主迴圈消費，比照 `_sampler_want`）：

```python
    def _handle_aim_reply(self, content: str):
        """NEEDS_HUMAN＋aim context 存活時，一般訊息當瞄準回覆解析（無前綴，2026-07-11 spec）。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ctx = self._aim_context
        layers = ("mid", "up", "down") if harvester.plan_pitch_layers(
            cfg.sweep_pitch_enabled, cfg.sweep_pitch_step_px,
            cfg.sweep_pitch_center_back_px) else ("mid",)
        reply = remote_aim.parse_reply(content, len(ctx.candidates), layers)
        if reply is None:
            notify.send_message(token, ch,
                "❓ 看不懂。可用：`2`（射候選②）、`5 C3` / `5U C3`（方位+格子）、"
                "`跳過`（回挖礦）、`全部`（補發其餘方位圖）")
            return
        if self._aim_busy:
            notify.send_message(token, ch, "⏳ 上一發還在執行，稍候")
            return
        if reply.kind == "all":
            sent = 0
            for s in ctx.shots:
                if s.snapshot_path and sent < 8:
                    notify.send_images_message(token, ch,
                        f"方位{s.dir_idx}（層 {s.layer}）", [s.snapshot_path])
                    sent += 1
            self.log_discord.info("AIM all -> 補發 %d 張", sent)
            return
        self._pending_aim = reply          # skip/candidate/grid：主迴圈消費
        notify.send_message(token, ch, f"✅ 收到（{reply.kind}），主迴圈執行中…")
        self.log_discord.info("AIM reply=%s -> pending", reply)
```

- [ ] **Step 3: `_tick` 加 NEEDS_HUMAN 分支**（`_tick` 的狀態分派處）

```python
        elif self.state is State.NEEDS_HUMAN and self._pending_aim is not None:
            reply, self._pending_aim = self._pending_aim, None
            self._tick_remote_aim(frame, reply)
```

- [ ] **Step 4: fire 執行主體**（新方法群，放 `_harvest_giveup` 之後）

```python
    def _tick_remote_aim(self, frame, reply):
        """消費一則瞄準回覆（主迴圈執行緒）。skip→回挖礦；candidate/grid→對齊+重掃+開火+驗證。

        一發＝一次 D3＋一個 verify 窗口，不自動 RETRY/RESWEEP（spec：要不要再射由使用者決定，
        每次回報附最新截圖）。全程 remote_aim_budget_s 預算防卡死。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ctx = self._aim_context
        if reply.kind == "skip":
            self.logger.info("AIM skip -> 回挖礦")
            self._aim_context = None
            self.human_cleared = True          # 下 tick decide_transition 回 MINING（同 resume）
            notify.send_message(token, ch, "▶️ 跳過這顆，回挖礦")
            return
        # 解目標 (層, 方位, 位置先驗)
        if reply.kind == "candidate":
            c = ctx.candidates[reply.number - 1]
            tgt_layer, tgt_dir, prior = c.layer, c.dir_idx, c.pos
        else:
            tgt_layer, tgt_dir = reply.layer, reply.dir_idx
            prior = remote_aim.grid_cell_center(reply.cell)
        self._aim_busy = True
        try:
            ok, detail = self._execute_remote_fire(ctx, tgt_layer, tgt_dir, prior)
        finally:
            self._aim_busy = False
        if ok:
            self._aim_context = None           # 成功收尾（_execute 內已切 MINING）
        else:
            # 失敗：留在 NEEDS_HUMAN、context 續命，附當下截圖讓使用者再決定
            cur = capture.grab()
            p1 = self._snapshot(cur, "aim_fail_scene")
            p2 = self._snapshot_crop(cur, cfg.chat_review_region, "aim_fail_chat")
            paths = [p for p in (p1, p2) if p]
            msg = f"❌ 未確認命中（{detail}）。可再回編號/格子重試，或 `跳過` 回挖礦"
            if paths:
                notify.send_images_message(token, ch, msg, paths)
            else:
                notify.send_message(token, ch, msg)

    def _execute_remote_fire(self, ctx, tgt_layer, tgt_dir, prior):
        """對齊姿態 → 重新 D2 掃描 → ROI 放寬重找 → 開火 → 聊天驗證。回 (confirmed, 說明)。"""
        from . import notify
        deadline = time.time() + cfg.remote_aim_budget_s
        hid = ctx.harvest_id
        if not self._focus_roblox():
            return False, "無法聚焦 Roblox"
        if self._mine_resetting:
            return False, "礦坑重置中"
        # 1. 對齊：yaw（驗證式）＋俯仰層（reset→nudge，同 pitch-sweep 慣例）
        steps, pitch = remote_aim.plan_alignment(
            ctx.pose_net_rotations, ctx.pose_pitch_layer, tgt_dir, tgt_layer)
        self.logger.info("[%s] AIM 對齊：rot=%+d pitch=%s（目標 dir=%d layer=%s）",
                         hid, steps, pitch, tgt_dir, tgt_layer)
        done = 0
        for _ in range(abs(steps)):
            if self._rotate_verified(1 if steps > 0 else -1):
                done += 1 if steps > 0 else -1
        ctx.pose_net_rotations += done         # 姿態記帳＝實際轉動（被吃不計）
        if done != steps:
            return False, f"轉向被吃（{done}/{steps}），姿態已記帳，可重試"
        if pitch is not None:
            nudge = {"up": -cfg.sweep_pitch_step_px, "down": cfg.sweep_pitch_step_px,
                     "mid": 0}[pitch]
            ok = self._pitch_drag_verified(
                f"[{hid}] AIM 俯仰歸位",
                lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                       cfg.sweep_pitch_center_back_px))
            if ok and nudge:
                ok = self._pitch_drag_verified(
                    f"[{hid}] AIM nudge {nudge}px", lambda: ic.pitch_nudge(nudge))
            if not ok:
                ctx.pose_pitch_layer = "mid"   # reset 至少跑過，保守記歸位
                return False, "俯仰對齊被吃，可重試"
            ctx.pose_pitch_layer = pitch if pitch != "mid" else "mid"
        # 2. 重新 D2 掃描（框早已到期；新 episode 語意，重拍 ref 正確——非 H026 情境）
        chat_base_crop = capture.crop(capture.grab(), cfg.chat_region)   # 開火前基準（截圖先、OCR 後）
        harvester.prepare_scan()
        gf = capture.grab()
        if self._harvest_boost_guard(gf):
            gf = capture.grab()
        ref = gf
        harvester.execute_scan()
        self._confirm_scan("remote-aim")
        # 3. ROI 放寬重找：先正常門檻，再 shape_threshold=0（colored 過即收、edge 排序）
        pos = None
        for thr in (cfg.tracker_shape_threshold, 0.0):
            if time.time() > deadline:
                return False, "預算用盡"
            f2 = capture.grab()
            pos = vision.find_tracker_near(
                f2, prior, cfg.remote_aim_refind_radius_px,
                frame_margin_frac=0.0, exclude=self._chat_exclude(),
                reference_bgr=ref, shape_templates=self._shape_templates,
                shape_threshold=thr, shape_hard_floor=0.0,
                shape_scales=cfg.tracker_shape_scales,
                shape_roi_px=cfg.tracker_shape_roi_px)
            if pos:
                self.logger.info("[%s] AIM 重找命中 (thr=%.2f) -> %s", hid, thr, pos)
                break
        if not pos:
            pos = prior                        # 4c. 直接朝先驗點開火（miss 代價＝一發）
            self.logger.info("[%s] AIM 重找全滅 -> 直接朝先驗點開火 %s", hid, pos)
        # 4. 開火（既有 D3 序列）
        self._hsnap(capture.grab(), "aim_fire_%dx%d" % tuple(pos[:2]))
        ic.key_press("2"); time.sleep(0.15)
        ic.key_press("3"); time.sleep(0.3)
        ic.click_at(int(pos[0]), int(pos[1]), hold=0.4)
        time.sleep(0.5)
        # 5. 驗證：基準 OCR（開火後才跑）＋窗口輪詢（幀差閘）＋最終確認
        common = game_data.common_ore_names()
        rare_names = game_data.rare_ore_names()
        chat_before = ocr.read_text_multi(chat_base_crop, cfg.tesseract_path)
        last_crop = chat_base_crop
        fired_at = time.time()
        while time.time() - fired_at < cfg.harvest_verify_window_s:
            if time.time() > deadline:
                break
            time.sleep(0.5)
            cur = capture.crop(capture.grab(), cfg.chat_region)
            if vision.frames_differ(last_crop, cur, cfg.chat_diff_threshold):
                chat_after, confirmed, special = self._verify_chat_ocr(
                    cur, chat_before, common, rare_names, hid, "remote-aim")
                last_crop = cur
                if confirmed:
                    self._remote_fire_success(ctx, hid)
                    return True, "confirmed"
        # 窗口到期最終確認（H020 慣例）
        cur = capture.crop(capture.grab(), cfg.chat_region)
        _, confirmed, _ = self._verify_chat_ocr(
            cur, chat_before, common, rare_names, hid, "remote-aim-final")
        if confirmed:
            self._remote_fire_success(ctx, hid)
            return True, "confirmed(final)"
        return False, "verify 窗口內聊天未確認"

    def _remote_fire_success(self, ctx, hid):
        """遠端開火確認成功：通知＋視角歸位＋回挖礦。"""
        from . import notify
        notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id,
                            f"🎉 [{hid}] 遠端瞄準採集成功！視角歸位、回挖礦")
        self.logger.info("[%s] AIM 採集成功 -> 歸位回 MINING", hid)
        if cfg.sweep_pitch_center_back_px > 0:   # 俯仰未校準（=0）絕不動；歸位冪等、多做無害
            self._pitch_drag_verified(
                f"[{hid}] AIM 收尾俯仰歸位",
                lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                       cfg.sweep_pitch_center_back_px))
        harvester.restore_view(ctx.pose_net_rotations, rotate=self._rotate_verified)
        self.state = State.MINING
        self._on_enter(State.MINING, capture.grab())
```

實作註記（opencode 必讀）：
- `self._chat_exclude()`：main.py 既有聊天區排除清單的組法（`_tick_harvest` 內 `_excl = [(_cr.x, ...)]`）——若無現成 helper 就抄該行內聯，勿發明新格式。
- `_verify_chat_ocr` 簽名照既有（crop, chat_before, common, rare_names, hid, why）。
- `cfg.chat_diff_threshold`／`chat_review_region` 名稱以 config.py 現況為準（找 `_tick_harvest` verify 輪詢用的同名鍵照用；名稱不同就用實際名稱）。
- `State.MINING` 切換照 `_harvest_resume_mining` 的既有模式（含 `init_mining_sequence`）——直接研究該方法，能共用就共用（例如把 `_remote_fire_success` 的歸位+回礦改為呼叫共用 helper），不要複製貼上兩份維護。
- `__init__` 初始化 `self._pending_aim = None`、`self._aim_busy = False`。

- [ ] **Step 5: 全套測試** Run: `python -m pytest -q` → 全綠

---

### Task B4: 實機端到端（Claude＋使用者，不委派 opencode）

- [ ] 人為造一次全空 giveup（暫調高 shape_threshold 或遮擋）→ 確認 Discord 收到候選編號疊圖＋網格
- [ ] 手機回 `2` → 確認轉向/重掃/開火/驗證/回報全鏈路；回 `5 C3` 網格路徑同測
- [ ] 回 `跳過` → 回挖礦；亂打字 → 只回格式提示不動作；fire 執行中再回 → 「稍候」
- [ ] 礦坑重置中回編號 → 回報「礦坑重置中」不白射
- [ ] 文件補記（CLAUDE.md 採集流程段＋docs/HANDOFF.md）＋commit

## Self-Review 紀錄

- Spec 覆蓋：近失候選外露（A1）、編號＋網格疊圖與「只發有候選的方位、`全部` 補發」（A2/A3/B3 Step 2）、無前綴解析與全案例拒收（B1）、絕對姿態記錄與兩條 giveup 路徑（A3 Step 3 在收尾後記 net/層——restore 路徑歸位完自然是 0/mid）、一律重掃＋放寬 ROI＋先驗點兜底（B3 步驟 3-4c）、一發一窗口不自動重試（B3）、重置守門與 busy 拒收（B3）、context 作廢（A3 Step 4）——全數有任務對應。
- 已知簡化（記錄於此、實機驗證時盯）：verify 用單一 `read_text_multi` 基準＋`_verify_chat_ocr` 輪詢，未接 ChatLedger 鏈式帳本（遠端 fire 為全新 episode、間隔長，晚到窗口風險低；若實機出現晚到假陰性再接帳本）。
- 型別一致性：`AimCandidate.pos`/`SweepShot.rejects`（A1 dict 格式）/`plan_alignment` 回傳 tuple／`AimReply` 欄位——B3 用名與 A2/B1/B2 定義一致。`find_tracker_near` 的參數名（`frame_margin_frac`）與 vision.py:448 現況一致。
