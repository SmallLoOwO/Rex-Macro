# Discord 遠端回礦（Remote Re-entry）實作計畫

> **For agentic workers:** 本 repo 慣例：程式實作委派 opencode（`opencode run`，GLM 無視覺、勿讀圖）；本計畫即 opencode 規格書的本體。分兩梯次委派：Phase R1（Task 1-3，純邏輯，全部可離線測試）先跑並人工審核，Phase R2（Task 4-5，Bot 接線）再跑。Phase R3（Task 6）＝Claude＋使用者實機校準與端到端。Steps 用 checkbox 追蹤。

**Goal:** 礦坑重置後 bot 傳地表、歸位角度、發八方位截圖到 Discord，使用者回訊息兩段式指位（粗格→數位放大細格），bot 點擊傳送、驗證、回挖礦；每輪互動落盤成未來自動化的 ground truth。

**Architecture:** 指令解析／格↔座標換算／疊圖／ledger 建構全在新純邏輯模組 `miningbot/reentry_remote.py`（TDD）；網格繪製與格中心換算從 `remote_aim.py` 通用化共用（既有 remote-aim 測試全數不變）。Bot 層：`reentry_mode` 三態 config、`_tick_reentry` 開頭分流 remote 分支、Discord 輪詢執行緒只寫單一 pending（比照 `_pending_aim`）、輸入全在主迴圈消費。

**Tech Stack:** Python、pytest、OpenCV、Discord Bot API（經 `notify`）。

**Spec:** `docs/superpowers/specs/2026-07-12-remote-reentry-design.md`（改動前先讀）

## Global Constraints

- TDD：先寫失敗測試再實作；完成標準 `python -m pytest -q` 全綠。
- **opencode 不 commit**（留人工審）；不動 `assets/`、不讀任何圖片。
- **⚠ 開跑前置**：工作區目前有未 commit 的 ability 指令改動（main.py/config.py/states.py/test_states.py）——**先 commit 或 stash 那批**再委派 opencode，否則兩批改動混在同一份 diff 無法分開審。
- 純邏輯進 `miningbot/reentry_remote.py`＋`tests/test_reentry_remote.py`；`remote_aim.py` 只做向後相容的通用化（全部既有 `tests/test_remote_aim.py` 必須原樣通過）；I/O 只進 `miningbot/main.py`。
- 解析不出的訊息一律不動作、只回格式提示（寧可不點不誤點）；`!` 前綴與既有命令行為完全不動；harvest 的 aim context 分派優先序不變。
- 執行緒安全：Discord 輪詢執行緒只寫 `self._pending_reentry` 單一欄位，**絕不碰 input_control 與 ledger 檔案**——全部由主迴圈消費（比照 `_pending_aim`／`_sampler_want`）。
- 座標系：全幀 1920×1080；粗網格 6×4（格 320×270、欄 A-F 列 1-4）；細網格 6×6（欄 A-F 列 1-6，映射回原幀一格 ≈53×45px）。
- ledger 為 **append-only JSONL**（作廢＝追加 void 記錄，不回頭改舊行——留審計軌跡）。

---

## Phase R1：純邏輯（opencode 梯次 1）

### Task 1: config 三態 `reentry_mode` 遷移＋Bot gating helpers

**Files:**
- Modify: `miningbot/config.py`（`auto_reenter` 一帶，line ~199）
- Modify: `miningbot/main.py`（`_auto_reenter_active`、`_reset_track`、banner worker gate、警告文案）
- Modify: `miningbot/states.py`（Observation 註解）
- Test: `tests/test_states.py`（既有 auto_reenter 測試不改語意）

**Interfaces:**
- Produces: config `reentry_mode: str = "off"`（取代 `auto_reenter: bool`）＋新鍵群 `reentry_remote_*`；`Bot._remote_reenter_active() -> bool`、`Bot._reentry_active() -> bool`。
- `states.Observation.auto_reenter` **欄位名不改**（避免波及面），語意更新為「任一回礦模式啟用」——Bot 端改傳 `self._reentry_active()`。

- [ ] **Step 1: config 改鍵**

刪 `auto_reenter: bool = False`，原位置換成：

```python
    reentry_mode: str = "off"                   # "off"=RESET_WAIT 等人工（今日行為）/"remote"=Discord 指位（2026-07-12 spec）/"auto"=全自動（2026-07-08 spec，面板模板校準完成前勿開）
```

`remote_aim_*` 區塊後加：

```python
    # --- Discord 遠端回礦（2026-07-12 spec：重置後發八方位圖，回訊息兩段式指位點傳送面板）---
    reentry_remote_fine_cols: int = 6           # 細網格欄數（放大圖上）
    reentry_remote_fine_rows: int = 6           # 細網格列數；6×6 映射回原幀一格 ≈53×45px（±27px）
    reentry_remote_zoom_scale: int = 3          # 粗格 320×270 → 放大 960×810 再疊細網格
    reentry_remote_drift_diff: float = 12.0     # 點擊前漂移守門：粗格區域幀平均差 ≥ 此值 → 不點、重發放大圖（H026 家族）
    reentry_remote_auto_resume: bool = False    # True=幀差+礦內亮度雙過即自動開挖；False=一律等「好」放行（亮度簽名校準前的安全預設）
    reentry_remote_ledger: str = "logs/reentry_remote/ledger.jsonl"   # append-only ground-truth 帳本
```

- [ ] **Step 2: main.py gating**

- `_auto_reenter_active`（main.py:301）改：

```python
    def _auto_reenter_active(self) -> bool:
        """auto 模式的有效值：mode=auto＋面板模板存在（缺模板視同關閉）。"""
        return cfg.reentry_mode == "auto" and bool(self._panel_templates)

    def _remote_reenter_active(self) -> bool:
        """remote 模式的有效值：mode=remote＋「回到地表」按鈕座標已校準（(0,0)=未校準視同關閉）。"""
        return cfg.reentry_mode == "remote" and tuple(cfg.reentry_surface_button_xy) != (0, 0)

    def _reentry_active(self) -> bool:
        """任一回礦模式啟用（REENTRY 觸發條件；傳 Observation.auto_reenter）。"""
        return self._auto_reenter_active() or self._remote_reenter_active()
```

