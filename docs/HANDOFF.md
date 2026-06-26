# 接手 Handoff — 重點：解決「稀有礦自動採集」

> 先讀 `CLAUDE.md`（含實機踩過的坑）、`docs/game-mechanics.md`。本檔記錄**目前進度**與**下一步**。
> 程式碼在分支 `feature/window-discord-controls`（`python -m pytest -q` 全綠，87 passed）。

## 0. 快覽（最近進度）

| 項目 | 狀態 |
|---|---|
| find_tracker accept+排名修復（UI 面板/裝備誤判） | ✅ 已 commit `e04bd4d` |
| 採集成功判定改差分（修掉 stale-chat 偽成功）+ 關鍵截圖 | ✅ 已實作 + 87 測試綠，**尚未 commit** |
| 採集端到端實機驗證 | ❌ **被 §3 的新問題擋住，未走通** |
| §3 新問題（聊天框假陽性 / chill 音訊漏抓 / 裸礦無框） | ⚠️ 已診斷 + 已設計解決方案（§4），**未實作** |

## 1. 現況

實機跑得起來、會穩定挖礦/補 boost/刷 D4/聽 chill/重置等人工，Discord 會通知。
採集流程的**判定邏輯**已修好（差分確認、find_tracker accept/排名），但**實機採集鏈路尚未走通** —— 本 session 實機測試發現一串新問題（§3），其中最致命的是 **chill 音訊偵測漏抓**（bot 根本沒進 HARVESTING）與 **find_tracker 把聊天框紅字當 tracker**。

## 2. 已完成的修復

### 2.1 find_tracker：accept 條件 + 排名（commit `e04bd4d`）
- accept 改 `((dark>0.10 and colored>0.04) or colored>0.50)` → 排除暗色 UI 面板（dark 高但 colored=0）
- 排名改用 `colored_frac`（最高優先）→ 真 tracker≈1.00 贏過裝備誤判 0.75-0.88
- 79 測試綠；`logs/rot_3.png` 驗證回傳 (1347,254)（不再錯選 UI 面板）

### 2.2 採集成功判定：差分聊天確認（已實作未 commit）
**舊 bug（沉默失敗）**：`_verify_success` 用 `ocr.contains_any`（**存在性**）。聊天框是累積的，
一旦出現過 "has found"，之後每次 D3（不管有沒有命中）都被判 `HARVEST_SUCCESS`。
實機 03:06 事件已證實：`confirmed=True tracker_gone=False` 偽成功 → bot 回 MINING → 追蹤框被丟著沒採。

**新邏輯（`miningbot/ocr.py` + `main.py:_tick_harvest`）**：
- `ocr.count_found(text, phrases)` → 計關鍵字出現次數（正規化）
- `ocr.has_new_found(before, after, phrases)` → **D3 後數量必須多於 D3 前**才算新事件
- `_tick_harvest`：D3 前讀 `chat_before` → D3 → 讀 `chat_after` → `confirmed = found_after > found_before`
- **特殊階標記**：`cfg.special_keywords=("ionized","spectral")`，同樣用差分 → `special=True/False`
  （ionized/Spectral 進「另一個背包」，左側 normal 面板看不到，只能靠聊天字樣）
- 連續同一個稀有礦也正確分辨（計數 +1）
- 已移除 `_verify_success`，改用 `_read_chat` + `_snapshot_crop` 兩個輔助函式
- **關鍵截圖**（你要的「盤別」功能）：`d3_fire_<x>x<y>.png`、`d3_chat_before.png`、`d3_chat_after.png`、
  `harvest_success.png`（或 `_special`）、`d3_miss_<n>.png`
- 87 測試綠（含 8 個新 ocr 差分測試）

## 3. ★ 實機測試發現的新問題（未修，本 session）

用 `logs/_test_harvest.py` 拿一顆 leftover tracker 做獨立採集測試，結果 D3 沒採到，連帶暴露一串問題：

