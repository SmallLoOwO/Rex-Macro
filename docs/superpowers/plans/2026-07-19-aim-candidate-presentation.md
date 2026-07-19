# 近失候選呈現改版＋手動模式現場重掃 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交人工卡的近失候選改成「編號↔圖一眼對得上、①＝最優快速重採」，`方位 格子` 降級為手動最後手段，且手動模式的全方位圖現場重掃保證 D2 效果亮著。

**Architecture:** 純決策（格子反算、總表組字、批次切分、回覆解析）全部進 `miningbot/remote_aim.py` 純函式；I/O（渲染、發送、重掃、旋轉）留在 `miningbot/main.py` 的 `Bot`。Discord 輪詢執行緒只寫 `_pending_aim`，遊戲輸入一律主迴圈消費（既有鐵律）。

**Tech Stack:** Python 3.11、OpenCV（疊圖）、既有 Discord REST helpers（`notify.py`）、pytest。

**Spec:** `docs/superpowers/specs/2026-07-19-aim-candidate-presentation-design.md`（本計畫的唯一需求來源）。

## Global Constraints

- 候選圖一律用偵測當下原幀，禁止事後補拍；手動模式圖一律「重按 D2＋`_confirm_scan` 確認生效」後才拍（spec 核心不變量）。
- Discord 輪詢執行緒絕不碰 `input_control`／`capture`；需要輸入的回覆種類全部走 `_pending_aim` → `_tick_remote_aim`。
- 座標、門檻、間隔只放 `Config`；本計畫不新增 config 欄位（沿用 `remote_aim_budget_s`、`remote_aim_snapshot_wait_s`、`remote_aim_max_candidates`）。
- 測試指令：`uv run pytest -q`（全綠才 commit）；lint：`uv run ruff check . --no-cache`。
- 每個 Task 完成即 commit，訊息中文；**不要 stage `miningbot/config.py`**（working tree 有一筆使用者校準值 400→370 的不相關修改，保留）。
- 圖上文字只能英文（cv2 無中文字型）；中文全部放 Discord caption／總表。
- 不動：射擊執行鏈（`_execute_remote_fire`）、`AimContext`/`AimCandidate` 結構、`draw_overlay` 候選框繪製、`parse_reply` 的編號/格子/跳過語法。

---

### Task 1: `grid_cell_of` 格子反算純函式

**Files:**
- Modify: `miningbot/remote_aim.py`（`grid_cell_center` 之後）
- Test: `tests/test_remote_aim.py`

**Interfaces:**
- Produces: `grid_cell_of(pos, w=1920, h=1080, cols=6, rows=4) -> str | None`——螢幕座標 → 網格代碼（如 `"C3"`）；畫面外回 `None`。Task 2 的總表用它算「約C3」。

- [ ] **Step 1: Write the failing tests**

在 `tests/test_remote_aim.py` 的 import 加入 `grid_cell_of`（併入既有 `from miningbot.remote_aim import (...)`），並在 `TestGridCellCenter` 後新增：

```python
class TestGridCellOf:
    def test_roundtrip_all_cells(self):
        # grid_cell_center 的逆函式：24 格 roundtrip 全對
        for col in "ABCDEF":
            for row in "1234":
                cell = f"{col}{row}"
                assert remote_aim.grid_cell_of(grid_cell_center(cell)) == cell

    def test_boundary_pixels(self):
        # 格界：319/269 仍在 A1，320/270 進 B2（格寬 320、格高 270）
        assert remote_aim.grid_cell_of((0, 0)) == "A1"
        assert remote_aim.grid_cell_of((1919, 1079)) == "F4"
        assert remote_aim.grid_cell_of((319, 269)) == "A1"
        assert remote_aim.grid_cell_of((320, 270)) == "B2"

    def test_out_of_screen_returns_none(self):
        assert remote_aim.grid_cell_of((-1, 5)) is None
        assert remote_aim.grid_cell_of((1920, 0)) is None
        assert remote_aim.grid_cell_of((0, 1080)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_remote_aim.py::TestGridCellOf -v`
Expected: FAIL，`AttributeError: module 'miningbot.remote_aim' has no attribute 'grid_cell_of'`

- [ ] **Step 3: Implement**

`miningbot/remote_aim.py`，緊接 `grid_cell_center` 之後：

