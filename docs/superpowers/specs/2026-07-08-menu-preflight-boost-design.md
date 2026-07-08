# 選單前置切換＋UI 前置檢查＋D5 新顯示適配 設計

日期：2026-07-08
狀態：設計定案，待實作計畫
關聯：`2026-07-08-mine-reentry-design.md`（REENTRY 主設計；本篇是其前置作業補強）

## 背景與動機（2026-07-08 實機發現）

1. **Click to Move 與 shift lock 衝突**：REENTRY 的右鍵 click-to-move 導航需要 Roblox 設定
   Movement Mode＝`Click to Move` 才可靠；但挖礦主迴圈（按住 W＋左鍵）要在鍵鼠模式下跑。
   → 導航前要自動切設定、進礦後要切回來。
2. **必要 UI 預設是關的**：左上聊天框預設收合——verify 全靠聊天 OCR，關著整條確認鏈都是瞎的。
   → 啟動時要檢查並打開。
3. **遊戲更新改了 D5 buff 顯示**：舊「瓶子 buff 圖示消失＝到期」邏輯的偵測區裡，
   現在常駐一顆長得一樣的永久計數圖示 → 舊邏輯會**永遠判 buff 還在、永遠不補 D5**。

## 已確認的事實（2026-07-08 實機截圖＋使用者問答）

| 環節 | 事實 | 對設計的意義 |
|---|---|---|
| Movement Mode 選項 | 三值循環：`Default (Keyboard)` → `Keyboard + Mouse` → `Click to Move`（右箭頭前進） | 最多點 3 次右箭頭必回到任意目標值 |
| 挖礦目標模式 | 使用者確認兩個鍵鼠模式都可 → 取 `Default (Keyboard)` | config 預設值 |
| 選單版面 | Esc → Settings 分頁 → 捲到「View & Controls」區；值文字在列中央、左右箭頭在固定 x 偏移；Shift Lock Switch 在下一列（On，**不動它**） | OCR 錨定可行；今天實測合成輸入（Esc/點擊/滾輪）都有效 |
| 選單自動化的坑 | 合成點擊偶爾把整個選單關掉（原因不明，兩次實錄）；點分頁後值列的螢幕 y 隨捲動位置變 | 每步都要 OCR 驗證＋失敗重開重試；列位置不可寫死，用「捲動→OCR 找標籤」迴圈 |
| D5 新顯示 | 右下（Go to surface 左側）**永久累計次數**圖示（紫框＋青瓶＋紅字，錨定不動）；生效中在其左側**多一顆同款圖示顯示剩餘秒數**（實測 47/61 都吻合 60s buff） | 生效判定＝排除錨位後區域內是否還有瓶子圖示；兩圖示同款、只能靠位置/數量區分 |
| D5 計數語意 | 紅字＝累計使用次數（使用者確認；重進伺服器歸零） | 計數值本身不做訊號 |
| D5 佔位 | 挖礦啟動即用 D5 → 計數圖示自然第一個佔位、位置固定 | 不需要啟動 preflight 特別處理 |
| 舊偵測區 | `boost_indicator_region=(1150,935,665,135)` 涵蓋新圖示位置，但下緣 1070 裁到圖示底（圖示到 y≈1080） | region 要調 |
| 聊天框 | 預設收合（只剩左上圖示）；點圖示（≈(174,71)）展開；展開後固定位置有輸入列「To chat click here or press / key」 | 開/關可從輸入列位置的畫面特徵偵測；今天截圖已有開/關兩態可當 fixture |
| 必要 UI 清單 | 使用者確認：**聊天框開啟＋移動模式正確**兩項，無其他 | preflight 範圍 |

今天實測座標（1920×1080，實作時進 config、校準可調）：Settings 分頁 ≈(760,157)、
聊天圖示 ≈(174,71)、值文字欄中心 x≈1153、左右箭頭 x≈883/1425、捲動滑鼠停 (960,500)。

## 第 1 節：選單驅動 `roblox_menu.py`（新模組）

決策純函式（TDD）＋ I/O 由 `Bot._set_movement_mode(target: str) -> bool` 執行。方案取
**OCR 錨定**（每步畫面驗證；否決盲點固定座標——Roblox 官方選單改版頻繁，盲操作失效時
的表現是亂點選單）。

