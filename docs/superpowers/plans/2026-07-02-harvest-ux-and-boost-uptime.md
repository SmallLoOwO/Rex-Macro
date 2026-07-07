# 採集 UX 調整 + boost 不空轉 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 `docs/superpowers/specs/2026-07-02-harvest-ux-and-boost-uptime-design.md` 實作 4 項採集/boost 改動：放棄截圖拆 4 張、放棄視角依有無框分流、boost 高頻偵測不空轉、移除 sweep strafe 挪位。

**Architecture:** 沿用既有狀態機。把「放棄時的視角+截圖決策」抽成 `harvester.plan_giveup()` 純函式（TDD），`main.Bot._harvest_giveup` 只做 I/O glue 呼叫它。boost 用既有節流骨架換高頻參數。strafe 是回退，刪函式/config/測試。

**Tech Stack:** Python 3、pytest（純邏輯 TDD）、OpenCV/numpy、mss、pydirectinput、tesserocr、Discord（notify）。

## Global Constraints

- **平台**：Windows 專用。測試命令 `python -m pytest -q`（從專案根目錄），**每個 Task 結束必須全綠**。
- **純邏輯 TDD**：新邏輯先寫失敗測試再實作。測試只碰純函式/純方法。
- **測試硬規則（`tests/AGENTS.md`，覆寫 spec 的「mock `_hsnap_crop`」建議）**：committed 測試**絕不用** `unittest.mock` / `monkeypatch` / `conftest.py` / `parametrize`。要驗 I/O glue，就把純決策抽出來測（本 plan 即用 `plan_giveup` 做到）。`main.Bot` 的 I/O glue 屬「untested by design」，靠純函式測試 + 全套件不回歸 + 實機手動驗證。
- **測試不寫死門檻**：`from miningbot.config import DEFAULT`，非預設值就本地 `Config(...)`。
- **座標/門檻集中在 `miningbot/config.py`**；輸入保留既有延遲。
- **commit 慣例**：先確認在 feature 分支（現為 `feature/chill-latency-resume-hotkeys`，非 main，OK）；commit 訊息結尾加
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **實機校準需 Roblox 開著**（最大化填滿螢幕、1920×1080 校準基準）；截圖指令見各 Task 的手動檢查點。

## File Structure

- `miningbot/harvester.py` — 新增純函式 `plan_giveup()` + `GiveupPlan`/`GiveupCrop` dataclass（Task 1）；刪 `should_strafe_at_dir`/`should_walk_back_to_weak`（Task 4）。
- `miningbot/config.py` — 新增 `chat_review_region`/`backpack_review_region`、移除 `human_review_region`（Task 2）；新增 `boost_buff_scales`、調小 `boost_check_interval_s`（Task 3）；移除 5 個 `sweep_strafe_*`（Task 4）。
- `miningbot/main.py` — 重寫 `_harvest_giveup`（Task 2）；`_boost_needs_refresh` 換 scales 參數（Task 3）；`_sweep_for_tracker` 移除 strafe 區塊與 walk-back gate（Task 4）。
- `tests/test_harvester.py` — 加 `plan_giveup` 測試（Task 1）；刪 strafe 測試與 import（Task 4）。
- `tests/test_miner.py` — 加 boost 高頻 config-lock 測試（Task 3）。
- `CLAUDE.md` — 更新放棄截圖段（Task 2）、boost 節流段（Task 3）。

---

## Task 1: `plan_giveup` 純決策（需求 A + C 的核心邏輯）

把「放棄時要不要轉回視角、主圖用追蹤框還是 4 張左側對比裁圖、以及那 4 張的順序/來源」抽成純函式，供 `_harvest_giveup` 呼叫。這是本 plan 唯一可完整 TDD 的邏輯單元。

**Files:**
- Modify: `miningbot/harvester.py`（在 `format_rotation_hint` 之後、`prepare_scan` 之前插入）
- Test: `tests/test_harvester.py`

**Interfaces:**
- Produces:
  - `GiveupCrop(source: str, region: str, label: str)` — frozen dataclass。`source ∈ {"before","after"}`、`region ∈ {"chat","backpack"}`、`label` 為快照檔名（`_hsnap_crop` 會再前綴本輪 harvest_id）。
  - `GiveupPlan(restore_view: bool, tracker_view: bool, review_crops: tuple)` — frozen dataclass。
  - `plan_giveup(face_tracker: bool) -> GiveupPlan`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_harvester.py` 的 import 區塊把 harvester import 補上新名稱（保留既有名稱，strafe 名稱本 Task 先不動，Task 4 再刪）：

```python
from miningbot.harvester import (next_harvest_step, HarvestState, restore_actions,
                                 decide_harvest_result, format_rotation_hint,
                                 format_harvest_id,
                                 should_strafe_at_dir, should_walk_back_to_weak,
                                 plan_giveup, GiveupPlan, GiveupCrop)