```python
def grid_cell_of(pos, w: int = 1920, h: int = 1080,
                 cols: int = 6, rows: int = 4):
    """螢幕座標 → 網格代碼（如 "C3"）；grid_cell_center 的逆函式。畫面外回 None。

    候選總表用它把已存座標反算成「約C3」，操作者不用自己對格線。
    """
    x, y = int(pos[0]), int(pos[1])
    if not (0 <= x < w and 0 <= y < h):
        return None
    ci = min(x * cols // w, cols - 1)
    ri = min(y * rows // h, rows - 1)
    return f"{GRID_COLS[ci]}{GRID_ROWS[ri]}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_remote_aim.py -v`
Expected: 全 PASS（含既有測試）

- [ ] **Step 5: Commit**

```bash
git add miningbot/remote_aim.py tests/test_remote_aim.py
git commit -m "feat(remote_aim): grid_cell_of 座標反算格子——候選總表「約C3」用（2026-07-19 spec §2）"
```

---

### Task 2: `circled`／`REASON_LABELS`／`format_candidate_summary` 候選總表

**Files:**
- Modify: `miningbot/remote_aim.py`
- Modify: `docs/superpowers/specs/2026-07-19-aim-candidate-presentation-design.md`（①範例行 `曾鎖定未採到` → `曾鎖定`，統一走對照表、不加後綴）
- Test: `tests/test_remote_aim.py`

**Interfaces:**
- Consumes: Task 1 的 `grid_cell_of`。
- Produces:
  - `circled(n: int) -> str`——1..9 回 ①..⑨，其餘回 `"(n)"`。
  - `REASON_LABELS: dict[str, str]`——原因/狀態代碼 → 中文短語。
  - `format_candidate_summary(candidates) -> str`——`[AimCandidate]`（已依編號排序）→ 多行總表字串；空清單回 `""`。Task 5 在 giveup 發送時呼叫。

- [ ] **Step 1: Write the failing tests**

`tests/test_remote_aim.py` import 加 `circled, format_candidate_summary`，新增：

```python
def _cand(number, dir_idx, pos, score, reason,
          status="rejected", source="near_miss"):
    return AimCandidate(number=number, layer="mid", dir_idx=dir_idx, pos=pos,
                        score=score, reason=reason, source=source, status=status)


class TestCircled:
    def test_1_to_9(self):
        assert [circled(n) for n in (1, 5, 9)] == ["①", "⑤", "⑨"]

    def test_out_of_range_fallback(self):
        assert circled(10) == "(10)"


class TestFormatCandidateSummary:
    def test_observation_first_line_quick_reharvest(self):
        # ① 是觀測證據（掃到未採）→ 最優提示行；② 一般近失行
        cands = [_cand(1, 5, (800, 675), 0.42, "sweep_stable",
                       status="accepted", source="sweep_stable"),
                 _cand(2, 2, (1100, 400), 0.38, "hard_rej")]
        lines = format_candidate_summary(cands).splitlines()
        assert lines[0] == "①（最優）DIR5・約C3・曾鎖定——回 1 快速重採"
        assert lines[1] == "② DIR2・約D2・分數0.38・形狀分不足"

    def test_number_one_near_miss_is_plain_line(self):
        # ① 不是觀測證據 → 不加（最優）提示（規則綁狀態、不綁編號）
        text = format_candidate_summary([_cand(1, 0, (10, 10), 0.44, "soft")])
        assert text == "① DIR0・約A1・分數0.44・形狀弱訊號"

    def test_hsv_only_candidate_shows_colored_not_negative(self):
        # 無 edge 候選排序鍵＝colored−1.0（負數）→ 顯示「色0.55」不出現負號
        text = format_candidate_summary([_cand(1, 7, (330, 700), -0.45, "margin")])
        assert text == "① DIR7・約B3・色0.55・太靠邊"
        assert "-" not in text

    def test_fired_and_seen_once_labels(self):
        cands = [_cand(1, 4, (400, 500), 0.05, "d3_fire",
                       status="fired", source="d3_fire"),
                 _cand(2, 6, (600, 300), 0.10, "double_frame_unstable",
                       status="seen_once", source="double_frame_unstable")]
        lines = format_candidate_summary(cands).splitlines()
        assert lines[0] == "①（最優）DIR4・約B2・射過未確認——回 1 快速重採"
        assert "單幀目擊" in lines[1]

    def test_unknown_reason_falls_through_as_is(self):
        assert "weird_code" in format_candidate_summary(
            [_cand(1, 0, (10, 10), 0.5, "weird_code")])

    def test_empty_candidates(self):
        assert format_candidate_summary([]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_remote_aim.py::TestCircled tests/test_remote_aim.py::TestFormatCandidateSummary -v`