流程：
1. `_focus_roblox` → 按 Esc → 截圖 → OCR 驗證選單開了（找得到分頁列文字）。
2. OCR 找「Settings」分頁文字框 → 點擊 → 驗證進入設定頁。
3. 捲動迴圈：OCR 找「Movement Mode」標籤；沒有 → 滾輪往下捲一段再找（上限 ~8 屏）。
4. 讀該列值文字：已是目標值 → 關選單收工（**idempotent，可直接當檢查用**）。
5. 否則點該列右箭頭（x 固定偏移、y 跟標籤列）→ 等 ~0.3s → 重新 OCR 驗證；最多 3 點。
6. Esc 關閉 → 驗證選單消失（幀差或 OCR 不再看到分頁列）。
7. 任一步失敗 → Esc 回中性狀態 → 整鏈重試 1 次 → 仍失敗回傳 False，由呼叫端分流。

值比對＝模糊比對且**嚴格贏過另外兩個模式名**（比照 `reentry.pick_layer_button` 的
雙向最近鄰、寧漏勿誤）。config 新增：`movement_mode_mining="Default (Keyboard)"`、
`movement_mode_reentry="Click to Move"`、分頁/箭頭/捲動座標與偏移、捲動屏數上限、重試預算。

## 第 2 節：REENTRY 接線

- 按「回到地表」**之前**：`_set_movement_mode(Click to Move)`；False → NEEDS_HUMAN
  （沒有 click-to-move 就無法導航，reroll 無意義）。
- 進礦驗證成功**之後**、`init_mining_sequence` 之前：`_set_movement_mode(Default (Keyboard))`；
  False → NEEDS_HUMAN（Click to Move 模式下挖礦行為不可信，不可帶病開挖）。
- **所有放棄路徑**交人工前 best-effort 切回 Default (Keyboard)；失敗不擋通知。
- 熱鍵（Q/Ctrl+Q/F12/R）全程照常有效。

## 第 3 節：UI 前置檢查（`Bot.run` 啟動、主迴圈前）

- **聊天框**：偵測輸入列在不在 → 關著 → 點聊天圖示 → 再驗證 → 仍關 → log＋HUD 警告後照常啟動
  （不發 Discord：啟動時人在旁邊；比照 preflight 警訊分流慣例）。
- **移動模式**：呼叫 `_set_movement_mode(movement_mode_mining)`——本身就是「不對就修」。
- REENTRY 期間的模式切換由第 2 節自己管；teleport 不會關聊天框，REENTRY 不重複檢查。

## 第 4 節：boost 偵測適配（D5 新顯示）

- `boost_indicator_region` 調整：右緣縮到永久計數圖示左緣、下緣延到 1080
  （排除錨位後，區域內出現的瓶子只可能是倒數圖示 → 「瓶子在＝生效中」舊邏輯不用改）。
- 新 `assets/boost_active.png` 模板：從 2026-07-08 實機截圖裁倒數圖示；紅字每秒變
  → 沿用既有「edge 形狀比對忽略數字」做法（`find_template_edges`＋`boost_buff_scales=(1.0,)`）。
- 回歸 fixtures（來源＝今天 `logs/d5_before.png`、`d5_active.png`、`d5_expired.png`、
  `reentry_check_now.png`，實作時裁進 `tests/fixtures/boost/`）鎖三態：
  只有計數（到期該補）、計數＋倒數（生效中；47/61 兩種數字變體）；
  「無圖示」態（新伺服器、尚未用過 D5）今天沒截到，下次重進伺服器時補
  （在補到之前，該態的預期行為＝找不到瓶子＝該補，與「只有計數」同向，風險低）。
- `use_boost()` 序列不動：只在 MINING（Default (Keyboard) 模式）跑，點擊不會誤觸走路。

## 第 5 節：測試

- `tests/test_roblox_menu.py`：找標籤/值模糊比對（嚴格贏過另兩值）/箭頭次數規劃/
  重試記帳/失敗分流 純函式。
- boost 三態 fixtures 回歸（`test_vision` 或新檔）。
- 聊天開/關偵測 fixtures（今天截圖兩態）。
- 實機校準清單：兩方向各切一次模式並驗證、聊天開合、REENTRY 全流程 dry-run。

## 風險邊界與明確不做的事

- 選單自動化任何不確定（OCR 對不到、點擊後畫面不符預期）→ Esc 回中性狀態 → 重試 1 次 →
  交呼叫端（NEEDS_HUMAN / 啟動警告）。最壞結局＝等人工＝今日現狀。
- 不做：Shift Lock Switch 切換（維持 On 不動）；選單其他設定；D5 錨位啟動 preflight
  （挖礦第一次用 D5 自然佔位）；倒數秒數 OCR（0.2s 高頻檢查跑 OCR 太貴，形狀比對已足夠）。