```

在檔案末尾加測試：

```python
# --- plan_giveup：放棄時視角處置 + 截圖方案（純函式，需求 A+C）---
def test_giveup_face_tracker_keeps_view_and_shows_tracker():
    # 有框採不到：不轉回、保持面對追蹤框，主圖給追蹤框裁圖
    plan = plan_giveup(face_tracker=True)
    assert plan.restore_view is False
    assert plan.tracker_view is True
    assert plan.review_crops == ()

def test_giveup_no_tracker_restores_and_uses_four_review_crops():
    # 沒找到框：轉回原視角 + 4 張左側前後對比裁圖
    plan = plan_giveup(face_tracker=False)
    assert plan.restore_view is True
    assert plan.tracker_view is False
    assert len(plan.review_crops) == 4

def test_giveup_review_crops_order_is_chat_then_backpack_before_after():
    # Discord 2x2 縮圖：上排聊天(前/後)、下排背包(前/後)
    crops = plan_giveup(face_tracker=False).review_crops
    assert [(c.source, c.region) for c in crops] == [
        ("before", "chat"), ("after", "chat"),
        ("before", "backpack"), ("after", "backpack"),
    ]

def test_giveup_review_crop_labels_are_unique_and_descriptive():
    crops = plan_giveup(face_tracker=False).review_crops
    labels = [c.label for c in crops]
    assert labels == ["giveup_before_chat", "giveup_after_chat",
                      "giveup_before_backpack", "giveup_after_backpack"]
    assert len(set(labels)) == 4
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_harvester.py -q`
Expected: FAIL — `ImportError: cannot import name 'plan_giveup'`（或 `GiveupPlan`/`GiveupCrop`）。

- [ ] **Step 3: 實作純函式**

在 `miningbot/harvester.py` 的 `format_rotation_hint` 之後、`prepare_scan` 之前插入：

```python
@dataclass(frozen=True)
class GiveupCrop:
    """放棄時要裁的一張左側對比圖（純資料）。

    source: "before"（本輪 _pre_scan_ref，採集開始基準）| "after"（放棄當下 frame）
    region: "chat"（左上 has-found 訊息）| "backpack"（左下 NORMAL 面板）
    label : 快照 label（_hsnap_crop 會再前綴本輪 harvest_id）
    """
    source: str
    region: str
    label: str


@dataclass(frozen=True)
class GiveupPlan:
    """採集放棄時的視角處置 + 截圖方案（純資料）。

    restore_view : 轉回原視角？（無框才轉回、便於判斷礦是否已被玩家挖走）
    tracker_view : 主圖用「面對追蹤框」裁圖？（有框採不到時 True，人工可據此手動採）
    review_crops : 無框路徑的 4 張左側前後對比裁圖（有框路徑為空 tuple）
    """
    restore_view: bool
    tracker_view: bool
    review_crops: tuple


# 無框放棄路徑固定的 4 張裁圖（Discord 2x2：上排聊天前後、下排背包前後）
_REVIEW_CROPS = (
    GiveupCrop("before", "chat", "giveup_before_chat"),
    GiveupCrop("after", "chat", "giveup_after_chat"),
    GiveupCrop("before", "backpack", "giveup_before_backpack"),
    GiveupCrop("after", "backpack", "giveup_after_backpack"),
)


def plan_giveup(face_tracker: bool) -> GiveupPlan:
    """採集放棄時依「有無追蹤框」決定視角處置 + 截圖方案（純函式，需求 A+C）。

    face_tracker=True（找到追蹤框但採不到，D3 階段失敗）：**不轉回**視角、保持面對追蹤框，
      主圖給「面對追蹤框」裁圖，人工一眼看到框可手動採。
    face_tracker=False（沒找到框 / 掃描超時 / 採到但重新聚焦失敗）：**轉回**原視角（快速恢復、
      便於判斷礦是否已被玩家挖走），附 4 張左側前後對比裁圖（聊天×前後、背包×前後）。
    """
    if face_tracker:
        return GiveupPlan(restore_view=False, tracker_view=True, review_crops=())
    return GiveupPlan(restore_view=True, tracker_view=False, review_crops=_REVIEW_CROPS)
```

（`harvester.py` 頂部已 `from dataclasses import dataclass`，無需再 import。）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_harvester.py -q`
Expected: PASS（含新 4 個 `plan_giveup` 測試）。

