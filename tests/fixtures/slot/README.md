# `slot/` — hotbar 槽位「是否已裝備」的區域顏色偵測

D1（鎬子）、D2（掃描器）、D3（傳送器）槽位的實機裁圖（皆 54×58，原點對齊取整塊）。

| 檔案 | 情境 | 期望 `slot_selected` |
|---|---|---|
| `slot1_equipped_green.png` | 按 D1 選中鎬子（槽位轉綠底） | `True` |
| `slot1_unequipped_gray.png` | 再按 D1 卸下（灰底） | `False` |
| `slot2_equipped_green.png` | harvest 121 mid 層：進場掃描成功、掃描器裝備中（綠底） | `True` |
| `slot2_unequipped_gray.png` | harvest 121 up 層：層轉換盲按 "2" 把掃描器 toggle 卸下（灰底） | `False` |

⚠ slot 3（D3）尚無實機裁圖；`d3_slot_region` 座標 (930,998,54,58) 由 slot1→slot2 的 +66px
間距推算，門檻沿用 5.0。下次實機採集 D3 裝備／卸下幀後補上 `slot3_*.png` 並用
`test_slot_fixtures.py` 的模式加測試兩側夾。

## 判定與兩側夾

看**區域顏色**而不是單點：`greenness = 平均G - 平均(R+B)/2`

```
slot1 裝備中（綠底）  +9.8 ~ +11.5     slot2 裝備中  ~+10.5
slot1 未裝備（灰底）  -1.4 ~  0.0      slot2 未裝備  ~+1.5（掃描器圖示帶微綠）
                        → 門檻 5.0（兩個 slot 都兩側夾；slot2 未裝備基線較高但仍是 UI 固定值）
```

## 為什麼不能用單點取樣

舊版寫死 `pixel_matches(slot_pixel=(1011,845), 0x232323)`。使用者把 Windows 工作列調回
顯示後，遊戲視窗底部整條 UI **上移約 50px**（實測 boost 瓶子 1039→989），那顆寫死的
單點就落到角色／場景上（實測讀到 ~[164,167,217] 的紅色）→ 判定全錯。

換句話說：單點取樣對「整條 UI 位移」零容忍。任何新的 UI 判定都不要用單點。

## ⚠ 數字鍵是 toggle

D1/D2/D5 等數字鍵**已裝備時再按會收起來**。取樣或驗證時忘記這件事，整組測試會白做
（畫面上看到的是「卸下」而不是「裝備」）。

D2 的 toggle 曾在 `harvester.execute_scan` 漏守：掃描器已裝備時它仍盲按 "2" → 卸裝 →
整層沒掃描（H065）。現已加 `slot_selected(d2_slot_region)` 守門，與 D1（`miner.py`）同套。
D3 同類問題在 `_fire_d3_at` 漏了 slot 確認（harvest 207：按鍵被吃、D3 從未裝備、3 發全空），
2026-08-06 補上 `slot_selected(d3_slot_region)` 守門。
**新增任何「按數字鍵裝備」的程式路徑，都必須先讀 slot_selected、已裝備就不按。**