- 全域搜 `_auto_reenter_active()` 呼叫點逐一判斷：**觸發/等待類**（`_reset_track` main.py:613、banner worker gate main.py:~700、`_maybe_observe` 建 Observation 傳 `auto_reenter=` 處 main.py:~600）改用 `_reentry_active()`；**auto 專屬**（模板缺失警告 main.py:296、`_on_enter(MINING)` 的 movement 檢查 main.py:~1890 與 RESET_WAIT 進場 main.py:~2016 的 `_movement_check_due`）維持 `_auto_reenter_active()`（remote 模式的 movement mode 走 Task 5 懶啟動，不用開機鏈）。
- `cfg.auto_reenter` 其餘引用全域搜掉（`rg "auto_reenter" miningbot tests` 清零 `cfg.auto_reenter`；`Observation.auto_reenter` 欄位保留）。

- [ ] **Step 3: states.py 只改註解**

```python
    auto_reenter: bool = False     # 任一回礦模式（remote/auto）啟用（Bot._reentry_active()；off＝RESET_WAIT 維持今日等人工行為）
```

- [ ] **Step 4: 跑全套** Run: `python -m pytest -q` → 全綠（test_states 既有案例語意不變）

---

### Task 2: 網格零件通用化＋`reentry_remote.py` 解析/幾何/疊圖

**Files:**
- Modify: `miningbot/remote_aim.py`（`GRID_ROWS` 擴充＋抽 `draw_grid`）
- Create: `miningbot/reentry_remote.py`
- Test: `tests/test_remote_aim.py`（不改既有案例）、`tests/test_reentry_remote.py`（新檔）

**Interfaces:**
- Produces（remote_aim 通用化，向後相容）:
  - `GRID_ROWS = "123456"`（`grid_cell_center` 用 `GRID_ROWS[:rows]` 截取，預設 `rows=4` 行為不變——既有測試 `test_invalid_cells` 的 `"A5"` 在 rows=4 下仍 None）
  - `draw_grid(img, cols, rows) -> None`（in-place 畫半透明格線＋格代碼；從 `draw_overlay` 抽出、`draw_overlay` 改呼叫它）
- Produces（reentry_remote）:
  - `RemoteReply(kind, dir_idx=0, cell="", layer="")`（frozen dataclass；kind ∈ `"coarse"/"fine"/"walk"/"sweep"/"reroll"/"skip"/"confirm"/"void"/"layer"`）
  - `parse_reply(text) -> RemoteReply | None`（phase 無關；時機合法性由 Bot 判）
  - `coarse_cell_region(cell, w=1920, h=1080, cols=6, rows=4) -> (x, y, rw, rh) | None`
  - `fine_cell_to_screen(region, cell, cols=6, rows=6) -> (x, y) | None`（region＝粗格原幀區域）
  - `render_zoom(frame_bgr, region, scale=3, cols=6, rows=6) -> ndarray`（裁格→放大→疊細網格；不改輸入）
  - `draw_click_marker(frame_bgr, pos) -> ndarray`（紅圈＋十字標點擊點；不改輸入）

- [ ] **Step 1: 失敗測試**

```python
# tests/test_reentry_remote.py（新檔）
import numpy as np
from miningbot.reentry_remote import (RemoteReply, parse_reply, coarse_cell_region,
                                      fine_cell_to_screen, render_zoom, draw_click_marker)


class TestParseReply:
    def test_coarse(self):
        r = parse_reply("3 C2")
        assert (r.kind, r.dir_idx, r.cell) == ("coarse", 3, "C2")

    def test_coarse_invalid(self):
        assert parse_reply("8 C2") is None       # 方位只有 0-7
        assert parse_reply("3 G2") is None       # 欄超界
        assert parse_reply("3 C5") is None       # 粗網格列只有 1-4

    def test_fine_bare_and_layer_override(self):
        r = parse_reply("B3")
        assert (r.kind, r.cell, r.layer) == ("fine", "B3", "")
        r = parse_reply("b5 Core Layer")          # 細網格列到 6；層名可含空白
        assert (r.kind, r.cell, r.layer) == ("fine", "B5", "Core Layer")

    def test_fine_invalid(self):
        assert parse_reply("B7") is None          # 細網格列只有 1-6
        assert parse_reply("G3") is None

    def test_walk(self):
        r = parse_reply("走 C2")
        assert (r.kind, r.cell) == ("walk", "C2")
        assert parse_reply("walk d4").cell == "D4"
        assert parse_reply("走 C5") is None       # walk 用粗網格（列 1-4）

    def test_keywords(self):
        assert parse_reply("掃").kind == "sweep"
        assert parse_reply("SWEEP").kind == "sweep"
        assert parse_reply("重骰").kind == "reroll"
        assert parse_reply("跳過").kind == "skip"
        assert parse_reply("好").kind == "confirm"
        assert parse_reply("OK").kind == "confirm"
        assert parse_reply("作廢").kind == "void"

    def test_layer_command(self):
        r = parse_reply("層 Mantle Layer")
        assert (r.kind, r.layer) == ("layer", "Mantle Layer")
        assert parse_reply("layer Core Layer").layer == "Core Layer"
        assert parse_reply("層") is None          # 空層名不合法

    def test_noise_and_fullwidth(self):
        assert parse_reply("　3　C2　").kind == "coarse"   # 全形空白
        assert parse_reply("哈哈這是聊天") is None
        assert parse_reply("") is None
        assert parse_reply("3") is None           # 單數字（無 aim 候選語意）


class TestGeometry:
    def test_coarse_cell_region_c3(self):
        # 6×4、1920×1080：格 320×270。C=idx2、3=idx2 → (640, 540, 320, 270)
        assert coarse_cell_region("C3") == (640, 540, 320, 270)

    def test_coarse_cell_region_invalid(self):
        assert coarse_cell_region("C5") is None
        assert coarse_cell_region("G1") is None

    def test_fine_cell_to_screen_center_of_subcell(self):
        region = (640, 540, 320, 270)             # 粗格 C3
        # 細 6×6：子格 53×45（floor）。A1＝region 左上子格中心
        x, y = fine_cell_to_screen(region, "A1")
        assert (x, y) == (640 + 53 // 2 + 0, 540 + 45 // 2 + 0)
        x, y = fine_cell_to_screen(region, "F6")
        assert x == 640 + 5 * (320 // 6) + (320 // 6) // 2
        assert y == 540 + 5 * (270 // 6) + (270 // 6) // 2

    def test_fine_cell_invalid(self):
        assert fine_cell_to_screen((0, 0, 320, 270), "B7") is None


class TestRender:
    def test_render_zoom_shape_and_input_intact(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        out = render_zoom(frame, (640, 540, 320, 270), scale=3)
        assert out.shape == (810, 960, 3)
        assert frame.sum() == 0                   # 輸入不被改
        assert out.sum() > 0                      # 有畫網格

    def test_draw_click_marker(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        out = draw_click_marker(frame, (700, 600))
        assert frame.sum() == 0
        assert out[600, 700 - 30:700 + 30].sum() > 0


def test_remote_aim_grid_rows_backward_compat():
    """GRID_ROWS 擴到 6 列後，remote_aim 預設 rows=4 行為不變。"""
    from miningbot.remote_aim import grid_cell_center
    assert grid_cell_center("A5") is None                 # 預設 rows=4 仍拒
    assert grid_cell_center("A5", rows=6) is not None     # 顯式 rows=6 才收
```