- [ ] **Step 5: 跑全套件確認不回歸**

Run: `python -m pytest -q`
Expected: 全綠。

- [ ] **Step 6: Commit**

```bash
git add miningbot/harvester.py tests/test_harvester.py
git commit -m "feat(harvest): plan_giveup 純決策（放棄視角分流+4張截圖方案）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 把 A+C 接進 `_harvest_giveup`（config 區域 + glue + 文件）

用 Task 1 的 `plan_giveup` 重寫 `_harvest_giveup`：加 `face_tracker` 參數、有框走追蹤框裁圖不轉回、無框走 4 張左側裁圖並轉回。新增兩個裁圖區域 config、移除舊 `human_review_region`。此為 `main.Bot` I/O glue（untested by design）→ 靠全套件不回歸 + 實機手動驗證。

**Files:**
- Modify: `miningbot/config.py:25-35`（region 區塊）
- Modify: `miningbot/main.py:1110-1153`（`_harvest_giveup` 全體）
- Modify: `miningbot/main.py:1188`（D3 階段超時 giveup 呼叫端，傳 `face_tracker=True`）
- Modify: `CLAUDE.md:95-98`（放棄截圖段）

**Interfaces:**
- Consumes（來自 Task 1）：`harvester.plan_giveup(face_tracker) -> GiveupPlan`；`GiveupPlan.restore_view/tracker_view/review_crops`；`GiveupCrop.source/region/label`。
- Consumes（既有）：`self._save_tracker_screenshot(frame, marker, net_rotations) -> str|None`（`main.py:745`）；`self._hsnap_crop(frame, region, label) -> str|None`（`main.py:1335`）；`harvester.restore_view(net)`；`capture.grab()`。

- [ ] **Step 1: 新增裁圖區域 config、移除 `human_review_region`**

在 `miningbot/config.py` 把現有這段：

```python
    # 採集放棄 NEEDS_HUMAN 附的「前/後對比」左側裁圖範圍：上半＝聊天/has-found 訊息、
    # 下半＝NORMAL 背包礦物清單與數量。人工靠這兩者判定「礦是否已被採走」（新 has-found 行
    # 或背包數量增加＝已採到＝好假警報）。左側 UI 是螢幕覆蓋層、不隨鏡頭角度變，前/後同框可直接對比。
    human_review_region: Region = field(default_factory=lambda: Region(0, 105, 470, 970))
```

換成（拆兩區，各貼近 Discord 縮圖比例；見 2026-07-02 spec 需求 A）：

```python
    # 採集放棄 NEEDS_HUMAN 附的左側「前/後對比」裁圖：拆成「聊天（寬短）」與「背包（窄高）」兩區，
    # 各自更貼近 Discord 縮圖比例、砍掉右側沒用的粉紅場景（見 2026-07-02 spec 需求 A）。
    # before＝本輪 _pre_scan_ref、after＝放棄當下；左側 UI 是螢幕覆蓋層、不隨鏡頭角度變 → 前後同框
    # 可直接對比「礦是否已被採走」（新 has-found 行 / 背包數量增加＝已採到）。**backpack 需實機校準**。
    chat_review_region: Region = field(default_factory=lambda: Region(0, 110, 460, 200))     # 左上 has-found 聊天（寬短；同 chat_region 上半）
    backpack_review_region: Region = field(default_factory=lambda: Region(0, 395, 185, 660)) # 左下 NORMAL 背包（礦名+數量，窄高）；座標為估值，Step 5 實機校準