Expected: FAIL，ImportError（`circled` 不存在）

- [ ] **Step 3: Implement**

`miningbot/remote_aim.py`，放在 `grid_cell_of` 之後：

```python
_CIRCLED = "①②③④⑤⑥⑦⑧⑨"


def circled(n: int) -> str:
    """候選編號顯示字：1..9 → ①..⑨；超出回 "(n)"（防禦，現行上限 9）。"""
    return _CIRCLED[n - 1] if 1 <= n <= 9 else f"({n})"


# 原因/狀態代碼 → 中文短語（總表與 caption 用；圖上標頭仍英文——cv2 無中文字型）。
# near-miss 用 reason（vision.find_tracker collect_rejects）；觀測證據用 status。
REASON_LABELS = {
    "hard_rej": "形狀分不足", "soft": "形狀弱訊號", "margin": "太靠邊",
    "exclude": "在排除區", "preexist": "掃描前已存在",
    "fired": "射過未確認", "accepted": "曾鎖定", "seen_once": "單幀目擊",
}

_OBS_STATUSES = ("fired", "accepted", "seen_once")


def format_candidate_summary(candidates) -> str:
    """候選總表（一行一候選）：編號↔DIR↔格子↔分數↔原因，一眼可對圖。

    - ① 是觀測證據（掃到過但沒採到）→「（最優）…回 1 快速重採」提示行。
    - score ≥ 0（有 edge）顯示「分數x.xx」；< 0（HSV-only，排序鍵 colored−1.0）
      顯示「色x.xx」，不出現負數。
    - 未知代碼原樣顯示（清單漂移要浮出來，不吞）。
    """
    lines = []
    for c in candidates:
        cell = grid_cell_of(c.pos) or "?"
        key = c.status if c.status in _OBS_STATUSES else c.reason
        label = REASON_LABELS.get(key, key)
        if c.number == 1 and c.status in _OBS_STATUSES:
            lines.append(f"①（最優）DIR{c.dir_idx}・約{cell}・{label}"
                         f"——回 1 快速重採")
        else:
            score = (f"分數{c.score:.2f}" if c.score >= 0
                     else f"色{c.score + 1.0:.2f}")
            lines.append(f"{circled(c.number)} DIR{c.dir_idx}・約{cell}・"
                         f"{score}・{label}")
    return "\n".join(lines)
```