### 問題 A：find_tracker 把聊天框紅字當 tracker（**最關鍵**）
- D2 掃描後偵測到 `(434, 385)` `colored=1.00 fill=0.30`，D3 點過去 → 沒採到（Cordis Gemma 4→4、Bandeau 19→19）
- `(434, 385)` 落在 **`cfg.chat_region=(0,110,460,280)` 內**（聊天框右下邊緣）
- 聊天框裡紅字「Bandeau」（Otherworldly 階）+ 紅色邊框 → 命中 `range3`（H=153-179 暗紅）→ 通過 hollow/colored 檢查 → **假陽性**
- 注意：`margin_frac=0.10` 只排除外框 10%（x<192），但聊天框延伸到 x=460，**深入搜尋區**
- 真正的綠色 Cordis Gemma 礦在 `(~1000, 300)` 但沒被選上（被假陽性蓋過／或當時無框）

### 問題 B：chill 音訊偵測漏抓（**同樣致命**）
- heartbeat 顯示 `audio=0.01`，但畫面**正顯示 chill**（「fluttering...comfort」文字 + tracker）
- 門檻 0.30，真實 chill 應 ≈0.4（CLAUDE.md）；0.01 = loopback 根本沒聽到 chill
- → bot 從不進 HARVESTING → 採集流程根本沒啟動（events.log 自重啟後無 RARE_FOUND）
- 可能原因：① loopback 綁錯音訊裝置 ② chill 參考 wav 不符此環境（twilight magic 區？）
  ③ 遊戲音效路由到別的裝置／被靜音

### 問題 C：D3 點到聊天框會清空聊天歷史
- 問題 A 的連鎖效應：D3 hold-click 落在聊天框邊緣 → 聊天歷史被清空/滾掉 → `chat_after=''`
- → 差分驗證讀到空白（恰好這次 found 3→0 判「未採到」是對的，但原因是 chat 被清，不是 diff 正常運作）
- 根本治 = 問題 A（別再點到聊天框）

### 問題 D：裸礦可能沒有 outline 框（**待確認**）
- agent 觀察到綠色 Cordis Gemma 礦體 `(~1000,300)` **沒有可見的彩色外框**
- 但那是 D2 掃描**前**的幀；掃描後理論上遊戲會畫框。測試時沒看到 "Local" 標籤 → **D2 掃描可能根本沒成功**
- 待確認：① 成功的 D2 掃描是否必定畫框？ ② 礦種是否影響有無框？

## 4. 解決方案設計（給下個 session 實作）

### 4.1 問題 A：find_tracker 加 `exclude` 參數排除 UI 區
```python
def find_tracker(frame_bgr, margin_frac=0.10, exclude=(), log=None):
    # exclude: 一串 (x0,y0,x1,y1) 矩形，候選中心落在任一矩形內就 reject
    ...
    in_area = (mx0 < cx < mx1 and my0 < cy < my1)
    in_exclude = any(x0 <= cx <= x1 and y0 <= cy <= y1 for (x0,y0,x1,y1) in exclude)
    accept = in_area and not in_exclude and frame_fill < 0.85 and (...)
```
- Bot 端：`vision.find_tracker(frame, exclude=_ui_zones(), log=...)`，其中 `_ui_zones()` 把
  `cfg.chat_region`（Region x,y,w,h）轉成 `(x, y, x+w, y+h)`，未來可加庫存面板等其他 UI 區
- TDD：合成一個 tracker-like blob 放在 chat_region 內 → 應回 None；放在區外 → 應偵測到
- 純函式、低風險、完全可測

### 4.2 問題 B：chill 音訊診斷 + 修復路徑
**先診斷**（決定是哪個原因）：
- heartbeat 加印**原始音訊 RMS**（`np.sqrt(np.mean(buf**2))`）。RMS≈0 → loopback 死；RMS 高但 score≈0 → 參考 wav 不符
- 確認 `audio.LoopbackCapture` 綁的 `defaultOutputDevice` = 遊戲實際輸出裝置
- 錄一段此環境的 chill → `python -m miningbot.convert_audio` 重生 `assets/chill_reference.wav`