```

- [ ] **Step 2: 重寫 `_harvest_giveup`**

把 `miningbot/main.py` 現有整個 `_harvest_giveup`（`def _harvest_giveup(self, reason: str):` 起，至 `self._on_enter(State.NEEDS_HUMAN, frame)` 止）替換為：

```python
    def _harvest_giveup(self, reason: str, *, face_tracker: bool = False):
        """採集放棄 → 依「有無追蹤框」決定視角處置 + 截圖，交人工（需求 A+C）。

        face_tracker=True（D3 階段失敗、追蹤框仍在畫面）：**保持面對追蹤框、不轉回**，主圖給
          追蹤框裁圖（人工可據此手動採；不附 rotation_hint，因已正對著框）。
        face_tracker=False（沒找到框/掃描超時/採到但重新聚焦失敗）：**轉回原視角** + 附 4 張左側
          前後對比裁圖（聊天×前後、背包×前後），判定礦是否已被玩家挖走（好假警報）。

        視角/截圖決策抽在 harvester.plan_giveup（純函式、有測試）；本方法只做 I/O glue。
        """
        # NEEDS_HUMAN 事件一律帶本輪編號（Discord 顯示 [Hxxx]，與截圖/log 串連，事後一鍵搜查）
        self._needs_human_extra_meta = {"harvest_id": self.harvest.harvest_id}
        # face_tracker 需真的有 marker 才成立（防呼叫端誤傳；D3 超時路徑 marker 必已設）
        plan = harvester.plan_giveup(face_tracker and self._target_marker is not None)

        if plan.restore_view and self.harvest.net_rotations:
            self.logger.info("[%s] 採集放棄 -> 轉回原方位 net=%d",
                             self.harvest.harvest_id, self.harvest.net_rotations)
            harvester.restore_view(self.harvest.net_rotations)
            self.harvest.net_rotations = 0

        self._human_reason = reason
        frame = capture.grab()              # 轉回後重抓（tracker_view 路徑沒轉回＝面對框現況）

        if plan.tracker_view:
            # 有框採不到：主圖給「面對追蹤框」裁圖（net_rot=0：現在正對著它，免旋轉提示）
            p = self._save_tracker_screenshot(frame, self._target_marker, 0)
            if p:
                self._needs_human_extra_meta["image_paths"] = [p]
        else:
            # 無框：4 張左側前後對比裁圖。before＝本輪 _pre_scan_ref、after＝現在（放棄時）。
            region_map = {"chat": cfg.chat_review_region, "backpack": cfg.backpack_review_region}
            src_map = {"before": getattr(self, "_pre_scan_ref", None), "after": frame}
            imgs = []
            for c in plan.review_crops:
                src = src_map[c.source]
                if src is None:                 # 首輪還沒 _pre_scan_ref → 跳過該來源
                    continue
                p = self._hsnap_crop(src, region_map[c.region], c.label)
                if p:
                    imgs.append(p)
            if imgs:
                self._needs_human_extra_meta["image_paths"] = imgs

        self.state = State.NEEDS_HUMAN
        self._on_enter(State.NEEDS_HUMAN, frame)
```

> 說明：此版**移除**了舊的 `format_rotation_hint` 呼叫（rotation_hint 只在「有框」路徑有意義，而有框路徑現在不轉回、已正對著框 → 不需提示）。`harvester.format_rotation_hint` 與其測試保留（純函式、可留作日後 Discord 提示用），只是不再被 `_harvest_giveup` 呼叫。

- [ ] **Step 3: D3 階段超時的呼叫端傳 `face_tracker=True`**

在 `miningbot/main.py` 的 `_tick_harvest` D3 階段超時分支，把：

```python
            self._harvest_giveup("稀有礦採集失敗（D3 階段超時），請手動處理")
```

改成：

```python
            self._harvest_giveup("稀有礦採集失敗（D3 階段超時），請手動處理", face_tracker=True)
```

> 其餘 3 個呼叫端（sweep 超時、sweep 找不到框、「採集成功但無法重新聚焦」）維持**不傳** `face_tracker`（預設 False）：sweep 兩者本來就無框；成功後聚焦失敗屬「已採到、只是續挖失敗」→ 該轉回原視角 + 4 張左側圖，正是 `face_tracker=False` 的行為。

- [ ] **Step 4: 跑全套件確認不回歸**

Run: `python -m pytest -q`
Expected: 全綠（本 Task 改的是 I/O glue，無新單元測試；靠 Task 1 純函式測試 + 此處不回歸把關）。

- [ ] **Step 5: 【手動檢查點｜需 Roblox 開著】實機校準 backpack 區域**

先抓一張實機全幀（Roblox 最大化填滿螢幕、背包 NORMAL 面板可見）：

```bash
python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab; cv2.imwrite('logs/calib_full.png', grab())"
```

再用候選區域裁出來檢查是否剛好框住 NORMAL 面板（礦名+數字，右緣不要吃到粉紅場景，也不要切掉大數字如 112,535）：

```bash
python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab, crop; from miningbot.config import DEFAULT as c; cv2.imwrite('logs/calib_bp.png', crop(grab(), c.backpack_review_region)); cv2.imwrite('logs/calib_chat.png', crop(grab(), c.chat_review_region))"
```

用 Read 看 `logs/calib_bp.png` / `logs/calib_chat.png`。若邊界不對，回 `config.py` 微調 `backpack_review_region`（多半是 `w`：太小切掉數字、太大吃到粉紅）與 `chat_review_region` 的 `h`（涵蓋 has-found 幾行）。反覆到滿意。

> 若此步暫時無法做（Roblox 沒開），可先用估值 commit，之後再校準微調——純套件與 Task 1 測試都不依賴確切座標。

- [ ] **Step 6: 更新 CLAUDE.md 放棄截圖段**

把 `CLAUDE.md` 這段（約 95-98 行）：

```markdown
- **需人工介入（採集放棄）附「前/後左側裁圖」**（`_harvest_giveup` → `image_paths`）：before＝該輪
  `_pre_scan_ref`（採集開始基準）、after＝放棄當下，皆裁 `human_review_region`（左側背包+聊天框）。左側是
  螢幕覆蓋層、不隨鏡頭轉動 → 前後同框可直接比對「礦是否已被採走」（新 has-found 行 / 背包數量增加＝已採到）。
  舊版只在 D3 有開火才附，實測放棄幾乎都是 sweep 未找到框（D3 沒開火）→ 只送單張，故改由 `_pre_scan_ref` 當 before。
