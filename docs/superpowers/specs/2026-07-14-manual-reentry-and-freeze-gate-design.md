# 手動回礦指令＋重生凍結活性閘 設計

日期：2026-07-14
狀態：設計定案，待實作計畫
前置：`2026-07-12-remote-reentry-design.md`（remote 回礦本體＋2026-07-13 H043 addendum）、`docs/incidents.md` H043/H044

## 目標與定位

兩件相關的事，一份設計：

1. **修 H044（觸發過早）**：礦坑重生期間遊戲客戶端會**整個渲染凍結約 1~2 分鐘**，現行
   REENTRY 觸發條件「banner 字樣消失＋沉澱 5s」在凍結幀上照樣成立 → 整條開場鏈打在凍結
   畫面上（點擊/俯仰/旋轉全被吃、8 方位拍同一張圖）。修法＝**探測式開場重試**（點擊當探針、
   遊戲區幀差當真值）＋傳送驗證區域化；凍結中最多每 ~20s 點一次「回到地表」，絕不俯仰/旋轉/拍圖。
2. **手動回礦指令**：新增 Discord 指令 `回礦`（同 `reenter`）＋「腳本可能卡住了」警告附
   🏠 反應鈕，隨時可手動走一次完整 REENTRY 流程。**用途不限卡死**——蒐集面板樣本
   （2026-07-12 設計的 ground truth 落盤）、換重生點、或任何使用者想回地表重進的情境都可用。

## H044 實機證據（2026-07-14 18:25，reentry ep3）

| 時刻 | 事件 | 佐證 |
|---|---|---|
| 18:25:43 | banner「reset in 28 seconds」→ RESET_WAIT → 撤離點擊成功 | miningbot.log |
| ~18:26:11 | 礦坑開始重生 → **客戶端渲染凍結**（頂部凍在事件橫幅「Viridescent ice crystals...」，無 reset 字樣） | 凍結幀快照 |
| 18:26:15 | banner-gone＋5s 沉澱成立 → REENTRY 開跑（**凍結中**） | STATE_CHANGE log |
| 18:26:18~40 | 開場「Go to surface」點擊：前兩次幀差不足，第三次被**覆蓋視窗重繪**灌爆門檻 → 誤判已傳送 | 見下方量測 |
| 18:26:40~18:27:13 | 俯仰歸位＋8 方位旋轉全部 mean=0.0 frac=0.0 被吃；8 張快照同一凍結畫面 | pitch_eaten/旋轉 WARNING×24 |
| 18:28:35 | 使用者按 📷 重掃，畫面已恢復、重掃正常 | discord.log |

**關鍵量測**（`reentry_game_region` 遊戲區裁圖 x1100-1790/y200-850；2026-07-14 晚間完整兩側夾）：

| 樣本對 | frac(>12) | mean | 說明 |
|---|---|---|---|
| 凍結 dir0↔dir1（5s）/dir0↔dir3（12s） | 0.0000 | 0.00 | 逐位元相同＝客戶端真凍結 |
| 凍結 dir5↔dir6（8s） | 0.0504 | 3.81 | 凍結期唯一 blip（單次瞬變） |
| **活著但靜止**（07-12 夜間地表，0.35s／4s／10s） | **0.0000~0.0004** | **0.00~0.09** | ⚠ 與凍結**不可分** |
| 活著、轉 45° 後（18:28 dir0↔dir1） | 0.0285 | 1.32 | 夜空為主的場景轉向後變化也小 |
| 真傳送（礦內→地表） | 0.9966 | 57.73 | 場景整個換掉，訊號極強 |

- 全幀幀差 11.3~13.2 ≥ 門檻 `reentry_teleport_diff=12`——**全部來自覆蓋視窗**（螢幕中央
  Claude 視窗重繪區域幀差 35.3）＋頂部橫幅區 7.5。全幀驗證在「凍結＋有覆蓋視窗」下必然假傳送。
