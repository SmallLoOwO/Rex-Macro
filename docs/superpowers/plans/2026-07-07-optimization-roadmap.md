# REX 挖礦 bot 優化 Roadmap（2026-07-07）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有 401 綠測試、H001–H039 事故對策全數落地的基礎上，收割「已知待辦＋實測到的維運痛點」——採集熱路徑提速 6 倍、堵住 D2 掃描空轉漏洞、消滅靜默降級、控制 632MB 快照膨脹、補齊 9 世界資料缺口。

**Architecture:** 全部遵循本專案既定模式——純決策函式抽到可測模組（TDD、禁 mock）、I/O glue 留在 main 並以實機觀察期裁決（RapidOCR 模式）；視覺路徑改動一律 fixture 先行（H 系列迴歸鎖）。

**Tech Stack:** Python / OpenCV / tesserocr+RapidOCR / mss / pytest（純邏輯）。無新增依賴。

## Global Constraints（每個 Task 隱含遵守）

- `python -m pytest -q` 改完必須全綠（現基線 **401 passed**）。
- 測試規範照 `tests/AGENTS.md`：**禁 mock/monkeypatch/parametrize/conftest**；純函式 TDD；門檻從 `config.DEFAULT` 注入不寫死；迴歸測試留事故引註。
- 視覺路徑（`vision.find_tracker` 一族）改動前必備 fixture，且既有 H 系列 fixture 測試不可轉紅。
- 所有座標/門檻進 `miningbot/config.py`，不散落。
- 實機驗證**絕不按 Esc**；只用遊戲按鍵（1–5、`,`/`.`、W、滑鼠）。
- 排除清單安全規則不可破：**Exotic 以上絕不可列**（有測試鎖）；清單人工維護，工具只出 diff/advisory。
- 每個 Phase 開獨立 feature 分支；commit 訊息結尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。
- 遊戲機制前提（改動時不可違反）：D5 buff 在時按 D5 無效（只能到期即補）；數字鍵 toggle 裝備；聊天只有 Surreal/Mythic（含 Rare/Master 變體）被動進場。

---

## 現況盤點（2026-07-07，為何是這些項目）

**已完成、本計劃不重做**（HANDOFF §9 的部分項目已過時）：
- 遠距控制已完備：`pause`/`resume`/`status`/`shot`/`keep` 系列（main.py:519-675）——HANDOFF 沒記到 resume/status/shot。
- 驗證式旋轉、episode 聊天帳本＋晚到確認、boost 守門、RapidOCR 首選、banner OCR 背景化、最短路徑旋回——均已落地（見 `docs/incidents.md`）。
- 截圖庫換 bettercam：**依 2026-07 依賴調查裁決不換**（mss 非瓶頸）。

**實測到的未解問題（本計劃的證據基礎）**：
| # | 證據 | 問題 |
|---|---|---|
| 1 | 記憶/裁決明載「verify 輪詢 gone 檢查每輪 ~2s，ROI 化可到 ~0.3s，未做」 | 8s 驗證窗口只裝得下 ~3 輪輪詢，confirmed 偵測慢、窗口利用率低 |
| 2 | CLAUDE.md：「掃描在有 UI 彈窗開著時點不到（點擊被彈窗吃掉）」；HANDOFF F | D2 掃描無成功確認——被吃掉就必然白掃 8 方位 ~19s ＋ 可能誤交人工 |
| 3 | 實測 `logs/snapshots` = **632MB**，且專案在 **OneDrive 同步夾**內 | 掛機愈久同步負擔愈重；無保留策略 |
| 4 | 文件明載多處靜默降級：markers 缺→退純 HSV、rare_ores.json 缺→fuzzy 停用、chill_refs 空→單參考、refs 過多→音訊積壓 | 任一 asset 缺失＝默默變弱，實機跑壞了才發現 |
| 5 | WIP diff 註解：「事件（events）目前為空 → D4 keep/reroll 與世界自動偵測對這些世界尚未生效」（9 世界中 7 個） | 世界鎖不住→排除清單永遠用保守聯集，同名礦跨世界階級不同時判斷變鈍 |
| 6 | H039：「fetch_ores 只收 Surreal+ 印不出 Rare/Master 底名 diff，缺口要從實機⚠警告補」 | 每個 Rare/Master 缺名都要實機踩一次才補得到 |
| 7 | HANDOFF §7 已知限制：D3 fire 序列阻塞、超時/暫停延遲數秒生效 | poll 迴圈最長 ~8s＋final-check OCR ~10s 不理會 F12/暫停旗標 |

---

## 總覽

| Phase | 內容 | 主要效益 | 風險 | 估工 |
|---|---|---|---|---|
| 0 | 收尾 WIP 分支＋文件同步 | 乾淨基線 | 低 | 0.5 天 |
| 1 | verify 輪詢 ROI 化＋輪詢協作式中斷 | 輪詢 ~2s→~0.3s；8s 窗口 ~3→8+ 輪；F12/暫停即時生效 | 中（視覺路徑，fixture 先行） | 1–1.5 天 |
| 2 | D2 掃描成功確認（觀察期→啟用重試） | 堵「白掃 19s＋誤交人工」漏洞 | 低（觀察期裁決） | 0.5 天＋跨 2-3 天觀察 |
| 3 | 啟動 preflight 自檢＋snapshots 保留策略 | 靜默降級現形；磁碟/OneDrive 受控 | 低 | 1 天 |
| 4 | 世界資料完備：礦名反推世界＋fetch_ores 低階 advisory | 7 個新世界也能鎖定；Rare/Master 缺名事前補 | 低（純邏輯＋工具） | 1 天 |
| 5 | 追蹤框模板/fixture 半自動收集工具 | 新框形（如 H039 enigmatic）擴充成本大降 | 極低（離線工具） | 0.5 天 |
| — | Backlog（明確緩做/不做＋理由） | — | — | — |

建議順序：0 → 1 → 2（觀察期跨天，期間並行 3）→ 4 → 5。總 active 工時 ~5 天。

---

## Phase 0：收尾與文件同步

**Files:**
- Modify: 無程式碼（只有 git 操作與文件）
- Modify: `tests/AGENTS.md`（過時計數）、`docs/HANDOFF.md`（過時數值）

