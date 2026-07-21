# 2026-07-21 手動瞄準放大精定位（harvest 101）：裁格放大偵測框中心＋FOV 一致性保證

## 0. 委派注意（實作者必讀）

- **不要嘗試目視讀取任何 PNG**。所有 fixture 的量測數字都在本規格的表格裡；
  測試用 `cv2.imread` 載入後計算數字斷言即可。
- 不 commit、不切 branch、不刪 runtime 證據、不操作 Roblox/Discord。
- 完成後執行並確保通過：`uv run pytest -q`、`uv run ruff check . --no-cache`。
- 座標／門檻／間隔只放 `miningbot/config.py`；純決策不做 I/O。
- 方位 1-8（訊息面）已於前一 commit 落地（`remote_aim` 內部仍 0-based）；本規格
  沿用該慣例，不再重述。

## 1. 背景（一句話根因）

手動瞄準（NEEDS_HUMAN → `手動` → 8 方位圖 → 回 `方位 格子`，如 `4 C1`）在
`_execute_remote_fire`（`miningbot/main.py`）對齊＋重掃 D2 後，用
`vision.find_tracker_near` 在**整張 1920×1080** 原幀、以粗格中心為錨半徑
`remote_aim_refind_radius_px=160` 重找框；找不到就**盲打粗格幾何中心**。

harvest 101（2026-07-21 13:44/13:48 兩發）實測：礦框在 C1、真值 `(851,189)`、
大小僅 **25×24px**。`find_tracker_near` 對這種小框在整幀偵測失敗（log
`AIM 重找全滅 -> 直接朝先驗點開火 (800,135)`），退回盲打格心 `(800,135)`，
距真框 **74px** → 兩發皆 verify `NORMAL` 未確認 → miss。

**boost 已排除為病因**：actions.log 顯示 `_harvest_boost_guard` 在兩發前
（13:44:35、13:47:58）都判「boost 消失 → 立即補 D5」，但補後開火幀的框仍
`25×24`、位置只飄 14px（放大圖 13:43 `(837,185)` vs 開火幀 13:47 `(851,189)`、
中央帶平均差 10.1）——D5 被吃/瓶空、FOV 全程維持收縮態、框一直看得到只是小。
故 101 的 FOV 從頭到尾一致，miss 純粹是**小框在整幀偵測失敗＋退格心**。

## 2. 目標 / 非目標

**目標**：選格子後不再盲打格心，而是**裁出該粗格放大 → 在放大圖偵測框 →
回推原幀中心座標 → 開火**；並**保證開火座標的 FOV 情境與偵測當下一致**，
不對已偏移的座標開火。

**非目標**：
- 不修 D5 被吃/瓶空（獨立問題線；`_harvest_boost_guard` 照跑，本規格不動它）。
- 不動 8 方位 survey（它是玩家挑方位＋粗格的入口）。
- 不改自動 sweep 主路徑（只動手動瞄準的 fire 路徑）。
- 不引入新的 boost 重上邏輯（現有守門已盡力補；本規格只加「不一致就作廢」的
  正確性保險）。

## 3. 核心不變量

**取座標的那一幀，與開火那一刻，必須在同一 boost 狀態。** boost 作用中↔到期會
以畫面中心為錨縮放 FOV（`_harvest_boost_guard` docstring：~2.6x、框外推 ~390px），
狀態一變框就位置平移、甚至被推出視野。違反＝打空。因 D5 可能被吃（無法強制
狀態），保證改用**檢查兩時刻狀態、不一致即作廢重來**，不依賴 D5 生效。

## 4. 流程（`_execute_remote_fire`，取代現行步驟 3「ROI 放寬重找」）