```

換成：

```markdown
- **需人工介入（採集放棄）依有無框分流（`_harvest_giveup` → `harvester.plan_giveup` 純決策）**：
  - **有框採不到**（D3 階段超時，`face_tracker=True`）：**不轉回**、保持面對追蹤框，主圖給追蹤框裁圖
    （`_save_tracker_screenshot`），人工一眼看到框可手動採；不附 rotation_hint（已正對著框）。
  - **沒找到框 / 掃描超時 / 採到但聚焦失敗**（`face_tracker=False`）：**轉回原視角** + 附 **4 張左側前後對比裁圖**
    （`chat_review_region`×前後、`backpack_review_region`×前後，Discord 2×2）。before＝該輪 `_pre_scan_ref`、
    after＝轉回後現況；左側 UI 是螢幕覆蓋層、不隨鏡頭轉動 → 前後同框可直接比對「礦是否已被採走」（新 has-found 行 /
    背包數量增加＝已採到）。舊版單一 `human_review_region` 窄高長條對 Discord 縮圖不友善，拆兩區更貼縮圖比例。
```

- [ ] **Step 7: Commit**

```bash
git add miningbot/config.py miningbot/main.py CLAUDE.md
git commit -m "feat(harvest): 放棄截圖拆4張(聊天/背包×前後)+視角依有無框分流

需求A：human_review_region 拆成 chat_review_region/backpack_review_region，
無框放棄附 4 張前後對比裁圖（Discord 2x2）。
需求C：有框採不到(D3超時)保持面對追蹤框不轉回、主圖給追蹤框裁圖。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: #4 boost 高頻偵測（不空轉，方案 A）

boost「提早補無意義、只能到期即補」→ 不空轉 ⇔ 越快偵測到瓶子消失越好。偵測已便宜（`buff_scales`+cvtColor），故把 boost 偵測**放寬到高頻**（0.2s、單尺度），D4 維持較疏。純 I/O glue，測試用 config-lock 鎖意圖，行為靠實機驗證。

**Files:**
- Modify: `miningbot/config.py:35`（`boost_check_interval_s`）+ 新增 `boost_buff_scales`
- Modify: `miningbot/main.py:207-209`（`_boost_needs_refresh` 換 scales 參數）
- Modify: `CLAUDE.md:90-94`（boost 節流段）
- Test: `tests/test_miner.py`

**Interfaces:**
- Produces（config）：`DEFAULT.boost_check_interval_s`（調小）、`DEFAULT.boost_buff_scales: tuple`（新增）。
- Consumes（既有）：`vision.find_template_edges(img, tmpl, thresh, scales)`；`_activity_ready` 續用 `cfg.buff_scales`（D4 不變）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_miner.py` 末尾加（檔案頂若尚未 import `DEFAULT`，補 `from miningbot.config import DEFAULT`；重複 import 無害）：

```python
from miningbot.config import DEFAULT

# --- boost 不空轉：高頻偵測 config-lock（需求 #4 方案 A）---
def test_boost_detection_is_high_frequency_and_single_scale():
    # 不空轉＝到期即補＝越快偵測瓶子消失越好；瓶子是固定尺寸 UI → 單尺度即可
    assert DEFAULT.boost_check_interval_s <= 0.3
    assert DEFAULT.boost_buff_scales == (1.0,)

def test_boost_checks_more_often_than_d4():
    # D4 不在意空轉 → 維持較疏節流；boost 要比 D4 更頻繁
    assert DEFAULT.boost_check_interval_s < DEFAULT.activity_check_interval_s
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_miner.py -q`
Expected: FAIL — `AttributeError: ... 'boost_buff_scales'`（config 尚無此欄位）。

- [ ] **Step 3: 改 config**

在 `miningbot/config.py` 把：

```python
    boost_check_interval_s: float = 1.0          # boost 偵測節流：每隔多久才真的 edge-match 一次（boost 撐 ~60s，不必每幀掃；節流間沿用上次結果）
