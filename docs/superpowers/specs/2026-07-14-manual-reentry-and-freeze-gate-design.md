# 手動回礦指令＋重生凍結活性閘 設計

日期：2026-07-14
狀態：設計定案，待實作計畫
前置：`2026-07-12-remote-reentry-design.md`（remote 回礦本體＋2026-07-13 H043 addendum）、`docs/incidents.md` H043/H044

## 目標與定位

兩件相關的事，一份設計：

1. **修 H044（觸發過早）**：礦坑重生期間遊戲客戶端會**整個渲染凍結約 1~2 分鐘**，現行
   REENTRY 觸發條件「banner 字樣消失＋沉澱 5s」在凍結幀上照樣成立 → 整條開場鏈打在凍結
   畫面上（點擊/俯仰/旋轉全被吃、8 方位拍同一張圖）。加「遊戲畫面活性閘」：凍結期間不觸發。
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

**關鍵量測**（dir0 vs dir1，相隔 5s）：
- 遊戲區（x1100-1900, y200-900）幀差 = **0.00 整**（逐位元相同）——客戶端真凍結，非低 FPS。
- 全幀幀差 11.3~13.2 ≥ 門檻 `reentry_teleport_diff=12`——**全部來自覆蓋視窗**（螢幕中央
  Claude 視窗重繪區域幀差 35.3）＋頂部橫幅區 7.5。全幀驗證在「凍結＋有覆蓋視窗」下必然假傳送。
- 對照組（活著但靜止的畫面，pitch fixtures，0.35s 間隔）：frac ≥ 0.022、mean 可達 3.29。

**一句話根因**：REENTRY 開場鏈在凍結畫面上全數空轉，因為 (a) 觸發條件只驗 banner 字樣、
凍結幀恰無該字樣，且 (b) 傳送驗證量全幀、被覆蓋視窗重繪灌爆門檻誤判已傳送。

## 已確認決策（2026-07-14 問答）

| 問題 | 決策 |
|---|---|
| 修法路線 | 方案 A：活性閘＋傳送驗證區域化（否決固定拉長 settle＝盲猜；否決聊天 OCR 等 regenerated 行＝貴且 H015/H032 淡出風險） |
| 手動觸發入口 | Discord 文字指令＋卡住警告附 🏠 反應鈕（遙控器常駐鈕、本機熱鍵不做） |
| 手動指令用途 | **不限卡死**——蒐集素材或任何因素皆可用 |
| 狀態轉換路徑 | 走 `states.decide_transition` 純函式慣例（否決主迴圈直接 set state） |

## 第 1 節：遊戲畫面活性閘（H044 對策 a）

新 config（全部 `reentry_*`，集中 config.py）：

- `reentry_game_region: Region = Region(1100, 200, 690, 650)` —— 遊戲專屬觀測區（右側場景帶
  x1100-1790 / y200-850）：避開頂部橫幅、左側聊天/NORMAL 面板、右側按鈕欄（x≥1800）、左下
  HUD/狀態小窗，也避開使用者常放覆蓋視窗的中央區。**活性閘與傳送驗證共用此區**。
  ⚠ 前提：此區必須保持無覆蓋視窗（有視窗在此重繪＝凍結中假活性，回到 H044）。
- `reentry_frozen_hold_s: float = 3.0` —— 遊戲區連續 ≥3s 無任何像素變化＝凍結。3s 是為了
  容忍重生恢復期低 FPS（1 FPS 也會在 1s 內產生變化）；真凍結是分鐘級，兩側餘裕都大。
- `reentry_alive_min_frac: float = 0.01` —— 「有變化」門檻（`vision.frames_changed_frac`）。
  兩側夾：真凍結 = 0.000 整（H044 多組 5s 間隔樣本）／活著但靜止 ≥ 0.022（pitch fixtures）。
- `reentry_freeze_timeout_s: float = 300.0` —— 凍結超過 5 分鐘 → Discord 警告一次
  （「客戶端疑似凍結/當機，維持 RESET_WAIT」），**不轉 NEEDS_HUMAN、不死鎖**：
  繼續等待解凍；使用者可 `shot` 查看、`回礦` 手動強制（見第 3 節）、或 `resume` 接手。

**活性追蹤器（純函式，`reentry.py`）**：狀態＝(ref 裁圖, last_change_ts)。每次餵入當前幀
遊戲區裁圖：`frames_changed_frac(ref, cur) >= reentry_alive_min_frac` → `last_change_ts=now`
且 ref 換成 cur（ref 只在變化時前進，慢速漂移可累積）；`alive = now - last_change_ts <=
reentry_frozen_hold_s`。RESET_WAIT 進場時初始化 `last_change_ts=now`（banner 倒數期間礦體
還在、必然活著）。