```
使用者回 `4 C1`（方位 4、粗格 C1）→
1. 對齊方位（既有，不變）
2. _harvest_boost_guard（既有）→ prepare/execute_scan 重掃 D2（既有）
3. 【新】裁格放大偵測：
     region = grid_cell_region("C1")（含邊界餘裕 zoom_margin_frac）
     f_detect = capture.grab()；state_detect = _boost_present（記下偵測幀狀態）
     crop = 放大(f_detect 裁 region, scale)
     hit  = vision.find_tracker(crop, margin_frac=0, ...)  # with_score
     若 hit → 回推原幀中心 pos = region 原點 + hit中心/scale
4. 【新】開火前 FOV 一致性閘：
     state_fire = _boost_present（重讀）
     state_fire == state_detect → 開火 pos（座標有效）
     state_fire != state_detect → 作廢 pos，回步驟 3 重來（現況重偵測）；
       受 remote_aim_budget_s 預算＋重試上限 gate
5. 【新】偵測不到（含重試耗盡）→ 退回手選：發【當下 f_detect】的放大圖＋細網格，
     使用者回細格（如 `B3`）→ 打細格中心（比照回礦 fine 流程，但用當下幀非舊 survey）
```

現行步驟 4「重找全滅 → 直接朝先驗點開火」的盲打分支**移除**（正是 101 的病灶）。

## 5. 元件（隔離邊界）

| 元件 | 位置 | 純度 | 職責 |
|---|---|---|---|
| `grid_cell_region(cell, margin_frac)` | `remote_aim.py`（新） | 純函式 | 粗格代碼→原幀子區域 (x,y,w,h)，含對稱邊界餘裕、clamp 到畫面內 |
| `map_zoom_point(region, scale, pt)` | `remote_aim.py`（新） | 純函式 | 放大圖內座標→原幀座標（`region原點 + pt/scale`） |
| `fov_state_consistent(detect_state, fire_state)` | `remote_aim.py`（新） | 純函式 | 兩 bool 相等→True（可開火）；不等→False（作廢） |
| 裁格放大＋`find_tracker`＋一致性閘＋退路 | `main.py`（改 `_execute_remote_fire`） | I/O | 編排上列純函式與既有 capture/vision/notify |

`grid_cell_region` 與 `remote_aim.grid_cell_center` 共用同一 6×4 幾何常數，避免漂移。

## 6. 偵測配方＋101 量測（fixture 斷言用）

fixture：`assets/aim_zoom_c1_expired_scene.png`（追蹤框場景一律入 `assets/*_scene.png`，
比照 `green_center_scene`／`edge_clipped_tracker_scene`）＝ 由 review 快照
`20260721_134803_262217600_000030_101_aim_fire_800x135.png` 原樣入庫
（boost 到期／窄 FOV 態）。

| 量 | 值 |
|---|---|
| 影格尺寸 | 1920×1080 |
| 粗格幾何 | 6 cols × 4 rows → cw=320, ch=270 |
| 粗格 C1 region（無餘裕） | (640, 0, 320, 270) |
| 真框 bbox | (839, 177, 25, 24) |
| 真框中心（原幀真值） | **(851, 189)** |
| 真框相對 C1 原點 | (211, 189) |
| 放大 scale=3（輸出寬 960） | 框中心（裁圖）(633, 567)、框尺寸 ~75×72 |
| `map_zoom_point((640,0,..),3,(633,567))` | (851, 189) ✅ 回推 == 真值 |
| 舊盲打格心 | (800, 135)，距真框 74px（本規格消除此誤差） |

偵測配方：`find_tracker(crop, margin_frac=0, shape_templates=<既有>,
shape_scales=<既有>, with_score=True)`。放大後框 ~75px，落在既有 `shape_scales`
量級；`margin_frac=0` 因裁圖小、不可再排邊。實作時以本 fixture 驗證命中，
必要時只調 `shape_scales`／裁圖 scale，**不放寬整幀主偵測門檻**。

**兩狀態測試要求**：上表為到期態（101，已有）。作用中態（寬 FOV、框在
P_active、尺寸更小）需一份 `assets/aim_zoom_*_active_scene.png` fixture——**101
全程到期、無現成作用中樣本**，故：
- 純函式（`grid_cell_region`／`map_zoom_point`／`fov_state_consistent`）與一致性閘
  邏輯**兩狀態皆可離線測**（餵 bool、餵座標），本次即完成。
- 作用中態的**偵測命中** fixture 留待下輪實機收（配方相同、僅框更小）；在 spec
  §10 標記為待補，不阻擋本次落地。

