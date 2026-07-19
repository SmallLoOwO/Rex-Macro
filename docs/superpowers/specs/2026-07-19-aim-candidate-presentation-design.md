# 近失候選呈現改版＋手動模式現場重掃（2026-07-19）

## 背景與問題

2026-07-11 遠端瞄準上線後，交人工卡的「近失候選」實際操作有三個斷點
（2026-07-19 使用者反映）：

1. **編號對不上圖**：初始把 4 張疊圖塞同一則訊息（Discord 排 2×2 縮
   圖），圖上只有小字英文標頭 `DIR 5 | LAYER MID | ...`；每張圖的中文
   caption（「方位 5｜層 mid」）在群發時被 `groups.insert(0, ("aim",
   paths))` 丟掉。使用者看得到黃框編號，卻不知道「哪個數字是哪張圖、
   方位 5 長什麼樣」。
2. **手動精瞄喧賓奪主**：群標題把「回編號」與「`方位 格子` 如 `5 C3`」
   並列，看起來是兩個同等選項。正確定位：候選已帶偵測當下的座標，主流
   程應是**回編號→腳本用已存座標自動對齊＋射擊**；`方位 格子` 是偵測
   全滅、人眼卻看得到框時的最後手段。
3. **手動模式素材不可靠**：要用 `方位 格子` 得先看到該方位的圖，但舊
   sweep 快照是歷史幀——D2 掃描效果有時效（框會淡掉），掃到後段的幀
   效果可能已消失，圖上什麼都沒有。

## 核心不變量（D2 效果保證）

- **候選圖一律用偵測當下的原幀**。近失／觀測候選就是從那一幀偵測出來
  的（colored>0.40 或形狀分存在＝框色在圖上亮著），效果保證成立。禁止
  事後補拍候選圖——補拍時效果早已到期。
- **手動模式的全方位圖一律現場重掃後拍**：重按 D2、`_confirm_scan` 確
  認生效，才逐方位擷取。不重發歷史 sweep 快照。
- Discord 輪詢執行緒只發布意圖（`_pending_aim`），遊戲輸入全部由主迴
  圈消費（既有鐵律，手動模式同樣適用）。

## 設計

### 1. 初始訊息流（維持 4 張/則群發）

- **圖片排序改「依圖內最小候選編號升冪」**（現行依最佳分數降冪）。
  `build_aim_context` 已把觀測證據（accepted/fired/seen_once＝掃到過但
  沒採到）排在近失前面，所以有這類證據時 ① 天然是最優快速重採入口，
  且**第一則訊息的第一張圖必含 ①**。
- **第一則**＝交人工內容＋群標題＋候選總表＋前 4 張圖。
- **後續批次**＝其餘候選圖 4 張一則（候選上限 9 → 最多 3 則），每則
  caption 列出該批內容，如「🎯 近失候選（續）：⑤⑥｜DIR3・DIR6」。
- **群標題改寫**：「🎯 近失候選——回編號（如 `2`）腳本自動對齊射擊；
  `跳過` 回挖礦；`手動` 最後手段（重掃＋全方位圖）」。`方位 格子` 語
  法從群標題移除。
- 實作沿用 `image_groups` 機制：`format_group_messages` 的 caption 查
  表本有 fallback（查不到 region 就直接把傳入字串當 caption），aim 從
  「一組 4 圖」改為「多組、組名即完整 caption」。群標題文案移入
  `remote_aim`，由批次組字函式組進首組 caption；
  `notify._REGION_CAPTIONS` 的 `"aim"` 鍵移除（改靠 fallback），
  `notify.py` 其餘零改動。批次切分／caption 組字抽成 `remote_aim` 純
  函式（如 `build_aim_groups(rendered) -> [(caption, paths)]`），
  `_render_aim_shots` 只負責 I/O。

### 2. 候選總表（純函式）

`remote_aim.format_candidate_summary(candidates) -> str`，一行一候選：

```
①（最優）DIR5・約C4・曾鎖定未採到——回 1 快速重採
② DIR2・約D2・分數0.38・形狀分不足
③ DIR7・約B3・色0.52・太靠邊
```

- 「約C3」由候選已存座標反算：新增 `grid_cell_of(pos, w, h, cols,
  rows) -> "C3"`，為 `grid_cell_center` 的逆函式。
- ① 為觀測證據（status 屬 fired/accepted/seen_once）時加「（最優）…
  快速重採」提示行格式；其餘照一般行。
- 分數顯示規則：score ≥ 0（有 edge）顯示 `分數{score:.2f}`；score <
  0（無 edge、排序鍵為 colored−1.0 的 HSV-only 候選）顯示
  `色{score+1.0:.2f}`，不出現負數。