同步把 spec `§2` 的範例行 `①（最優）DIR5・約C4・曾鎖定未採到——回 1 快速重採` 改為 `①（最優）DIR5・約C4・曾鎖定——回 1 快速重採`（label 統一走對照表）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_remote_aim.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add miningbot/remote_aim.py tests/test_remote_aim.py docs/superpowers/specs/2026-07-19-aim-candidate-presentation-design.md
git commit -m "feat(remote_aim): 候選總表純函式——編號/DIR/約格子/分數/原因中文化，①觀測證據標最優快速重採（2026-07-19 spec §2）"
```

---

### Task 3: `AIM_GROUP_HEADER`／`MANUAL_SURVEY_HELP`／`build_aim_groups` 批次切分

**Files:**
- Modify: `miningbot/remote_aim.py`
- Test: `tests/test_remote_aim.py`

**Interfaces:**
- Consumes: Task 2 的 `circled`。
- Produces:
  - `AIM_GROUP_HEADER: str`——初始群標題（只提 編號/跳過/手動；不含格子語法）。
  - `MANUAL_SURVEY_HELP: str`——手動模式首則 caption（格子語法只在這裡出現）。
  - `build_aim_groups(rendered, summary, batch=4) -> list[(caption, [paths])]`——
    `rendered=[(candidate_numbers: tuple[int,...], dir_idx: int, layer: str, path: str)]`
    （numbers 非空，由 Task 5 的 `_render_aim_shots` 保證）。Task 5 用它組
    `image_groups`。

- [ ] **Step 1: Write the failing tests**

import 加 `build_aim_groups, AIM_GROUP_HEADER, MANUAL_SURVEY_HELP`，新增：

```python
class TestBuildAimGroups:
    def test_sorted_by_min_number_and_batched_by_four(self):
        # 依各圖最小候選編號升冪 → ① 的圖必在首組首張（最優快速重採入口）
        rendered = [((5, 6), 3, "mid", "d3.png"),
                    ((1,), 5, "mid", "d5.png"),
                    ((2, 3), 0, "mid", "d0.png"),
                    ((4,), 7, "up", "d7.png"),
                    ((7,), 2, "mid", "d2.png")]
        groups = build_aim_groups(rendered, "總表內容")
        assert len(groups) == 2
        cap0, paths0 = groups[0]
        assert paths0 == ["d5.png", "d0.png", "d7.png", "d3.png"]
        assert cap0 == f"{AIM_GROUP_HEADER}\n總表內容"
        cap1, paths1 = groups[1]
        assert paths1 == ["d2.png"]
        assert cap1.startswith("🎯 近失候選（續）")
        assert "⑦" in cap1 and "DIR2" in cap1

    def test_single_group_header_and_summary(self):
        groups = build_aim_groups([((1,), 0, "mid", "a.png")], "line")
        assert groups == [(f"{AIM_GROUP_HEADER}\nline", ["a.png"])]

    def test_empty_summary_header_only(self):
        groups = build_aim_groups([((1,), 0, "mid", "a.png")], "")
        assert groups == [(AIM_GROUP_HEADER, ["a.png"])]

    def test_empty_rendered(self):
        assert build_aim_groups([], "x") == []

    def test_header_offers_number_skip_manual_but_not_grid(self):
        # 指令降級（spec §1/§5）：格子語法不在群標題，只在手動模式 caption
        assert "手動" in AIM_GROUP_HEADER and "跳過" in AIM_GROUP_HEADER
        assert "C3" not in AIM_GROUP_HEADER
        assert "C3" in MANUAL_SURVEY_HELP and "5U C3" in MANUAL_SURVEY_HELP
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_remote_aim.py::TestBuildAimGroups -v`
Expected: FAIL，ImportError（`build_aim_groups` 不存在）

- [ ] **Step 3: Implement**

`miningbot/remote_aim.py`（`format_candidate_summary` 之後）：

```python
AIM_GROUP_HEADER = ("🎯 近失候選——回編號（如 `2`）腳本自動對齊射擊；"
                    "`跳過` 回挖礦；`手動` 最後手段（重掃＋全方位圖）")
MANUAL_SURVEY_HELP = ("🧭 手動瞄準（D2 已重掃、效果窗內實況）——回 `方位 格子` 射擊："
                      "`5 C3`＝DIR5 的 C3 格；`5U C3`/`5D C3`＝上/下層（盲射）；"
                      "`跳過` 回挖礦")


def build_aim_groups(rendered, summary: str, batch: int = 4) -> list:
    """疊圖批次切分（4 張/組）＋caption 組字（純函式）。

    rendered = [(candidate_numbers, dir_idx, layer, path), ...]（numbers 非空）。
    依各圖最小候選編號升冪——① 的圖必在首組首張。首組 caption＝群標題＋總表
    （notify.format_group_messages 的 fallback 直接把組名當 caption 用），
    續組列出該批編號與 DIR，解決「不知道哪個數字是哪張圖」。
    """
    items = sorted(rendered, key=lambda r: min(r[0]))
    out = []
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        if i == 0:
            caption = AIM_GROUP_HEADER + (f"\n{summary}" if summary else "")
        else:
            nums = "".join(circled(n) for r in chunk for n in sorted(r[0]))
            dirs = "・".join(f"DIR{r[1]}" for r in chunk)
            caption = f"🎯 近失候選（續）：{nums}｜{dirs}"
        out.append((caption, [r[3] for r in chunk]))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_remote_aim.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add miningbot/remote_aim.py tests/test_remote_aim.py
