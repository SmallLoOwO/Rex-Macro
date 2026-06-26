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

## 硬規則 / 重要前提（多為實機踩過的坑）
- **Roblox 要「最大化填滿螢幕」**：視覺座標照 1920×1080 校準。`_focus_roblox` 用 **SW_MAXIMIZE**，
  **絕不可用 SW_RESTORE**（會把全螢幕縮成小視窗、座標全錯）。音訊不受畫面影響。
- **啟動先設 DPI-aware**（`main._set_dpi_aware`）：否則 `mss` 第一次截圖才把行程切 DPI-aware，
  害 `GetWindowRect`/輸入座標在截圖前後不一致（視窗跑位偵測誤判 resized）。
- **道具數字鍵會 toggle 裝備**：對已拿著的工具再按一次該數字鍵 = **收起來**。所以 init 只在
  槽位像素顯示「沒拿鎬子」時才按 D1（見 `miner._ensure_pickaxe`）；D5/D4 用完按 D1 是從別的工具切回，OK。
- **轉視角＝ `,` / `.`（轉 45°，可數、可回歸）**；`pydirectinput.moveRel` 單獨用**不會**轉視角，
  細部瞄準要 **按住右鍵**拖曳（`input_control.aim_move`）。但右鍵難精準，策略以 `,`/`.` 為主。
- **稀有礦追蹤框偵測＝顏色**：`vision.find_tracker`（亮綠外框＋黑色方環＋彩色中心）。**不要**用 wiki 邊緣模板
  （wiki 只有外框、且**中心顏色隨礦物變**，記不完）。會排除場景綠色與綠色數字（如 $金額）。
- **D2 掃描在有 UI 彈窗（如合成視窗）開著時點不到**（點擊被彈窗吃掉）→ 掃描前要先確保無彈窗。
- **chill 偵測靠喇叭 loopback**（`audio.LoopbackCapture` 餵 `ChillListener`）；預設只靠音訊
  （`chill_require_ocr=False`）。**真實 chill 約 0.4**（非參考檔的 1.0），門檻設 ~0.30。
- **所有座標/門檻改 `miningbot/config.py`**；**輸入保留延遲**（太快會被吃掉，放開挖礦左鍵後要 `settle`）。
- 熱鍵用**全域輪詢**（`Bot._check_hotkeys`，GetAsyncKeyState）：**Ctrl+Q** 緊急停、**Q** 暫停/繼續、
  **F12** 結束。焦點在遊戲也有效（`keyboard` 庫在遊戲前景時收不到，已棄用）。

## 實機排錯（怎麼看到畫面）
- 截圖：`python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab; cv2.imwrite('logs/x.png', grab())"` → 再 Read `logs/x.png`。
- 也可用 computer-use（先 `request_access` Roblox）截圖/觀察；驅動遊戲時**只用遊戲按鍵**（1–5、`,`/`.`、W、左右鍵），**絕不要按 Esc**（會開選單）。
- log：`logs/miningbot.log`（動作/狀態/音訊/視窗）、`logs/events.log`、`logs/snapshots/`；`config.log_level="DEBUG"` 看每幀細節。

## 工作慣例
- 純邏輯改動走 TDD（先寫失敗測試）。
- 在預設分支先開 feature 分支再 commit；commit 訊息結尾加 `Co-Authored-By: Claude ...`。

## 延伸文件（不在此重複）
- 遊戲機制與道具：`docs/game-mechanics.md`
- 設計與計畫：`docs/superpowers/specs/`、`docs/superpowers/plans/`
- 接手微調指引：`docs/HANDOFF.md`
