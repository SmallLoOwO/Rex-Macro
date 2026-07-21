# 2026-07-21 手動瞄準精定位（harvest 101）：限縮單格特徵偵測自動命中＋放大手選退路＋放大圖落 log 養素材

> **版本沿革**
> - v1：核心「裁格放大跑 `find_tracker`」——實機 fixture 驗證**不可行**（find_tracker 對本框整幀假陽性、放大 2/3/4 倍全 MISS）。作廢。
> - v2：改「手選細格」。算術驗出**單層 6×6 細格心距真框 29px、框卡格角落在框外**——單層不保證命中。作廢為主路徑。
> - **v3（本版）**：玩家提供**粗格方位**→特徵偵測器**限縮該格**找框真正中心→自動命中；抓不到才退回**放大手選（含連鎖放大）**；放大／裁格圖一律落 log 當其他色系 fixture 素材。

## 0. 委派注意（實作者必讀）

- **不要目視讀 PNG**；量測數字都在表格，用 `cv2.imread` 計算斷言。
- 不 commit、不切 branch、不刪 runtime 證據、不操作 Roblox/Discord。
- 完成過：`uv run pytest -q`、`uv run ruff check . --no-cache`。
- 座標／門檻／間隔只放 `miningbot/config.py`；純決策不做 I/O。
- 方位 1-8（訊息面）已落地（`remote_aim` 內部 0-based）；沿用不重述。

## 1. 背景（一句話根因）

手動瞄準（NEEDS_HUMAN→`手動`→8 方位圖→回 `方位 格子`）在 `_execute_remote_fire`
用 `find_tracker_near` 整幀以**粗格幾何中心**為錨重找框、找不到即**盲打粗格中心**。
harvest 101：框在 C1、真值 (851,189)、僅 25×24px；重找全滅→盲打 (800,135)、距真框
**74px**→兩發皆 miss。根因：粗格中心與真框結構性可差半格（水平 160px）。

## 2. 洞察與策略（v3）

- **`find_tracker` 對本類框有結構盲點**（尖刺太陽星框＋實心亮綠中心＋綠地形背景）：
  實機驗證整幀假陽性 (824,1055)、裁 C1 放大全 MISS。放棄它做本路徑偵測。
- **玩家提供粗格＝限縮偵測範圍**：偵測器只掃那一格，無全幀干擾、無假陽性，直接回
  框**真正中心**（非格心量化值）→ 一發命中。實機驗證（§6）：限縮 C1 命中 (851,189)
  **0px 誤差**、空鄰格 B1 回 None。
- **色系漸進 + 退路兜底**：偵測器色門檻每色系要 fixture 兩側夾，現僅綠色驗證。
  非綠色框→偵測 None→退回放大手選。**永不誤射**（找不到就不打）。
- **放大圖落 log＝養素材**：每次裁格/放大的圖存檔索引，成為補齊其他色系 profile 的
  fixture 來源（邊跑邊長語料，解掉「只有一張綠樣本」的死結）。

## 3. 目標 / 非目標

**目標**：選粗格後——(a) 限縮該格特徵偵測框中心→命中即自動開火精確中心；(b) 抓不到
→放大手選細格（含連鎖放大逐層逼近）作最後精細手段；(c) 裁格/放大圖落 log 當素材。

**非目標**：不修 D5 被吃/瓶空；不動 8 方位 survey 與自動 sweep 主路徑；不改回礦流程
（借回礦純函式、不共用其狀態機）；不憑空寫未驗證色系門檻（靠退路兜底）。

## 4. 核心不變量

**開火座標所依據的畫面，與開火那一刻，須同一 FOV 情境。** boost 作用中↔到期以畫面
中心為錨縮放 FOV、框位置平移。
- **自動路徑**：偵測幀→開火機器背靠背（無人延遲窗），FOV 天然一致——不需 boost 閘。
- **退路（放大手選）**：有人延遲窗（發圖→玩家思考→回細格），窗內 boost 若變 FOV 位移
  →作廢重發。故退路發圖記 boost 狀態、開火前重讀，不一致即作廢重發（不依賴 D5）。