**現況**：分支 `feature/episode-chat-ledger` 落後 main 20 個 commit 未合回，工作區另有一批未提交 WIP（9 世界 common_ores 匯入＋H039 Heartstone＋fixtures）。

- [ ] **Step 1: 驗證 WIP 完整性**

Run: `python -m pytest -q`
Expected: `401 passed`（或更多）；紅了先修再繼續。

- [ ] **Step 2: 提交 WIP**

```bash
git add miningbot/ tests/
git commit -m "feat(data): 匯入全部 9 世界 common_ores＋H039 Heartstone 底名對策

Co-Authored-By: Claude <noreply@anthropic.com>"
```

（`.claude/` 是否入版控由使用者決定；不確定就先不加。）

- [ ] **Step 3: 合回 main**

```bash
git checkout main && git merge --no-ff feature/episode-chat-ledger
python -m pytest -q   # 合併後再驗一次
```

- [ ] **Step 4: 文件同步（過時處更正，敘事不重寫）**

`tests/AGENTS.md`：131/123 測試計數 → 實際數（跑 pytest 取）；結構表補新測試檔（test_ocr_fixtures 等）。
`docs/HANDOFF.md`：§0 測試數、§1 的 `harvest_verify_timeout_s=15s` → 45s、find_tracker 門檻 0.45/0.25 → 0.42/0.30、§9 已完成項標註（resume/status/shot 已有、margin 0.02 已收窄）。內文指向 `docs/incidents.md`，不複製敘事。

- [ ] **Step 5: Commit 文件**

```bash
git add tests/AGENTS.md docs/HANDOFF.md
git commit -m "docs: 同步測試計數與 HANDOFF 過時數值

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 1：verify 輪詢 ROI 化＋協作式中斷

**動機**：D3 開火後的驗證輪詢（main.py:1500-1527）每輪對**全幀 1920×1080** 跑 `find_tracker`（~2s）。但開火座標已知、追蹤框不會瞬移——gone 檢查只需看「原位置周圍」。已知待辦，效益 ~2s→~0.3s/輪；8s 窗口從 ~3 輪變 8+ 輪，confirmed 更早偵測到、更少踩 H015 型空窗。

**設計核心（安全前提）**：ROI miss **不等於** gone——H026 證明 D5 到期的 FOV 縮放會整批位移座標。故：**ROI 命中＝還在（快路徑）；ROI miss → 全幀後備確認一次；後備命中 → 更新 ROI 中心（漂移吸收）；後備也 miss → 才 latch gone**。成本分析：常見路徑（框在原地等命中判定）每輪 ~0.3s；框淡出/漂移那一輪 0.3+2s 僅一次。語意與現行「全幀每輪」完全等價，只是快。

### Task 1.1: `vision.find_tracker_near` 純函式

**Files:**
- Modify: `miningbot/vision.py`（`find_tracker` 之後新增）
- Modify: `miningbot/config.py`（新增 `verify_roi_radius_px`）
- Test: `tests/test_vision.py`

**Interfaces:**
- Consumes: 既有 `find_tracker(frame_bgr, margin_frac, exclude, log, reference_bgr, shape_templates, shape_threshold, shape_hard_floor, shape_scales, shape_roi_px, with_score)`
- Produces: `find_tracker_near(frame_bgr, center_xy, radius_px, *, frame_margin_frac=0.0, exclude=(), reference_bgr=None, log=None, **kwargs) -> tuple|None`——回傳**全幀座標**（含 with_score 時的 edge），找不到回 None

- [ ] **Step 1: 寫失敗測試**（加入 `tests/test_vision.py`，沿用檔內既有 `_scene_with_patch`/`_draw_tracker` 輔助與 fixture skip 模式）

```python
def test_find_tracker_near_maps_roi_hit_back_to_full_frame_coords():
    scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _draw_tracker(scene, 900, 500, size=44, color=(60, 220, 240))
    full = find_tracker(scene, margin_frac=0.02)
    near = find_tracker_near(scene, (905, 495), 180, frame_margin_frac=0.02)
    assert full is not None and near is not None
    assert abs(near[0] - full[0]) <= 2 and abs(near[1] - full[1]) <= 2


def test_find_tracker_near_returns_none_when_center_far_from_tracker():
    scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _draw_tracker(scene, 1500, 800, size=44, color=(60, 220, 240))
    assert find_tracker_near(scene, (300, 300), 180, frame_margin_frac=0.02) is None


def test_find_tracker_near_shifts_exclude_rects_into_roi():
    scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _draw_tracker(scene, 900, 500, size=44, color=(60, 220, 240))
    excl = [(860, 460, 940, 540)]   # 全幀座標蓋住框 → ROI 內也必須被排除
    assert find_tracker_near(scene, (905, 495), 180,
                             frame_margin_frac=0.02, exclude=excl) is None


