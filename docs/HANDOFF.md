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
- **★ 追蹤框偵測已解**：`vision.find_tracker` 用「亮綠外框＋空心率＋黑環 OR 彩色中心」顏色偵測，
  實機真畫面準確命中、排除側邊面板/綠色數字/純綠背景/掃描道具誤判。74 個單元測試全綠。
- **★ 採集端到端已驗證 (2026-06-27)**：`start_scan()` 按 2 + click 觸發 D2 → 旋轉找 tracker →
  裝 D3（等 0.6s）→ hold click 0.4s 在 tracker 螢幕座標 → 立即消失 = 成功。
  聊天框確認「has found」、礦物數量增加。全流程不需精準置中 camera。

## 2. ✅ 已解決：採集端到端打通（2026-06-27）

`start_scan()` 按 2 裝備 + 點中央觸發，`find_tracker` 找到框後裝 D3（等 0.6s）+ hold click（0.4s）在框的螢幕座標，框立即消失確認成功。

**實機驗證踩過的坑**：
- D2 按 2 後還要**左鍵點畫面**才算真正觸發（純裝備不夠）。
- D3 必須 **hold click（按住 0.4s）**，瞬間 click 無效；且按 3 後要等 **0.6s** 裝備動畫。
- 掃描道具（hand 持 D2 時的綠色 star）誤判：area=229 < 400 → 面積門檻自動過濾。
- 純綠背景對策：`find_tracker` 加了空心率檢查（`green_fill < 0.85`），框是空心的 ≈ 56%，實心背景 ≈ 100%。

## 3. 下一步（依優先序）

1. **重掃描邏輯**：`_tick_harvest` 目前的「else 分支」（D3 沒立即消失）只記 log 繼續試，
   但若是掃描到期（tracker 緩慢消失），下一 tick 自然找不到 → 轉回礦坑等下一次 chill。
   若想自動重掃，需在掃描到期後呼叫 `harvester.start_scan()` 重試（可先手動觀察是否需要）。
2. **掃描冷卻偵測**：D2 冷卻中（右下角有冷卻圖）→ 不要再按 D2。可參考 D4 冷卻偵測方式加模板。
3. **垂直方向追蹤框**：目前只用 `,`/`.` 水平旋轉，仰角/俯角的礦沒有處理。
   視需要加上滑鼠右鍵拖曳垂直旋轉（`aim_move`）或放寬 `vertical_extreme_ratio` 判人工的條件。
4. **（次要）** D4 加強事件（左鍵）目前未做，使用者說之後再做；現在 D4 只用右鍵刷新。

## 4. 排錯工具（本階段用到的）
- **mss 截圖看畫面**：`python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab; cv2.imwrite('logs/x.png', grab())"` → Read `logs/x.png`。比 computer-use 截圖乾淨（實體像素、不被遮罩）。
- **computer-use**：可 `request_access` Roblox 後截圖/驅動；驅動只用遊戲鍵（1–5、`,`/`.`、W、左右鍵），**不要按 Esc**。
- **顏色/形狀偵測**：找追蹤框用 HSV 綠 + 黑環 + 彩色中心（見 `find_tracker`）；調參時把候選 blob 印出來看。
- **log**：採集流程已加 INFO log（見 `_tick_harvest`），`config.log_level="DEBUG"` 看更細。

## 5. 怎麼測
- 純邏輯：`python -m pytest -q`（要綠）。
- 實機：Roblox 最大化 → `python -m miningbot.main` → 看 HUD / `logs/`；或用上面的截圖一格一格除錯。
