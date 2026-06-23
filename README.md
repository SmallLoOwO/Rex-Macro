# Roblox 挖礦自動化

## 安裝
1. 安裝 Python 3.11+（python.org，勾選 "Add Python to PATH"）
2. 安裝 Tesseract OCR：下載 UB-Mannheim build，安裝後記下路徑（預設 `C:\Program Files\Tesseract-OCR\tesseract.exe`），填入 `miningbot/config.py` 的 `tesseract_path`
3. `pip install -r requirements.txt`
4. 把 chill 音檔轉成 `assets/chill_reference.wav`（見 assets/README.md）
5. 執行校準：`python -m miningbot.calibrate`
6. 啟動：`python -m miningbot.main`

## 熱鍵
- F8：暫停 / 恢復
- F9：NEEDS_HUMAN 狀態下，處理完按此恢復挖礦
- F12：緊急停止並結束