def test_find_tracker_near_keeps_h026_bottom_edge_tracker_visible():
    # 對應 H026：ROI 路徑不可重新引入邊緣排除帶殺真框的機制。
    # 全幀 margin 0.02 收得回 (1288,1020) → ROI 版在同 margin 下也必須收得回；
    # margin 0.10 下必須同樣拒收（語意與全幀版一致）。
    img_path = "assets/bottom_edge_tracker_scene.png"
    tmpls = {}
    for n in ("exotic_tracker_real", "exquisite_tracker_real", "transcendent_tracker_real"):
        t = cv2.imread(f"assets/markers/{n}.png", cv2.IMREAD_UNCHANGED)
        if t is not None and t.ndim == 3 and t.shape[2] == 3:
            tmpls[n] = t
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    kw = dict(shape_templates=tmpls, shape_threshold=cfg.tracker_shape_threshold,
              shape_scales=cfg.tracker_shape_scales, shape_roi_px=cfg.tracker_shape_roi_px,
              shape_hard_floor=cfg.tracker_shape_hard_floor)
    loc = find_tracker_near(img, (1288, 1020), 180,
                            frame_margin_frac=cfg.tracker_margin_frac, **kw)
    assert loc is not None and abs(loc[0] - 1288) < 40 and abs(loc[1] - 1020) < 40
    assert find_tracker_near(img, (1288, 1020), 180,
                             frame_margin_frac=0.10, **kw) is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_vision.py -q -k find_tracker_near`
Expected: FAIL（`ImportError`/`NameError: find_tracker_near`）。記得在檔頭 import 列補 `find_tracker_near`。

- [ ] **Step 3: 實作**（`miningbot/vision.py`）

```python
def find_tracker_near(frame_bgr, center_xy, radius_px, *, frame_margin_frac=0.0,
                      exclude=(), reference_bgr=None, log=None, **kwargs):
    """在 center_xy 周圍 radius_px 的方形 ROI 內跑 find_tracker，座標映射回全幀。

    verify 輪詢的 gone 檢查用：開火座標已知，全幀掃描（~2s）是浪費——ROI 版 ~0.3s。
    frame_margin_frac＝「全幀」邊緣排除帶：ROI 邊不是螢幕邊，故子圖內 margin 一律 0、
    改在映射回全幀後套同一條帶（語意與全幀版一致，H019/H026 的 margin 教訓不重演）。
    找不到回 None——呼叫端自行決定是否全幀後備（H026 FOV 位移可能超出任何小 ROI）。
    """
    h, w = frame_bgr.shape[:2]
    cx, cy = int(center_xy[0]), int(center_xy[1])
    x0, y0 = max(0, cx - radius_px), max(0, cy - radius_px)
    x1, y1 = min(w, cx + radius_px), min(h, cy + radius_px)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None
    sub = frame_bgr[y0:y1, x0:x1]
    sub_ref = reference_bgr[y0:y1, x0:x1] if reference_bgr is not None else None
    shifted = []
    for ex0, ey0, ex1, ey1 in exclude:
        sx0, sy0 = max(ex0 - x0, 0), max(ey0 - y0, 0)
        sx1, sy1 = min(ex1 - x0, x1 - x0), min(ey1 - y0, y1 - y0)
        if sx1 > sx0 and sy1 > sy0:
            shifted.append((sx0, sy0, sx1, sy1))
    res = find_tracker(sub, margin_frac=0.0, exclude=tuple(shifted),
                       reference_bgr=sub_ref, log=log, **kwargs)
    if res is None:
        return None
    mapped = (res[0] + x0, res[1] + y0) + tuple(res[2:])
    mx, my = int(w * frame_margin_frac), int(h * frame_margin_frac)
    if not (mx <= mapped[0] <= w - mx and my <= mapped[1] <= h - my):
        return None
    return mapped
```

`miningbot/config.py`（採集區段，`harvest_verify_poll_interval_s` 附近）：

```python
    verify_roi_radius_px: int = 180              # verify 輪詢 gone 檢查的 ROI 半徑：涵蓋雙幀穩定 8px 誤差
                                                 # ＋輕微視角/FOV 殘餘漂移；大位移（D5 到期縮放）由
                                                 # 「ROI miss → 全幀後備」兜住（見 find_tracker_near 註解）
```

- [ ] **Step 4: 跑測試確認通過＋全套迴歸**

Run: `python -m pytest tests/test_vision.py -q && python -m pytest -q`
Expected: 全綠，既有 H019/H026 fixture 測試不動。

- [ ] **Step 5: Commit**

```bash
git add miningbot/vision.py miningbot/config.py tests/test_vision.py
git commit -m "feat(vision): find_tracker_near ROI 偵測——verify 輪詢提速的純函式層

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 1.2: 接入 verify 輪詢＋協作式中斷

**Files:**
- Modify: `miningbot/main.py`（`_find_tracker` 旁新增 wrapper；`_tick_harvest` 輪詢迴圈 main.py:1500-1527）

**Interfaces:**
- Consumes: Task 1.1 的 `vision.find_tracker_near`；既有 `self._running` / `self.paused` 旗標（main.py:679/597）
- Produces: 無新對外介面（行為等價、變快）

- [ ] **Step 1: 新增 Bot wrapper**（緊接 `_find_tracker` 之後，鏡射同組參數）

```python
    def _find_tracker_near(self, frame, center, exclude, reference_bgr=None):
        """verify 輪詢快路徑：只搜開火座標周圍 ROI（參數組與 _find_tracker 一致）。"""
        return vision.find_tracker_near(
            frame, center, cfg.verify_roi_radius_px,
            frame_margin_frac=cfg.tracker_margin_frac,
            exclude=exclude, reference_bgr=reference_bgr,
            shape_templates=self._shape_templates,
            shape_threshold=cfg.tracker_shape_threshold,
            shape_hard_floor=cfg.tracker_shape_hard_floor,
            shape_scales=cfg.tracker_shape_scales,
            shape_roi_px=cfg.tracker_shape_roi_px)
```

- [ ] **Step 2: 改輪詢迴圈**（main.py `while True:` 輪詢段；`roi_center` 以開火座標 `(cx, cy)` 起始）

```python
        roi_center = (cx, cy)
        while True:
            if not self._running or self.paused:
                # 協作式中斷（HANDOFF §7 已知限制）：F12/Ctrl+Q/Q 期間不再困在
                # 最長 ~8s 輪詢＋~10s final-check 裡；鍵盤已由 _pause/_quit 清掉，
                # 直接棄本輪驗證，run() 的暫停/結束分支接手。
                self.log_harvest.info("[%s] verify 輪詢中斷（%s）", hid,
                                      "quit" if not self._running else "pause")
                return
            after = capture.grab()
            if self._harvest_boost_guard(after):   # H026：到期即補，gone 檢查才在正確 FOV 下跑
                after = capture.grab()
            if first_poll:
                self._hsnap(after, "d3_after")
                first_poll = False
            if not gone:
                hit = self._find_tracker_near(after, roi_center, _excl, reference_bgr=_ref)
                if hit is not None:
                    roi_center = hit[:2]           # 微漂移吸收，下一輪仍走快路徑
                else:
                    # ROI miss ≠ gone（H026：FOV 位移可超出 ROI）→ 全幀後備確認一次
                    full = self._find_tracker(after, _excl, reference_bgr=_ref)
                    if full is not None:
                        roi_center = full          # 大漂移：更新中心回快路徑
                    gone = full is None
```

（迴圈其餘部分——chat 差分、`decide_verify_poll`、sleep——不動。）

- [ ] **Step 3: 全套測試**