git commit -m "feat(remote_aim): build_aim_groups 批次切分＋群標題/手動說明文案——①圖首發、續批列編號與DIR（2026-07-19 spec §1）"
```

---

### Task 4: `parse_reply` 新增 `手動`（`全部` 改別名）

**Files:**
- Modify: `miningbot/remote_aim.py:192-224`（`parse_reply`）＋ `AimReply` docstring
- Test: `tests/test_remote_aim.py`（改寫既有 `test_skip_and_all`）

**Interfaces:**
- Produces: `parse_reply` 對 `手動`/`manual`/`全部`/`all`（不分大小寫）回 `AimReply("manual")`；kind `"all"` 退役。Task 5/6 依 kind `"manual"` 分流。

- [ ] **Step 1: Update tests（先改測試讓它紅）**

把 `TestParseReply.test_skip_and_all` 換成：

```python
    def test_skip(self):
        assert parse_reply("跳過", 3).kind == "skip"
        assert parse_reply("SKIP", 3).kind == "skip"

    def test_manual_keywords_and_all_alias(self):
        # `全部`/`all` 為舊別名（統一走手動最後手段：重掃＋全方位圖）
        for word in ("手動", "manual", "全部", "all", "MANUAL"):
            assert parse_reply(word, 3).kind == "manual"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_remote_aim.py::TestParseReply -v`
Expected: `test_manual_keywords_and_all_alias` FAIL（`手動` 回 None、`全部` 回 kind="all"）

- [ ] **Step 3: Implement**

`parse_reply` 內把

```python
    if low in ("skip", "跳過"):
        return AimReply("skip")
    if low in ("all", "全部"):
        return AimReply("all")
```

改為

```python
    if low in ("skip", "跳過"):
        return AimReply("skip")
    if low in ("manual", "手動", "all", "全部"):
        # 最後手段：現場重掃＋全方位圖（`全部`/`all` 為 2026-07-11 舊別名）
        return AimReply("manual")
```

`AimReply` 的 kind 註解 `"candidate" / "grid" / "skip" / "all"` 改為
`"candidate" / "grid" / "skip" / "manual"`；`parse_reply` docstring 的
`"跳過"/"skip" → skip；"全部" → all（補發其餘方位快照）` 改為
`"跳過"/"skip" → skip；"手動"/"全部" → manual（重掃＋全方位圖）`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_remote_aim.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add miningbot/remote_aim.py tests/test_remote_aim.py
git commit -m "feat(remote_aim): parse_reply 手動關鍵字——全部/all 併為別名、kind=all 退役（2026-07-19 spec §4）"
```

---

### Task 5: 發送端整合（`main.py`＋`notify.py`）

**Files:**
- Modify: `miningbot/notify.py:67-74`（`_REGION_CAPTIONS` 移除 `"aim"` 鍵）
- Modify: `miningbot/main.py`：`_render_aim_shots`（約 3069-3114）、giveup 組群處（約 3049-3062）、`_handle_aim_reply`（約 1891-1926）；新增 `_draw_aim_header`
- Test: 既有全套（此 Task 為 I/O 面，無新單元測試；靠 Task 1-4 純函式測試＋全套回歸）

**Interfaces:**
- Consumes: `format_candidate_summary`（Task 2）、`build_aim_groups`（Task 3）、kind `"manual"`（Task 4）。
- Produces:
  - `_render_aim_shots(ctx) -> list[(numbers: tuple, dir_idx: int, layer: str, path: str)]`（不再回 caption、不再排序——交 `build_aim_groups`）。
  - `_draw_aim_header(img, text)`——黑條 56px＋字級 1.1 標頭；Task 6 的手動模式共用。
  - `_handle_aim_reply` 把 manual 寫入 `_pending_aim`（舊 all 分支刪除）。

- [ ] **Step 1: `notify.py` 移除 aim 鍵**

`_REGION_CAPTIONS` 刪掉 `"aim"` 一行，註解補一句：

```python
# 人工介入分組截圖的群標題（Discord「先聊天框、再背包」分開發送用；
# D3 超時（有框）路徑另有 tracker 群＝追蹤框現況，排最前）
# 近失候選（aim）群改由 remote_aim.build_aim_groups 直接產 caption，
# 走本表 fallback（get(region, region)），不再登記於此。
_REGION_CAPTIONS = {
    "tracker": "🎯 追蹤框（現況）",
    "chat": "📨 聊天框（前 / 後）",
    "backpack": "🎒 背包（前 / 後）",
}
```

- [ ] **Step 2: `main.py` 新增 `_draw_aim_header`、改 `_render_aim_shots`**

在 `_render_aim_shots` 旁新增：

```python
    def _draw_aim_header(self, img, text: str) -> None:
        """疊圖上緣黑條＋大字標頭——縮圖牆也能辨認 DIR（2026-07-19 spec §3）。"""
        import cv2
        cv2.rectangle(img, (0, 0), (img.shape[1], 56), (0, 0, 0), -1)
        cv2.putText(img, text, (12, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    (0, 215, 255), 3)
```

