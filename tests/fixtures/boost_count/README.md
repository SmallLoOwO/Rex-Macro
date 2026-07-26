# `boost_count/` — 右下角 boost 使用次數紅字

`vision.read_boost_use_count` 的素材。這個數字是 boost 強度的 **ground truth**：
數字越大 buff 越強，重進遊戲會歸零重算。

| 檔案 | 期望讀值 |
|---|---|
| `count_15.png` `count_17.png` `count_32.png` `count_39.png` `count_41.png` `count_42.png` `count_43.png` `count_50.png` `count_80.png` `count_83.png` `count_124.png` `count_166.png` `count_211.png` | 檔名裡的數字 |
| `none_sky.png` | `None`（畫面上根本沒有計數） |
| `none_red_scene.png` | `None`（**紅色場景**，顏色像但不是數字） |

13 個正樣本橫跨 1~3 位數（15 → 211），確保位數變化不會讓判定翻面。

## 為什麼用內嵌數字模板而不是 Tesseract

Tesseract 對這種小紅字會把 **8 讀成 10**（實測），已棄用。現行走內嵌數字模板比對。

## 兩個負樣本是重點

`none_red_scene` 比 `none_sky` 重要得多——紅色場景跟紅字同色系，只靠顏色過濾一定誤判。
沒有這張，判定會在紅色礦區整場回報假數字。

## 用途

boost FOV 隨使用次數累積漂移（作用中變大、到期變小、重進遊戲重製，上限位置未知）。
次數是擬合 FOV 曲線的自變數，實機每 10 次會落一組前後幀對 + `boost_fov` jsonl。
