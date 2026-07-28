# 手動瞄準精定位 驗收檢查清單（給下個 session）

> **歷史資料（已驗收完畢）**。實作已 commit（`66e922b`／`4357620`／`e3919e9`），
> 離線驗收補洞在 `96eeb78`。⚠ 下方第 0 節寫的 `assets/aim_tracker_core_green_scene.png`
> 是**錯的路徑**——`assets/**/*.png` 被 gitignore，驗收時已改放
> `tests/fixtures/aim/`（見該目錄 README）。照本檔操作前先讀 `docs/README.md`。

> **用途**：實作已外派。下個 session 拿這份**逐項打勾驗收**外派交付品是否符合
> [spec v3](2026-07-21-manual-aim-precision-checklist.md 的姊妹檔 ../specs/2026-07-21-manual-aim-zoom-refine-design.md)
> 與 [實作計畫](2026-07-21-manual-aim-precision.md)。**每一項都給了指令與期望值**，不必回頭推導。
> 紅字＝發現不符時的處置。**驗收＝全綠＋易錯點全過＋實機 log 確認**（測試綠只證邏輯）。

真值基準（harvest 101 fixture）：框在 C1、真正中心 **(851,189)**、粗格 C1 region **(640,0,320,270)**、
舊盲打粗格心 (800,135) 距框 74px。所有數字以此為準。

---

## 0. 先跑一次全域（30 秒內判生死）

- [ ] **全測試綠**：`uv run pytest -q` → 尾行 `N passed`、**0 failed**。
      ✗ 有 failed → 記下哪個 test，對照下方對應 Task 段落。
- [ ] **lint 乾淨**：`uv run ruff check . --no-cache` → `All checks passed!`
- [ ] **lock 一致**：`uv lock --check` → 無變動（本任務不該動依賴）。
- [ ] **只動該動的檔**：`git status --short` 應只含
      `miningbot/remote_aim.py`、`miningbot/vision.py`、`miningbot/main.py`、
      `miningbot/config.py`、`tests/test_remote_aim.py`、`tests/test_vision.py`、
      `tests/test_main_aim_core.py`、`assets/aim_tracker_core_green_scene.png`。
      ✗ 動到 `reentry_remote.py` 的**行為**（非純 import 借用）、或無關檔 → 退回。

---

## 1. Task 1｜純函式 `grid_cell_region` / `fov_state_consistent`（remote_aim.py）

- [ ] 兩函式存在：`rg -n "^def grid_cell_region|^def fov_state_consistent" miningbot/remote_aim.py`
- [ ] `grid_cell_region` 值正確（`uv run pytest tests/test_remote_aim.py -q -k GridCellRegion`）：
      - `("C1")` → `(640,0,320,270)`
      - `("C1",0.15)` → `(592,0,416,310)`（頂緣 clamp）
      - `("A1",0.15)` → `(0,0,368,310)`（左上兩邊 clamp）
      - `("F4",0.15)` → `(1552,770,368,310)`（右下 clamp）
      - `("C3",0.15)` → `(592,500,416,350)`（內部格對稱擴）
      - 非法（`"G1"/"A5"/""/"C"/None`）→ `None`
- [ ] `fov_state_consistent`：`(T,T)/(F,F)`→True、`(T,F)/(F,T)`→False。
- [ ] **內部 dir_idx 仍 0-based**（此函式不涉方位，但確認沒被順手改動）。

## 2. Task 2｜偵測器 `vision.detect_tracker_core` ＋ 綠 fixture

- [ ] fixture 入庫：`ls -la assets/aim_tracker_core_green_scene.png`（應存在、~2MB）。
- [ ] 函式簽名回 **4 元組**：`(cx, cy, profile_name, border_frac)｜None`，座標**相對 region**。
      `rg -n "def detect_tracker_core" miningbot/vision.py`
- [ ] 三則 fixture 測試綠：`uv run pytest tests/test_vision.py -q -k DetectTrackerCore`
      - **命中**：裁 C1（`frame[0:270,640:960]`）→ 回 `(211±15, 189±15, "green", bf≥0.15)`
        （＝絕對 (851,189)、**框真正中心非格心**；101 實測 0px、bf=0.35）。
      - **空鄰格**：裁 B1（`frame[0:270,320:640]`）→ `None`（負樣本兩側夾）。
      - **空 profiles**：`detect_tracker_core(crop, [])` → `None`。