Run: `python -m pytest -q`
Expected: 全綠（此步是 glue，無新純邏輯測試；行為由 Task 1.1 的 fixture 測試與實機驗證撐）。

- [ ] **Step 4: 實機驗證（照 tuning-from-incidents 慣例）**

1. `config.log_level="DEBUG"`，實機跑到一次完整採集。
2. `Get-Content logs\harvest.log -Encoding UTF8 | Select-String "verify poll"`：
   - 驗收 A：相鄰兩輪 `t=` 差值（單輪耗時）< 0.8s（原 ~2.5s）。
   - 驗收 B：8s 窗口內輪詢 ≥ 8 輪（原 ~3）。
   - 驗收 C：一次成功採集 end-to-end 正常（confirmed 早退、restore、續挖）。
3. 輪詢中按 Q：1s 內看到「verify 輪詢中斷（pause）」。

- [ ] **Step 5: Commit**

```bash
git add miningbot/main.py
git commit -m "perf(harvest): verify 輪詢 gone 檢查 ROI 化＋協作式中斷——單輪 ~2s→~0.3s

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**風險與回退**：若實機出現「框還在卻判 gone」（假 RESWEEP 增多），先看 harvest.log 是否 ROI miss→全幀後備也 miss（那是原行為就會 gone 的情況，非 ROI 引入）；仍可疑時把 `verify_roi_radius_px` 拉大（240/300）或暫時繞過（wrapper 直接呼叫 `_find_tracker`）。

---

## Phase 2：D2 掃描成功確認（觀察期 → 啟用重試）

**動機**：CLAUDE.md 明載「D2 純按 2 只裝備不掃；click 才觸發；**有 UI 彈窗開著時點擊會被吃掉**；掃描成功＝左下出現 Local」。現在 `execute_scan()` 後盲等 1.5s——被吃掉就白掃 8 方位 ~19s，且「全 8 方位無框→交人工」的 H019 分流會把這誤判成好假警報。掃描確認只在 HARVESTING 進場跑一次（非熱路徑），一次小裁圖 tesserocr ~0.4s。

**Rollout 採本專案既定的觀察期模式**（RapidOCR 前例）：`off` → 校準座標 → `observe`（只記 log 不重試，收 2-3 天數據）→ 誤陰性 <5% → `enforce`（失敗重聚焦重掃一次）。

### Task 2.1: 純判定函式 `harvester.scan_succeeded`

**Files:**
- Modify: `miningbot/harvester.py`、`miningbot/config.py`
- Test: `tests/test_harvester.py`

**Interfaces:**
- Produces: `scan_succeeded(texts: list[str]) -> bool`——OCR 逐 pass 文字列表，任一行含 Local-ish token 即 True

- [ ] **Step 1: 失敗測試**（`tests/test_harvester.py`）

```python
def test_scan_succeeded_exact_local():
    assert harvester.scan_succeeded(["Local"]) is True

def test_scan_succeeded_tolerates_ocr_noise():
    # 遊戲字型 i/l 同形（H033 教訓）＋常見誤讀
    assert harvester.scan_succeeded(["LocaI 12"]) is True
    assert harvester.scan_succeeded(["1ocal"]) is True

def test_scan_succeeded_rejects_empty_and_unrelated():
    assert harvester.scan_succeeded([]) is False
    assert harvester.scan_succeeded([""]) is False
    assert harvester.scan_succeeded(["Global"]) is False   # ratio("global","local")≈0.73 < 0.75
```

- [ ] **Step 2: 確認失敗**

Run: `python -m pytest tests/test_harvester.py -q -k scan_succeeded`
Expected: FAIL（AttributeError）。

- [ ] **Step 3: 實作**（`miningbot/harvester.py`；檔頭補 `from difflib import SequenceMatcher`）

```python
def scan_succeeded(texts) -> bool:
    """D2 掃描成功確認：OCR 文字裡有 Local-ish token 即成功（左下 Local 標籤）。

    彈窗吃掉 click 時掃描沒觸發 → 白掃 8 方位 ~19s（CLAUDE.md D2 段）。
    容忍 OCR 噪音（i/l 同形），0.75 門檻夾在 'global'(0.73) 與 'locaI'(0.8+) 之間。
    """
    for text in texts or []:
        for tok in (text or "").lower().split():
            t = tok.strip(":.,!1234567890 ")
            if not t:
                continue
            if t == "local" or SequenceMatcher(None, t, "local").ratio() >= 0.75:
                return True
    return False
```

`miningbot/config.py`（採集區段）：

```python
    # D2 掃描成功確認（HANDOFF F）：掃描後 OCR 左下 Local 標籤。彈窗吃掉 click → 白掃
    # 8 方位 ~19s＋可能誤交人工。模式循 RapidOCR 觀察期慣例：
    #   off=不跑；observe=只記 log 收誤判數據（不重試）；enforce=失敗重聚焦重掃一次
    scan_confirm_mode: str = "off"               # 校準 region 後先切 observe，2-3 天裁決再 enforce
    scan_confirm_region: Region = field(default_factory=lambda: Region(20, 850, 200, 60))  # 左下 Local 標籤（估值，校準時調——照 chat_review_region 慣例從 logs/snapshots 全幀圖裁）
```

- [ ] **Step 4: 通過＋Commit**

```bash
python -m pytest -q
git add miningbot/harvester.py miningbot/config.py tests/test_harvester.py
git commit -m "feat(harvest): scan_succeeded 純判定——D2 掃描確認的邏輯層

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.2: 接入 HARVESTING 進場＋校準＋觀察期

**Files:**
- Modify: `miningbot/main.py`（`_on_enter(HARVESTING)` 的 `execute_scan()` 之後；`_reharvest_sweep` 同點）

- [ ] **Step 1: 校準 `scan_confirm_region`**

從 `logs/snapshots` 挑一張「掃描成功後」全幀截圖（sweep 系列），Read 目視左下 Local 標籤，量出座標填進 config。無合適截圖時實機 `python -c "...capture.grab()..."`（CLAUDE.md 排錯段指令）補拍。

- [ ] **Step 2: 接線**（兩個掃描點共用同一 helper）

