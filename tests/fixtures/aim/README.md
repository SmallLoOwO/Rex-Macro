# `aim/` — harvest 手動瞄準單格限縮偵測

`vision.detect_tracker_core` 的兩側夾語料。這條路徑是「玩家在 Discord／網頁指定一格
→ bot 只在那格內找框心 → 命中就自動朝框中心開火」，所以**誤判的代價是對地形開一發 D3**。

fixture 是**粗格原生裁圖**（320×270），正是 `detect_tracker_core` 在實機吃到的東西。

| 檔案 | 是什麼 | 期望判定 |
|---|---|---|
| `101_core_green_c1.png` | harvest 101 dir2 survey 幀的 C1 格，格內有真的綠框心 | 命中 ≈(211,189)、`name="green"`、`border_frac ≥ 0.15` |
| `101_core_green_b1.png` | 同一幀的 B1 空鄰格 | `None`（空格不得命中） |
| `101_terrain_fp_d1.png` | 同一幀的 D1 格，**整片亮綠地形** | `None` |

## 為什麼 D1 那張是這個目錄最重要的檔

亮綠地形跟框心同屬綠 HSV 範圍，而且 `ar`／`extent`／`border_frac` **三道關卡全過**：
實心（extent 0.70）、被格邊裁成近方形（198×185、ar 1.07）、bbox 外環帶落在暗地形上
（border_frac **0.89**，比真框的 0.35 還漂亮）。

唯一的結構差異是**面積**：框心 256（17×17）vs 地形 25631（≈100 倍）。沒有面積上限時
`best` 取面積最大 → 就算那格真的有框也會被地形蓋掉，朝地形中心開一發。

兩側夾：真框心 256／6／663（含 `edge_clipped_tracker_scene` 33×32）
vs 亮綠地形 4918／15043／17268／25631 → **`tracker_core_max_area = 1800`**。

`test_detect_tracker_core_bright_terrain_is_not_a_tracker` 有紅綠自證：拿掉面積上限，
同一張圖就會回報 (207,177)。門檻若被回退，那個 assert 必紅。

⚠ **只看分數會得到完全相反的結論**——這批素材就是為了記住這件事而存在的。

## `auto_*` 自動收集素材

玩家在網頁介入（pinch-zoom + tap）後，`main.Bot._save_auto_fixture` 會把該格裁圖寫進
這個目錄，兩檔一組：

```
auto_<episode_id>_success.png / .json      verify 通過（對照組，symptom=null）
auto_<episode_id>_fail.png / .json         verify 未通過（症狀組）
```

`.json` schema 見 `miningbot/web_annotation.py:build_annotation`；玩家在 `/annotate`
網頁補 rarity 與「看到什麼」。**根因描述不寫在 `.json` 裡**，寫
`docs/incidents.md`（spec §12 非目標）。

`symptom` 不是玩家挑的（2026-07-31）：玩家只答 `observation`
（`ore`／`decoy`／`empty`／`unsure`），配上快照 label 記的 bot 當下判定
（`web_history.label_verdict`）推成症狀（`web_annotation.symptom_from_observation`）。
**推導不可逆**——`decoy`（像礦的地形／裝備／UI）與 `empty` 在 bot 拒絕時都推成
`no_target`，只有 `observation` 欄位分得出誰是硬負樣本；調門檻要挑素材時看它，
不要只看 `symptom`。

## `/annotate` 手動標註素材（2026-07-26 起也是兩檔一組）

玩家在歷史頁點任一張快照縮圖進 `/annotate`，在**全幀**上拖曳出方框送出後，
`POST /api/annotate` 會寫：

```
<原始快照 stem>.png    ← 以方框中心裁出的 320×270 粗格裁圖
<原始快照 stem>.json   ← metadata；cx/cy 已換算成**裁圖內座標**
```

裁圖尺寸與自動收集路徑共用 `web_annotation.cell_crop_box`（`screen_w//6 ×
screen_h//4`），因為 `detect_tracker_core` 實機吃的就是這個尺寸——這批素材的
用途正是加強目標框偵測，尺寸不對就餵不進去。

⚠ **先前這條路徑只寫 `.json`**（2026-07-26 修正）：`image` 欄放原始快照 basename，
但那個檔名在本目錄根本不存在，等於產出指向空氣的孤兒。若日後又看到只有 `.json`
沒有同名 `.png` 的素材，就是這個迴歸復發——`tests/test_web_annotate_png_pair.py`
盯著它。

⚠ 方框只是 `.json` 裡的 metadata，**不是裁圖邊界**。存整片 320×270 是刻意的：
本目錄最重要的負樣本（`101_terrain_fp_d1.png`）靠的就是「框心 256 vs 亮綠地形
25631」的面積差，裁成貼著框邊的小圖就再也看不出兩側夾。

## 為什麼不照 spec 分 `green/`、`terrain_false_positive/` 子目錄

`docs/superpowers/specs/2026-07-26-web-ui-design.md` §5 畫的是按色系分子目錄，但同一份
spec 的自動收集設計把 `auto_*` 直接寫進 `aim/`——**bot 不知道玩家點的那一格是什麼色系**
（玩家點哪打哪，這條路徑刻意不跑偵測）。硬要分層就得為 auto 檔另開 `unknown/`，反而更亂。

