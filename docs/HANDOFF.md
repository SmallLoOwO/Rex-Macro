# 接手 Handoff — 重點：解決「稀有礦自動採集」

> 先讀 `CLAUDE.md`（含實機踩過的坑）、`docs/game-mechanics.md`。本檔記錄**目前進度**與**下一步**。
> 程式碼在分支 `feature/window-discord-controls`（多個 commit，`python -m pytest -q` 全綠）。

## 1. 現況：挖礦主流程穩定，採集卡在「掃描」

實機跑得起來、會穩定挖礦/補 boost/刷 D4/聽 chill/重置等人工，Discord 會通知。**唯一沒打通的是稀有礦採集的「掃描→定位」**。

### 已完成並驗證（本階段）
- **視窗/輸入基礎修復**：`_focus_roblox` 改 SW_MAXIMIZE（原 SW_RESTORE 把全螢幕縮小）；啟動先設 DPI-aware
  （否則 mss 截圖中途切 DPI 害視窗基準誤判 resized）；拿不到前景焦點就中止、不空挖瞎挖。
- **全域熱鍵**：`Bot._check_hotkeys` 用 GetAsyncKeyState 輪詢，Ctrl+Q/Q/F12 焦點在遊戲也有效（`keyboard` 庫已棄用）。
- **D4 冷卻偵測**：偵測右下角「Used」圖示在不在（`miner.cooldown_ready` + `assets/d4_cooldown.png`），冷卻好就用。
- **Discord 通知**：`notify.py`（Bot API），RARE_FOUND/HARVEST_SUCCESS/NEEDS_HUMAN/STUCK/MINE_RESET，已實測送達。
- **挖礦序列對照原巨集**：init 只在槽位像素顯示沒拿鎬子時才按 D1（避免 toggle 收起十字鎬）；boost/D4 用完按 D1 切回。
- **音訊門檻 0.55→0.30**（真實 chill 實測約 0.4）。
- **★ 追蹤框偵測已解**：`vision.find_tracker` 用「亮綠外框＋黑色方環＋彩色中心」顏色偵測，
  實機真畫面準確命中、排除側邊面板與綠色 $金額誤判。4 個單元測試（含換中心色仍偵測到）。
- **採集瞄準機制已釐清**：粗轉用 `,`/`.`（45°、可數可回歸，`harvester` 已記 net_rotations）；
  細部瞄準用按住右鍵拖曳（`input_control.aim_move`）；D3 是用滑鼠點選追蹤框位置來遠距挖。

## 2. 主要待解：採集「掃描」打不通（阻塞點）

實測 D2 掃描**點不出去**：按 2 會選到槽位 2（scanner 確實裝備，hotbar 槽 2 變綠），但左鍵點畫面**沒觸發掃描**
（右下角沒出現雷達冷卻、左下沒出現「Local」）。**研判主因：畫面有 UI 彈窗（合成視窗「Affement [1/2]」）開著，
把點擊吃掉了**。沒掃描就沒有綠色追蹤框，`find_tracker` 自然找不到（這部分是對的，不是偵測的問題）。

次要疑點：D2 掃描本身可能有冷卻（連續掃會點不動）。

## 3. 下一步（依優先序）

1. **讓掃描確實觸發**（核心）：
   - 掃描前先確保無彈窗。需要找出「在遊戲內關掉合成/彈窗」的可靠方法（**不能用 Esc**，會開系統選單）。
     可能：點彈窗的關閉鈕、或某個遊戲鍵。請使用者確認關閉彈窗的操作，或讓 bot 偵測彈窗存在就先提醒/略過掃描。
   - 確認 D2 掃描的冷卻時間（量「按下→雷達冷卻消失」的秒數），避免冷卻內狂點。
   - 驗證成功訊號：掃描成功時**左下出現「Local」**、右下出現雷達冷卻 → 可加偵測當作「掃描成功」確認。
2. **端到端採集驗證**：`main._tick_harvest` 已改成**簡化流程**（待實機跑通）：
   `find_tracker` 找綠框 → 沒看到就轉 `,`/`.` 找 → 看到就**裝 D3 + 直接點選綠框位置**（`ic.click_at`，
   不再精準置中、不用 `next_harvest_step`/`aim_decision`，那些函式留著但未使用）→ 成功判定＝追蹤框消失
   或聊天框「has found」→ 轉回原方位。**注意這條未實機驗證**（掃描卡住，沒機會跑到）。
3. **瞄準微調**：以 `,`/`.` 為主（右鍵難控）。確認 D3 是否需精準置中、或點到框附近即可。垂直偏高的礦
   目前會判 vertical-extreme 轉人工（`vertical_extreme_ratio`），視需要放寬。
4. **（次要）** D4 加強事件（左鍵）目前未做，使用者說「之後再做」；現在 D4 用右鍵刷新。

## 4. 排錯工具（本階段用到的）
- **mss 截圖看畫面**：`python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab; cv2.imwrite('logs/x.png', grab())"` → Read `logs/x.png`。比 computer-use 截圖乾淨（實體像素、不被遮罩）。
- **computer-use**：可 `request_access` Roblox 後截圖/驅動；驅動只用遊戲鍵（1–5、`,`/`.`、W、左右鍵），**不要按 Esc**。
- **顏色/形狀偵測**：找追蹤框用 HSV 綠 + 黑環 + 彩色中心（見 `find_tracker`）；調參時把候選 blob 印出來看。
- **log**：採集流程已加 INFO log（見 `_tick_harvest`），`config.log_level="DEBUG"` 看更細。

## 5. 怎麼測
- 純邏輯：`python -m pytest -q`（要綠）。
- 實機：Roblox 最大化 → `python -m miningbot.main` → 看 HUD / `logs/`；或用上面的截圖一格一格除錯。
