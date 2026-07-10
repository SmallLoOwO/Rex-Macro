# 啟動加速＋跳過環境檢查 設計

日期：2026-07-10　狀態：已與使用者確認方向

> **修訂（2026-07-10 實機）**：原第 2 節的 F8 專用鍵**與 Roblox 內建功能衝突**
> （按下會觸發遊戲功能）而廢棄，改採使用者原始提案「暫停重新繼續」語意——
> **啟動環境檢查期間按 Q＝跳過**。語意分派收進 `states.toggle_pause_action`
> 新增的 `skip_env` 分支（startup_phase 最優先，有單元測試）；`_HotkeyController`
> 不再有專用跳過鍵。下文 F8 字樣依此修訂閱讀，其餘機制（skip_event、檢查點、
> 預算、旗標）全部不變。

## 背景（實測數據，logs 2026-07-10 18:44 啟動）

正常啟動要 **~2 分鐘**、失敗路徑 **3 分 26 秒**，且啟動期間熱鍵完全無效：

| 項目 | 實測 | 根因 |
|------|------|------|
| RapidOCR 冷啟動 | 11.3s（同步卡住） | 預熱執行緒排在 UI 檢查**之後**才啟動，第一個 UI 檢查自己踩冷 init |
| 聊天框檢查 | ~11s | OCR 8.2s＋點擊後複檢 2.6s |
| Movement Mode 鏈 | 成功 71~82s／失敗 170s | 每屏選單 OCR 實測 7~24s（設計預期 1~3s）；失敗＝捲 8 屏全吃滿＋重試 |
| 熱鍵 | 啟動期間全滅 | `_hotkey_loop` 執行緒在 init 完成後（run() 尾）才啟動；使用者想中斷只能乾等 |
| STUCK 假警報 | 初始化完成 2s 後就發 | `_last_progress` 在 `__init__` 設定，啟動 3.5 分鐘被算成「無進度」 |

使用者情境：**程式重開（環境沒變）** 佔多數——三項 UI 檢查（玩家列表/聊天框/
Movement Mode）多半是白付的，只要「Q 恢復等價」的 init（聚焦＋視角歸位＋握鎬開挖）。

## 變更

### 1. 熱鍵執行緒提早啟動
`_hotkey_loop` 執行緒從 run() 尾移到 run() 開頭（`_focus_roblox` 之前）。
效果：環境檢查期間 Q/Ctrl+Q/F12 全部生效。F12 之後，各環境檢查步驟間檢查
`self._running`，False 即中止啟動。

### 2. F8 ＝ 跳過環境檢查（新熱鍵）
- `_HotkeyController` 加 `on_skip`（VK 0x77，邊緣觸發，樣式同 R）。
- Bot 設 `self._skip_env_check = threading.Event()`；F8 callback 只在
  **啟動環境檢查階段**（`self._startup_phase=True`）設 event＋log；其餘時間按了無作用
  （單向跳過，非 toggle）。
- 檢查點：三項檢查各自開始前＋玩家列表/聊天框的「第二次確認 OCR」前＋
  **Movement Mode 鏈內部**（重試迴圈每輪頂、捲屏迴圈每輪頂、箭頭點擊迴圈每輪頂）。
  觸發後：MM 鏈內（選單開著）先 Esc＋settle 收選單再中止；檢查與檢查之間直接略過。
- 跳過後照常跑 `init_mining_sequence`（視角歸位＋確認鎬子＋W+左鍵，~5-10s）。
- HUD 提示：環境檢查開始時 `last_action="環境檢查中…（F8 跳過）"`。
- 為何 F8：S（角色後退）/Enter（聊天）/R、Q 等皆衝突；F 系與 F12 一致。

### 3. RapidOCR／tesserocr 預熱移到 `Bot.__init__`
與音訊載入、HUD 倒數、聚焦重疊，UI 檢查不再踩冷 init（可遮蔽 6~11s）。

### 4. Movement Mode 總時間預算 `menu_budget_s`（config，預設 90s）
`_set_movement_mode` 起算 deadline，鏈內所有檢查點（同 F8 檢查點）超時即中止
（選單開著先 Esc 收）、回 False 走既有「記警告繼續」路徑。失敗上限 170s+ → 90s。
**所有呼叫端**（啟動/REENTRY/採集恢復）都吃預算；F8 skip 只有啟動呼叫端傳入。

### 5. STUCK 計時器主迴圈入口重置
進主迴圈前 `self._last_progress = time.time()`，啟動耗時不再觸發假警報。

## 不做（後續候選）
- 選單 OCR 本身 7~24s/屏 的加速（滑條直拉到底、座標快取直點——code 註解已有候選、
  log 已有數據）。動視覺路徑迴歸風險高；F8＋預算先把痛點壓住。

## 測試
- `_HotkeyController` F8 邊緣觸發＋未掛 callback 不炸（照 TestHotkeyR 樣板）。
- 跳過/預算決策若抽純函式則補測；I/O 編排靠實機驗證（重開程式按 F8，量啟動→開挖秒數）。