`_render_aim_shots` 整段改為（黑條/caption/排序三處變更，其餘照舊）：

```python
    def _render_aim_shots(self, ctx):
        """Render direction-labelled overlays after async source snapshots are ready.

        回 [(候選編號 tuple, dir_idx, layer, 疊圖路徑)]；排序、批次與 caption
        交給 remote_aim.build_aim_groups（純函式）。候選圖一律用偵測當下原幀
        （D2 效果保證，spec 核心不變量）。
        """
        import cv2
        out = []
        deadline = time.monotonic() + cfg.remote_aim_snapshot_wait_s
        for shot in ctx.shots:
            exact = [candidate for candidate in ctx.candidates
                     if candidate.snapshot_path
                     and candidate.snapshot_path == shot.snapshot_path]
            legacy = [candidate for candidate in ctx.candidates
                      if not candidate.snapshot_path
                      and (candidate.layer, candidate.dir_idx) ==
                      (shot.layer, shot.dir_idx)]
            candidates = exact or legacy
            if not candidates or not shot.snapshot_path:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            if not self._wait_snapshot_ready(shot.snapshot_path, remaining):
                self.logger.warning("AIM source snapshot missing: %s", shot.snapshot_path)
                continue
            image = cv2.imread(shot.snapshot_path)
            if image is None:
                self.logger.warning("AIM source snapshot unreadable: %s", shot.snapshot_path)
                continue
            overlaid = remote_aim.draw_overlay(image, candidates, grid=True)
            statuses = ",".join(dict.fromkeys(c.status for c in candidates))
            self._draw_aim_header(
                overlaid,
                f"DIR {shot.dir_idx} | {shot.layer.upper()} | {statuses.upper()}")
            path = os.path.splitext(shot.snapshot_path)[0] + "_aim.png"
            if not cv2.imwrite(path, overlaid):
                self.logger.warning("AIM overlay write failed: %s", path)
                continue
            label = (f"{ctx.harvest_id}_aim_overlay_dir{shot.dir_idx}_"
                     f"{shot.layer}_{statuses}")
            try:
                diagnostics.append_snapshot_index(cfg.log_dir, label, path)
            except Exception as exc:
                self.logger.warning("AIM overlay index failed (%s): %s", path, exc)
            numbers = tuple(sorted(c.number for c in candidates))
            out.append((numbers, shot.dir_idx, shot.layer, path))
        return out
```

- [ ] **Step 3: giveup 組群處改用 `build_aim_groups`**

`main.py` 約 3049-3062（`self._aim_context = None` 起）改為：

```python
        self._aim_context = None
        if (cfg.remote_aim_enabled
                and (self._sweep_shots or self._target_observations)):
            ctx = remote_aim.build_aim_context(
                self._sweep_shots, self.harvest.net_rotations,
                self.harvest.pitch_layer, self.harvest.harvest_id,
                now=time.time(), max_candidates=cfg.remote_aim_max_candidates,
                observations=self._target_observations)
            rendered = self._render_aim_shots(ctx)   # 疊圖＋落盤
            self._aim_context = ctx
            if rendered:
                # 全候選圖都發（4 張/組批次）；caption 由純函式組（群標題＋總表）。
                # 組名即 caption——走 format_group_messages 的 fallback。
                summary = remote_aim.format_candidate_summary(ctx.candidates)
                groups = remote_aim.build_aim_groups(rendered, summary) + groups
```

（舊 `aim_paths[:4]` 截斷與 `groups.insert(0, ("aim", ...))` 刪除。）

- [ ] **Step 4: `_handle_aim_reply` 刪 all 分支、改 help 文案**

刪除整段：

```python
        if reply.kind == "all":
            rendered = self._render_aim_shots(ctx)
            sent = 0
            for caption, path in rendered[:8]:
                notify.send_images_message(token, ch, caption, [path])
                sent += 1
            self.log_discord.info("AIM all -> 補發 %d 張", sent)
            return
```

help 文案改為：

```python
        if reply is None:
            notify.send_message(token, ch,
                "❓ 看不懂。可用：`2`（射候選②）、`跳過`（回挖礦）、"
                "`手動`（最後手段：重掃＋全方位圖＋格子瞄準說明）")
            return
```

