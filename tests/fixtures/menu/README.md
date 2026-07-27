# `menu/` — Roblox 設定選單 Movement Mode

設定選單的實機截圖＝`cfg.menu_panel_region` 那塊裁圖（2026-07-28 於**全螢幕版面**重拍，
1040×910；原版拍於視窗化最大化、1000×880）。OCR 時偏移用 `cfg.menu_panel_region` 取，
不寫死座標。全螢幕版面下 Movement Mode **不在 Settings 首屏**，這兩張是照 bot 的路徑
（Settings 分頁 → 捲 4 次 `menu_scroll_amount`）捲到該列後拍的，列中心 y≈836。測試路徑：
`ocr.read_text_boxes` → `roblox_menu.find_label_row_y` → `read_row_value`
→ `value_matches_target`。

| 檔案 | Movement Mode 當前值 |
|---|---|
| `mm_cycle0.png` | `Default (Keyboard)` |
| `mm_cycle1.png` | `Keyboard + Mouse` |

## 為什麼要兩張

這兩個值**字面上互相包含**（都有 Keyboard）。只有一張的話，模糊比對門檻 0.6 訂多少
都看不出差別。`mm_cycle1` 那個測試的名字就叫
`..._not_confused_with_default`——它守的就是這件事。

`value_matches_target(value, target, others, 0.6)` 的 `others` 參數存在的理由也在這裡：
必須同時比「像不像目標」和「像不像其他選項」，只比前者會兩邊都判 True。

## 這個檢查什麼時候會跑

Movement Mode 不對會讓 W + 左鍵的挖礦序列失效。但**啟動時不再跑這個檢查**
（2026-07-11）：session 之間沒有東西會動到這個設定。只有 `auto_reenter` 實際啟用
（config 開 + 面板模板在）時，才在 session 內第一次 `RESET_WAIT` 結束、回 `MINING`
時跑一次。

需要 RapidOCR；未裝時 skip。