## 7. FOV 一致性保證（§4 步驟 4 細節）

- `state = _boost_present`：既有布林，來源 `boost_active` 瓶子圖 edge-match
  （`boost_indicator_region`，~56ms）。偵測幀抓一次、開火前重讀一次。
- 相等即開火；不等即作廢該 pos、回步驟 3 重掃重偵測（現況）。
- 護欄：`remote_aim_fov_recheck_max`（預設 2）次重試上限；耗盡→步驟 5 手選退路。
  全程仍受 `remote_aim_budget_s` 總預算 gate（既有）。
- **不強制 boost 狀態**（不主動補/解 D5 來對齊）——D5 可能被吃，強制不可靠；
  只保證「偵測與開火同態」，補得成是 `_harvest_boost_guard` 的事。

## 8. 退路（手選，當下幀）

偵測不到（或一致性重試耗盡）→ 用**步驟 3 的當下幀 f_detect** 裁 region 放大、
疊細網格發送（比照回礦 fine：`fine_cell_subregion` 換算細格→原幀子區域）。用當下
幀而非舊 survey 圖，自然吸收 survey/開火 FOV 不一致——玩家看到的是現況。
使用者回細格 → 打細格中心（無偵測依賴、零 miss 風險，代價是多一次來回）。

## 9. 玩家可見訊息（同步更新，見 [[feedback_new_command_must_update_player_messages]]）

- 偵測命中開火：沿用既有「✅ 收到…執行中」＋開火後 verify 回報。
- 退路發圖：新 caption「🎯 已放大 DIR{n} 的 {cell} 格但沒自動抓到框——回細格
  （如 `B3`）打中心；或 `跳過`」。
- 一致性作廢重試：不必每次吵玩家（內部 log 即可）；耗盡轉手選時才發圖。
- `MANUAL_SURVEY_HELP`／aim `看不懂` 訊息若涉及流程說明，順帶對齊。

## 10. 測試

| 測試 | 型 | 內容 |
|---|---|---|
| `grid_cell_region` | 純函式 | C1→(640,0,320,270)；含餘裕版對稱擴張＋畫面內 clamp；非法格回 None |
| `map_zoom_point` | 純函式 | ((640,0,..),3,(633,567))→(851,189)；scale=1 恆等 |
| `fov_state_consistent` | 純函式 | (T,T)/(F,F)→True；(T,F)/(F,T)→False |
| 偵測命中（到期態） | fixture | `aim_zoom_c1_expired_scene.png` 裁 C1 放大→`find_tracker` 命中、回推中心落在 (851,189) ±15px（門檻寫死於測試） |
| 偵測命中（作用中態） | fixture | **待下輪實機補** `aim_zoom_*_active_scene.png`；本次先留 `pytest.mark.skip` 佔位並註明待補 |
| 一致性閘編排 | 邏輯 | 模擬 state_detect≠state_fire → 不開火、走重試；耗盡 → 手選分支 |

回歸：`uv run pytest -q` 全綠；動過 vision 需過既有 assets 場景回歸。

## 11. Config 新增（`miningbot/config.py`）

| 名 | 預設 | 說明 |
|---|---|---|
| `remote_aim_zoom_scale` | 3 | 粗格放大倍率（輸出寬 ~960） |
| `remote_aim_zoom_margin_frac` | 0.15 | 裁格對稱邊界餘裕（防框貼格線被裁） |
| `remote_aim_fov_recheck_max` | 2 | FOV 一致性作廢後的重偵測上限 |

移除：現行 `remote_aim_refind_radius_px=160` 的整幀重找＋盲打格心分支（由裁格放大
取代）。實作時 `rg remote_aim_refind_radius_px` 全庫確認僅此處引用後，連同 config
常數一併刪除；若他處尚有引用則先處理再刪。

## 12. 非本次範圍

- D5 被吃/瓶空（`_harvest_boost_guard` 補而不生效）——獨立問題線。
- 自動 sweep 主路徑的小框偵測（`project_sweep_all_empty_giveups`）——同源弱點但
  不同流程，本次只解手動瞄準 fire 路徑。
- 作用中態偵測 fixture 的實機採集（§10 待補）。