```

換成：

```python
    boost_check_interval_s: float = 0.2          # boost 高頻偵測「不空轉」：boost 到期→立刻補，越快偵測瓶子消失越好（提早補無意義且浪費換道具時間，見 2026-07-02 spec #4 方案 A）
    boost_buff_scales: tuple = (1.0,)            # boost 瓶子＝固定尺寸 UI → 單尺度即可（~56ms/次），高頻掃描才不吃 CPU（D4 續用 buff_scales）
```

- [ ] **Step 4: `_boost_needs_refresh` 換成 boost 專屬 scales**

在 `miningbot/main.py` 的 `_boost_needs_refresh`，把 edge-match 的 `cfg.buff_scales` 換成 `cfg.boost_buff_scales`：

```python
            self._boost_present = vision.find_template_edges(
                capture.crop(frame, cfg.boost_indicator_region), t,
                cfg.boost_edge_threshold, cfg.boost_buff_scales) is not None
```

> `_activity_ready`（D4）**不動**，續用 `cfg.buff_scales` 的 3 尺度 + `activity_check_interval_s=3s`。

- [ ] **Step 5: 跑測試確認通過 + 全套件**

Run: `python -m pytest tests/test_miner.py -q`
Expected: PASS。
Run: `python -m pytest -q`
Expected: 全綠。

- [ ] **Step 6: 更新 CLAUDE.md boost 節流段**

把 `CLAUDE.md` 這段（約 90-94 行）：

```markdown
- **boost/D4 偵測節流 + 少尺度（`buff_scales`）**：`_boost_needs_refresh`/`_activity_ready` 原本每幀跑
  5 尺度 edge-match（共 ~344ms/幀）。改成每 `boost_check_interval_s`(1s)/`activity_check_interval_s`(3s) 才真掃、
  其餘沿用快取（`_boost_present`/`_activity_present`）；且 buff/冷卻是**固定尺寸 UI** → 用 `buff_scales=(0.9,1.0,1.1)`
  取代給會變追蹤框的 `marker_scales`(5 尺度)，實測單次 216→143ms。**注意**：節流與「boost 絕不空轉」有張力
  （見設計 spec，未來可能改成近到期高頻、中段跳過的自適應頻率）。
```

換成：

```markdown
- **boost 高頻偵測「不空轉」＋ D4 較疏節流（`buff_scales`）**：`_boost_needs_refresh`/`_activity_ready` 原本每幀跑
  5 尺度 edge-match（共 ~344ms/幀）→ 改成節流 + 少尺度、其餘沿用快取（`_boost_present`/`_activity_present`）。
  - **boost（不空轉）**：提早補 D5 無意義（不刷新、還浪費換道具時間打斷挖礦）→ 只能「到期瞬間即補」＝越快偵測
    瓶子消失越好。偵測已便宜（單尺度 `boost_buff_scales=(1.0,)` ~56ms）→ 用高頻 `boost_check_interval_s=0.2s`，
    到期延遲 ≈ 一個 tick + D5 生效，幾乎不空轉。
  - **D4（不在意空轉）**：維持 `buff_scales=(0.9,1.0,1.1)` 3 尺度 + `activity_check_interval_s=3s` 較疏。
  - 進階（未做，spec #4 方案 B）：用數字模板讀瓶底秒數做自適應頻率（中段跳過、近到期高頻）——僅在量到中段 CPU 仍痛時才上。
```

- [ ] **Step 7: Commit**

```bash
git add miningbot/config.py miningbot/main.py tests/test_miner.py CLAUDE.md
git commit -m "perf(boost): 高頻偵測不空轉（0.2s+單尺度），D4 維持較疏

需求#4方案A：boost 到期即補靠快偵測瓶子消失；boost_buff_scales=(1.0,)
單尺度 ~56ms，boost_check_interval_s 1s→0.2s。D4 續用 buff_scales/3s。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 需求 B — 移除 sweep strafe「先 D 挪位」，回歸單純八方旋轉

回退近期 strafe 功能：sweep 純 `rotate_right×7`、弱候選走回最佳框（回歸原行為）。刪 2 純函式、5 config 旋鈕、6 測試、main 兩處。最後做並保留 git 可回溯。

**Files:**
- Modify: `miningbot/main.py`（`_sweep_for_tracker`：移除 strafe 區塊 + walk-back gate）
- Modify: `miningbot/harvester.py`（刪 `should_strafe_at_dir`/`should_walk_back_to_weak`）
- Modify: `miningbot/config.py:92-97`（移除 5 個 `sweep_strafe_*`）
- Modify: `tests/test_harvester.py`（刪 import + 6 測試）