- [ ] 🔴 **永不誤射未驗證色系**（最重要的安全性質）：確認非綠色框走 None → 退路，
      **不會亂打**。手動抽驗：`detect_tracker_core(任意非綠裁圖, 綠 profile)` 應多為 None。
      ✗ 若門檻被放寬到會在空格/雜訊誤命中 → 退回，**不可為了涵蓋而放寬**（tuning 鐵律）。

## 3. Task 3｜config

- [ ] 新欄位齊：`rg -n "tracker_core_profiles|tracker_core_min_area|tracker_core_border|remote_aim_zoom_margin_frac|remote_aim_fine_grid|remote_aim_fov_recheck_max" miningbot/config.py`
- [ ] `tracker_core_profiles` 預設**只有綠色** `("green",(40,150,150),(85,255,255))`
      （其他色系無 fixture、不得憑空加）。
- [ ] 🔴 **盲打常數已移除**：`rg remote_aim_refind_radius_px` → **0 命中**（config 與 main 都不留）。
      ✗ 還在 → 表示 main.py 的整幀重找＋盲打分支沒清乾淨，退回 Task 4。

## 4. Task 4｜接進 `_execute_remote_fire`（限縮偵測自動命中＋裁格 log）

- [ ] `_execute_remote_fire` 有 **region 參數**、呼叫端（`_tick_remote_aim`）用
      `grid_cell_region(cell, cfg.remote_aim_zoom_margin_frac)` 算好傳入。
- [ ] step 3 已換成**限縮偵測**：`rg -n "detect_tracker_core|find_tracker_near" miningbot/main.py`
      - `_execute_remote_fire` 內**應呼叫 `detect_tracker_core`**、**不再有 `find_tracker_near`**。
      - 命中 → `pos = (region.x + hit.cx, region.y + hit.cy)` 走既有 fire+verify 尾。
      - `hit` 為 None → **回報退路字串**（Task 5 前）或**進 awaiting_fine**（Task 5 後），
        **不得退回盲打粗格心**。
- [ ] 🔴 **裁格 log 素材**：`rg -n "aim_cell_dir|aim_core_miss" miningbot/main.py`
      - 每次偵測都存 `aim_cell_dir{n}_{cell}`；None 時**額外**存 `aim_core_miss_dir{n}_{cell}`。
      - 這批圖＝之後補其他色系 profile 的 fixture 來源，**必須有**。
- [ ] log 命中訊息可實機 grep：偵測命中應印類似 `AIM 限縮偵測命中 (x,y) (green bf=..)`。
- [ ] `test_main_aim_core.py` 綠：`uv run pytest tests/test_main_aim_core.py -q`。

## 5. Task 5｜放大手選退路（awaiting_fine＋連鎖放大＋FOV 閘）

> 若外派只做到 Task 1-4（先上機驗證綠框），本段標記「暫緩」，但下列 AimContext 欄位
> 可能已先落（不影響 Task 1-4 綠）。

- [ ] `AimContext` 有 zoom 欄位：`awaiting_fine`、`zoom_region`、`zoom_stack`、
      `fov_state0`（或等義的發圖 boost 狀態）、`fov_rechecks`。
- [ ] `parse_reply` 有 `awaiting_fine` 參數；`awaiting_fine=True` 時：
      裸 `B3`→`fine`、`放大 B3`→`magnify`、`退`→`zoom_back`；
      `awaiting_fine=False` 時裸 `B3`→**None**（不誤射）。
      `uv run pytest tests/test_remote_aim.py -q -k "awaiting_fine or ParseReply"`
- [ ] 借回礦純函式**非重複實作**：`rg -n "fine_cell_subregion|magnify_scale|pop_zoom_layer" miningbot/main.py`
      應是 `reentry_remote.xxx` 呼叫，不是 main 內另寫一份。