- [ ] **Step 2: 跑紅** Run: `python -m pytest tests/test_reentry_remote.py -q` → FAIL（module 不存在）

- [ ] **Step 3: 實作**

remote_aim.py 兩處：`GRID_ROWS = "1234"` → `"123456"`；`draw_overlay` 的網格段抽成：

```python
def draw_grid(img, cols: int = 6, rows: int = 4) -> None:
    """in-place 疊半透明格線＋格代碼（A1..）。draw_overlay 與 reentry_remote 共用。"""
    import cv2
    h, w = img.shape[:2]
    cw, ch = w // cols, h // rows
    for i in range(1, cols):
        cv2.line(img, (i * cw, 0), (i * cw, h), (90, 90, 90), 1)
    for j in range(1, rows):
        cv2.line(img, (0, j * ch), (w, j * ch), (90, 90, 90), 1)
    for i in range(cols):
        for j in range(rows):
            cv2.putText(img, f"{GRID_COLS[i]}{GRID_ROWS[j]}",
                        (i * cw + 6, j * ch + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 140, 140), 1)
```

（`draw_overlay` 內原網格迴圈刪除、改 `if grid: draw_grid(out, len(GRID_COLS), 4)`——**rows 寫死 4**，維持 aim 疊圖現狀。）

```python
# miningbot/reentry_remote.py
"""Discord 遠端回礦（2026-07-12 spec）：回覆解析／粗細網格座標換算／放大圖與
點擊標記疊圖／ledger 記錄建構——全部純函式，I/O 在 main.Bot。"""
import re
from dataclasses import dataclass, field

from .remote_aim import GRID_COLS, GRID_ROWS, draw_grid, grid_cell_center


@dataclass(frozen=True)
class RemoteReply:
    kind: str        # "coarse"/"fine"/"walk"/"sweep"/"reroll"/"skip"/"confirm"/"void"/"layer"
    dir_idx: int = 0
    cell: str = ""
    layer: str = ""  # layer 指令的新層名；fine 的單次覆寫（空＝無）


_KEYWORDS = {
    "掃": "sweep", "sweep": "sweep",
    "重骰": "reroll", "reroll": "reroll",
    "跳過": "skip", "skip": "skip",
    "好": "confirm", "ok": "confirm",
    "作廢": "void", "void": "void",
}
_FINE_CELL = re.compile(r"^[A-F][1-6]$")


def _valid_coarse(cell: str) -> bool:
    return grid_cell_center(cell) is not None            # 預設 6×4


def parse_reply(text: str):
    """REENTRY 等待時的一般訊息解析（無前綴；寧可不點不誤點，解析不出回 None）。

    phase 無關——`B3` 在「等細格」外收到＝時機不合法，由 Bot 回提示；解析只管語法。
    """
    t = (text or "").replace("　", " ").strip()
    if not t:
        return None
    low = t.lower()
    if low in _KEYWORDS:
        return RemoteReply(_KEYWORDS[low])
    parts = t.split()
    head = parts[0].lower()
    if head in ("層", "layer") and len(parts) >= 2:
        return RemoteReply("layer", layer=" ".join(parts[1:]))
    if head in ("走", "walk") and len(parts) == 2:
        cell = parts[1].upper()
        return RemoteReply("walk", cell=cell) if _valid_coarse(cell) else None
    if len(parts) == 2 and re.fullmatch(r"[0-7]", parts[0]):
        cell = parts[1].upper()
        return RemoteReply("coarse", dir_idx=int(parts[0]), cell=cell) \
            if _valid_coarse(cell) else None
    cell = parts[0].upper()
    if _FINE_CELL.fullmatch(cell):
        return RemoteReply("fine", cell=cell, layer=" ".join(parts[1:]))
    return None


def coarse_cell_region(cell: str, w: int = 1920, h: int = 1080,
                       cols: int = 6, rows: int = 4):
    """粗格代碼 → 原幀裁圖區域 (x, y, rw, rh)；不合法回 None。"""
    cell = (cell or "").strip().upper()
    if len(cell) != 2 or cell[0] not in GRID_COLS[:cols] or cell[1] not in GRID_ROWS[:rows]:
        return None
    cw, ch = w // cols, h // rows
    return (GRID_COLS.index(cell[0]) * cw, GRID_ROWS.index(cell[1]) * ch, cw, ch)


def fine_cell_to_screen(region, cell: str, cols: int = 6, rows: int = 6):
    """細格代碼＋粗格區域 → 絕對螢幕座標（子格中心）；不合法回 None。"""
    cell = (cell or "").strip().upper()
    if len(cell) != 2 or cell[0] not in GRID_COLS[:cols] or cell[1] not in GRID_ROWS[:rows]:
        return None
    x, y, rw, rh = region
    sw, sh = rw // cols, rh // rows
    return (x + GRID_COLS.index(cell[0]) * sw + sw // 2,
            y + GRID_ROWS.index(cell[1]) * sh + sh // 2)


def render_zoom(frame_bgr, region, scale: int = 3, cols: int = 6, rows: int = 6):
    """裁粗格 → 放大 scale 倍 → 疊細網格（純函式，不改輸入）。"""
    import cv2
    x, y, rw, rh = region
    crop = frame_bgr[y:y + rh, x:x + rw]
    out = cv2.resize(crop, (rw * scale, rh * scale), interpolation=cv2.INTER_CUBIC)
    draw_grid(out, cols, rows)
    return out


def draw_click_marker(frame_bgr, pos):
    """紅圈＋十字標出實際點擊座標（回報「沒點歪」核對用；不改輸入）。"""
    import cv2
    out = frame_bgr.copy()
    x, y = int(pos[0]), int(pos[1])
    cv2.circle(out, (x, y), 24, (0, 0, 255), 3)
    cv2.line(out, (x - 36, y), (x + 36, y), (0, 0, 255), 2)
    cv2.line(out, (x, y - 36), (x, y + 36), (0, 0, 255), 2)
    return out
```

- [ ] **Step 4: 跑綠（含既有 remote_aim 全數）** Run: `python -m pytest tests/test_reentry_remote.py tests/test_remote_aim.py -q` → 全 PASS

---

### Task 3: context 與 ledger 建構純函式

