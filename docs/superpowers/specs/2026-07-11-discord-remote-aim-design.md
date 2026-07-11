# Discord 遠端瞄準（Remote Aim）設計

日期：2026-07-11
狀態：設計定案，待實作計畫
前置：`2026-07-11-pitch-sweep-design.md`（本功能用其分層快照；俯仰掃描未實作時退化成只有標準層，功能仍可用）

## 目標與可行性結論

giveup 交人工的最大痛點＝必須遠端桌面接管，但 sweep 快照裡**往往已經拍到框**（H040/H007 型：真框被 hard_rej 而全空），甚至有幾次其實已採到只是驗證假陰性。本設計讓使用者在 Discord 上直接回訊息指定「哪個方位、大概哪個位置」，bot 自己轉向、重掃、開火——把「遠端桌面接管」降級成「回一則訊息」。

**可行性：可行。** D3 本來就是滑鼠點哪打哪（不需 crosshair 對準）；Discord 收發、表情輪詢、`_rotate_verified`、D2 掃描、verify 管線全是現成零件。最壞結局＝射偏浪費一發 D3、回報失敗繼續等人工＝不比現狀差。

## 已確認的決策（2026-07-11 與使用者問答）

| 問題 | 決策 | 對設計的意義 |
|---|---|---|
| 回應時效 | 不一定，幾分鐘到 10 分鐘以上都有 | **一律重掃**：使用者的點選是「位置先驗」不是實彈座標（D2 框早就到期）；重掃找不到→回報當下截圖再決定 |
| 指位方式 | **候選框編號為主、網格後備** | giveup 案例多半是「偵測有看到但被拒」，回一個數字就能命中；零候選才用網格 |
| 命令格式 | **不用 `!` 前綴**，一般訊息直接解析 | NEEDS_HUMAN 待命時頻道訊息即命令；解析不出→回格式提示、不動作 |

## 第 1 節：giveup 附圖增強（候選編號＋網格）

- **`vision.find_tracker` 增加近失候選外露**：新增選項回傳「被拒但值得人工看」的候選列表——colored_frac 過但 shape 分數落在 hard_floor 附近或以下、被邊緣帶擋、被 preexist 差分擋的 bbox，各附（分數、被拒原因）。每方位依 edge 分數取前 3 個，防洗版。既有回傳簽名與判定邏輯**零改動**（純外掛欄位）。
- **sweep 過程記錄 `SweepRecord`**（harvester 純資料結構）：每（層, 方位）一筆＝快照路徑＋近失候選列表＋拍攝時姿態（該方位的 net_rotations、俯仰層）。三層全空 giveup 時整批送出。
- **附圖疊加**（純函式，輸入幀＋候選列表→輸出疊圖）：
  - 近失候選畫框＋**全域流水編號** ①②③…（跨方位跨層連號，編號→(層,方位,bbox) 對照表存在 aim context）
  - 淡色網格：6×4（格 320×270px），欄 A–F、列 1–4，格線半透明不遮畫面
  - 每張圖 caption 標「方位 N（層 U/–/D）」
- **發送**：沿用 `image_groups` 分則機制。有近失候選的方位優先發（最多 4 張圖一則、依候選最高分排序）；全部方位快照太多（3 層×8=24 張）→ 只發「有候選的」＋「使用者可用 `全部` 指令要求補發其餘方位」。首則帶完整說明文字（回覆格式）。

## 第 2 節：回覆解析（無前綴）

NEEDS_HUMAN 且本輪 giveup 已建立 aim context 時，Discord 輪詢（既有 `_discord_poll_loop`，3s）收到的**一般訊息**直接解析（`remote_aim.parse_reply` 純函式，大小寫不拘、容忍多餘空白）：

| 回覆 | 意義 |
|---|---|
| `2` | 射候選②（層/方位/位置由編號對照表帶入） |
| `5 C3`／`5U C3`／`5D C3` | 網格後備：方位 5、層（U 上/D 下/不帶＝標準層）、C3 格中心 |
| `跳過`／`skip` | 放棄這顆，`_harvest_giveup` 收尾語意改為直接回 MINING（init 序列） |
| `全部` | 補發其餘方位快照（不動作） |
| 其他 | 回一則格式提示，**不動作**（寧可不射不誤射） |

- 編號超出範圍、格子代碼不合法 → 同「其他」處理。
- 一次只執行一發：fire 執行中收到新回覆 → 回「執行中，稍候」忽略之（不排隊，避免舊指令在局勢已變時補刀）。
- aim context 在「回 MINING／轉 RESET_WAIT／新一輪 HARVESTING 開始」時作廢；作廢後的回覆回「目前沒有待瞄準的採集」。
- 執行緒安全：輪詢執行緒只把解析結果寫入單一 pending 欄位（附鎖），輸入操作一律由主迴圈在 NEEDS_HUMAN tick 消費——比照 `_sampler_want` 旗標模式，**輪詢執行緒絕不直接碰 input_control**。

## 第 3 節：執行流程（主迴圈消費 pending fire）

