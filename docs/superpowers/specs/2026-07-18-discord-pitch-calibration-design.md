# Discord 俯仰校準遙控（校準 挖礦／回礦）設計

日期：2026-07-18
狀態：已實作（2026-07-18；計畫 docs/superpowers/plans/2026-07-18-discord-pitch-calibration.md）
前置：`2026-07-17-standard-pitch-presets-design.md`（兩套具名標準角＋calibrate_pitch CLI）、
`2026-07-12-remote-reentry-design.md`（Discord 輪詢／pending 消費模式）、
`2026-07-14-manual-reentry-and-freeze-gate-design.md`（`仰角` 指令與 `_pitch_drag_verified`）

## 問題與目標

`uv run python -m miningbot.calibrate_pitch` 是 console 互動 CLI；Roblox 全螢幕時
console 與遊戲來回切換極難操作。目標：把俯仰校準搬進 Discord，用 embed＋emoji
反應遠端操控，含幅度切換（1/5/10/50 px）細調模式，校準完成把角度值**自動寫回
`config.py`**。可校準的兩個角：

| 目標角 | 欄位 | 夾限欄位 |
|---|---|---|
| 挖礦標準角 | `sweep_pitch_center_back_px` | `sweep_pitch_clamp_px` |
| 回礦標準角 | `reentry_pitch_back_px` | `reentry_pitch_clamp_px` |

## 已確認決策（2026-07-18 問答）

| 問題 | 決策 |
|---|---|
| 執行情境 | **整合進運行中的 bot**（否決獨立程序＝要自建輪詢迴圈且不能同時掛機） |
| 記錄方式 | **自動寫回 config.py**＋同步更新記憶體 cfg 立即生效（否決只顯示＝還是得回電腦改檔） |
| 幅度切換 | **🔁 單顆循環** 1→5→10→50→1，embed 即時顯示目前幅度（否決四顆 emoji＝50 無直覺符號） |
| 截圖回饋 | **每次調完自動截圖**（否決手動 📷＝連續微調操作步數翻倍） |
| 架構 | **方案 A：paused 底下的校準 session 旗標**（否決 B 新增 states.py 正式狀態＝高風險區不值得；否決 C 只放寬 `仰角` 指令＝無 embed/幅度/自動截圖） |

## 硬約束（沿用專案既有鐵律）

1. **Discord 背景執行緒只能發布 pending/cache；遊戲輸入由主迴圈消費。**
   反應輪詢執行緒只記「使用者按了什麼」，聚焦、拖曳、截圖全在主迴圈執行。
2. **無 Websocket/interaction 基礎建設**（全程 stdlib urllib）：「按鈕」＝emoji
   反應輪詢（與遙控器 ▶️⏸️⚡📷🏠 同一條已驗證路徑），不是 Discord Components。
3. **俯仰無絕對讀數**：一切記帳建立在 `pitch_reset`（夾限飽和→回拉）絕對定位上；
   下調在夾限處飽和，記帳同步夾 0（與 CLI `apply_calib_step` 同語意）。
4. 拖曳走 `_pitch_drag_verified`（幀差驗證；被吃警告不擋，比照 `仰角` 指令慣例）。

## 第 1 節：進入／離開

**指令**：`校準 挖礦`／`校準 回礦`（英文同義名 `calib mining`/`calib reentry`）；
無參數預設挖礦。走 `discord_commands.parse_command` 既有解析邊界。

**接受條件**：回礦 episode 進行中拒絕（回覆說明）；已在校準中再收到 `校準` 也拒絕。
其餘（MINING、paused）皆可進入。

**進入流程**（主迴圈消費 pending 後執行）：

1. 記住原 `paused` 狀態 → 強制暫停（借用現有 pause 機制，不新增 states.py 狀態）。
2. 聚焦 Roblox＋settle（沿用俯仰拖曳共用前置）。
3. `pitch_reset(目標角 clamp, 目標角 config 現值)`——**從目前設定值起算微調**，
   不從夾限歸零開始；offset 記帳＝現值。
4. 發校準 embed、貼反應（⬆️⬇️🔁🧭📷💾❌）、自動送第一張截圖。

**離開（❌）**：不寫檔；若 offset ≠ config 現值，離場訊息附上最終 offset 供手抄。
恢復原 `paused` 狀態。無逾時——校準模式與 paused 同等待人語意。

**與其他遙控的互動**：校準期間遙控器 ▶️/⏸️ 與 `pause`/`resume` 指令照常記帳原
paused 意圖但不解除校準；離開校準時以最後意圖恢復。⚡/🏠 等其他遊戲輸入動作在
校準期間一律拒絕並回覆「校準中」（不排隊延後）。

## 第 2 節：embed 與反應