**Files:**
- Modify: `miningbot/reentry_remote.py`
- Test: `tests/test_reentry_remote.py`

**Interfaces:**
- Produces:
  - `RemoteReentryContext(episode_id, created_at, sticky_layer, cur_dir=0, phase="awaiting_cmd", attempt=1, zoom_dir=0, zoom_region=(), shots=[], log=[], clicks=[], walked=False)`（dataclass；phase ∈ `"awaiting_cmd"/"awaiting_fine"/"awaiting_confirm"`）
  - `next_episode_id(last_ledger_line: str | None) -> int`（讀 ledger 末行 episode+1；無/壞行回 1）
  - `log_command(ctx, raw, reply, now) -> None`（附掛指令流水：dict{t, raw, kind, pose_dir}）
  - `record_click(ctx, pos, layer, region, now) -> None`（附掛 clicks：dict{t, pos, layer, dir, region, invalid: False}）
  - `ledger_entry(ctx, outcome, world, duration_s) -> dict`（episode 收尾行；outcome ∈ `"success"/"confirmed_by_user"/"skip"/"reset_interrupt"`）
  - `void_entry(episode_id, click_index, now) -> dict`（`{"type": "void", ...}` 作廢追加行）

- [ ] **Step 1: 失敗測試**

```python
import json
from miningbot.reentry_remote import (RemoteReentryContext, next_episode_id,
                                      log_command, record_click, ledger_entry, void_entry)


class TestContextLedger:
    def _ctx(self):
        return RemoteReentryContext(episode_id=17, created_at=100.0,
                                    sticky_layer="Mantle Layer")

    def test_next_episode_id(self):
        assert next_episode_id(None) == 1
        assert next_episode_id('{"episode": 16, "outcome": "success"}') == 17
        assert next_episode_id('{"type": "void", "episode": 16}') == 17
        assert next_episode_id("not json") == 1

    def test_log_and_click_accumulate(self):
        ctx = self._ctx()
        ctx.cur_dir = 3
        log_command(ctx, "3 C2", parse_reply("3 C2"), now=101.0)
        record_click(ctx, (700, 600), "Mantle Layer", (640, 540, 320, 270), now=102.0)
        assert ctx.log[0]["kind"] == "coarse" and ctx.log[0]["pose_dir"] == 3
        assert ctx.clicks[0]["pos"] == (700, 600) and ctx.clicks[0]["invalid"] is False

    def test_ledger_entry_fields(self):
        ctx = self._ctx()
        record_click(ctx, (700, 600), "Core Layer", (640, 540, 320, 270), now=102.0)
        e = ledger_entry(ctx, "success", world="Aesteria", duration_s=88.5)
        assert e["episode"] == 17 and e["outcome"] == "success"
        assert e["world"] == "Aesteria" and e["sticky_layer"] == "Mantle Layer"
        assert e["clicks"][0]["layer"] == "Core Layer"
        json.dumps(e, ensure_ascii=False)         # 必須可序列化

    def test_void_entry(self):
        v = void_entry(17, click_index=0, now=200.0)
        assert v["type"] == "void" and v["episode"] == 17 and v["click_index"] == 0
```

（`parse_reply` import 已在檔頭。）

- [ ] **Step 2: 跑紅** → FAIL

- [ ] **Step 3: 實作**

```python
import json


@dataclass
class RemoteReentryContext:
    episode_id: int
    created_at: float
    sticky_layer: str            # 黏性目標層（層指令改；純使用者宣告、bot 不驗證）
    cur_dir: int = 0             # 目前面向（相對開場 sweep 起始面向的淨右轉 mod 8）
    phase: str = "awaiting_cmd"  # awaiting_cmd / awaiting_fine / awaiting_confirm
    attempt: int = 1             # reroll 次數記帳（human-driven，無上限）
    zoom_dir: int = 0            # 等細格時：目標方位
    zoom_region: tuple = ()      # 等細格時：粗格原幀區域 (x, y, w, h)
    shots: list = field(default_factory=list)    # [(dir_idx, snapshot_path)]
    log: list = field(default_factory=list)      # 指令流水
    clicks: list = field(default_factory=list)   # 點擊記錄（ground truth 本體）
    walked: bool = False         # 本 episode 用過 `走`（movement mode 已切、收尾要切回）


def next_episode_id(last_ledger_line):
    """ledger 末行 episode+1；無檔/壞行回 1（編號只求人眼可對，不求嚴格連續）。"""
    if not last_ledger_line:
        return 1
    try:
        return int(json.loads(last_ledger_line).get("episode", 0)) + 1
    except (ValueError, KeyError, TypeError):
        return 1


def log_command(ctx, raw, reply, now):
    ctx.log.append({"t": now, "raw": raw, "kind": reply.kind if reply else None,
                    "pose_dir": ctx.cur_dir})


def record_click(ctx, pos, layer, region, now):
    ctx.clicks.append({"t": now, "pos": tuple(pos), "layer": layer,
                       "dir": ctx.cur_dir, "region": tuple(region), "invalid": False})


def ledger_entry(ctx, outcome, world, duration_s):
    """episode 收尾行（append-only；快照路徑在 shots/clicks 內，離線可回放）。"""
    return {"episode": ctx.episode_id, "t": ctx.created_at, "world": world,
            "outcome": outcome, "attempt": ctx.attempt,
            "sticky_layer": ctx.sticky_layer, "shots": list(ctx.shots),
            "log": list(ctx.log), "clicks": list(ctx.clicks),
            "duration_s": round(duration_s, 1)}


def void_entry(episode_id, click_index, now):
    """作廢追加行：資料消費端讀到後把該 episode 第 click_index 筆點擊視為 invalid。"""
    return {"type": "void", "episode": episode_id, "click_index": click_index, "t": now}
```

- [ ] **Step 4: 跑綠＋全套** Run: `python -m pytest -q` → 全綠
- [ ] **Step 5: Commit 訊息建議**（人工審後）`feat(remote-reentry): reentry_mode 三態＋純邏輯模組（解析/網格/ledger）`

---

## Phase R2：Bot 接線（opencode 梯次 2）

### Task 4: 開場鏈＋Discord 分派＋等待/antiafk＋context 生命週期

**Files:**
- Modify: `miningbot/main.py`