**修復選項**（依診斷結果）：
- 參考 wav 不符 → 重生（最可能）
- 裝置不對 → 改 LoopbackCapture 指定裝置
- **快速止血**：暫時 `cfg.chill_require_ocr=True`，用 OCR 抓「A chill goes down your spine」文字觸發（不靠音訊）

### 4.3 問題 C：隨 A 解決 + diff 容錯
- 主要：問題 A 修好後 D3 不會再點聊天框 → chat 不會被清
- 次要：差分若讀到 `chat_after` 空白但 `chat_before` 有內容 → 視為可疑，re-grab+re-read 一次再判（chat 不該瞬間全清）

### 4.4 問題 D：先確認遊戲機制
- **問玩家**：成功的 D2 掃描是否必定在稀有礦上畫 outline 框？不同礦種是否都會畫？
- 加 D2 掃描成功驗證：`start_scan()` 後檢查左下 "Local" 標籤是否出現（CLAUDE.md 說這是成功訊號）；
  沒出現 → 掃描失敗 → 重試或 NEEDS_HUMAN（目前完全沒驗證）
- 若確認裸礦常態無框 → find_tracker 改偵測「高飽和度方塊本體」而非「外框」，是較大改動

## 5. 驗證項目（修完 §4 後跑）

1. `python -m pytest -q` 全綠（目前 87）
2. `logs/rot_3.png` → find_tracker 應回傳 (1347,254)
3. `logs/d3test_rot1.png` → 應回傳 None
4. `logs/rescan_init.png` → 應回傳約 (1352,256)
5. **新增（問題 A）**：合成 tracker 放在 chat_region 內 → find_tracker(exclude=[chat_rect]) 應回 None
6. **實機**：跑 `logs/_test_harvest.py`（見 §6），D3 應命中真礦、稀有庫存 +1、聊天出新 "has found"
7. **實機**：bot 跑到 chill → 進 HARVESTING → 採集成功 → HARVEST_SUCCESS 含 `found N->M (M>N)`

## 6. 排錯工具（logs/ 內，可能未被 git 追蹤）

- **`logs/_cap.py [name]`**：截圖存 `logs/<name>.png`（設好 DPI-aware + sys.path）
- **`logs/_test_harvest.py`**：★ 獨立測完整採集流程（不跑 bot）。目前缺：**沒存 post-scan 幀**。
  → 下個 session 增强：存 pre-scan/post-scan/post-D3 三幀 + 每步完整候選 log，才能診斷問題 A/D
- **`logs/_diag_tracker.py`**：對指定 PNG 跑 find_tracker 印出所有候選（不只 OK 的）
- mss 截圖 one-liner、`vision.find_tracker(img, log=print)`：見 CLAUDE.md
- log：`logs/miningbot.log`（動作/狀態/音訊/視窗）、`logs/events.log`（結構化事件）、`logs/snapshots/`

### 重要環境提醒（本 session 踩過）
- **SSH 連線 = Session 0 Isolation**：從 SSH 跑的程式抓不到實體桌面（Session 2）的 Roblox。
  機器人必須在**本機桌面**啟動（或 RDP console session）。log/snapshot 檔案共享，可從遠端監看。
- **Windows Store 版 Python** 的 image name 不是 `python.exe`，`tasklist /FI python.exe` 會漏抓 →
  用視覺證據（HUD 截圖）判斷 bot 是否在跑，別信 process name 過濾。

## 7. 其他待辦（優先序較低）
- 掃描 8 幀無 tracker → NEEDS_HUMAN + Discord（邏輯已有，待實機驗證）
- D2 冷卻偵測（仿 D4 冷卻模板）
- 垂直方向追蹤框（仰角礦，目前只水平旋轉；`aim_move` 未整合）
- D4 加強事件（左鍵）
- **庫存數量 diff 驗證**（玩家提案，需「礦物→稀有度」對應表）：左側面板是 normal 背包當前狀態，
  normal 礦可監看這欄計數；ionized/Spectral 進別的背包只能靠聊天字樣。需玩家提供礦物清單。