- **被動活性閘被量測否決**：原構想「遊戲區連續 3s 無變化＝凍結」不成立——夜間地表活畫面
  跨 4~10s 的 frac 只有 0.0004，與凍結（0.0000）同量級；被動像素信號無法區分「凍結」與
  「活著但靜止」，硬上會在靜止地表假凍結、卡到超時。改用第 1 節的探測式開場。

**一句話根因**：REENTRY 開場鏈在凍結畫面上全數空轉，因為 (a) 觸發條件只驗 banner 字樣、
凍結幀恰無該字樣，且 (b) 傳送驗證量全幀、被覆蓋視窗重繪灌爆門檻誤判已傳送。

## 已確認決策（2026-07-14 問答）

| 問題 | 決策 |
|---|---|
| 修法路線 | **探測式開場重試**＋傳送驗證區域化（否決固定拉長 settle＝盲猜；否決聊天 OCR 等 regenerated 行＝貴且 H015/H032 淡出風險；**否決被動活性閘＝量測證實與活著靜止畫面不可分**，見上表） |
| 手動觸發入口 | Discord 文字指令＋卡住警告附 🏠 反應鈕（遙控器常駐鈕、本機熱鍵不做） |
| 手動指令用途 | **不限卡死**——蒐集素材或任何因素皆可用 |
| 狀態轉換路徑 | 走 `states.decide_transition` 純函式慣例（否決主迴圈直接 set state） |

## 第 1 節：探測式開場重試（H044 對策 a）

核心想法：**不做被動凍結偵測（量測否決），把「回到地表」點擊本身當探針**——凍結中點擊
必然無反應（區域幀差恆 0，第 2 節保證量的是遊戲不是覆蓋視窗）；點了沒反應就隔一段時間
再點，解凍後的下一次探測自然傳送成功、開場鏈無人工介入地繼續。虛空（H043 偶發成功）也
被同一迴圈吸收——多次探測比單輪 3 連擊更有機會撈到偶發成功。

新 config（全部 `reentry_*`，集中 config.py）：

- `reentry_game_region: Region = Region(1100, 200, 690, 650)` —— 遊戲專屬觀測區（右側場景帶
  x1100-1790 / y200-850）：避開頂部橫幅、左側聊天/NORMAL 面板、右側按鈕欄（x≥1800）、左下
  HUD/狀態小窗，也避開使用者常放覆蓋視窗的中央區。**傳送驗證（第 2 節）用此區**。
  ⚠ 前提：此區必須保持無覆蓋視窗（有視窗在此重繪＝凍結中假傳送，回到 H044）。
- `reentry_open_retry_wait_s: float = 20.0` —— 開場點擊判「未傳送」後，隔多久再探一次。
- `reentry_open_budget_s: float = 300.0` —— 開場探測總預算（自 REENTRY 開場第一擊起算）。
  H044 實測凍結 ~1-2.5 分鐘，300s 蓋過最壞觀測值 2 倍；預算內約 7-8 次探測。

**行為（`Bot._rr_open_episode`＋`_tick_reentry_remote`）**：

1. 開場 `_click_surface_verified`（3 連擊、區域化驗證）判「未傳送」→ **不立刻通知**：
   記 log、排下一次探測（`_rr_open_retry_at = now + reentry_open_retry_wait_s`）、
   HUD `last_action`＝「回礦開場探測中（畫面可能凍結）」。
2. `_tick_reentry_remote` 每 tick 檢查：探測時刻到＋預算未盡 → 重跑開場（reroll 語意，
   attempt+1 記帳——若點擊實際上有效那就是換了重生點，記帳誠實）。非阻塞（主迴圈照常跑
   antiafk／熱鍵／`_mine_resetting` 中斷檢查全程有效）。
3. 傳送成功 → 清探測狀態，照常走俯仰歸位→八方位→發圖（此時畫面必然是活的，
   今天「8 張凍結圖」不再可能——傳送驗證過不了就到不了拍照）。