## 5. 流程（`_execute_remote_fire` 收到 coarse `4 C1`）

```
1. 對齊方位（既有）
2. _harvest_boost_guard（既有）→ 重掃 D2（既有）
3. region = remote_aim.grid_cell_region("C1", margin_frac)
   frame = capture.grab()
   cell_crop = frame 裁 region
   【LOG】存 cell_crop（label: aim_cell_dir{n}_{cell}）＋放大圖，索引落 snapshot_index（素材）
4. hit = vision.detect_tracker_core(cell_crop, cfg.tracker_core_profiles, ...)   # 座標相對 region
   4a. hit → pos = (region.x + hit.cx, region.y + hit.cy) → 開火 pos（既有 fire+verify 尾）→ 回挖礦
   4b. None → 進 awaiting_fine 退路（步驟 5）；並【LOG】cell_crop 標 detect=None（＝待補色系素材）
5. 放大手選（最後精細手段，退路）：
   big = 放大(cell_crop, magnify_scale) → 疊 6×6 細網格 → 發圖；記 state0=_boost_present；
   存 aim.zoom_region=region、zoom_stack=[]
   玩家回：
     細格 `B3` → sub = fine_cell_subregion(zoom_region,"B3");  state1=_boost_present
                fov_state_consistent(state0,state1)? True→開火 sub 中心；False→重抓當下重發放大圖
     `放大 B3` → zoom_stack.push(zoom_region); zoom_region=fine_cell_subregion(zoom_region,"B3");
                重放大重發（逐層逼近；格子縮到 <框 即穩命中）
     `退`     → pop_zoom_layer 回上一層重發
     `跳過`   → 回挖礦；`手動` → 重走 8 方位 survey（既有）
```

移除：`find_tracker_near` 整幀重找＋盲打粗格心分支（101 病灶）。

## 6. 偵測器＋色系 profile（實機量測，fixture 斷言用）

fixture 存 **`tests/fixtures/aim/`**（不是 `assets/`——`assets/**/*.png` 被 .gitignore 排除，
屬機器本地 runtime 輸入；追蹤的事故場景一律進 `tests/fixtures/`，見 `tests/AGENTS.md`）。
存的是**粗格原生裁圖**（正是 `detect_tracker_core` 實機吃到的東西），非整幀：

| fixture | 來源快照 | 期望 |
|---|---|---|
| `101_core_green_c1.png` | review `…_000030_101_aim_fire_800x135.png` 裁 C1 | (211,189)、green、bf 0.35 |
| `101_core_green_b1.png` | 同上裁 B1（空鄰格） | None |
| `101_terrain_fp_d1.png` | trace `…_000021_101_manual_survey_dir2.png` 裁 D1 | None（無 max_area 則 bf 0.85 誤收） |

`vision.detect_tracker_core(region_bgr, profiles, *, min_area, max_area, ar_lo, ar_hi,
extent_min, border_margin, border_dark_max, border_dark_frac_min)`：對每個 profile 的 HSV 範圍取
mask→morphology open→輪廓→篩「方形＋實心＋周圍黑邊」→多命中取面積最大→回
`(cx, cy, profile_name, border_frac)|None`（座標相對 region）。

| 參數 | 值（config 化） | 佐證 |
|---|---|---|
| green profile HSV | lo (40,150,150) hi (85,255,255) | 框中心亮飽和綠 |
| min_area | 80（cell 原生解析度） | 框面積實測 256 |
| **max_area** | **1800** | **框心 256×6／663 vs 亮綠地形 4918/15043/17268/25631（見下）** |
| 方形 ar | 0.6–1.7 | 框 ar=1.0 |
| 實心 extent_min | 0.6 | 框 extent=0.89 |
| black-border margin | 6px | — |
| black-border dark_max（gray） | 70 | 黑邊 |
| black-border dark_frac_min | 0.15 | 框實測 0.35（真值），空格 0（→拒） |

