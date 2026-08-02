# `boost/` — D5 boost 生效判定三態

`cfg.boost_indicator_region` 的實機裁圖（正是 `find_template_edges` 在正式程式碼裡
實際會收到的輸入）。

| 檔案 | 畫面上有什麼 | 期望 |
|---|---|---|
| `before_only_count.png` | 只有常駐的**使用次數計數圖示**（舊 145px region） | 偵測不到瓶子 → 該補 D5 |
| `active_47.png` | 計數圖示 + 倒數 47s 的瓶子 | 偵測到 → 生效中，不補 |
| `active_61.png` | 同上，倒數 61s | 偵測到 → 生效中，不補 |
| `h168_sweep_no_boost.png` | harvest 168 sweep 幀：只有使用次數 icon（D5 未生效） | 偵測不到 → 該補 D5（H073） |
| `h168_mining_boost_active.png` | harvest 168 mining 幀：active buff + 次數 icon | 偵測到 → 生效中（H073） |

兩種倒數數字（47／61）是刻意的：驗證邊緣比對**不受數字內容影響**。

## 為什麼會有這批素材（2026-07-08 遊戲更新）

右下角原本只有「boost 生效中的瓶子圖示」。遊戲更新後多了一顆**常駐的使用次數計數
圖示，長得跟 boost 瓶子一模一樣**，只是位置固定在瓶子右側、永遠不會消失。

舊的 `boost_indicator_region` 涵蓋到它 → 判定邏輯（瓶子消失＝該補 D5）永遠看到一顆
「瓶子」→ **永遠判生效中、永遠不補 D5**。

對策是把 region 右緣縮到計數圖示左緣。`before_only_count` 就是驗這件事的：那顆計數
圖示必須被新 region 排除在外。

## 缺口

「完全無圖示」（新伺服器、從未用過 D5）**至今沒有樣本**。要補的話需要一個沒用過 D5 的
帳號或伺服器。

## 相關

boost FOV 會隨使用次數累積漂移（作用中變大／到期變小／重進遊戲重置）。次數本身的
OCR 素材在 [`../boost_count/`](../boost_count/README.md)。按 D5 時 boost 仍在＝沒作用，
只能到期即補——**絕不因此提醒使用者重進遊戲**（次數越大 buff 越強）。
