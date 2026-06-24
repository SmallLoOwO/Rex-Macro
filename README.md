# Roblox 挖礦自動化

## 安裝
1. 安裝 Python 3.11+（python.org，勾選 "Add Python to PATH"）
2. 安裝 Tesseract OCR：下載 UB-Mannheim build，安裝後記下路徑（預設 `C:\Program Files\Tesseract-OCR\tesseract.exe`），填入 `miningbot/config.py` 的 `tesseract_path`
3. `pip install -r requirements.txt`
4. 複製 `.env.example` 成 `.env`，填入 Discord token（Phase 2 用，可先留空）
5. 把 chill 音檔轉成 wav：`python -m miningbot.convert_audio "你的chill.mp3"` → 產生 `assets/chill_reference.wav`
6. 下載階級標記模板：`python -m miningbot.fetch_trackers`（高階級；`--all` 含低階級）
7. 執行校準：`python -m miningbot.calibrate`
8. 啟動：`python -m miningbot.main`

## 熱鍵
- **Ctrl+Q**：緊急停止（**不結束程式**）— 放開所有按鍵、停在原地，等你按 Q 重新啟動
- **Q**：手動切換 暫停 ↔ 繼續（緊急停止後、或 NEEDS_HUMAN 處理完，也按 Q 重新啟動）
- **F12**：真正結束程式

## 記錄與除錯
- `logs/miningbot.log`：完整執行記錄（時間戳、狀態切換、偵測動作、提醒）。會自動輪替。
- `logs/events.log`：結構化事件記錄。
- `logs/snapshots/`：關鍵時刻（偵測到 chill、採集成功/失敗、卡住、音訊觸發但文字沒對上）的畫面截圖，方便事後查「機器人當下看到什麼」。
- 想看更細的每幀偵測（音訊分數、標記座標）：把 `config.py` 的 `log_level` 改成 `"DEBUG"`。