```
1. _focus_roblox
2. 姿態對齊：由 giveup 時記錄的「當前姿態」（face_tracker 有無轉回、net_rotations、俯仰層）
   與目標 (層, 方位) 算旋轉計畫（純函式，沿用 plan_return_rotations 最短路徑）
   → _rotate_verified 轉向；俯仰層走 pitch_reset → nudge（同 pitch-sweep 層轉換）
3. 重新 D2 掃描：prepare_scan（置中、拍新 pre_scan_ref——新 episode，非 H026 的重掃中途禁重拍情境）
   → execute_scan
4. 目標點重找：候選路徑用候選 bbox 中心、網格路徑用格中心，取 ROI（tracker_shape_roi_px 同尺寸）
   a. 先用正常門檻在 ROI 內 find_tracker → 命中用當下座標
   b. 未中→放寬：ROI 內 colored_frac 過即收（人工指定＝最強先驗，shape 門檻整段跳過）
   c. 再未中→直接朝目標點中心開火（miss 代價＝一發 D3）
5. 既有 D3 射擊序列 → 既有 verify 管線（新 episode：開火前重截聊天基準、ChatLedger 重啟）
6. confirmed → 走 _harvest_success 收尾（含俯仰歸位＋restore_view）→ MINING，Discord 回報成功
   未確認 → Discord 回報「未確認命中」＋附當下該方位截圖與聊天裁圖 → 留在 NEEDS_HUMAN 等下一則回覆
7. 全程守門：步驟每階段前查 _mine_resetting → 重置中→回報「礦坑已重置」→ RESET_WAIT，不白射；
   _harvest_boost_guard 照跑（重定位前 FOV 必須穩定）
```

- 姿態基準是最脆的一環：**giveup 收尾時必須落盤 aim context**＝(編號對照表、每筆 SweepRecord 姿態、giveup 後的實際姿態)。兩條 giveup 路徑姿態不同（face_tracker=True 停在最佳方位未歸位；False 已 restore_view＋俯仰歸位），context 記「絕對姿態」而非路徑旗標，旋轉計畫純函式可完整單元測試。
- 單發預算：一次 fire ＝ 1 個 D3 嘗試＋一個 verify 窗口（沿用 `harvest_verify_window_s`），不自動 RETRY/RESWEEP——要不要再射由使用者決定（每次回報附最新截圖，人比 bot 更清楚要不要堅持）。

## 第 4 節：與既有機制的邊界

- **「其實已採到」假陰性情境**：giveup 訊息本來就附聊天前後對比；使用者看到成功行→回`跳過`（或按遙控器 ▶️）直接回挖礦即可，不需要為此加「標記成功」指令（通知/統計價值低於複雜度）。
- 遙控器 ▶️/⏸️、既有 `!keep` 等命令**完全不動**；`!` 開頭訊息仍走舊命令分派，不進 aim 解析。
- Q/Ctrl+Q/F12 熱鍵在整個流程有效；人工遠端桌面接管永遠是後備。
- 俯仰掃描（前置 spec）未實作或 `sweep_pitch_enabled=False` 時：SweepRecord 只有標準層、`U`/`D` 解析為不合法→格式提示。

## 第 5 節：模組切分與測試（TDD）

- 新模組 `miningbot/remote_aim.py`（純邏輯，有單元測試）：`parse_reply`、編號對照表建構、網格格→螢幕座標、旋轉計畫（目標姿態 vs 當前姿態）、疊圖繪製（框/編號/網格）。
- `vision.find_tracker` 近失候選外掛欄位＋回歸測試（既有 fixture 全數不變＝判定零影響；新增「近失被列出」案例，H040 幀是現成素材）。
- `Bot`：aim context 落盤/作廢時機、pending fire 消費 tick、Discord 收發。
- 單元測試鎖：解析表全案例（含全形空白、大小寫、越界編號）、兩條 giveup 路徑的姿態→旋轉計畫、格中心座標、context 作廢後回覆的拒絕行為。
- 完成標準：`python -m pytest -q` 全綠；實機端到端＝人為造一次全空 giveup（遮擋或假門檻）→ 手機回編號 → 確認轉向/重掃/開火/回報全鏈路。

## 風險與對策

| 風險 | 對策 |
|---|---|
| 舊指令打到已變的局勢（礦重置/被撿走） | 一律重掃＋每階段查 `_mine_resetting`；重找不到→b/c 降級也只是浪費一發 |
| 誤解析聊天訊息當指令 | 僅 NEEDS_HUMAN＋aim context 存活時解析；解析不出一律不動作只提示 |
| 姿態記錄與實際脫鉤（旋轉被吃家族） | 全程 `_rotate_verified`／`_pitch_drag_verified`；重試用盡→回報「轉向失敗」不開火 |
| 附圖過多洗版 | 只發有候選的方位、每則 ≤4 張、`全部` 按需補發 |
| 放寬門檻誤收非框 | 放寬只在人工指定的 ROI 內；誤收後果＝射偏一發，verify 不會假成功（ChatLedger 寧漏勿假） |
