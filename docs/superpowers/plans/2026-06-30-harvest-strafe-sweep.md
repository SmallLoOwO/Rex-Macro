# 採集掃描加入 strafe 挪位 — 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 掃描稀有礦時，在基本方位短按 D 把角色挪離牆邊、身體靠側，清出中央視野，露出原本被身體/牆擋住的追蹤框。

**Architecture:** 沿用 `main._sweep_for_tracker` 既有 8 方位旋轉 + 雙幀穩定 + 形狀 edge 偵測 + 早停就地開火的架構，只插入兩處：(1) 在指定基本方位（右/後/左 = dir 2/4/6）轉動前短按 strafe 鍵挪位；(2) 整圈只有弱候選時，strafe 模式不再走回弱框（身體已飄移、舊座標不可靠），改交人工/重掃。決策抽成 `harvester` 純函式做 TDD；I/O 挪位用 `input_control.hold_key`。

**Tech Stack:** Python 3、pytest、pydirectinput、既有 `miningbot` 狀態機。

## Global Constraints

- 純邏輯改動走 TDD（先寫失敗測試）；`python -m pytest -q` 改完必須全綠。
- 視覺座標照 1920×1080；`_focus_roblox` 用 SW_MAXIMIZE，**絕不可用 SW_RESTORE**。
- 數字鍵會 toggle 裝備；strafe 用移動鍵 D，不在 D3 開火時按住。
- 所有座標/門檻集中在 `miningbot/config.py`。
- commit 訊息結尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 已在 feature 分支 `feature/harvest-strafe-sweep`，直接在此分支提交。

## File Structure

- `miningbot/config.py` — 新增 4 個 strafe 旋鈕（在 `max_harvest_attempts` 後）。
- `miningbot/harvester.py` — 新增兩個純函式 `should_strafe_at_dir`、`should_walk_back_to_weak`。
- `miningbot/input_control.py` — 新增 I/O primitive `hold_key(key, seconds)`。
- `miningbot/main.py` — `_sweep_for_tracker` 接線：迴圈內挪位、迴圈後弱候選分支。
- `tests/test_harvester.py` — config 旋鈕與兩個純函式的測試。

---

### Task 1: config 新增 strafe 旋鈕

**Files:**
- Modify: `miningbot/config.py:84`（在 `max_harvest_attempts: int = 5` 之後插入）
- Test: `tests/test_harvester.py`

**Interfaces:**
- Produces: `DEFAULT.sweep_strafe_enabled: bool`、`DEFAULT.sweep_strafe_key: str`、`DEFAULT.sweep_strafe_hold_s: float`、`DEFAULT.sweep_strafe_dirs: tuple[int,...]`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_harvester.py` 檔尾加入：

```python
# --- strafe 掃描旋鈕（採集時短按 D 挪位清視野）---
def test_config_has_strafe_knobs():
    assert DEFAULT.sweep_strafe_enabled is True
    assert DEFAULT.sweep_strafe_key == "d"
    assert DEFAULT.sweep_strafe_dirs == (2, 4, 6)   # 右/後/左；前(dir 0)與斜角不挪
    assert DEFAULT.sweep_strafe_hold_s > 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_harvester.py::test_config_has_strafe_knobs -q`
Expected: FAIL（`AttributeError: ... 'sweep_strafe_enabled'`）

- [ ] **Step 3: 加入 config 欄位**

在 `miningbot/config.py` 的 `max_harvest_attempts: int = 5` 那一行之後插入：

```python
    # 採集掃描 strafe 挪位：短按 D 把角色挪離牆邊、身體靠側，清出中央視野（露出被身體/牆擋住的追蹤框）
    sweep_strafe_enabled: bool = True            # 關閉則沿用原地掃描（不挪位、弱候選仍走回舊行為）
    sweep_strafe_key: str = "d"                  # 往右挪（與鏡頭 rotate_right 順時針掃描同向）
    sweep_strafe_hold_s: float = 0.6             # 短按秒數；使用者意圖「按幾秒」，但整圈 3 次累積位移大，預設保守，實機校準
    sweep_strafe_dirs: tuple = (2, 4, 6)         # 在這些方位（右/後/左）轉動前挪位；前(dir 0)與斜角(1/3/5/7)不挪
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_harvester.py::test_config_has_strafe_knobs -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add miningbot/config.py tests/test_harvester.py
git commit -m "feat: config 新增採集掃描 strafe 挪位旋鈕（enabled/key/hold_s/dirs）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: harvester 純函式 — 挪位時機 + 弱候選走回決策（TDD）

