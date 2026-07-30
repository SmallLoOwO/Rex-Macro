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