**限縮 C1 命中量測**：region (640,0,320,270) → 偵測回相對 (211,189) → +原點 = (851,189)、
**0px**、border_frac 0.35。空鄰格 B1 (320,0,320,270) → None。
（此真值出自 101 **第二發** `aim_fire` 幀＝`tests/fixtures/aim/101_core_green_c1.png`；
同輪 dir4 survey 幀的框在 (837,185)——兩幀間鏡頭漂移 14px，兩者皆 0px 命中，別當成矛盾。）

**⚠ 亮綠地形假陽性（2026-07-21 離線驗收發現，實作後補）**：地形與框心同屬 green HSV，
大塊地形被格邊裁切後 **ar/extent/black-border 三關全過**（實測 ar 0.99–1.27、extent
0.70–0.84、border_frac 0.45–0.89，**比真框的 0.35 還高**），且 `best` 取面積最大
→ **同格即使有真框也會被地形蓋掉、朝地形中心開一發**。唯一乾淨的判別是**面積**：
真框心 256/256/256/256/256/256/663（含 `edge_clipped_tracker_scene` 33×32）
vs 地形最小 4918 → `max_area=1800`（真值 2.7 倍、誤收 1/2.7）。
方向＝**寧漏勿誤射**（漏＝退回放大手選，誤射＝浪費一發且打空）。
離線回歸：16 張 survey＋3 張 aim_fire × 24 粗格 ×（margin 0／0.15）＝**456 格 0 假陽性**，
5 命中全為肉眼確認的真框（bf 一律 0.35）。負例 fixture＝`tests/fixtures/aim/101_terrain_fp_d1.png`。

色系覆蓋：`tracker_core_profiles` 現只 green（唯一有 fixture）。其他色系（橘 Exotic／
萊姆／H040 紅粗框／藍菱星）**留空、遇到→None→退路**；靠 §5 步驟 3 的 log 素材逐色補
profile（新色 fixture 到手才加，兩側夾，比照 tuning-from-incidents）。

## 7. 元件（隔離邊界）

| 元件 | 位置 | 純度 | 職責 |
|---|---|---|---|
| `grid_cell_region(cell, margin_frac)` | `remote_aim.py`（新） | 純函式 | 粗格→原幀子區域，含餘裕＋clamp；非法 None |
| `fov_state_consistent(s0, s1)` | `remote_aim.py`（新） | 純函式 | 兩 bool 相等→True |
| `detect_tracker_core(region_bgr, profiles, ...)` | `vision.py`（新） | 純函式（吃 array） | 限縮區域找框中心（色 profile＋方形＋黑邊）；fixture 可測 |
| `fine_cell_subregion` / `magnify_scale` / `pop_zoom_layer` | `reentry_remote.py`（**既有借用**） | 純函式 | 退路連鎖放大用 |
| aim 自動偵測開火＋awaiting_fine 退路＋放大 log | `main.py` / `remote_aim.parse_reply` | I/O＋parse | 編排 |

借回礦純函式**不共用其狀態機**（兩流程刻意分離；off-by-one 教訓）。

## 8. 放大圖 log 機制（素材）

- 每次裁粗格（步驟 3）＋每層放大（步驟 5）都 `_hsnap` 存圖，label
  `aim_cell_dir{n}_{cell}[_zoomN]`，`diagnostics.append_snapshot_index` 落索引。
- detect=None（未覆蓋色系）時**額外**存原生 cell_crop 標 `aim_core_miss_dir{n}_{cell}`——
  這批就是「補新色系 profile」的直接 fixture 來源。
- 存圖走既有非同步快照佇列（不卡開火路徑）＋落盤等待（發圖前 `_wait_snapshot_ready`）。
- 落 `Config.log_dir`（MSIX 重導見 CLAUDE.md）；素材撈取＝grep 該 label 前綴。

## 9. 玩家可見訊息（同步更新，見 [[feedback_new_command_must_update_player_messages]]）

- 自動命中：沿用「✅ 收到…執行中」＋開火後 verify 回報。
- 抓不到→退路發圖 caption：「🔍 沒自動抓到框（可能非綠色框），已放大 DIR{n} 的 {cell}——
  回細格（如 `B3`）打中心、`放大 B3` 再放大、`退` 退一層、`跳過`／`手動`」（DIR 1-8）。