```python
    def _confirm_scan(self, where: str) -> bool:
        """D2 掃描確認（scan_confirm_mode 控制）。回傳 False 表示 enforce 模式下已重試仍失敗。"""
        if cfg.scan_confirm_mode == "off":
            return True
        crop = capture.crop(capture.grab(), cfg.scan_confirm_region)
        ok = harvester.scan_succeeded([ocr.read_text(crop, cfg.tesseract_path)])
        self.log_harvest.info("[scan-confirm] %s ok=%s mode=%s", where, ok, cfg.scan_confirm_mode)
        if ok or cfg.scan_confirm_mode == "observe":
            return True
        self.logger.warning("[scan-confirm] %s 未見 Local → 重新聚焦＋重掃一次", where)
        self._focus_roblox()
        harvester.execute_scan()
        crop = capture.crop(capture.grab(), cfg.scan_confirm_region)
        ok = harvester.scan_succeeded([ocr.read_text(crop, cfg.tesseract_path)])
        self.log_harvest.info("[scan-confirm] %s retry ok=%s", where, ok)
        return True   # 重試後不論成敗都繼續 sweep（寧多掃勿誤棄；失敗已留 WARNING）
```

呼叫點：`_on_enter(HARVESTING)` 的 `execute_scan()` 後加 `self._confirm_scan("enter")`；`_reharvest_sweep()` 的重掃 D2 後加 `self._confirm_scan("resweep")`。

- [ ] **Step 3: 測試＋Commit**

```bash
python -m pytest -q
git add miningbot/main.py
git commit -m "feat(harvest): D2 掃描確認接線——observe 模式先行收數據

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 4: 觀察期裁決（跨 2-3 天掛機）**

`scan_confirm_mode="observe"` 跑 2-3 天 → `Select-String "scan-confirm"`：
- `ok=False` 但該輪 sweep 有找到框 ＝ **誤陰性**（region/門檻要調）。
- 誤陰性率 <5% → 切 `enforce`。驗收：enforce 後 events.log 的「sweep 全空→人工」次數下降。

---

## Phase 3：preflight 自檢＋snapshots 保留策略

**動機**：多處**靜默降級**（盤點表 #4）——缺一個 asset 就默默變弱模式，實機跑壞才發現；`logs/snapshots` 已 632MB 且在 OneDrive 同步夾內無限成長。

### Task 3.1: `miningbot/preflight.py`（純決策＋facts 注入）

**Files:**
- Create: `miningbot/preflight.py`
- Test: `tests/test_preflight.py`（新檔，照 tests/AGENTS.md 慣例：輔助函式檔內自建）
- Modify: `miningbot/main.py`（`Bot.run()` 啟動段收集 facts → 記 log ＋ 併入既有啟動 Discord 通知）

**Interfaces:**
- Produces: `PreflightFacts`（dataclass，main 收集 I/O 事實）；`run_checks(facts) -> list[tuple[str, str]]`（`[(level, message)]`，level ∈ {"WARN","INFO"}）

- [ ] **Step 1: 失敗測試**（節錄核心案例；每條檢查至少一正一反）

```python
from miningbot.preflight import PreflightFacts, run_checks

def facts(**kw):
    base = dict(marker_real_count=3, chill_ref_count=6, rare_ores_json_age_days=10,
                ores_all_present=True, d4_cooldown_present=True, discord_token_set=True,
                tesserocr_ok=True, rapidocr_ok=True, log_dir_abspath="C:/x/logs",
                snapshots_total_mb=100, audio_decimate=8, audio_interval_s=0.3)
    base.update(kw)
    return PreflightFacts(**base)

def test_run_checks_all_good_yields_no_warnings():
    assert [m for lv, m in run_checks(facts()) if lv == "WARN"] == []

def test_missing_markers_warns_pure_hsv_fallback():
    warns = [m for lv, m in run_checks(facts(marker_real_count=0)) if lv == "WARN"]
    assert any("純 HSV" in m for m in warns)

def test_few_chill_refs_warns_family_coverage():
    # H034：chill 至少 4+ 音效家族，單參考必漏
    warns = [m for lv, m in run_checks(facts(chill_ref_count=2)) if lv == "WARN"]
    assert any("chill" in m for m in warns)

def test_chill_ref_budget_overrun_warns():
    # 12 refs×k=4 一輪 ~312ms > 0.3s 間隔必積壓（config 註解實測值：~12ms/ref @k=8）
    warns = [m for lv, m in run_checks(facts(chill_ref_count=30)) if lv == "WARN"]
    assert any("積壓" in m or "預算" in m for m in warns)

def test_onedrive_log_dir_with_big_snapshots_warns():
    warns = [m for lv, m in run_checks(facts(
        log_dir_abspath="C:/Users/p/OneDrive/Desktop/game/logs",
        snapshots_total_mb=700)) if lv == "WARN"]
    assert any("OneDrive" in m for m in warns)

def test_stale_rare_ores_json_warns_fetch_ores():
    warns = [m for lv, m in run_checks(facts(rare_ores_json_age_days=90)) if lv == "WARN"]
    assert any("fetch_ores" in m for m in warns)
```

- [ ] **Step 2: 確認失敗 → 實作**

`miningbot/preflight.py`：

```python
"""啟動自檢：把「靜默降級」變成看得見的警告。

純決策層——main 收集 I/O 事實（檔案存在/計數/大小/引擎可用性）塞進 PreflightFacts，
run_checks 只做判斷（可測、禁 mock 規範友善）。每條警告對應一個文件明載的降級路徑。
"""
from dataclasses import dataclass

_MS_PER_REF_K8 = 13.0     # k=8 實測 8 refs ~98ms、12 refs ~131ms（config 註解）→ 保守取 13ms/ref
_BUDGET_FRAC = 0.8        # 音訊執行緒預算：一輪比對不得吃超過 interval 的 8 成

@dataclass
class PreflightFacts:
    marker_real_count: int          # assets/markers 無 alpha 實機裁圖數（形狀確認集）
    chill_ref_count: int            # assets/chill_refs/*.wav 數
    rare_ores_json_age_days: float  # assets/rare_ores.json mtime 距今天數；缺檔給 -1
    ores_all_present: bool
    d4_cooldown_present: bool
    discord_token_set: bool
    tesserocr_ok: bool
    rapidocr_ok: bool
    log_dir_abspath: str
    snapshots_total_mb: float
    audio_decimate: int
    audio_interval_s: float