**Interfaces:**
- Removed：`harvester.should_strafe_at_dir`、`harvester.should_walk_back_to_weak`、`cfg.sweep_strafe_enabled/key/hold_s/settle_s/dirs`。
- 行為變更：整圈只有弱候選時**恢復走回最佳弱框 + verify**（原地掃描的舊行為；等同舊 `should_walk_back_to_weak(False)==True`）。

- [ ] **Step 1: 刪 test_harvester.py 的 strafe import 與 6 個測試**

改 import（移除 strafe 兩名；Task 1 已加的 `plan_giveup` 等保留）：

```python
from miningbot.harvester import (next_harvest_step, HarvestState, restore_actions,
                                 decide_harvest_result, format_rotation_hint,
                                 format_harvest_id,
                                 plan_giveup, GiveupPlan, GiveupCrop)
```

刪掉這 6 個測試（含上方 `# --- strafe ...` 註解與 `# --- should_walk_back_to_weak ...` 註解區塊）：
`test_config_has_strafe_knobs`、`test_strafe_at_cardinal_dirs_right_back_left`、
`test_no_strafe_at_front_and_diagonals`、`test_strafe_disabled_never_strafes`、
`test_strafe_mode_does_not_walk_back_to_weak`、`test_non_strafe_mode_keeps_old_walk_back`。

- [ ] **Step 2: 跑測試確認仍綠（此為刪除型任務，非 red→green）**

Run: `python -m pytest tests/test_harvester.py -q`
Expected: **PASS**。移除 6 個 strafe 測試 + import 後，其餘測試不再引用 strafe → 綠（此時 production 端 strafe 函式/config 仍在、只是沒被引用）。Step 3-6 移除 production strafe code 後，Step 7 全套件仍應綠。

> 這是「移除近期功能」的回退，程式碼與其測試一起刪、套件從綠到綠——不套 red→green。若 Step 1 後**沒有**變綠（出現 `ImportError`），代表 import 行未清乾淨或還有別的測試引用 strafe，先修到綠再往下。

- [ ] **Step 3: 刪 harvester.py 兩個純函式**

移除 `should_strafe_at_dir`（含 docstring）與 `should_walk_back_to_weak`（含 docstring）整段（位於 `format_rotation_hint` 之前）。刪除後 `restore_actions` 之後應直接接 `format_rotation_hint`（Task 1 加的 `plan_giveup` 區塊在 `format_rotation_hint` 之後，不受影響）。

- [ ] **Step 4: `_sweep_for_tracker` 移除 strafe 區塊**

在 `miningbot/main.py` 的 `_sweep_for_tracker` 迴圈開頭，移除這 5 行 strafe 區塊：

```python
            if harvester.should_strafe_at_dir(i, cfg):
                self.log_harvest.info("[%s] sweep dir=%d: 短按 %s %.2fs 挪位清視野",
                                      hid, i, cfg.sweep_strafe_key, cfg.sweep_strafe_hold_s)
                ic.hold_key(cfg.sweep_strafe_key, cfg.sweep_strafe_hold_s)
                time.sleep(cfg.sweep_strafe_settle_s)   # 挪位後沉澱，等角色停住/鏡頭穩定再擷幀（太短會在角色還滑時就轉鏡頭）
```

移除後迴圈 body 第一行應為 `f = capture.grab()`。

- [ ] **Step 5: `_sweep_for_tracker` 移除 walk-back gate**

移除這段（弱候選不走回的 gate）：

```python
        if not harvester.should_walk_back_to_weak(cfg.sweep_strafe_enabled):
            self.log_harvest.info(
                "[%s] sweep: 只有 %d 個弱候選（無一過 early_exit=%.2f）；strafe 模式不走回弱框（身體已飄移、舊座標不可靠）→ 交人工/重掃",
                hid, len(candidates), cfg.tracker_shape_early_exit)
            return None

```

移除後，`if not candidates: ... return None` 之後應直接接 `best_dir, best_pos = candidates[0]`（無條件走回最佳弱候選 + 既有 verify 邏輯）。

- [ ] **Step 6: 移除 config 的 5 個 strafe 旋鈕**

在 `miningbot/config.py` 移除整段（92-97 行，含 `# 採集掃描 strafe 挪位：...` 註解與 5 個欄位）：