- 原因／狀態中文對照（總表與 caption 用；圖上標頭仍英文）：
  `hard_rej`→形狀分不足、`soft`→形狀弱訊號、`margin`→太靠邊、
  `exclude`→在排除區、`preexist`→掃描前已存在、`fired`→射過未確認、
  `accepted`→曾鎖定、`seen_once`→單幀目擊。未知代碼原樣顯示。
- 總表用 `DIR n` 與圖上燒錄標頭同字（cv2 無法畫中文，統一以 DIR 對
  齊，不再一邊「方位」一邊「DIR」）。

### 3. 疊圖標頭加大

`_render_aim_shots` 的黑條標頭加高（38 → 約 56px）、字級加大（0.72 →
約 1.1、thickness 3），內容維持 `DIR 5 | MID | FIRED` 形式——縮圖牆
狀態也能辨認 DIR。候選框、編號字、網格繪製（`draw_overlay`）不動。

### 4. 手動模式（最後手段：現場重掃＋全方位圖）

- `parse_reply`：新增 `手動`/`manual` → `AimReply("manual")`；
  `全部`/`all` 改為同義別名（舊「補發已渲染圖」行為退役，統一走重掃）。
- Poller 端（`_handle_aim_reply`）：manual 需要遊戲輸入 → 寫
  `_pending_aim` 交主迴圈（不再像舊 `all` 直接在 poller 發圖）；busy
  檢查照舊。
- 主迴圈 `_tick_remote_aim` 消費 manual，全程 `remote_aim_budget_s`
  預算：
  1. `_focus_roblox`、`_mine_resetting` 檢查（同 fire 路徑；無需 D3
     冷卻——只拍照不開火）。
  2. 俯仰歸位 mid（`pitch_reset`，`_pitch_drag_verified`），
     `ctx.pose_pitch_layer = "mid"`。只拍 mid 層；`5U C3`/`5D C3` 盲
     射語法保留可用。
  3. `prepare_scan` → `execute_scan` → `_confirm_scan("remote-aim-manual")`
     確認掃描生效；失敗 → Discord 回報「掃描未生效，可再回 `手動` 重
     試或 `跳過`」，不自動重試（有界）。
  4. 8 方位逐一：先擷取目前方位幀（`abs_dir = ctx.pose_net_rotations
     % 8`）→ 存快照 → `_rotate_verified(+1)`，成功才
     `ctx.pose_net_rotations += 1`（被吃不計，該方位可能缺圖，姿態記
     帳保持正確）。轉滿 8 次回原方位。
  5. 每張疊 `draw_grid` ＋大字 `DIR n | MID` 標頭（無候選框），照 4
     張一則發兩則；首則 caption 附格子瞄準說明：
     「回 `方位 格子` 射擊：`5 C3`＝DIR5 的 C3 格；`5U C3`/`5D C3`＝
     上/下層（盲射）；`跳過` 回挖礦」。
  6. 完成後 `_aim_context` 保留，等下一則回覆（編號仍可用）。
- 快照走 `_hsnap`／`append_snapshot_index` 既有落盤與索引慣例。

### 5. help 訊息（「❓ 看不懂」）

改為：「可用：`2`（射候選②）、`跳過`（回挖礦）、`手動`（最後手段：
重掃＋全方位圖＋格子瞄準說明）」。`方位 格子` 語法細節只在手動模式補
發訊息裡出現（解析器平時仍接受，直接打有效）。

### 6. 明確不做

- 射擊執行鏈（對齊、重掃、ROI 放寬重找、開火、聊天驗證）不動。
- `AimContext`／`AimCandidate` 結構不動（排序、編號邏輯已滿足需求）。
- 手動模式不拍 U/D 層（時間成本 ×3，YAGNI；盲射語法兜底）。
- 失敗後的 `aim_fail_scene` 回報圖不在 D2 保證範圍（那是狀態回報，不
  是瞄準素材）。

## 測試

全部純函式面（I/O 端沿用既有人工驗證慣例）：

1. `grid_cell_of` 與 `grid_cell_center` 全格 roundtrip 互逆＋非法輸入
   回 None／邊界座標落格正確。
2. `format_candidate_summary`：觀測 ① 提示行、一般行、`色x.xx` 負分
   顯示規則、原因中文對照、未知代碼原樣。
3. `build_aim_groups`：依最小候選編號排序、4 張/組切分、首組與續組
   caption 格式（含編號與 DIR 列表）。
4. `parse_reply`：`手動`/`manual`/`全部`/`all` → manual；既有編號、
   `5 C3`、`5U C3`、`跳過` 回歸不變。
5. 既有 `tests/test_remote_aim.py` 回歸全綠。

## 驗收

- 交人工卡第一則可直接讀出「回哪個編號、為什麼」；縮圖牆能對出 DIR。
- 有「掃到未採」證據時，① 與第一張圖就是它。
- 回 `手動` 後收到的 8 方位圖是當下重掃、效果亮著的實況。