- FOV 作廢重發：「📷 畫面變了，重發當下放大圖，請重選」。
- `MANUAL_SURVEY_HELP` 末補一句「選格後會先自動抓框，抓不到再放大讓你點」。

## 10. 測試

| 測試 | 型 | 內容 |
|---|---|---|
| `grid_cell_region` | 純函式 | C1→(640,0,320,270)；margin 0.15→(592,0,416,310)（含頂緣 clamp y0=0）；非法 None |
| `fov_state_consistent` | 純函式 | (T,T)/(F,F)→True；(T,F)/(F,T)→False |
| `detect_tracker_core` 命中（綠） | fixture | `tests/fixtures/aim/101_core_green_c1.png`→回相對 (211,189)±15px、profile="green"、border_frac≥0.15 |
| `detect_tracker_core` 拒亮綠地形 | fixture | `tests/fixtures/aim/101_terrain_fp_d1.png`→None（拿掉 max_area 則回 bf 0.85，紅綠自證） |
| `detect_tracker_core` 空格 | fixture | 同圖裁 B1→None（兩側夾負樣本） |
| `detect_tracker_core` 空 profile | 純函式 | profiles=[] → None（未覆蓋色系不誤射） |
| `fine_cell_subregion`（借用回歸） | 純函式 | 既有＋加 C1+`放大`一層 subregion 數字 |
| `parse_reply` awaiting_fine | 純函式 | awaiting_fine=True 裸 `B3`→fine、`放大 B3`→magnify、`退`→back；False 裸 `B3`→None |
| awaiting_fine 編排 | 邏輯 | state0≠state1→重發；連鎖放大 push/pop zoom_stack |

回歸：`uv run pytest -q` 全綠；動過 vision 過既有 assets 場景回歸。

## 11. Config 新增（`miningbot/config.py`）

| 名 | 預設 | 說明 |
|---|---|---|
| `tracker_core_profiles` | `[("green",(40,150,150),(85,255,255))]` | 色系 HSV 範圍清單（漸進擴充） |
| `tracker_core_min_area` / `_max_area` / `_ar_lo` / `_ar_hi` / `_extent_min` | 80 / 1800 / 0.6 / 1.7 / 0.6 | 方形實心篩（`_max_area` 夾亮綠地形，§6） |
| `tracker_core_border_margin` / `_border_dark_max` / `_border_dark_frac_min` | 6 / 70 / 0.15 | 黑邊判別 |
| `remote_aim_zoom_margin_frac` | 0.15 | 裁格對稱餘裕 |
| `remote_aim_fine_grid` | 6 | 細網格 6×6（同回礦） |
| `remote_aim_fov_recheck_max` | 2 | 退路 FOV 作廢重發上限 |

~~移除：`remote_aim_refind_radius_px=160`（`rg` 確認僅此引用後連 config 刪）。~~
**實作裁決（保留，勿再刪）**：`candidate` 路徑（回候選編號）仍用它跑 `_refind_tracker_near`
整幀重找——那條路徑的先驗位置已精修過，非本次目標。grid 與 candidate 兩路**刻意分離**
（共用狀態正是 101 off-by-one 的成因）。刪掉會拆掉 candidate 路徑。

## 12. 非本次範圍

- D5 被吃/瓶空、自動 sweep 小框偵測（同源盲點不同流程）。
- 其他色系 profile：靠 §8 log 素材逐色補（新色 fixture 到手才加）。

## 13. 分階段落地建議（給計畫）

1. 純函式（`grid_cell_region`／`fov_state_consistent`）＋ `detect_tracker_core`＋綠 fixture。
2. 接進 `_execute_remote_fire`：限縮偵測→命中自動開火；抓不到→回報退路占位＋裁格 log。
   （此階段已修好 101 綠框自動命中＋開始養素材。）
3. 放大手選退路（awaiting_fine＋連鎖放大＋FOV 閘＋parse），把退路從「回報」升級為
   「放大手選」。
（1→2 即可獨立實機驗證綠框自動命中；3 補最後精細手段。）