**Interfaces:**
- Consumes: Task 1-3 全部；既有 `_rotate_verified`、`_pitch_drag_verified`、`ic.pitch_reset`、`ic.click_at`、`vision.frame_mean_diff`、`notify.send_message/send_images_message`、`_antiafk_tick`、`_snapshot`、`diagnostics.snapshot_subdir`
- Produces: `Bot._rr_ctx: RemoteReentryContext | None`、`Bot._pending_reentry: (raw, RemoteReply) | None`、`Bot._rr_busy: bool`、`Bot._rr_sticky_layer: str`、`Bot._rr_movement_ready: bool`、`Bot._tick_reentry_remote(frame)`、`Bot._rr_open_episode(reroll=False)`、`Bot._rr_sweep_and_send(prefix_msg="")`、`Bot._rr_ledger_append(d)`

- [ ] **Step 1: `__init__` 初始化**（`_pending_aim` 一帶）

```python
        # Discord 遠端回礦（2026-07-12 spec）：輪詢執行緒只寫 _pending_reentry（含原文，
        # 供 ledger 指令流水），主迴圈消費；比照 _pending_aim。
        self._rr_ctx = None
        self._pending_reentry = None
        self._rr_busy = False
        self._rr_sticky_layer = cfg.reentry_target_layer   # 黏性目標層（`層` 指令改，session 內沿用）
        self._rr_movement_ready = False                    # `走` 懶啟動：session 內只跑一次選單鏈
```

- [ ] **Step 2: `_poll_discord` 分派**（aim 分支之後）

```python
            elif self._rr_ctx is not None and self.state is State.REENTRY:
                self._handle_reentry_reply(content)
```

新方法（放 `_handle_aim_reply` 附近；**輪詢執行緒：只解析/回覆/寫 pending**）：

```python
    def _handle_reentry_reply(self, content: str):
        """REENTRY 遠端等待時，一般訊息當回礦指令解析（無前綴，2026-07-12 spec）。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        reply = reentry_remote.parse_reply(content)
        if reply is None:
            notify.send_message(token, ch,
                "❓ 看不懂。可用：`3 C2`（方位+粗格）、`B3`／`B3 <層名>`（細格）、"
                "`走 C2`、`掃`、`重骰`、`層 <層名>`、`好`、`作廢`、`跳過`")
            return
        if self._rr_busy or self._pending_reentry is not None:
            notify.send_message(token, ch, "⏳ 上一則指令還在執行，稍候")
            return
        self._pending_reentry = (content, reply)
        self.log_discord.info("RR reply=%s -> pending", reply)
```

- [ ] **Step 3: `_tick_reentry` 分流＋remote tick**

`_tick_reentry`（main.py:3050）最頂端加：

```python
        if self._remote_reenter_active():
            self._tick_reentry_remote(frame)
            return
```

新方法群（放 `_tick_reentry` 之前）：

```python
    def _tick_reentry_remote(self, frame):
        """REENTRY 遠端模式主迴圈（2026-07-12 spec）：首 tick 開場，之後消費 pending 指令。

        等待回覆無硬超時（使用者延遲以分鐘計）；防踢由 run() 主迴圈的 antiafk 分支保活。
        """
        if self._mine_resetting:
            self._rr_abort_reset(frame)
            return
        if self._rr_ctx is None:
            self._rr_busy = True
            try:
                self._rr_open_episode()
            finally:
                self._rr_busy = False
            return
        if self._pending_reentry is not None:
            (raw, reply), self._pending_reentry = self._pending_reentry, None
            reentry_remote.log_command(self._rr_ctx, raw, reply, time.time())
            self._rr_busy = True
            try:
                self._rr_execute(reply)
            finally:
                self._rr_busy = False

    def _rr_abort_reset(self, frame):
        """等待/執行間礦坑又重置：收尾 ledger、作廢 context、回 RESET_WAIT。"""
        from . import notify
        if self._rr_ctx is not None:
            self._rr_finalize("reset_interrupt")
        notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id,
                            "🔄 礦坑重置中，本輪回礦作廢、重來")
        self.state = State.RESET_WAIT
        self._on_enter(State.RESET_WAIT, frame)

    def _rr_finalize(self, outcome):
        """episode 收尾：寫 ledger 一行、清 context/pending。"""
        ctx, self._rr_ctx = self._rr_ctx, None
        self._pending_reentry = None
        if ctx is None:
            return
        world = game_data.current_world_name()   # 以 game_data 現況 API 為準；未鎖回 None
        self._rr_ledger_append(reentry_remote.ledger_entry(
            ctx, outcome, world, time.time() - ctx.created_at))

    def _rr_ledger_append(self, d):
        os.makedirs(os.path.dirname(cfg.reentry_remote_ledger), exist_ok=True)
        with open(cfg.reentry_remote_ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
```

（`game_data.current_world_name()`：查 game_data 實際 API——鎖定世界的讀法（`set_world` 的對偶）；沒有現成 getter 就加一個回 `_current_world.name` 或 None 的小函式，勿發明複雜介面。`import json`/`os` 檔頂已有則不重複。）

- [ ] **Step 4: 開場鏈**