- [ ] 🔴 **FOV 一致性閘**：發放大圖時記 `_boost_present`（state0）、玩家回細格開火前
      重讀（state1）、`fov_state_consistent` 不一致 → **重發當下放大圖不開火**
      （`remote_aim_fov_recheck_max` 上限）。確認**不依賴 D5 生效**（不強制補 boost 對齊）。

## 6. 🔴 易錯點專項（回歸/契約，最容易被外派弄壞）

- [ ] **方位 1-8 沒被回退**（前一 commit a536e61 的成果）：
      `uv run pytest tests/test_remote_aim.py -q -k "ParseReply or FormatCandidate or grid"` 全綠；
      圖上標頭 `rg -n "DIR .*dir_idx \+ 1|dir_idx \+ 1" miningbot/main.py miningbot/remote_aim.py`
      仍在；grid 解析仍 `[1-8]` 後 `-1`。✗ 任何一處變回 0-7 → 退回。
- [ ] **玩家訊息同步**（見 memory `feedback_new_command_must_update_player_messages`）：
      退路 caption、FOV 重發訊息、`MANUAL_SURVEY_HELP`、aim `看不懂` 都要提到新流程
      （選格→自動抓→抓不到放大手選）。`rg -n "MANUAL_SURVEY_HELP|看不懂" miningbot/`
      逐條看有沒有漏。✗ 有新指令沒寫進玩家可見訊息 → 退回（這是重複犯過的錯）。
- [ ] **兩流程不共用狀態機**：aim 的 awaiting_fine 是 aim 自己的欄位，**沒有**把 reentry
      的 ctx/狀態機接進來（只借純函式）。off-by-one 就是共用沒同步炸的，別重演。
- [ ] **偵測跑原生解析度**：`detect_tracker_core` 吃的是**原生 cell 裁圖**（非放大圖）——
      放大只用於發給玩家看＋log。確認沒有把偵測搬到放大圖上（會慢且無必要）。

## 7. Spec v3 覆蓋對照（逐節點名）

- [ ] §5 流程：限縮偵測自動命中（Task4）＋放大手選退路（Task5）都在。
- [ ] §6 偵測器＋綠 profile：`detect_tracker_core`＋fixture 測試（Task2）。
- [ ] §7 元件邊界：三純函式＋偵測器＋借用回礦純函式，各歸其位。
- [ ] §8 log 素材：`aim_cell_*`／`aim_core_miss_*` 落 snapshot_index。
- [ ] §9 訊息：§6 易錯點已查。
- [ ] §10 測試：Task1/2/5 各 test step 綠。
- [ ] §11 config：Task3；refind 已刪。
- [ ] §12 非本次範圍：沒有順手改 D5/sweep 主路徑/其他色系門檻。

## 8. 實機驗收（結案＝下一輪掛機，非測試綠）

外派實作＋測試綠後，掛機跑一場手動瞄準，去 `Config.log_dir`（MSIX 重導見 CLAUDE.md，
一律 `Get-Content -Tail` 看內容時間戳）grep：

- [ ] **綠框自動命中**：`harvest.log` 見 `AIM 限縮偵測命中 (x,y) (green bf=..)`，
      且該發 verify 確認成功（`confirmed=True` / RARE 收尾），**不再是 74px 打空**。
- [ ] **非綠框走退路**：見 `AIM 限縮偵測無框` → 發退路放大圖（Task5 後為手選、之前為回報）。
- [ ] **素材有落**：`logs/snapshots/` 出現 `aim_cell_*` / `aim_core_miss_*` 圖，
      供之後補其他色系 profile。
- [ ] 若命中座標仍偶爾打偏 → 收該幀 `aim_core_miss_*` / `aim_cell_*` 當 fixture，
      走 `tuning-from-incidents` 兩側夾調 `detect_tracker_core` 門檻（**不放寬到誤收**）。

---

### 發現不符時的通則

1. 對照 spec v3 該節與計畫該 Task 的程式碼區塊，找出偏離點。
2. 純函式偏離 → 直接照 spec 表格數字修＋補測試。
3. 安全性質偏離（誤射未驗證色系／盲打回退／1-8 回退）→ **必退回重做**，不放行。
4. I/O 編排偏離但測試綠 → 仍以**實機 log**（§8）為準，測試綠不算結案。
