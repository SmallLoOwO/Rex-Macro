# CLAUDE.md — Roblox REX 挖礦自動化

Windows 專用 Python 機器人，掛機玩 Roblox 遊戲「REX」（rex-3 wiki）：自動挖礦、用道具、聽到 chill 音效時採集稀有礦、礦坑重置時停下等人工。

## 指令
- 測試：`python -m pytest -q`（純邏輯 TDD，不需遊戲；改完必須綠）
- 啟動：`python -m miningbot.main`（Roblox 要先開好）
- 轉 chill 音檔：`python -m miningbot.convert_audio "chill.mp3"` → `assets/chill_reference.wav`
- 下載階級標記模板：`python -m miningbot.fetch_trackers`（→ `assets/markers/`）
- 擷取事件模板：`python -m miningbot.capture_template boost`
- 校準偵測區：`python -m miningbot.calibrate`

## 架構（狀態機）
主迴圈每 ~50ms 擷取一幀，純函式決定動作。狀態：`MINING / HARVESTING / NEEDS_HUMAN / RESET_WAIT`。
- **I/O 薄封裝**：`capture`(mss 截圖)、`audio`(喇叭 loopback + 交叉相關)、`vision`(OpenCV)、`ocr`(Tesseract)、`input_control`(pydirectinput)
- **純邏輯（有單元測試）**：`states`(轉換)、`geometry`(瞄準)、`miner`(事件分派)、`harvester`(採集步驟)、`events`
- `main.Bot` 組裝主迴圈；`status_hud` 置頂狀態窗；**`config.DEFAULT` 集中所有座標/門檻/熱鍵**。

## 硬規則 / 重要前提
- **Roblox 必須「填滿螢幕」**：所有視覺座標都照 **1920×1080 全螢幕**校準，視窗化會全錯。音訊偵測不受畫面影響。
- **chill 偵測靠喇叭 loopback**（`audio.LoopbackCapture` 餵 `ChillListener`）。預設只靠音訊（`chill_require_ocr=False`），因 OCR 不穩。
- **所有座標/門檻改 `miningbot/config.py`**，不要散落各處。
- **輸入要保留延遲**（`input_control` 已放慢）；太快會被遊戲吃掉（W/Shift/點擊漏掉）。
- 熱鍵：**Ctrl+Q** 緊急停（不結束）、**Q** 暫停/繼續/重新定位後繼續、**F12** 結束。

## 工作慣例
- 純邏輯改動走 TDD（先寫失敗測試）。
- 在預設分支先開 feature 分支再 commit；commit 訊息結尾加 `Co-Authored-By: Claude ...`。

## 延伸文件（不在此重複）
- 遊戲機制與道具：`docs/game-mechanics.md`
- 設計與計畫：`docs/superpowers/specs/`、`docs/superpowers/plans/`
- 接手微調指引：`docs/HANDOFF.md`