**接線（`Bot._update_reset_complete`）**：主迴圈 RESET_WAIT tick 餵活性追蹤器（裁圖＋frac
計算 ~ms 級，可比照 boost 檢查節流 0.2s）。`reset_complete` 條件從「banner-gone 沉澱 5s」
改為「banner-gone **且 alive** 沉澱 5s」——凍結中沉澱計時歸零重來（與 banner 字樣回來同語意）。

不變：RESET_WAIT 進場即撤離（H043 對策）不受影響——banner 出現當下礦體還在、畫面活著。

## 第 2 節：傳送驗證區域化（H044 對策 b）

`Bot._click_surface_verified` 的幀差驗證從**全幀**改為 `reentry_game_region` 裁圖：

- 真傳送＝場景整個換掉，區域化只會讓訊號更強（H043 全幀 ~19 是被靜態 UI 稀釋後的值）。
- 覆蓋視窗（中央）、HUD（左下）、橫幅（頂部）的重繪全部出區 → 假傳送來源根除。
- 門檻 `reentry_teleport_diff=12` 沿用為起點；**實作計畫須用既有快照重新兩側夾**：
  凍結對（H044 dir0/dir1 裁區＝0.00）、真傳送對（ep1-3 開場前後幀、18:25 撤離前後）、
  活著靜止對（pitch fixtures 裁區）。夾不出安全 gap 才調值。
- 順帶效果：凍結中點擊 → 區域幀差恆 0 → 判「未傳送」→ 通知附截圖等使用者指示，
  今天的「無聲拍 8 張凍結圖」變成明確的失敗回報。故開場鏈**不另加**逐步活性等待迴圈（YAGNI）。

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

- **fixture 固化（H044）**：凍結幀對（dir0/dir1/dir3 的 `reentry_game_region` 裁圖）→
  `tests/fixtures/reentry/h044_frozen_*.png`；活著靜止對（pitch fixtures 裁區）；
  真傳送對（ep 開場前後幀裁區）。無樣本的修復＝下次必迴歸。
- 活性追蹤器純函式：凍結對不前進 ts、活著對前進、3s hold 判凍結、RESET_WAIT 進場初始化。
- `decide_transition`：manual×各狀態×auto_reenter 開關矩陣；判序（chill/mine_resetting/
  human_cleared 並存）各一測。
- `can_accept_manual_reentry` 矩陣。
- 傳送驗證區域化：門檻兩側夾數據寫進測試（凍結 0.00／傳送 ≥實測值／靜止 ≤實測值）。
- 回歸：`python -m pytest -q` 全綠；動到 vision 輔助函式則跑 assets 場景回歸。

## 錯誤處理與邊界

- 凍結中收到手動 `回礦`（RESET_WAIT）：強制進 REENTRY → 開場點擊在凍結畫面上區域幀差 0
  → 判未傳送 → 通知附截圖，使用者可 `重骰`/`跳過`。強制權在人、失敗回報明確，可接受。
- 活性閘假凍結（遊戲真的完全靜止 3s+）：地表/礦內都有粒子特效（實測 frac ≥0.022 @0.35s），
  3s 內無任何變化的活畫面未曾觀測到；即使發生也只是多等幾秒（閘會在下次變化解除），方向安全。
- `reentry_game_region` 被覆蓋視窗侵入：文件化前提（config 註解＋CLAUDE.md），使用者
  遠端掛機時本來就無覆蓋視窗；在電腦前操作時人眼即時可見、風險可控。

## 不做的事（YAGNI）

- STUCK 自動觸發回礦（使用者要的是手動版；誤觸發成本高）
- 開場鏈逐步活性等待迴圈（區域化傳送驗證已把失敗顯性化）
- 聊天 OCR「The mine has regenerated」正向完成信號（貴＋淡出風險；活性閘已足）
- 遙控器常駐回礦鈕、本機熱鍵（問答否決）

## 文件更新

- `docs/incidents.md` 新增 **H044**（重生凍結期 REENTRY 誤跑＋覆蓋視窗假傳送）：症狀/時間線/
  量測/對策/fixture/commit。
- `CLAUDE.md` REENTRY 段補 H044 一句話對策＋手動回礦指令；Discord 指令清單補 `回礦`。
- memory `project_reentry_void_fall` 或新檔補凍結事實（重生＝分鐘級客戶端凍結）。