一則校準 embed（`send_embed` 取 message id；狀態變化用**刪舊貼新**（delete＋repost）
而非 `edit_message`——DM 無法清除他人反應（HTTP 403 code 50003），repost 讓反應歸零
使用者才能連按同一顆，與遙控器同一條已驗證路徑；2026-07-19 實作定案修正本行）：

- **標題**：固定字串（供跨重啟掃頻道辨識殘留訊息；比照遙控器 `_REMOTE_TITLE`
  慣例，跨重啟殘留的校準 embed 啟動時只作廢不認領——校準 session 不跨重啟）。
- **欄位**：目標角名稱、目前 offset（夾限上 N px）、config 現值、目前幅度、
  操作說明一行。
- **反應語意**：

| 反應 | 動作 | 遊戲輸入 |
|---|---|---|
| ⬆️ | offset += 幅度；`pitch_nudge(-幅度)` | 有 |
| ⬇️ | offset = max(0, offset − 幅度)；`pitch_nudge(+幅度)`（夾限飽和記帳夾 0） | 有 |
| 🧭 | `pitch_reset(clamp, 0)` 歸位到夾限；offset = 0 | 有 |
| 🔁 | 幅度循環 1→5→10→50→1；只改 embed | 無 |
| 📷 | 手動截圖一張 | 無（唯讀抓幀） |
| 💾 | 寫回 config.py＋記憶體 cfg（見第 3 節） | 無 |
| ❌ | 離開校準（見第 1 節） | 無 |

**每次 ⬆️⬇️🧭 執行後**：`_pitch_drag_verified` → `edit_message` 更新 embed offset
→ 自動送一則**新訊息**附截圖（caption 含目前 offset 與幅度）。截圖走新訊息而非
編輯 embed 附件：現有 `edit_message` 是純 JSON PATCH，換附件需另建 multipart
編輯路徑，不值得。拖曳疑似被吃時 embed 與截圖 caption 標 ⚠（記帳照調，比照
`仰角` 慣例；懷疑沒動就 🧭 重新絕對定位）。

**輪詢**：校準 embed 的反應由既有 Discord 背景輪詢執行緒認領（與遙控器同 cadence
與去重模式：讀反應→比對非 bot 使用者→記 pending→移除該使用者反應）。

## 第 3 節：存檔（💾）

1. 錨定 regex 改寫 `miningbot/config.py` 目標欄位預設值一行（如
   `sweep_pitch_center_back_px: int = 0` → `= 435`），保留該行註解與其他所有行。
2. 同步更新記憶體 `cfg` 對應欄位——本次執行立即生效（挖礦標準角 >0 即解鎖
   啟動歸位／mid 層基準；回礦標準角下次 episode 生效）。
3. Discord 回報「欄位：舊值 → 新值」。
4. 改寫失敗（錨點找不到、檔案異動中）**不硬寫**：回報錯誤與最終 offset 供手抄，
   記憶體 cfg 也不更新（檔案與記憶體不分岔）。
5. 存檔後**停留在校準模式**（可繼續微調再存）；換另一個角＝❌ 離開後重下指令。

## 第 4 節：純函式邊界與測試

純函式（各自單測；I/O 全在 main）：

- `discord_commands`：`校準` 指令解析（含目標角參數與預設值）。
- 幅度循環：`next_step(1)→5→10→50→1`；非法現值回 1。
- offset 記帳：**重用 `calibrate_pitch.apply_calib_step`**（up/down/reset 語意
  已測，不重寫）。
- 反應 emoji→動作映射（未知 emoji 不動作）。
- embed 組字（目標角/offset/現值/幅度 → embed dict）。
- config.py 文字改寫：`rewrite_config_value(text, field, new_value) -> str | None`
  ——錨點不存在回 None；測試含：正常改寫、錨點缺失、值已相同（仍回改寫文，
  冪等）、其他行 byte-level 不變、兩個欄位互不干擾。

流程測試：進入時「記原 paused→強制暫停→離開恢復」順序；回礦 episode 中拒絕
進入；存檔失敗不更新記憶體 cfg。

**不動任何現有 pitch 回歸**（pitch_eaten、probe_frozen、sweep_pitch、
apply_calib_step 既有測試全保留）。CLI `calibrate_pitch` 保留不動（無 Discord
時的備援）。

## 使用者責任（明文）

`校準 回礦` 時角色須自行先站在合適位置（地表傳送框可見處）；bot 只管相機角度
與記帳，不跑位。挖礦角同理（站在礦內代表性位置）。

## 範圍外（明文排除）

- Discord Components 真按鈕／interaction endpoint——無 Websocket 基礎建設。
- states.py 新狀態。
- `sweep_pitch_enabled` 開啟——校準完成只是解鎖前置。
- 校準逾時自動退出。
- 一個 session 內切換目標角。