**Files:**
- Modify: `miningbot/harvester.py`（在 `restore_actions` 後新增兩函式）
- Test: `tests/test_harvester.py`

**Interfaces:**
- Consumes: `DEFAULT`（Task 1 的旋鈕）
- Produces:
  - `should_strafe_at_dir(dir_idx: int, cfg) -> bool`
  - `should_walk_back_to_weak(strafe_enabled: bool) -> bool`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_harvester.py` 頂部 import 補上兩個新函式與 `replace`：

```python
from dataclasses import replace
from miningbot.harvester import (next_harvest_step, HarvestState, restore_actions,
                                 decide_harvest_result, format_rotation_hint,
                                 format_harvest_id,
                                 should_strafe_at_dir, should_walk_back_to_weak)
```

並在檔尾加入：

```python
# --- should_strafe_at_dir：哪些方位轉動前要先短按 D 挪位（純函式）---
def test_strafe_at_cardinal_dirs_right_back_left():
    for d in (2, 4, 6):
        assert should_strafe_at_dir(d, DEFAULT) is True

def test_no_strafe_at_front_and_diagonals():
    for d in (0, 1, 3, 5, 7):
        assert should_strafe_at_dir(d, DEFAULT) is False

def test_strafe_disabled_never_strafes():
    cfg = replace(DEFAULT, sweep_strafe_enabled=False)
    for d in range(8):
        assert should_strafe_at_dir(d, cfg) is False

# --- should_walk_back_to_weak：整圈只有弱候選時要不要走回弱框（純函式）---
def test_strafe_mode_does_not_walk_back_to_weak():
    # strafe 模式：身體已橫向飄移，弱框舊座標不可靠 → 不走回
    assert should_walk_back_to_weak(strafe_enabled=True) is False

def test_non_strafe_mode_keeps_old_walk_back():
    # 原地掃描：維持舊行為，走回最佳弱框驗證
    assert should_walk_back_to_weak(strafe_enabled=False) is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_harvester.py -q -k "strafe or walk_back"`
Expected: FAIL（`ImportError: cannot import name 'should_strafe_at_dir'`）

- [ ] **Step 3: 實作兩個純函式**

在 `miningbot/harvester.py` 的 `restore_actions` 函式之後插入：

```python
def should_strafe_at_dir(dir_idx: int, cfg) -> bool:
    """掃描某方位前是否要先短按 strafe 鍵挪位清視野（純函式）。

    只在指定基本方位（預設 右/後/左 = dir 2/4/6）挪位；前(dir 0)與斜角方位(1/3/5/7)不挪。
    `sweep_strafe_enabled=False` 時一律 False（沿用原地掃描）。
    """
    return cfg.sweep_strafe_enabled and dir_idx in cfg.sweep_strafe_dirs


def should_walk_back_to_weak(strafe_enabled: bool) -> bool:
    """整圈只有弱候選（無一過 early_exit）時，是否走回最佳弱框開火（純函式）。

    strafe 模式下身體已橫向飄移，弱框的舊螢幕座標不再可靠 → 不走回（False），交人工/重掃。
    非 strafe（原地掃描）維持舊行為：走回最佳弱框驗證後採用（True）。
    """
    return not strafe_enabled
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_harvester.py -q -k "strafe or walk_back"`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/harvester.py tests/test_harvester.py
git commit -m "feat: harvester 純函式 should_strafe_at_dir / should_walk_back_to_weak（TDD）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: input_control.hold_key + 接線進 _sweep_for_tracker

**Files:**
- Modify: `miningbot/input_control.py`（檔尾新增 `hold_key`）
- Modify: `miningbot/main.py:920`（迴圈內挪位）、`miningbot/main.py:951-981`（弱候選分支）

**Interfaces:**
- Consumes: `should_strafe_at_dir`、`should_walk_back_to_weak`（Task 2）；`cfg.sweep_strafe_*`（Task 1）
- Produces: `input_control.hold_key(key: str, seconds: float)`

- [ ] **Step 1: 新增 hold_key I/O primitive**

在 `miningbot/input_control.py` 檔尾（`rotate_left` 之後）加入：

```python
def hold_key(key: str, seconds: float):
    """按住某鍵 seconds 秒再放開（strafe 挪位用：短按 D 幾秒把角色挪離牆/身體靠側清視野）。"""
    pydirectinput.keyDown(key)
    time.sleep(seconds)
    pydirectinput.keyUp(key)
    time.sleep(_STEP)