```python
    def _rr_open_episode(self, reroll: bool = False):
        """按回到地表 → 等傳送 → 俯仰歸位 → 八方位拍照 → Discord 發送 → 建/續 context。

        同步阻塞主迴圈 ~20-30s（比照 _sweep_for_tracker 慣例）；步驟間查 _mine_resetting。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，回 `重骰` 重試或 `跳過`")
            self._rr_ensure_ctx(reroll)
            return
        ref = capture.grab()
        ic.click_at(*cfg.reentry_surface_button_xy)
        deadline = time.time() + cfg.reentry_teleport_wait_s
        teleported = False
        while time.time() < deadline:
            time.sleep(0.4)
            if vision.frame_mean_diff(ref, capture.grab()) >= cfg.reentry_teleport_diff:
                teleported = True
                break
        self._rr_ensure_ctx(reroll)
        if not teleported:
            notify.send_message(token, ch,
                f"⚠ 回礦 #{self._rr_ctx.episode_id}：按「回到地表」畫面無變化，"
                "回 `重骰` 重試或 `跳過`")
            return
        time.sleep(1.0)                          # 傳送落地沉澱
        ok = self._pitch_drag_verified(
            f"[RR#{self._rr_ctx.episode_id}] 俯仰歸位",
            lambda: ic.pitch_reset(cfg.reentry_pitch_clamp_px, cfg.reentry_pitch_back_px))
        if not ok:
            notify.send_message(token, ch, "⚠ 俯仰歸位被吃（已重試）；圖照發，角度可能偏")
        self._rr_sweep_and_send()

    def _rr_ensure_ctx(self, reroll: bool):
        """建新 context 或 reroll 續用（同 episode 號、attempt+1、面向/快照歸零）。"""
        if reroll and self._rr_ctx is not None:
            ctx = self._rr_ctx
            ctx.attempt += 1
            ctx.cur_dir = 0
            ctx.phase = "awaiting_cmd"
            ctx.shots = []
            ctx.zoom_region = ()
            return
        last = None
        try:
            with open(cfg.reentry_remote_ledger, "rb") as f:
                lines = f.read().splitlines()
                last = lines[-1].decode("utf-8") if lines else None
        except OSError:
            pass
        self._rr_ctx = reentry_remote.RemoteReentryContext(
            episode_id=reentry_remote.next_episode_id(last),
            created_at=time.time(), sticky_layer=self._rr_sticky_layer)

    def _rr_sweep_and_send(self, prefix_msg: str = ""):
        """八方位拍照（`,`×8 驗證式，轉滿一圈回原向）→ 疊粗網格 → 分則發送。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ctx = self._rr_ctx
        ctx.shots = []
        pairs = []                                # [(dir_idx, grid_path)]
        for i in range(8):
            if self._mine_resetting:
                return                            # 上層 tick 下一輪處理 reset
            f = capture.grab()
            path = self._snapshot(f, f"reentry_ep{ctx.episode_id}_dir{i}")
            ctx.shots.append((i, path or ""))
            grid_img = f.copy()
            remote_aim.draw_grid(grid_img, 6, 4)
            gpath = self._snapshot(grid_img, f"reentry_ep{ctx.episode_id}_dir{i}_grid")
            pairs.append((i, gpath))
            self._rotate_verified(1)              # 8 次右轉＝轉滿一圈回原向；cur_dir 座標系不變
        head = (prefix_msg or
                f"⛏ 回礦 #{ctx.episode_id}（attempt {ctx.attempt}）｜目標層：{ctx.sticky_layer}\n"
                f"回 `方位 粗格`（如 `3 C2`）指位；`走 C2` 走近；`重骰` 換重生點；"
                f"`層 <名>` 改目標層；`跳過` 交人工")
        batch = [p for _, p in pairs if p]
        notify.send_images_message(token, ch, head + "\n方位 0-3", batch[:4])
        if len(batch) > 4:
            notify.send_images_message(token, ch, "方位 4-7", batch[4:8])
```

（快照走 `_snapshot`＝非同步佇列**回傳路徑但檔案稍後才落盤**——發送前需要檔案已存在：疊網格圖改用**同步寫檔**（`cv2.imwrite` 直接寫 `diagnostics.snapshot_subdir` 路徑）或發送前 `_snapshot_queue.join()`；查 `_render_aim_shots` 怎麼處理同一問題（它同步 `cv2.imwrite`），照抄該做法。）

- [ ] **Step 5: antiafk 等待分支**

run() 主迴圈（main.py:1645 一帶）：

```python
                if self.state in (State.NEEDS_HUMAN, State.RESET_WAIT):
                    self._antiafk_tick("需人工/重置等待")
```

改成：

```python
                rr_waiting = (self.state is State.REENTRY and self._rr_ctx is not None
                              and not self._rr_busy and self._pending_reentry is None)
                if self.state in (State.NEEDS_HUMAN, State.RESET_WAIT) or rr_waiting:
                    self._antiafk_tick("需人工/重置等待" if not rr_waiting else "回礦等待指令")
```

（下方 `elif self._antiafk_last and not self.paused:` 歸零分支不動——rr_waiting 為 True 時不會走到 elif。）

- [ ] **Step 6: context 生命週期**

`_on_enter` 的 `State.MINING` 分支與 `State.RESET_WAIT` 分支各加：`self._rr_ctx = None`、`self._pending_reentry = None`（MINING 進場代表 episode 已收尾；RESET_WAIT 進場代表重置搶先，`_rr_abort_reset` 已 finalize，此處是保險清掃）。檔頂 `from . import reentry_remote`。

- [ ] **Step 7: 全套測試** Run: `python -m pytest -q` → 全綠

---

### Task 5: 指令執行鏈＋驗證三態＋回報

**Files:**
- Modify: `miningbot/main.py`

**Interfaces:**
- Consumes: Task 2-4 全部；既有 `harvester.plan_return_rotations`、`_set_movement_mode`、`reentry.movement_status`、config `reentry_nav_timeout_s/reentry_move_stable_ticks/reentry_move_diff/reentry_teleport_wait_s/reentry_teleport_diff/reentry_mine_max_brightness/stuck_region`
- Produces: `Bot._rr_execute(reply)` 與其動作 helpers

- [ ] **Step 1: 指令分派**

```python
    def _rr_execute(self, reply):
        """主迴圈消費一則回礦指令（輸入操作全在此執行緒）。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ctx = self._rr_ctx
        k = reply.kind
        if k == "layer":
            self._rr_sticky_layer = reply.layer
            ctx.sticky_layer = reply.layer
            notify.send_message(token, ch, f"✅ 目標層改為：{reply.layer}")
        elif k == "void":
            self._rr_void_last(ctx)
        elif k == "skip":
            self._rr_finalize("skip")
            self._reentry_failed = True           # decide_transition → NEEDS_HUMAN
            notify.send_message(token, ch, "⏭ 跳過，交人工（NEEDS_HUMAN）")
        elif k == "reroll":
            self._rr_open_episode(reroll=True)
        elif k == "sweep":
            self._rr_sweep_and_send(prefix_msg=f"🔁 回礦 #{ctx.episode_id} 重新八方位掃描")
        elif k == "walk":
            self._rr_walk(ctx, reply.cell)
        elif k == "coarse":
            self._rr_zoom(ctx, reply.dir_idx, reply.cell)
        elif k == "fine":
            if ctx.phase != "awaiting_fine":
                notify.send_message(token, ch, "❓ 現在不是等細格的時候，先回 `方位 粗格`（如 `3 C2`）")
                return
            self._rr_click(ctx, reply.cell, reply.layer)
        elif k == "confirm":
            if ctx.phase != "awaiting_confirm":
                notify.send_message(token, ch, "❓ 目前沒有待確認的點擊")
                return
            self._rr_success(ctx, "confirmed_by_user")
```

- [ ] **Step 2: coarse → zoom**

