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
網頁補 rarity／礦名／症狀／關聯事故編號。**根因描述不寫在 `.json` 裡**，寫
`docs/incidents.md`（spec §12 非目標）。

## 為什麼不照 spec 分 `green/`、`terrain_false_positive/` 子目錄

`docs/superpowers/specs/2026-07-26-web-ui-design.md` §5 畫的是按色系分子目錄，但同一份
spec 的自動收集設計把 `auto_*` 直接寫進 `aim/`——**bot 不知道玩家點的那一格是什麼色系**
（玩家點哪打哪，這條路徑刻意不跑偵測）。硬要分層就得為 auto 檔另開 `unknown/`，反而更亂。

現況維持平鋪，用檔名前綴區分（`101_core_green_*` / `101_terrain_fp_*` / `auto_*`）。
要改結構前先解決 auto 檔的歸類問題。
