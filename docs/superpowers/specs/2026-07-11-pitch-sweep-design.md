# 失敗路徑俯仰掃描（Pitch Sweep）設計

日期：2026-07-11
狀態：設計定案，待實作計畫
關聯：`2026-07-11-discord-remote-aim-design.md`（Part 2 遠端瞄準會用到本功能的分層快照）

## 目標與可行性結論

現行 sweep 只掃 8 個 yaw 方位、俯仰固定：追蹤框在標準俯仰的垂直視野之外（礦在高處壁上／腳下坡道）時 8 方位怎麼轉都看不到（yaw 只改 x 不改 y，H026 已證實底緣框「換方位也救不回」）。本設計在**失敗路徑**（標準層 8 方位全空、本來就要 giveup 的案例）加掃上、下兩個俯仰層，用時間換遠端介入次數。

**可行性：可行，風險有界。** 最壞結局＝三層都空才 giveup＝多花 ~30-40s 後回到今天的現狀。唯一要認真防的是**俯仰視角回不去**（類比拖曳無精確逆操作，與 yaw 45° 斜角事故同族）——由「層間轉換一律從 pitch_reset 絕對基準出發＋收尾歸位到置中標準角」把關。

## 已確認的決策（2026-07-11 與使用者問答）

| 問題 | 決策 | 對設計的意義 |
|---|---|---|
| 觸發時機 | **失敗路徑限定**：標準層 8 方位全空才掃俯仰層 | 正常採集零額外成本；只在 giveup 前多花 30-40s |
| 掃完視角回哪 | **pitch_reset 標準角即可**，挖礦不挑俯仰 | 不做相對回推記帳，零飄移風險 |
| 標準角定義 | 使用者平常挖礦「會想辦法讓視角置中」 | `pitch_reset` 的回拉量校準成**置中視角**，歸位＝回到使用者習慣角度 |

## 第 1 節：層規劃與流程

```
標準層 8 方位全空（現行 decide_sweep_failure 的「全空→人工」分支）
→ pitch_reset → 上仰 nudge（sweep_pitch_step_px）→ 8 方位掃
→ 全空 → pitch_reset → 下俯 nudge → 8 方位掃
→ 全空 → pitch_reset（回置中標準角）→ giveup（附三層快照）
任一層找到穩定框 → 就地開火（不回標準俯仰）
```

- **層間轉換一律「pitch_reset → nudge N 步」**，不做「從上層直接拖到下層」的相對移動：每層都從夾限飽和的絕對基準出發，單次拖曳被吃不會污染下一層。
- 俯仰拖曳沿用 `Bot._pitch_drag_verified`（幀差驗證，量測同 `_rotate_verified`）：驗證失敗重試 1 次，再失敗→**跳過該層**記 WARNING 繼續下一層（寧可少掃一層，不可在角度不明時記帳硬掃——45° 斜角事故的教訓）。
- 層順序固定「上→下」：實機經驗礦多在壁上高處；H026 證實下方也會漏，故兩層都掃，不做只上不下。
- **只掛在「全空」分支**。`decide_sweep_failure` 的另一分支「看過穩定框但 verify 失敗→重掃一次」不動：那是 FOV 位移問題，框就在標準層，加俯仰只是浪費時間。

## 第 2 節：找到框之後

- **就地開火**：D3 以滑鼠點擊位置瞄準（不需 crosshair 對準），在上/下層直接用當下座標走既有射擊序列（按 2→3→hold click），不先回標準俯仰。旋回最佳方位仍走 `plan_return_rotations` 最短路徑（同層內 yaw 邏輯完全沿用）。
- D3 / verify / RESWEEP / RETRY 全程停留在該俯仰層；`_reharvest_sweep`（RESWEEP、D3 連 miss 重掃）**只重掃當前層**，不重跑三層地毯（框剛剛就在這層看到過）。
- **收尾統一歸位**：成功（`_harvest_success`）與放棄（`_harvest_giveup`）路徑，在既有 `restore_view`（yaw）之外加 `pitch_reset` 回置中標準角。face_tracker=True 的放棄路徑（保持面對框）**不歸位俯仰**——與「不轉回 yaw」同理，人工要看著框。
- HARVESTING 期間的 `_harvest_boost_guard` 在俯仰層照跑（D5 到期 FOV 縮放對俯仰層一樣致命）；guard 補瓶後重抓幀的既有行為不變。