4. **預算用盡** → Discord 警告一次（附當下截圖：全黑＝虛空、有畫面＝凍結/按鈕失效
   一眼可辨），停止自動探測，等 `重骰`／`跳過`／`回礦`（手動指令＝重啟探測預算）。

不變：RESET_WAIT 觸發條件（banner-gone＋沉澱 5s）**維持原樣**——觸發進 REENTRY 在凍結中
發生也無害了：開場探測只會每 ~20s 點一次「回到地表」（本來就要按的鍵），不會俯仰/旋轉/拍圖。
RESET_WAIT 進場即撤離（H043 對策）也不受影響——banner 出現當下礦體還在、畫面活著。

## 第 2 節：傳送驗證區域化（H044 對策 b）

`Bot._click_surface_verified` 的幀差驗證從**全幀**改為 `reentry_game_region` 裁圖：

- 真傳送＝場景整個換掉，區域化只會讓訊號更強（H043 全幀 ~19 是被靜態 UI 稀釋後的值）。
- 覆蓋視窗（中央）、HUD（左下）、橫幅（頂部）的重繪全部出區 → 假傳送來源根除。
- **兩側夾已完成**（見 H044 量測表）：真傳送 mean 57.73／frac 0.9966，活著靜止 mean ≤0.09／
  frac ≤0.0004，凍結 0.00。判定改**雙訊號 OR**：`mean ≥ reentry_teleport_diff(12.0)` 或
  `frac ≥ reentry_teleport_frac(0.05)`——frac 對「夜空為主、mean 被大片黑稀釋」的地表↔地表
  傳送更靈敏（兩側餘裕 20x／125x）。
- 凍結中點擊 → 區域幀差恆 0 → 判「未傳送」→ 進第 1 節探測迴圈。

## 第 3 節：手動回礦觸發

**純函式（`states.py`，TDD）**：

- `Observation` 加 `manual_reentry: bool = False`。
- `decide_transition` 新分支（均須 `auto_reenter`＝任一回礦模式啟用）：
  - `MINING`＋manual → REENTRY（判序：chill 優先、`mine_resetting` 優先——banner 已出現
    就走既有重置流程，手動旗標作廢）。
  - `NEEDS_HUMAN`＋manual → REENTRY（判序在 `human_cleared` 之前——兩旗標並存時尊重更明確的意圖）。
  - `RESET_WAIT`＋manual → REENTRY，**繞過 reset_complete（含活性閘）**＝人工強制。
    使用者看過畫面（`shot`）決定的，人比閘準；也是凍結超時後的手動逃生口。
    判序：chill 例外仍最優先；manual 在 `human_cleared` **之前**（與 NEEDS_HUMAN 同規則，
    兩旗標並存時尊重更明確的意圖）。
  - `HARVESTING`：不接受（採集有自己的超時/giveup 路徑，插入會亂時序）。
- 新純函式 `can_accept_manual_reentry(state, reentry_active) -> (ok, reason)`：
  指令接收時的守門（HARVESTING/REENTRY 拒收、模式未啟用拒收），回覆文案用 reason。

**Discord 指令 `回礦`／`reenter`（`_handle_discord_command`）**：

- 輪詢執行緒只寫 `self._manual_reentry = True` 旗標（GIL 原子，比照 `_pending_ability`），
  **絕不碰 input_control**；主迴圈建 Observation 時讀取並消費（讀後即清）。
- 消費後若轉出的狀態不是 REENTRY（競態：指令到主迴圈 tick 之間狀態變了，如 chill 搶轉
  HARVESTING）→ 回覆「已忽略（狀態已變 X）」，不留舊旗標補刀（比照 aim-reply 不排隊原則）。
- 暫停中：自動解除暫停（比照 `resume` 語意），回覆註明。
- 拒收情境即時回覆：HARVESTING（「採集中，稍後再送」）、REENTRY（「已在回礦中」）、
  模式未啟用（「reentry_mode=off 或未校準」）。
- `help` 文案補一行。