def run_checks(f: PreflightFacts) -> list:
    out = []
    if f.marker_real_count == 0:
        out.append(("WARN", "assets/markers 無實機裁圖 → 追蹤框偵測退回純 HSV（形狀確認停用）"))
    if f.chill_ref_count == 0:
        out.append(("WARN", "chill_refs 空 → 退回單一參考檔（H034：至少 4+ 音效家族，單參考必漏）"))
    elif f.chill_ref_count < 4:
        out.append(("WARN", f"chill 參考只有 {f.chill_ref_count} 個（<4 家族），漏抓風險高（H034）"))
    est_ms = f.chill_ref_count * _MS_PER_REF_K8 * (8 / max(f.audio_decimate, 1))
    if est_ms > f.audio_interval_s * 1000 * _BUDGET_FRAC:
        out.append(("WARN", f"chill 參考 {f.chill_ref_count} 個估 {est_ms:.0f}ms/輪，"
                            f"超出 {f.audio_interval_s}s 間隔預算 → 音訊積壓風險，調 audio_match_decimate"))
    if f.rare_ores_json_age_days < 0:
        out.append(("WARN", "assets/rare_ores.json 缺 → fuzzy 兜底/三態分類降級全 unknown（跑 fetch_ores）"))
    elif f.rare_ores_json_age_days > 60:
        out.append(("WARN", f"rare_ores.json 已 {f.rare_ores_json_age_days:.0f} 天未更新，"
                            f"遊戲更新後記得跑 fetch_ores"))
    if not f.ores_all_present:
        out.append(("WARN", "assets/ores_all.json 缺（fetch_ores 產物）"))
    if not f.d4_cooldown_present:
        out.append(("INFO", "d4_cooldown.png 缺 → D4 退回定時刷新後備模式"))
    if not f.discord_token_set:
        out.append(("INFO", "Discord token 未設 → 通知/遠距命令停用"))
    if not f.tesserocr_ok:
        out.append(("WARN", "tesserocr 不可用 → 退回 pytesseract（每次 OCR +2.5s，boost 偵測會被餓死）"))
    if not f.rapidocr_ok:
        out.append(("WARN", "RapidOCR 不可用 → 聊天 OCR 退回 tesseract 三 pass（讀歪類假陰性風險回升）"))
    if "onedrive" in f.log_dir_abspath.lower() and f.snapshots_total_mb > 500:
        out.append(("WARN", f"log 目錄在 OneDrive 同步夾且 snapshots 已 {f.snapshots_total_mb:.0f}MB"
                            f" → 同步負擔/IO 干擾；考慮 log_dir 移出或依賴保留策略"))
    return out
```

main 接線（`Bot.run()` 啟動段，背景執行即可）：收集 facts（`os.path`/`glob`/引擎 import 試探——引擎試探沿用 ocr 模組既有的 init 成敗旗標）→ `for lv, m in run_checks(f): logger.warning/info(m)` → WARN 條目併進既有啟動 Discord 通知文字。

- [ ] **Step 3: 通過＋Commit**

```bash
python -m pytest -q
git add miningbot/preflight.py tests/test_preflight.py miningbot/main.py
git commit -m "feat(preflight): 啟動自檢——靜默降級現形（markers/chill refs/OCR 引擎/資料檔/OneDrive）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3.2: snapshots 保留策略

**Files:**
- Modify: `miningbot/diagnostics.py`、`miningbot/config.py`、`miningbot/main.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Produces: `plan_snapshot_cleanup(entries, now_ts, max_age_days, max_total_mb) -> list[str]`——entries=`[(path, mtime_ts, size_bytes)]`，回傳應刪路徑（純函式，I/O 由 main 的背景執行緒做）

- [ ] **Step 1: 失敗測試**

```python
from miningbot.diagnostics import plan_snapshot_cleanup

DAY = 86400.0

def test_cleanup_deletes_only_expired_when_under_cap():
    entries = [("old.png", 0.0, 10), ("new.png", 40 * DAY, 10)]
    assert plan_snapshot_cleanup(entries, now_ts=41 * DAY,
                                 max_age_days=30, max_total_mb=1000) == ["old.png"]

def test_cleanup_evicts_oldest_first_to_meet_cap():
    mb = 1024 * 1024
    entries = [("a.png", 1 * DAY, 600 * mb), ("b.png", 2 * DAY, 600 * mb),
               ("c.png", 3 * DAY, 600 * mb)]
    got = plan_snapshot_cleanup(entries, now_ts=4 * DAY, max_age_days=365, max_total_mb=1024)
    assert got == ["a.png", "b.png"]   # 刪到 ≤1GB，留最新

def test_cleanup_noop_when_fresh_and_small():
    entries = [("a.png", 9 * DAY, 100)]
    assert plan_snapshot_cleanup(entries, now_ts=10 * DAY,
                                 max_age_days=30, max_total_mb=1000) == []
```

- [ ] **Step 2: 實作**

```python
def plan_snapshot_cleanup(entries, now_ts, max_age_days, max_total_mb):
    """快照保留決策：先刪過期，仍超容量上限就從最舊開始刪到達標。

    純函式（entries 由呼叫端 os.scandir 收集）；632MB/OneDrive 同步夾的實測痛點對策。
    """
    cutoff = now_ts - max_age_days * 86400.0
    doomed = [p for p, m, _ in entries if m < cutoff]
    keep = sorted(((p, m, s) for p, m, s in entries if m >= cutoff), key=lambda e: e[1])
    total = sum(s for _, _, s in keep)
    cap = max_total_mb * 1024 * 1024
    i = 0
    while total > cap and i < len(keep):
        doomed.append(keep[i][0])
        total -= keep[i][2]
        i += 1
    return doomed
```

`config.py`（記錄/診斷區段）：

```python
    snapshot_retention_enabled: bool = True      # 啟動時清理過舊/過量快照（實測 632MB 且在 OneDrive 同步夾）
    snapshot_max_age_days: int = 30              # 快照保留天數（trace/review 排錯過了熱度就不會再看）
    snapshot_max_total_mb: int = 2048            # snapshots 總量上限，超過從最舊開始刪
