# `effect_row/` — D2 雷達效果列判讀

`cfg.scan_confirm_region` 裁圖（右下角效果列整條），驗 `vision.find_effect_slots`
與掃描成功判定。

| 檔案 | 情境 | 徽章數 | 掃描判定 |
|---|---|---|---|
| `local_only.png` | D2 左鍵後，只有 Local（x=1676） | 1 | 成功 |
| `local_and_caveskim.png` | 左鍵＋Z，Local 1676、Cave Skim 1612 | 2 | 成功 |
| `local_displaced_3slots.png` | Z→D5→左鍵，Local 被推到 1548 | 3 | 成功 |
| `caveskim_only.png` | 只按了 Z（同樣是雷達徽章） | 1 | **不成功** |
| `d4_used_only.png` | 只有 D4 的 Used 徽章 | 1 | 不成功 |
| `no_effects.png` | 效果列全空 | 0 | 不成功 |

## 為什麼要整條 OCR 而不是固定單格

舊的 `scan_confirm_region` 是左下角估值，離線重放 22 幀 **TP=0**——那個位置讀到的是
左側礦物面板的文字，從來沒對過。

改成整條效果列後還有第二個坑：**徽章會疊加位移**（`local_displaced_3slots` 就是
Local 被推到 1548 的實例），所以必須**逐格 OCR**。固定單格與「整條一次 OCR」兩種做法
都已實測失敗，別再試。

`caveskim_only` 是這裡最重要的負樣本：Cave Skim 跟 Local 一樣是雷達徽章，只按 Z 沒按
左鍵時效果列**看起來有東西**，但掃描其實沒生效——判成功就會白掃一輪。