現況維持平鋪，用檔名前綴區分（`101_core_green_*` / `101_terrain_fp_*` / `auto_*`）。
要改結構前先解決 auto 檔的歸類問題。

## 2026-07-31 玩家標註批次（`20260728_*`~`20260731_*`，15 組）

玩家在標註頁對 sweep/D3 快照畫框的第一批成果，是 **H068 的證據來源**。判讀時注意
這批的 `.png` 是粗格裁圖，**兩側夾要回全幀量**——`shape_roi_px=320` 在 320×270 的
裁圖上會被裁掉一角，crop 上算出來的 `edge` 系統性偏低，拿它訂門檻會訂歪。全幀在
MSIX LocalCache `snapshots/review/`，用 `matchTemplate` 把 crop 定位回去就有絕對座標。

- `symptom="false_negative"`：玩家看得到框、bot 判空。10 張，全部是黃色尖刺太陽外框
  ＋實心綠心，多半被角色或裝備擋掉外框一角 → H068 二維軟收（11/12 已救回）。
- `symptom=None` + `observation="ore"`：對照組（bot 當時就收了），拿來確認調門檻沒把
  原本收得到的弄丟。
- `20260730_200052_..._128_sweep_accepted_dir7`：**唯一的淡薄荷色框**（核心 H=60
  S=128 V=255）。`find_tracker` 收得到，但 `detect_tracker_core` 的
  `tracker_core_profiles` 只有 S≥150 的飽和綠 → 這格回 None，手動瞄準退回放大手選。
  見 `docs/open-detection-issues.md` D10。
- `20260728_..._119_d3_miss_1`：藍菱星框，核心是**土黃色方塊**（H=14 S=160 V=147），
  跟泥土地形同色帶。加 profile 前務必先收地形負樣本，D10 一併記著。

## 2026-08-01 玩家標註批次（`20260730_*`~`20260801_*`，58 組）

第二批，涵蓋 episode 131~150。判讀時同樣注意「`.png` 是粗格裁圖，兩側夾要回全幀量」
（全幀在 MSIX LocalCache `snapshots/review/`，**同檔名**，用 `matchTemplate` 定位）。

分佈（`.json` 的 `symptom` / `observation`）：

| 組別 | 張數 | 是什麼 |
|---|---|---|
| `symptom=null` + `observation="ore"` | 51 | 對照組（bot 當時就收了） |
| `symptom="false_negative"` | 11 | 玩家看得到框、bot 判空 |
| `symptom="should_reject_failed"` + `observation="decoy"` | 12 | bot 收了，玩家說那不是礦 |
| `symptom="false_positive"` + `observation="empty"` | 4 | bot 收了，那格其實空的 |

### 收側 11 張的量測結論：**根因是 D06，不是門檻**

11 張全部是同一種框（綠色四角凹星外框＋實心淡薄荷心，核心 HSV 恆為 **H=60 S=128
V=255**），其中 1 張是 Exotic 黃橘框。逐關拆解（`find_tracker`，production 參數）：

- 形狀 `edge` 在標註處全部是 **1.000**（模板配得極準），門檻完全沒問題；
- 7/11 的核心與同色地形黏成超大輪廓（最大 949×444），走 H057 救援，
  子分割後 blob 是乾淨的 25×25 / area 576，**全過救援子閘**；
- 真正殺掉它們的是 **`ref_fill > 0.15` 的 preexist 差分**：拿同場 `dir0` 幀當
  reference 代理重放，9 張可測的有 **6 張**被判 preexist（`ref_fill` = 1.00／0.78／
  0.70／0.22／0.16／1.00），而參考幀那塊 bbox 只是**別的方位的暗綠牆**
  （V 中位 53~134）。這正是 `docs/open-detection-issues.md` **D06**。

⚠ **不要為這批調 `tracker_shape_*` 或 `tracker_rescue_*`**：那幾關本來就過了，
動它們只會製造假陽性。D06 的三條路與各自的量測（含已被否決的兩條）記在該條目。

### 誤收側 12 張其實只有 3 種東西

| 群 | 座標 | 是什麼 |
|---|---|---|
| ep134（4 張） | (666,981)／(772,1015~1017) | **hotbar 的紫色圓角外框與 `[~]` 按鈕**——落在 Exclusive 暗紫色域，`d3_fire_dir2_772x1017` 是真的朝它開了一發 |
| ep143／146（7 張） | (1020,595)／(1036,596) | 玩家自己的角色身體與背包（螢幕中央偏右） |
| ep133（1 張） | (1354,533) | 綠色地形方塊 |

hotbar 看似該進 `Bot._tracker_exclusions()`（比照 H068 的聊天／礦石面板），但**夾不出
兩側**：hotbar 展開成 10 格時橫跨 x 628~1290、y 988~1065，而 H026 的真框就在
(1288,1020)（`assets/bottom_edge_tracker_scene.png`，`tracker_margin_frac` 0.10→0.02
正是為了收回它）——同一塊螢幕區域兩邊都要。維持現況，記在 D06 誤收側。