```

main 接線：`Bot.run()` 啟動時丟背景執行緒——`os.scandir` 遞迴收集 `logs/snapshots` 下檔案 →（entries）→ `plan_snapshot_cleanup` → 逐一 `os.remove`，收尾 `logger.info("快照清理：刪 %d 檔、釋出 %.0fMB", ...)`。**只碰 `log_dir/snapshots` 底下**，其他一概不動。

- [ ] **Step 3: 通過＋Commit＋實機**

```bash
python -m pytest -q
git add miningbot/diagnostics.py miningbot/config.py miningbot/main.py tests/test_diagnostics.py
git commit -m "feat(diagnostics): 快照保留策略——30 天/2GB 上限，堵 OneDrive 同步夾無限膨脹

Co-Authored-By: Claude <noreply@anthropic.com>"
```

實機驗收：首次啟動 log 見清理統計；`du -sh logs/snapshots` 降到 cap 內；隔天再啟動為 no-op。

> ⚠ **使用者決策點**：預設 30 天/2GB 會真的刪舊快照（僅限 bot 自產的 `logs/snapshots`，不碰 `C:\Users\puppy\OneDrive\Pictures\Roblox` 的手動 ground-truth 截圖）。若想全留，把 `snapshot_retention_enabled=False`、改走「log_dir 移出 OneDrive」路線（config 一行改絕對路徑）。

---

## Phase 4：世界資料完備

### Task 4.1: 礦名反推世界 `game_data.detect_world_from_ore`

**動機**：7/9 世界 events 空 → 事件式偵測永遠鎖不了 → `common_ore_names()` 永遠用保守聯集（同名礦跨世界階級不同時，可能把當前世界的高階目標誤排除）。被動聊天行（Surreal/Mythic）挖礦時源源不絕——礦名是比事件更高頻的世界信號，且 **verify OCR 已經在讀聊天行，零額外 OCR 成本**。

**Files:**
- Modify: `miningbot/game_data.py`、`miningbot/main.py`
- Test: `tests/test_game_data.py`

**Interfaces:**
- Produces: `detect_world_from_ore(ore_name: str) -> World | None`——剝變體/冠詞後（沿用 `classify_found_ore` 同一套前處理）在各世界 `common_ores` 找 startswith 命中；**唯一命中一個世界才回傳**，跨世界同名回 None（保守，同事件式偵測的規則）

- [ ] **Step 1: 失敗測試**（從匯入表挑實名——Digita 的 `Hyposhock` 只在 World 0、`Heartstone` 只在 Lucernia；跨世界撞名案例從 fetch_ores 的衝突報告挑一個）

```python
def test_detect_world_from_ore_unique_name_locks_world():
    w = game_data.detect_world_from_ore("Hyposhock")
    assert w is not None and w.name == "Digita"

def test_detect_world_from_ore_variant_prefix_stripped():
    w = game_data.detect_world_from_ore("an ionized Heartstone")
    assert w is not None and w.name == "Lucernia"

def test_detect_world_from_ore_ambiguous_or_unknown_returns_none():
    assert game_data.detect_world_from_ore("NotARealOre") is None
    # 跨世界同名（fetch_ores 衝突報告首例，換成實際存在的名字）：
    # assert game_data.detect_world_from_ore("<兩世界都有的礦>") is None
```

- [ ] **Step 2: 實作**（結構同 `detect_world` 事件版：掃 `WORLDS`、唯一命中才鎖；剝前綴呼叫既有 `_strip_variant` 路徑）＋跑綠。

- [ ] **Step 3: main 接線（零額外 OCR）**

`_verify_chat_ocr` 與 `_late_chat_confirm` 已萃取的「新增行」礦名（帳本路徑）→ 逐名呼叫 `detect_world_from_ore` → 命中且 `self._world` 未鎖 → 沿用既有 `set_world` 流程（log INFO「世界鎖定（礦名反推）」）。MINING 期間的聊天輪詢版**不做**（要加 OCR 成本，等實測發現鎖定太慢再議）。

- [ ] **Step 4: Commit**

```bash
git add miningbot/game_data.py miningbot/main.py tests/test_game_data.py
git commit -m "feat(world): 礦名反推世界鎖定——events 空的 7 世界也能收斂排除清單

Co-Authored-By: Claude <noreply@anthropic.com>"
```

驗收：在非 Aesteria/Lucernia 世界掛機，第一次採集 verify 後（或 30 分鐘內）log 出現世界鎖定。

### Task 4.2: fetch_ores 低階底名 advisory

**動機**：H039 教訓——Rare/Master 底名（如 Heartstone）的 ionized/spectral 變體會被動進聊天，缺列＝假 special/假 rare count；現在只能等實機「⚠ 未知礦名」警告一個補一個。fetch_ores 早已抓全 tier 資料（663 礦，commit 253ec8d），只是輸出時濾掉——加一個 advisory 輸出，人工一次補齊。

**安全分析**：Rare/Master 永非 D3 目標（chill 只對 Exotic+），列底名不會重演 H014「把採集目標誤排除」；「Exotic 以上絕不可列」既有測試繼續鎖住。**清單仍人工維護**——工具只印 advisory，不自動寫入 game_data。

**Files:**
- Modify: `miningbot/fetch_ores.py`
- Test: `tests/test_fetch_ores.py`

**Interfaces:**
- Produces: `low_tier_advisory(all_ores: list[dict]) -> list[dict]`——過濾出 tier ∈ {"Rare","Master"} 的底名（照世界分組排序）；CLI 加 `--audit-low-tiers` 印表

- [ ] **Step 1: 失敗測試**

```python
def test_low_tier_advisory_keeps_only_rare_and_master():
    ores = [{"ore": "A", "tier": "Rare", "world": "X"},
            {"ore": "B", "tier": "Master", "world": "X"},
            {"ore": "C", "tier": "Exotic", "world": "X"},      # D3 目標，絕不可入 advisory
            {"ore": "D", "tier": "Surreal", "world": "X"}]     # 已由主清單涵蓋
    got = fetch_ores.low_tier_advisory(ores)
    assert [o["ore"] for o in got] == ["A", "B"]