行尾註解 `# skip/candidate/grid：主迴圈消費` 改 `# skip/candidate/grid/manual：主迴圈消費`。
（manual 需要遊戲輸入，必須走 `_pending_aim` 由主迴圈消費——輪詢執行緒鐵律。）

- [ ] **Step 5: Run full tests + lint**

Run: `uv run pytest -q` → 全 PASS；`uv run ruff check . --no-cache` → 無新違規。
（此時回 `手動` 會落到 `_tick_remote_aim` 的未處理 kind——Task 6 補；先確認無回歸。）

- [ ] **Step 6: Commit**

```bash
git add miningbot/main.py miningbot/notify.py
git commit -m "feat(main/notify): 近失候選發送改版——全圖4張/組批次、caption含總表、①圖首發、all分支退役（2026-07-19 spec §1/§5）"
```

---

### Task 6: 手動模式現場重掃（`_tick_remote_aim` 分流＋`_execute_manual_survey`）

**Files:**
- Modify: `miningbot/main.py`：`_tick_remote_aim`（約 3117-3162）＋新增 `_execute_manual_survey`（放 `_tick_remote_aim` 與 `_execute_remote_fire` 之間）
- Test: 既有全套（I/O 面；純函式部分已在 Task 3/4 蓋住）

**Interfaces:**
- Consumes: `MANUAL_SURVEY_HELP`／`draw_grid`（remote_aim）、`_draw_aim_header`（Task 5）、kind `"manual"`（Task 4）、既有 `_focus_roblox`／`_pitch_drag_verified`／`_confirm_scan`／`_rotate_verified`／`_hsnap`／`_wait_snapshot_ready`。
- Produces: 回 `手動` → 重掃＋8 方位圖兩則訊息；`_aim_context` 保留待下一則回覆。

- [ ] **Step 1: `_tick_remote_aim` 加 manual 分流**

在 `if reply.kind == "skip":` 區塊之後、「# 解目標」之前插入：

```python
        if reply.kind == "manual":
            self._aim_busy = True
            try:
                self._execute_manual_survey(ctx)
            finally:
                self._aim_busy = False
            return
```

並把 `_tick_remote_aim` docstring 首行的 `skip→回挖礦；candidate/grid→…` 補成
`skip→回挖礦；manual→重掃＋全方位圖；candidate/grid→對齊+重掃+開火+驗證`。

- [ ] **Step 2: 新增 `_execute_manual_survey`**

