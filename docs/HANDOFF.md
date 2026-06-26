# 接手微調 Handoff

把下面整段貼進新 session 當開場提示詞即可。

---

我在接續一個既有專案：Roblox 遊戲「REX」的 Python 自動掛機機器人。**基本功能已完成並驗證，接下來只剩實機微調。** 請先讀 `CLAUDE.md`、`docs/game-mechanics.md`、`docs/superpowers/specs/` 與 `plans/` 了解全貌，再開始。

## 現況（已完成並驗證，51 個 pytest 全綠）
- 狀態機：MINING / HARVESTING / NEEDS_HUMAN / RESET_WAIT
- 挖礦循環、boost（D5，偵測右下角瓶子**消失**才重上）、D4 定時右鍵刷新事件
- **chill 音訊偵測**（喇叭 WASAPI loopback + 交叉相關）— 實測靜音 0.004、播 chill 飆 0.999
- 稀有礦採集：D2 掃描 → 多階級標記「邊緣+多尺度」比對 → `.`/`,` 轉 45° + 滑鼠瞄準（瞄準前連按兩次 Shift 置中）→ D3 → 聊天框「has found」確認 → 轉回原角度
- 礦坑重置偵測：OCR 頂部「reset in」→ RESET_WAIT 停下等重新定位（期間 chill 仍可搶先採集）→ Q 繼續
- 啟動先聚焦 Roblox + 初始化定位才開始；輸入已放慢防漏；置頂不搶焦點的狀態 HUD（左下）
- 診斷：`logs/miningbot.log`（動作/狀態/音訊分數/心跳）、`logs/snapshots/`（關鍵時刻截圖）、`logs/events.log`

## 重要前提（會影響判斷）
- **Roblox 要填滿螢幕**：視覺座標全照 1920×1080 全螢幕校準，視窗化會全錯。音訊不受影響。
- 所有座標/門檻都在 `miningbot/config.py`。
- 改完跑 `python -m pytest -q`（要綠）。純邏輯都有測試。
- 熱鍵 Ctrl+Q 緊急停 / Q 暫停繼續 / F12 結束。

## 接下來要微調 / 補的（依優先序）
1. **採集瞄準**（最需要真實 chill 來調）：`mouse_aim_gain`（滑鼠靈敏度縮放）、`marker_edge_threshold`（標記比對門檻）。等真實 chill 出現，看 `logs/snapshots/` 的 `rare_found` / `needs_human` 截圖逐步調。
2. `audio_match_threshold`（目前 0.55；實測真實 chill 分數再調，避免漏抓或誤觸）。
3. 各偵測區座標若 UI 有出入：`chill_text_region`、`boost_indicator_region`、`chat_region`（用 `python -m miningbot.calibrate`）。
4. **未實作**：跑到一半畫面跑位（Roblox 失焦/視窗位移）的偵測 + 自動重新初始化（第三個觸發）。
5. **（可選）** 礦坑「重置完成音」自動偵測：需使用者提供該音效錄音檔，比照 chill 做音訊比對。
6. OCR 品質偏低（文字會糊）；若要靠 OCR（重置/chill 文字確認），可加影像前處理（放大+二值化）或保持音訊為主。

## 怎麼測
- 純邏輯：`python -m pytest -q`
- 實機：Roblox **全螢幕** → `python -m miningbot.main` → 觀察 HUD / `logs/`
- 想看細節把 `config.log_level` 改 `"DEBUG"`

請先讀文件，然後我們一項一項微調。