```

- [ ] **Step 2: 迴圈內插入挪位**

在 `miningbot/main.py` 的 `_sweep_for_tracker` 迴圈開頭（`for i in range(NUM_DIRS):` 之下、`f = capture.grab()` 之上）插入挪位：

```python
        for i in range(NUM_DIRS):
            if harvester.should_strafe_at_dir(i, cfg):
                self.log_harvest.info("[%s] sweep dir=%d: 短按 %s %.2fs 挪位清視野",
                                      hid, i, cfg.sweep_strafe_key, cfg.sweep_strafe_hold_s)
                ic.hold_key(cfg.sweep_strafe_key, cfg.sweep_strafe_hold_s)
                time.sleep(0.1)                 # 挪位後沉澱，等畫面/鏡頭穩定再擷幀
            f = capture.grab()
```

（其餘偵測、早停、`rotate_right`/`net_rotations` 邏輯保持不變。）

- [ ] **Step 3: 弱候選分支改為 strafe 模式不走回**

把 `miningbot/main.py` 迴圈後、`if not candidates:` 區塊之後到 `return None` 為止（原 best_dir 走回驗證那段，約 955–981 行）改寫為：strafe 模式不走回。將原本：

```python
        best_dir, best_pos = candidates[0]  # 取第一個穩定候選（colored_frac 最高的）
```

之前插入分支：

```python
        if not harvester.should_walk_back_to_weak(cfg.sweep_strafe_enabled):
            self.log_harvest.info(
                "[%s] sweep: 只有 %d 個弱候選（無一過 early_exit=%.2f）；strafe 模式不走回弱框（身體已飄移、舊座標不可靠）→ 交人工/重掃",
                hid, len(candidates), cfg.tracker_shape_early_exit)
            return None

        best_dir, best_pos = candidates[0]  # 取第一個穩定候選（colored_frac 最高的）
```

（保留其後原本的走回 / verify / return 邏輯不動 —— 那段只在 `sweep_strafe_enabled=False` 時才會執行。`return None` 後，呼叫端 `_tick_harvest` 既有邏輯走 `_harvest_giveup`「未找到追蹤框」交人工。）

- [ ] **Step 4: 跑全測試確認綠**

Run: `python -m pytest -q`
Expected: PASS（全綠；既有測試不受影響，新測試通過）

- [ ] **Step 5: 靜態檢查無語法錯**

Run: `python -c "import miningbot.main, miningbot.input_control, miningbot.harvester"`
Expected: 無輸出、exit 0（import 成功，接線無語法/名稱錯誤）

- [ ] **Step 6: Commit**

```bash
git add miningbot/input_control.py miningbot/main.py
git commit -m "feat: 採集掃描在右/後/左方位短按 D 挪位清視野；strafe 模式弱候選不走回改交人工

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 實機驗證點（人工驗收，非自動測試）

實作完成、單元測試全綠後，啟動 `python -m miningbot.main` 觸發一次採集，對照確認：

1. **挪位確實清視野**：dir 2/4/6 擷幀時角色靠右、中央視野清空，原本被身體擋的追蹤框露出。
2. **短按後身體仍離心**：若鏡頭把角色拉回正中，調 `sweep_strafe_hold_s` 或在挪位後縮短沉澱時間（趁 D 生效窗內擷幀）。
3. **飄移可接受**：整圈 3 次挪位後角色偏右距離不致跑出礦區；過大則調小 `sweep_strafe_hold_s`。
4. **D 不干擾開火**：就地開火（按 2→3→點擊）期間未按住 D，數字鍵/點擊正常。
5. **弱候選交人工**：只有弱框時走 `_harvest_giveup`，不再走回弱框亂射。

對應 spec 風險點（右緣自我遮擋、`reference_bgr` 差分變弱）一併留意 harvest.log 偵測敘事。

## Self-Review

- **Spec coverage**：機制（短按 D）✅Task 1+3；挪位時機（右/後/左 dir 2/4/6）✅Task 2 `should_strafe_at_dir`+Task 3 接線；就地開火不走回✅沿用既有早停；弱框不走回交人工✅Task 2 `should_walk_back_to_weak`+Task 3 分支；不追蹤位移✅（無 net_strafe）；採後接受飄移✅（未動 restore_view/init）；config 旋鈕✅Task 1；TDD 純函式✅Task 1/2。
- **Placeholder scan**：無 TBD/TODO；每個 code step 皆含完整程式碼。
- **Type consistency**：`should_strafe_at_dir(dir_idx, cfg)`、`should_walk_back_to_weak(strafe_enabled)`、`hold_key(key, seconds)`、`sweep_strafe_{enabled,key,hold_s,dirs}` 全計畫一致。