**卡住警告 🏠 反應鈕**：

- STUCK 警告（「腳本可能卡住了」）送出時記 message id（`_stuck_alert_mid`）＋掛 🏠 反應
  （send 需回 mid；`notify` 若 send_message 不回 mid 則比照 send_embed 擴充）。
- Discord 輪詢迴圈在 `_stuck_alert_mid` 存活時輪詢 🏠 反應（照抄 `_poll_rr_reactions`
  同步語意，含「fetch 失敗回空不可清 seen」守門）；新點擊 → 設同一 `_manual_reentry` 旗標。
- 作廢時機：進度恢復（`_stuck_notified` 重新武裝時）、狀態離開 MINING、或新 STUCK 警告
  取代舊 mid。作廢＝清 mid、停輪詢（訊息留著不刪）。

**記帳**：ledger 條目加 `trigger: "reset" | "manual"` 欄位（蒐集素材時可區分樣本來源）；
REENTRY embed footer 標「手動」。episode 編號沿用既有流水號。

## 第 4 節：測試與 fixture

- **fixture 固化（H044）**：凍結幀對（dir0/dir1 的 `reentry_game_region` 裁圖）、活著靜止對
  （07-12 pitch_eaten 全幀裁區）、真傳送對（礦內→地表裁區）→
  `tests/fixtures/reentry/h044_*.png`。無樣本的修復＝下次必迴歸。
- 開場探測純函式 `reentry_remote.plan_open_retry(first_open_ts, now, wait_s, budget_s, last_probe_ts)`
  → `"probe" | "wait" | "give_up"`：預算內到時刻→probe、未到→wait、預算盡→give_up。
- `decide_transition`：manual×各狀態×auto_reenter 開關矩陣；判序（chill/mine_resetting/
  human_cleared 並存）各一測。
- `can_accept_manual_reentry` 矩陣。
- 傳送驗證區域化：門檻兩側夾數據寫進測試（凍結 0.00／傳送 ≥實測值／靜止 ≤實測值）。
- 回歸：`python -m pytest -q` 全綠；動到 vision 輔助函式則跑 assets 場景回歸。

## 錯誤處理與邊界

- 凍結中收到手動 `回礦`（RESET_WAIT 強制、或預算用盡後重啟）：進 REENTRY → 開場點擊
  區域幀差 0 → 判未傳送 → 進探測迴圈（預算重新起算）。強制權在人、失敗仍有預算收口。
- 真傳送被漏判（兩個重生點在此區的視野恰好都近全黑）：mean 會被大片黑稀釋，frac 雙訊號
  補位（實測真傳送 0.9966，門檻 0.05 留 20x 餘裕）；就算兩訊號都漏，探測重試自然收斂
  ——漏判一次只是多點一次「回到地表」（再換一次重生點），不會卡死。
- `reentry_game_region` 被覆蓋視窗侵入：文件化前提（config 註解＋CLAUDE.md），使用者
  遠端掛機時本來就無覆蓋視窗；在電腦前操作時人眼即時可見、風險可控。

## 不做的事（YAGNI）

- STUCK 自動觸發回礦（使用者要的是手動版；誤觸發成本高）
- 被動凍結偵測／活性閘（量測否決：夜間地表活畫面與凍結像素不可分，見 H044 量測表）
- 聊天 OCR「The mine has regenerated」正向完成信號（貴＋淡出風險；探測式開場已足）
- 遙控器常駐回礦鈕、本機熱鍵（問答否決）

## 文件更新

- `docs/incidents.md` 新增 **H044**（重生凍結期 REENTRY 誤跑＋覆蓋視窗假傳送）：症狀/時間線/
  量測/對策/fixture/commit。
- `CLAUDE.md` REENTRY 段補 H044 一句話對策＋手動回礦指令；Discord 指令清單補 `回礦`。
- memory `project_reentry_void_fall` 或新檔補凍結事實（重生＝分鐘級客戶端凍結）。