```python
    def _rr_zoom(self, ctx, tgt_dir, cell):
        """轉到目標方位、裁粗格放大＋細網格回傳，進「等細格」。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，稍後重試")
            return
        steps = harvester.plan_return_rotations(ctx.cur_dir % 8, tgt_dir % 8)
        for _ in range(abs(steps)):
            if self._rotate_verified(1 if steps > 0 else -1):
                ctx.cur_dir += 1 if steps > 0 else -1
        if ctx.cur_dir % 8 != tgt_dir % 8:
            notify.send_message(token, ch, "⚠ 轉向被吃，目前面向可能偏；重下一次 `方位 粗格` 即重對齊")
            return
        f = capture.grab()
        region = reentry_remote.coarse_cell_region(cell)
        zoom = reentry_remote.render_zoom(
            f, region, scale=cfg.reentry_remote_zoom_scale,
            cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)
        base = os.path.join(diagnostics.snapshot_subdir("reentry"),
                            f"ep{ctx.episode_id}_zoom_{tgt_dir}{cell}")
        cv2.imwrite(base + "_src.png", capture.crop_region(f, region))   # 漂移守門基準（同步寫）
        cv2.imwrite(base + ".png", zoom)
        ctx.phase = "awaiting_fine"
        ctx.zoom_dir = tgt_dir
        ctx.zoom_region = region
        notify.send_images_message(token, ch,
            f"🔍 方位 {tgt_dir} 的 {cell} 格放大。回細格（如 `B3`）點擊；"
            f"要換層回 `B3 <層名>`；太粗回 `走 {cell}` 走近", [base + ".png"])
```

（`capture.crop_region`：查 capture/vision 現有裁區 API（`capture.crop`？`Region` 型別？）——`zoom_region` 是 tuple (x,y,w,h)，用 numpy 切片 `f[y:y+h, x:x+w]` 最直接，勿為此加新 API。守門基準檔名 `_src.png` 由 `_rr_click` 讀回。）

- [ ] **Step 3: fine → 漂移守門 → 點擊 → 驗證三態**

```python
    def _rr_click(self, ctx, fine_cell, layer_override):
        """細格點擊：漂移守門 → 左鍵點傳送按鈕 → 三態（成功/等確認/無反應）。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        pos = reentry_remote.fine_cell_to_screen(
            ctx.zoom_region, fine_cell,
            cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)
        if pos is None:
            notify.send_message(token, ch, "❓ 細格代碼不合法（A1–F6）")
            return
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，稍後重試")
            return
        # 漂移守門（H026 家族）：粗格區域現況 vs 放大圖來源
        x, y, rw, rh = ctx.zoom_region
        cur = capture.grab()
        base = os.path.join(diagnostics.snapshot_subdir("reentry"),
                            f"ep{ctx.episode_id}_zoom_{ctx.zoom_dir}...")   # 與 _rr_zoom 同名規則組回
        src = cv2.imread(base + "_src.png")
        if src is not None and vision.frame_mean_diff(
                src, cur[y:y + rh, x:x + rw]) >= cfg.reentry_remote_drift_diff:
            zoom = reentry_remote.render_zoom(cur, ctx.zoom_region,
                                              scale=cfg.reentry_remote_zoom_scale,
                                              cols=cfg.reentry_remote_fine_cols,
                                              rows=cfg.reentry_remote_fine_rows)
            cv2.imwrite(base + ".png", zoom)
            cv2.imwrite(base + "_src.png", cur[y:y + rh, x:x + rw])
            notify.send_images_message(token, ch,
                "⚠ 畫面已漂移（buff 到期/保活跳動），沒有點。這是更新後的放大圖，請重指細格",
                [base + ".png"])
            return
        layer = layer_override or ctx.sticky_layer
        marker = reentry_remote.draw_click_marker(cur, pos)
        mpath = os.path.join(diagnostics.snapshot_subdir("reentry"),
                             f"ep{ctx.episode_id}_click{len(ctx.clicks)}_marker.png")
        cv2.imwrite(mpath, marker)
        fpath = os.path.join(diagnostics.snapshot_subdir("reentry"),
                             f"ep{ctx.episode_id}_click{len(ctx.clicks)}_full.png")
        cv2.imwrite(fpath, cur)                  # 點擊瞬間全幀（ground truth 樣本）
        reentry_remote.record_click(ctx, pos, layer, ctx.zoom_region, time.time())
        ic.click_at(int(pos[0]), int(pos[1]))
        # 驗證：等傳送幀差
        deadline = time.time() + cfg.reentry_teleport_wait_s
        teleported = False
        while time.time() < deadline:
            time.sleep(0.4)
            if vision.frame_mean_diff(cur, capture.grab()) >= cfg.reentry_teleport_diff:
                teleported = True
                break
        if not teleported:
            notify.send_images_message(token, ch,
                "❌ 點了畫面無變化（紅圈＝實際點擊處）。重指細格、或 `走`/`重骰`", [mpath])
            return                                # 留在 awaiting_fine
        time.sleep(1.5)                          # 傳送落地
        land = capture.grab()
        lpath = os.path.join(diagnostics.snapshot_subdir("reentry"),
                             f"ep{ctx.episode_id}_click{len(ctx.clicks)-1}_landing.png")
        cv2.imwrite(lpath, land)
        in_mine = vision.region_mean_brightness(land, cfg.stuck_region) \
            <= cfg.reentry_mine_max_brightness
        if cfg.reentry_remote_auto_resume and in_mine:
            notify.send_images_message(token, ch,
                f"✅ 回礦 #{ctx.episode_id} 傳送成功（層：{layer}）。紅圈＝點擊處；自動開挖",
                [mpath, lpath])
            self._rr_success(ctx, "success")
        else:
            ctx.phase = "awaiting_confirm"
            notify.send_images_message(token, ch,
                f"❓ 已傳送（層標籤：{layer}）。左圖紅圈＝點擊處、右圖＝落點。"
                f"沒問題回 `好` 開挖；點錯回 `重骰`；資料要作廢回 `作廢`",
                [mpath, lpath])

    def _rr_success(self, ctx, outcome):
        """成功收尾：movement mode 復原（若走過位）→ ledger → 回 MINING。"""
        from . import notify
        if ctx.walked:
            self._set_movement_mode(cfg.movement_mode_mining)
        self._rr_finalize(outcome)
        self._reentry_done = True                 # decide_transition → MINING → init 序列
        notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id, "⛏ 回礦完成，開挖")

    def _rr_void_last(self, ctx):
        """作廢最後一筆點擊（ledger 追加 void 行＋ctx 標 invalid）。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        if not ctx.clicks:
            notify.send_message(token, ch, "❓ 本輪還沒有點擊記錄")
            return
        idx = len(ctx.clicks) - 1
        ctx.clicks[idx]["invalid"] = True
        self._rr_ledger_append(reentry_remote.void_entry(ctx.episode_id, idx, time.time()))
        notify.send_message(token, ch, f"🗑 已作廢本輪第 {idx + 1} 筆點擊資料")
```