```python
    def _execute_manual_survey(self, ctx):
        """手動最後手段（2026-07-19 spec §4）：現場重按 D2＋確認生效 → 8 方位各拍一張
        （效果窗內＝手動圖的 D2 保證）→ 疊網格＋DIR 標頭 → 4 張/則發送＋格子瞄準說明。

        只拍 mid 層（`5U C3`/`5D C3` 盲射語法仍可用）、不開火；失敗回報後不自動重試
        （有界），_aim_context 保留等下一則回覆。姿態記帳走 ctx.pose_net_rotations，
        旋轉被吃不計（同 fire 路徑慣例）——轉滿 8 次回原方位。
        """
        from . import notify
        import cv2
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        hid = ctx.harvest_id
        deadline = time.time() + cfg.remote_aim_budget_s
        if not self._focus_roblox():
            notify.send_message(token, ch, "❌ 無法聚焦 Roblox，可再回 `手動` 重試或 `跳過`")
            return
        if self._mine_resetting:
            notify.send_message(token, ch, "❌ 礦坑重置中，`跳過` 回挖礦")
            return
        if ctx.pose_pitch_layer != "mid":
            ok = self._pitch_drag_verified(
                f"[{hid}] MANUAL 俯仰歸位",
                lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                       cfg.sweep_pitch_center_back_px))
            ctx.pose_pitch_layer = "mid"   # reset 至少跑過，保守記歸位（同 fire 路徑）
            if not ok:
                notify.send_message(token, ch, "❌ 俯仰歸位被吃，可再回 `手動` 重試或 `跳過`")
                return
        harvester.prepare_scan()
        harvester.execute_scan()           # 重按 D2：手動圖必須在掃描效果窗內拍
        if not self._confirm_scan("remote-aim-manual"):
            notify.send_message(token, ch, "❌ 掃描未生效，可再回 `手動` 重試或 `跳過`")
            return
        snaps = {}                          # {abs_dir: 原幀快照路徑}；被吃重拍同方位保留最新
        for _ in range(8):
            if time.time() > deadline:
                self.logger.warning("[%s] MANUAL survey 預算用盡（拍到 %d 方位）",
                                    hid, len(snaps))
                break
            abs_dir = ctx.pose_net_rotations % 8
            frame = capture.grab()
            path = self._hsnap(frame, f"manual_survey_dir{abs_dir}")
            if path:
                snaps[abs_dir] = path
            if self._rotate_verified(1):
                ctx.pose_net_rotations += 1
        rendered = []
        wait_deadline = time.monotonic() + cfg.remote_aim_snapshot_wait_s
        for abs_dir in sorted(snaps):
            path = snaps[abs_dir]
            remaining = max(0.0, wait_deadline - time.monotonic())
            if not self._wait_snapshot_ready(path, remaining):
                self.logger.warning("MANUAL snapshot missing: %s", path)
                continue
            image = cv2.imread(path)
            if image is None:
                self.logger.warning("MANUAL snapshot unreadable: %s", path)
                continue
            remote_aim.draw_grid(image)
            self._draw_aim_header(image, f"DIR {abs_dir} | MID")
            out_path = os.path.splitext(path)[0] + "_manual.png"
            if not cv2.imwrite(out_path, image):
                self.logger.warning("MANUAL overlay write failed: %s", out_path)
                continue
            try:
                diagnostics.append_snapshot_index(
                    cfg.log_dir, f"{hid}_manual_survey_dir{abs_dir}", out_path)
            except Exception as exc:
                self.logger.warning("MANUAL overlay index failed (%s): %s", out_path, exc)
            rendered.append(out_path)
        if not rendered:
            notify.send_message(token, ch, "❌ 全方位快照失敗，可再回 `手動` 重試或 `跳過`")
            return
        for i in range(0, len(rendered), 4):
            caption = (remote_aim.MANUAL_SURVEY_HELP if i == 0
                       else "🧭 手動瞄準（續）")
            notify.send_images_message(token, ch, caption, rendered[i:i + 4])
        self.log_discord.info("MANUAL survey -> %d 方位圖已發", len(rendered))
```

- [ ] **Step 3: Run full tests + lint**

Run: `uv run pytest -q` → 全 PASS；`uv run ruff check . --no-cache` → 無新違規。

- [ ] **Step 4: 靜態自查（無實機）**

逐項核對（讀碼確認，不跑遊戲）：
1. `_execute_manual_survey` 全程只在主迴圈執行緒（由 `_tick_remote_aim` 呼叫）。
2. 拍照在 `_rotate_verified` 之前 → 每方位的幀都在該方位靜止時拍。
3. 旋轉被吃：`abs_dir` 不變 → 下輪重拍同方位覆蓋 `snaps[abs_dir]`，缺的是「沒轉到的」方位（記帳正確、不誤標）。
4. `ctx` 未清 → 使用者接著回 `5 C3` 或編號都走既有 `_tick_remote_aim` 路徑。

- [ ] **Step 5: Commit**

```bash
git add miningbot/main.py
git commit -m "feat(main): 手動模式現場重掃——D2重按+確認生效後8方位各拍一張、網格+DIR標頭、4張/則+格子瞄準說明（2026-07-19 spec §4）"
```

---

### Task 7: 收尾驗證

**Files:**
- 無新檔；全 repo 驗證

- [ ] **Step 1: 全套驗證**

```bash
uv run pytest -q
uv run ruff check . --no-cache
uv lock --check
git status --short   # 只應剩 miningbot/config.py 的既有校準修改
```

Expected: pytest 全綠、ruff 無違規、lock 同步、working tree 僅剩 config.py。

- [ ] **Step 2: Spec 驗收對照**

逐條核對 spec「驗收」節：
1. 第一則訊息含群標題＋總表（編號/DIR/約格子/原因）→ Task 3/5。
2. ① 觀測證據時第一張圖＝①（`build_aim_groups` 依最小編號排序）→ Task 3。
3. `手動` 收到當下重掃、效果亮著的全方位圖 → Task 6。

發現缺漏→補實作＋測試再 commit；無缺漏→計畫完成（實機驗證待下輪掛機，
比照 repo 慣例「待實機驗證不是不 commit 的理由」）。
