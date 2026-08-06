# `markers/` — `detect_tracker_core` 形狀 fallback 的外框模板（進版控）

`assets/markers/*.png` 是既有 `find_tracker` 用的外框模板，**整個目錄被 `.gitignore` 排除**
（機器本地素材），既有測試靠 `if not os.path.exists(...): pytest.skip()` 容忍缺席——
`tuning-from-incidents` skill 明講這是要避免的舊坑：「不可放 assets/，別台機器 clone
下來測試就 skip，無樣本的修復＝下次必迴歸」。

這個目錄放 `detect_tracker_core` 形狀 fallback（2026-08-06 起）要用的外框模板，**進版控**，
測試永遠跑得到。production 執行時仍讀 `assets/markers/`（機器本地）——新增模板時記得
順手複製一份過去（純檔案複製，不進 git）。

## 兩側夾方法：按 `tier` 分組，不是按內心色

91 張玩家標註 fixture（`tests/fixtures/aim/`）肉眼核對後發現：**內心方塊顏色**跟外框樣式
是分開變化的兩個維度——同一種外框可能配好幾種內心色（Transcendent 藍菱星就配過棕/白/暗
三種），而且同一批標註若只靠內心色 HSV 分群會把不同外框的素材混在一起（`config.py`
`tracker_core_profiles` 的四色系新 profile，就是踩過這個坑才發現要分開處理）。**外框要
按玩家標註的 `tier` 欄位分組**才對得上——這是使用者在標註當下就留的訊號，不是事後猜的。

| 檔案 | tier | 場次證據（同外框，肉眼核對過） |
|---|---|---|
| `transcendent_diamond_tracker_real.png` | Transcendent | 139／153／162（3 場一致） |
| `exquisite_star_tracker_real.png` | Exquisite | 128／147／148／197／205（5 場一致） |
| `enigmatic_spikystar_tracker_real.png` | Enigmatic | 196（1 場） |
| `exotic_octagon_tracker_real.png` | Exotic（主流款） | 138／158／161／198／199（5 場一致） |
| `exotic_burst_tracker_real.png` | Exotic（變體） | 159 |
| `exotic_cross_tracker_real.png` | Exotic（變體） | 145 |
| `exotic_circle_tracker_real.png` | Exotic（變體） | 207 |

Exotic 一個階級底下量到 4 種不同外框——推測是特定道具各自帶自己的圖標，不是階級本身決定
外框（否則同階級該只有一種）。`exotic_octagon` 是這批裡出現頻率最高的款，其餘三款各只有
單一場次證據，門檻要收緊一點或標記信心較低。

裁圖固定 90×90（以標註 `cx,cy`=(160,135) 為中心，半徑 45px），跟既有 `assets/markers/
*_tracker_real.png` 的裁圖慣例（真實遊戲截圖、含少量背景雜訊，非去背）一致。

## 尚未收錄

這 7 張只覆蓋這批 91 張標註裡出現過的外框；沒出現在這批素材裡的道具／階級組合（例如
Mythic、Surreal 等其他階級的追蹤框長相）還沒有樣本，遇到時 `_detect_core_in_cell` 的
miss 路徑會自動存 `aim_core_miss_*` fixture，下次標註驅動微調再補模板。