```

- [ ] **Step 2: 實作＋CLI 旗標＋跑綠＋Commit**

```bash
git add miningbot/fetch_ores.py tests/test_fetch_ores.py
git commit -m "feat(data): fetch_ores --audit-low-tiers——Rare/Master 底名 advisory，H039 類缺口事前補

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 3: 資料任務（人工過目）**：跑 `python -m miningbot.fetch_ores --audit-low-tiers`，把當前世界（Lucernia/Aesteria 優先）的 Rare/Master 底名人工審核後補進 `game_data` 各世界 `common_ores`（tier 照實填 Rare/Master），每加一批跑 `pytest -q`（「Exotic+ 絕不可列」鎖必須仍綠）。

**外部依賴（非程式任務，列此追蹤）**：7 個新世界的 `events` 資料需人工從 wiki 各世界頁整理＋實機驗證後填入（`_AESTERIA_EVENTS` 格式）。填入即自動獲得：該世界 D4 keep/reroll＋事件式世界偵測。

---

## Phase 5：追蹤框模板/fixture 半自動收集

**動機**：H039 出現首個新框形（enigmatic 尖刺太陽）——新階級框都要人工從 snapshots 找圖、裁圖、命名、放對資料夾。工具化把「發現新框 → 模板入庫」從 ~30 分鐘壓到 ~3 分鐘，也順手產迴歸 fixture。既有 `_diag_tracker.py` 已可帶路徑＋自動載模板，擴充即可。

**Files:**
- Modify: `_diag_tracker.py`

**設計**（離線工具，不碰 bot 執行路徑，無純邏輯新增 → 不進 pytest，人工 smoke）：

- [ ] **Step 1: 加 `--crop-to <dir>` 旗標**：診斷找到最佳候選後，以候選中心裁 `±(shape_roi_px)` 方形，存 `<dir>/<原檔名>_edge<score>.png`（分數進檔名，人工一眼挑高分）。
- [ ] **Step 2: 支援 glob 批次**：`python _diag_tracker.py "logs/snapshots/trackers/*.png" --crop-to assets/markers/staging`。
- [ ] **Step 3: 人工流程文件化**（CLAUDE.md 一行）：staging 裡挑乾淨的改名 `<tier>_tracker_real.png` 移入 `assets/markers/`；場景圖挑代表性的入 `assets/` 當 fixture。
- [ ] **Step 4: Smoke 驗收**：對 3 張既有 sweep_confirmed 快照跑批次，產出裁圖肉眼可用。

```bash
git add _diag_tracker.py CLAUDE.md
git commit -m "feat(tools): _diag_tracker --crop-to——追蹤框模板/fixture 半自動收集

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Backlog（明確緩做/不做——連同理由記錄，避免重複評估）

| 項目 | 決定 | 理由 |
|---|---|---|
| 仰角追蹤框掃描（HANDOFF E） | **緩** | H001–H039 無一例仰角漏抓證據；等 NEEDS_HUMAN 截圖出現「框在垂直視野外」實例再立案。右鍵拖曳仰角控制難度高，無證據不值得冒險 |
| chill 延遲 <0.5s／onset detection（HANDOFF J） | **緩** | 現 ~1s 是交叉相關本質限制、實戰夠用；音訊執行緒動輒積壓（6s 延遲事故前科），風險 > 收益 |
| boost 讀秒自適應頻率（spec #4 方案 B） | **緩** | 文件明載「僅在量到中段 CPU 仍痛時才上」；現 MINING tick 0.12–0.16s 未痛 |
| 截圖庫換 bettercam | **不做** | 2026-07 依賴調查已裁決：mss 非瓶頸、bettercam 冷門風險 |
| 自動賣礦/背包容量監控（HANDOFF G/L） | **先 spike** | UI 佐證不足（Capacity 顯示位置未確認）；先從 snapshots 找證據＋確認流程可行性，再決定是否立 spec。大功能不直接排 |
| tier-specific chill 模式（HANDOFF I） | **不做** | HANDOFF 自評：28 項資料任一缺失即漏抓；unified chill＋遊戲端音效開關的天然過濾已夠 |
| main.py 拆分（1967 行） | **順手做** | 熱路徑 glue 無測試防護、整體重構風險 > 可讀性收益；只在動到某區時順手抽（如日後改 Discord 命令時抽 `discord_commands.py`），不獨立立案 |
| verify 聊天 OCR 再提速 | **不做** | RapidOCR ~3s 已裁決留用；幀差閘＋episode 帳本已把 OCR 次數壓到最低 |

---

## 驗收總表

| Phase | 驗收標準 |
|---|---|
| 0 | main 分支 pytest 全綠；HANDOFF/tests-AGENTS 無過時數值 |
| 1 | harvest.log：verify 單輪 <0.8s、8s 窗口 ≥8 輪；H019/H026 fixture 測試綠；實機一次完整採集成功；輪詢中按 Q 於 1s 內中斷 |
| 2 | observe 期誤陰性 <5%；enforce 後 events.log 的 sweep 全空→人工 次數下降 |
| 3 | 啟動 log 有 preflight 摘要；故意改名一個 asset 能看到對應警告；snapshots 總量 ≤ cap 且隔日啟動 no-op |
| 4 | 非 Aesteria/Lucernia 世界掛機 30 分鐘內世界鎖定；「Exotic+ 絕不可列」測試恆綠；advisory 輸出無 Exotic+ |
| 5 | 3 張既有快照批次產出可用裁圖 |

## 計劃自審記錄（writing-plans self-review）

- 覆蓋：盤點表 #1→Phase 1、#2→Phase 2、#3→Phase 3.2、#4→Phase 3.1、#5→Phase 4.1＋外部依賴、#6→Phase 4.2、#7→Phase 1 Task 1.2。
- 已核實符號：`self._running`（main.py:679）／`self.paused`（main.py:597）／`_scene_with_patch`・`_draw_tracker`（test_vision.py:8,16）／fixture skip 模式（test_vision.py:569）／`find_tracker` 簽名（vision.py:277）。
- 型別一致：`find_tracker_near` 回傳（x,y[,edge]）全幀座標；`scan_succeeded(list[str])→bool`；`run_checks(PreflightFacts)→list[(level,msg)]`；`plan_snapshot_cleanup(entries,…)→list[path]`。
- 待執行時確認的實值（非佔位、有預設）：`scan_confirm_region` 估值需校準（Task 2.2 Step 1 即校準步驟）；Task 4.1 跨世界撞名測試名從 fetch_ores 衝突報告取實名。