實作註記（opencode 必讀）：
- `_rr_zoom`/`_rr_click` 的守門基準檔名要一致——把路徑組進 `ctx` 存（建議 ctx 加欄位 `zoom_base: str = ""`，`_rr_zoom` 寫、`_rr_click` 讀，Task 3 的 dataclass 同步補欄位＋測試不用改（有 default））；上方示意碼的 `"..."` 即此意，實作用 ctx 欄位不要重組字串。
- `vision.region_mean_brightness`：查 vision.py 是否已有（auto 版 CLICK_VERIFY main.py:3144 一帶怎麼算礦內亮度就照抄）；沒有就在 vision 加：`Region` 裁圖後 `cv2.cvtColor(gray).mean()`，附 3 行 docstring。
- `awaiting_confirm` 時收到 `重骰` → `_rr_execute` 現有分派已處理（reroll 不看 phase）——會開新 attempt、phase 重置，符合「點錯層 reroll」語意。
- `stuck_region`/`reentry_teleport_*` 等鍵名以 config.py 現況為準，名稱不同就用實際名稱。

- [ ] **Step 4: `走` 指令**

```python
    def _rr_walk(self, ctx, cell):
        """右鍵 click-to-move 到當前面向的粗格中心，走完重拍回傳（其餘方位圖視為過期）。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        if not self._rr_movement_ready:
            notify.send_message(token, ch, "⏳ 首次走位：切換移動模式（最多 ~90s）…")
            if not self._set_movement_mode(cfg.movement_mode_reentry):
                notify.send_message(token, ch, "⚠ 移動模式切換失敗，走位不可用；請 `重骰` 或 `跳過`")
                return
            self._rr_movement_ready = True
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，稍後重試")
            return
        target = remote_aim.grid_cell_center(cell)          # 粗網格 6×4 格中心
        ic.click_at(target[0], target[1], button="right")
        ctx.walked = True
        # 到位偵測：連續 N tick 幀差近零＝停下（沿用 auto 版門檻）
        diffs, prev = [], capture.grab()
        deadline = time.time() + cfg.reentry_nav_timeout_s
        while time.time() < deadline:
            time.sleep(0.5)
            f = capture.grab()
            diffs.append(vision.frame_mean_diff(prev, f))
            prev = f
            if reentry.movement_status(diffs, cfg.reentry_move_diff,
                                       cfg.reentry_move_stable_ticks) == "stopped":
                break
        f = capture.grab()
        grid_img = f.copy()
        remote_aim.draw_grid(grid_img, 6, 4)
        gpath = os.path.join(diagnostics.snapshot_subdir("reentry"),
                             f"ep{ctx.episode_id}_walk_{cell}.png")
        cv2.imwrite(gpath, grid_img)
        ctx.phase = "awaiting_cmd"
        ctx.zoom_region = ()
        notify.send_images_message(token, ch,
            f"🚶 已走位（其餘方位圖已過期）。回 `{ctx.cur_dir % 8} 粗格` 繼續指位，或 `掃` 重掃八方位",
            [gpath])
```

- [ ] **Step 5: HUD 等待顯示**

查 `status_hud` 從 Bot 讀狀態文字的現有機制（`_poll` 讀哪些欄位），在該處加：state 為 REENTRY 且 `_rr_ctx` 存在時顯示 `回礦等待指令 #<episode>（已等 <N> 分）`（用 `created_at` 算；文字全 BMP-safe，不放 astral emoji）。照現有樣式最小改動。

- [ ] **Step 6: 全套測試** Run: `python -m pytest -q` → 全綠
- [ ] **Step 7: Commit 訊息建議**（人工審後）`feat(remote-reentry): Bot 接線——開場鏈/指令執行/驗證三態/ledger 落盤`

---

## Phase R3：校準與實機端到端（Claude＋使用者，不委派 opencode）

### Task 6: 校準＋端到端＋文件

- [ ] 校準 `reentry_surface_button_xy`：R 視窗截圖 → Claude 量「回到地表」按鈕座標寫入 config
- [ ] `reentry_pitch_back_px` 若尚未校準：R 視窗俯仰鈕實測「拖到夾限→回拉」的合適回拉量
- [ ] `config.reentry_mode = "remote"` 開啟 → 真實重置一輪端到端：八方位圖送達 → `3 C2` → 放大圖 → `B3` → 紅圈+落點雙圖 → `好` → 回 MINING 開挖
- [ ] 邊界案例實測：`重骰`、亂打字只回提示、細格時機錯誤提示、`層 Core Layer` 換層、`作廢`、等待 >15 分（antiafk 保活、Roblox 未踢）
- [ ] 檢查 `logs/reentry_remote/ledger.jsonl` 首批記錄欄位齊全、快照齊全（八方位原始幀/點擊全幀/marker/landing）
- [ ] 文件補記：CLAUDE.md（重置自動回礦段補 remote 模式一句話＋指令表指到 spec）、`docs/manual-sampling.md` 若校準流程有新步驟
- [ ] Commit：`feat(remote-reentry): 實機校準＋端到端驗證`

## Self-Review 紀錄

- **Spec 覆蓋**：三態 config（Task 1）、開場鏈與八方位分則發送（Task 4）、全指令詞彙含層黏性/覆寫/作廢/好（Task 2 解析＋Task 5 執行）、兩段式放大與 ±27px 換算（Task 2 幾何＋Task 5 zoom/click）、漂移守門（Task 5 Step 3）、三態驗證與紅圈+落點回報（Task 5）、`走` 懶啟動 movement mode（Task 5 Step 4）、antiafk 沿用（Task 4 Step 5）、reset 中斷守門（Task 4 `_rr_abort_reset`＋sweep 內查）、episode 編號與 append-only ledger/void（Task 3）、快照落盤（八方位原始幀/點擊全幀/marker/landing，Task 4/5）、HUD（Task 5 Step 5）——全數有任務對應。
- **已知簡化**（記錄於此、實機驗證時盯）：`掃` 從當前面向重掃（走位後 cur_dir 記帳延續，方位號與最初 sweep 的號碼系一致）；粗格跨兩方位的目標（框在畫面邊緣）由使用者換相鄰方位重指，不做跨方位縫合；zoom 基準圖同步寫檔（一次性、非熱路徑）。
- **型別一致性**：`RemoteReply` 欄位（Task 2 定義、Task 5 使用）、`RemoteReentryContext` 欄位含補充的 `zoom_base`（Task 3 定義、Task 4/5 使用）、`ledger_entry`/`void_entry` dict 鍵（Task 3 定義、Task 4/5 寫入）、`coarse_cell_region` 回 (x,y,w,h) 與 `fine_cell_to_screen` 的 region 參數同構——一致。
- **與工作區衝突**：main.py/config.py/states.py 有未 commit 的 ability 改動——Global Constraints 已標注「先 commit/stash 再委派」。