## 第 3 節：config 與校準

新增 config（全走 `sweep_pitch_*` 前綴，與 reentry 的 `reentry_pitch_*` 分開——兩者用途、校準情境不同）：

| 鍵 | 預設 | 說明 |
|---|---|---|
| `sweep_pitch_enabled` | `True` | 關掉＝完全回到今天的行為 |
| `sweep_pitch_step_px` | 待校準 | 一層的 nudge 量；目標＝約半個垂直視野，三層銜接不留縫也不重複過多 |
| `sweep_pitch_clamp_px` | 沿用 `reentry_pitch_clamp_px` 初值 | pitch_reset 的飽和拖曳量 |
| `sweep_pitch_center_back_px` | 待校準 | 夾限→置中視角的回拉量（＝標準角） |

校準流程＝R 視窗既有俯仰歸位/微調＋編號截圖：在礦內實測「置中回拉量」與「一步 nudge 的視野位移」，數字寫回 config。**校準完成前 `sweep_pitch_enabled` 保持關閉**（比照 reentry 慣例）。

## 第 4 節：超時與快照

- **每層獨立 `sweep_timeout_s`（30s）預算**：層開始時重置計時器（比照「sweep 完成後重置 D3 計時器」的既有先例），不改共用 config；最壞總計 ~90s＋兩次 pitch_reset。
- `sweep_empty_snapshot` 擴充：三層全空時每層每方位快照都落盤 `snapshots/trace/`，檔名帶層標記（`_mid`／`_up`／`_down`），供 `_diag_tracker` 裁模板與遠端瞄準附圖使用。giveup Discord 附圖仍走既有分則機制，不因三層放大附圖數（遠端瞄準 spec 另行處理附圖）。

## 第 5 節：模組切分與測試（TDD）

- **純函式進 `harvester.py`**：
  - `plan_pitch_layers()` → 層序列（含每層的 reset+nudge 參數）；`sweep_pitch_enabled=False` 回空序列
  - `decide_sweep_failure` 擴充：回傳值加「還有俯仰層可掃」的分支（全空 ∧ 尚有未掃層 → `NEXT_LAYER`；層用盡才 `GIVE_UP`）
  - 快照層標記命名
- **I/O 留 `Bot`**：`_sweep_for_tracker` 外包一層「逐層迴圈」，層內邏輯（8 方位、雙幀穩定、早停、boost guard）完全不動。
- 單元測試鎖：層序列（開/關、跳層）、decide_sweep_failure 新分支不破壞既有兩分支（H019 回歸）、收尾歸位在成功/放棄/face_tracker 三路徑的呼叫決策。
- 完成標準：`python -m pytest -q` 全綠；實機驗證＝人為把礦放在標準層看不到的位置（或等自然案例）確認上/下層能撈到＋收尾視角回置中。

## 風險與對策

| 風險 | 對策 |
|---|---|
| 俯仰拖曳被吃、視角不明 | 層間一律從 pitch_reset 絕對基準出發；drag 驗證失敗跳層不硬掃 |
| pitch_reset 在礦內夾限行為與地表不同 | 校準在礦內做；`sweep_pitch_clamp_px` 與 reentry 分開可調 |
| 多 60s 掃描期間礦坑重置 | 既有背景 banner OCR 快取仍在跑；掃層迴圈每層開始前查 `_mine_resetting`，重置中→直接放棄掃描走 giveup/RESET_WAIT 既有路徑 |
| D2 掃描到期（框淡出）跨層失效 | 每層本來就重新雙幀穩定偵測；框淡出＝該層看不到，行為同今天的 RESWEEP 語意，不新增特殊處理 |