```python
    # 採集掃描 strafe 挪位：短按 D 把角色挪離牆邊、身體靠側，清出中央視野（露出被身體/牆擋住的追蹤框）
    sweep_strafe_enabled: bool = True            # 關閉則沿用原地掃描（不挪位、弱候選仍走回舊行為）
    sweep_strafe_key: str = "d"                  # 往右挪（與鏡頭 rotate_right 順時針掃描同向）
    sweep_strafe_hold_s: float = 0.3             # 短按秒數；整圈 3 次累積位移大，預設保守降到 0.3（首跑安全），實機校準後再視效果加大
    sweep_strafe_settle_s: float = 0.35          # 按完 D 後等角色停下/鏡頭穩定再擷幀+轉動；原 0.1 太短，角色還在滑時就轉鏡頭→畫面糊/偵測不準（H005@23:10 根因之一）
    sweep_strafe_dirs: tuple = (2, 4, 6)         # 在這些方位（右/後/左）轉動前挪位；前(dir 0)與斜角(1/3/5/7)不挪
```

- [ ] **Step 7: 跑全套件確認全綠**

Run: `python -m pytest -q`
Expected: 全綠（strafe 測試已刪、strafe 引用已清）。

- [ ] **Step 8: grep 確認 strafe 已無殘留（docs 歷史檔除外）**

Run: `python -c "import subprocess,sys; sys.exit(0)"` 之後用 Grep 工具搜 `sweep_strafe|should_strafe|should_walk_back`，預期只剩 `docs/superpowers/specs/2026-06-30-*`、`docs/superpowers/plans/2026-06-30-*` 與本 plan / 2026-07-02 spec（歷史設計記錄，**不改**）。`miningbot/`、`tests/`、`CLAUDE.md` 應為 0 命中。

> CLAUDE.md 本來就沒有 strafe 文字（sweep 段只寫「單純八方旋轉/rotate_right×7」），故 Task 4 不需改 CLAUDE.md。

- [ ] **Step 9: Commit**

```bash
git add miningbot/main.py miningbot/harvester.py miningbot/config.py tests/test_harvester.py
git commit -m "revert(harvest): 移除 sweep strafe 挪位，回歸單純八方旋轉

需求B：刪 should_strafe_at_dir/should_walk_back_to_weak 與 5 個 sweep_strafe_*
config；弱候選恢復走回最佳框+verify（原地掃描舊行為）。可能重現身體/牆遮擋
漏抓，屬使用者決策，保留 git 可回溯。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage：**
- 需求 A（4 張截圖）→ Task 1（`plan_giveup` 的 `_REVIEW_CROPS` 順序/來源）+ Task 2（config 兩區、glue 裁 4 張、Discord 已支援多圖無需改 notify）。✅
- 需求 B（移除 strafe）→ Task 4（函式/config/測試/main 兩處全清）。✅
- 需求 C（放棄視角分流）→ Task 1（`restore_view`/`tracker_view` 分支）+ Task 2（`face_tracker` 參數、D3 超時傳 True、其餘 False）。✅
- 需求 #4（boost 不空轉，方案 A）→ Task 3（`boost_buff_scales=(1.0,)`、`boost_check_interval_s=0.2`、`_boost_needs_refresh` 換參數）。方案 B（數字模板）明確不做。✅
- 實作順序（spec 建議 A+C → #4 → B）→ Task 1/2（A+C）、Task 3（#4）、Task 4（B）。✅

**與 spec 的刻意差異（已在對應 Task 註明）：**
1. **測試手法**：spec 寫「mock `_hsnap_crop`」，但 `tests/AGENTS.md` 硬規則禁 mock。改為抽 `plan_giveup` 純函式 TDD + glue 靠不回歸/實機驗證。`verify_giveup` 在 repo 不存在（前一 session 的一次性腳本），不沿用。
2. **需求 C 分支條件**：spec 寫「`_target_marker is not None`」，但這會誤中「採集成功但無法重新聚焦」路徑（marker 仍設、但該轉回原視角）。改用顯式 `face_tracker` 參數，只有 D3 超時路徑傳 True，語意更準。
3. `human_review_region` spec 說「可保留或 deprecate」→ 直接移除（所有引用已改到新兩區）。

**Placeholder scan：** 各 code step 均為完整可貼上的內容；無 TBD/TODO/「類似上面」。backpack 座標為估值，已標明 Step 2-5 實機校準（不影響測試綠）。

**Type consistency：** `GiveupPlan.restore_view/tracker_view/review_crops`、`GiveupCrop.source/region/label` 於 Task 1 定義，Task 2 glue 一致引用；`plan_giveup(face_tracker)` 參數名貫穿；`region_map` 鍵 `"chat"/"backpack"` 對上 `GiveupCrop.region`、`src_map` 鍵 `"before"/"after"` 對上 `GiveupCrop.source`。✅
