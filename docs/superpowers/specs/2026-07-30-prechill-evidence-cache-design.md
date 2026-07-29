# chill 前證據快取 ＋ chill 上升緣時間戳（純記錄，不改決策）

日期：2026-07-30
狀態：設計定案，待實作
關聯：`2026-07-30-giveup-rescue-already-mined-design.md`（消費本 spec 的快取）、
`2026-07-30-double-chill-reconciliation-design.md`（消費本 spec 的上升緣時間戳）、
H064（`_reveal_chat`，commit `9a9db7b`）、H054/H055（聊天基準閘與 UI 殘留）

本 spec **不改變任何決策行為**，只新增兩份記錄。可獨立 commit、獨立上線收資料。

## Problem Statement

實機最常見的交人工是「礦在角色直線移動路徑上，chill 響之前就被鎬子挖掉了」——之後
八方位掃描必然全空，走到 `_harvest_giveup("全方位掃描未找到追蹤框（礦可能已被挖走）")`。

07-29 harvest 125 是這型的乾淨樣本：`giveup_before_chat` 最底行就是
`small_lo has found Faedrine`（Faedrine 不在 `common_ore_names()`），左下 NORMAL 面板也
有 Faedrine，但 bot 仍然交了人工。

要判「是不是已經被挖走」，需要一個 **chill 之前**的參考點，而現在完全沒有：

- 聊天基準裁圖在 `_on_enter(State.HARVESTING)`（`main.py:3243`）才拍，那時礦**已經**被挖掉，
  證據就在基準裡面，差分恆為 0。
- `_late_chat_confirm`（`main.py:5914`）第一行 `if self._chat_baseline is None ... return False`；
  `_chat_baseline` 只在開火**之後**才 OCR。sweep 全空＝沒開過火＝三個呼叫點
  （pre-sweep `5491`、post-sweep `5512`、d3-timeout `5574`）全部是 no-op。

第二個缺口：同一 episode 內第二聲 chill 完全沒有留痕。07-29 14:43:58 chill 進 harvest 123，
**14:44:14 又響一次**，log 只有一行「chill 觸發」——沒有計數、沒有事件、沒有通知
（`_check_spawn_chill` 只覆蓋 `NEEDS_HUMAN`／`REENTRY`）。而且 `latest_score()` 是滾動比對，
同一聲會連續多個 tick 都在門檻上（07-22 01:43:31~33 三秒七行是同一聲），要分辨「兩聲」
必須數上升緣——但**現在沒有任何回落資料可以拿來定 debounce**。

## Solution

### A. chill 前證據快取

MINING tick 期間持續保留最近幾秒的兩份裁圖，供之後的救援邏輯當差分基準。

- **只裁圖、不 OCR**。裁圖是 numpy slice，成本可忽略；OCR 是 MINING 迴圈最貴的東西
  （H026 就是 3-pass OCR 卡在確認→開火之間造成的），絕不進主迴圈熱路徑。
- 兩份區域：`cfg.chat_region`、`cfg.backpack_review_region`。
- 環形緩衝，固定間隔取樣：`prechill_cache_interval_s`（預設 `1.0`）、深度
  `prechill_cache_depth`（預設 `6`）→ 覆蓋約 6 秒，記憶體約
  `6 × (460×280 + 226×335) × 3B ≈ 3.7MB`。
- 每筆存 `(timestamp, chat_crop, panel_crop)`。
- 只在 `State.MINING` 且未暫停時更新（其他狀態的畫面對「挖礦途中挖到什麼」沒有意義）。
- 進 `HARVESTING` 時**不清空**——救援要在 episode 中後段才用得到它。
- 取用介面：`Bot._prechill_ref(before_ts, min_age_s)` 回傳「時間戳 ≤ `before_ts - min_age_s`
  的最新一筆」，沒有符合的回 `None`。
  - `prechill_min_age_s` 預設 `3.0`。為什麼要有下界：太新的參考可能已經含了那次挖掘
    （chill 偵測本身有延遲）；太舊則把無關的挖掘一併算進差分、製造假「已被挖走」。
    這個值**待實機資料修正**，先給保守初值。

### B. chill 上升緣時間戳

`observe()` 內既有的 `chill_audio = score >= cfg.audio_match_threshold` 後面加一段純記錄：

- 維護 `self._chill_above: bool`。
- `False → True`：記一筆上升緣（時間戳、分數）到 `harvest.log`，並 append 到
  `self._chill_edges`（bot 級 list，`_on_enter(MINING)` 時清空＝以 MINING 為 episode 邊界）。
- `True → False`：記一筆回落（時間戳、分數）。
- **不做 debounce、不做任何門檻判斷、不影響 `chill_audio` 的值。** 這一版的唯一目的是
  產生「上升緣與回落之間隔多久」的實機分布，讓
  `2026-07-30-double-chill-reconciliation-design.md` 有數字可以填。
- H060 的防掛機靜音（`audio.chill_muted_after_antiafk`）**在上升緣判定之前**套用，
  免得防掛機跳躍音污染這份資料。

## Config

```python
prechill_cache_interval_s: float = 1.0    # chill 前裁圖取樣間隔
prechill_cache_depth: int = 6             # 環形緩衝深度（× interval = 回溯秒數）
prechill_min_age_s: float = 3.0           # 參考點至少要比 chill 早這麼久（待實機修正）
```

## Testing

純函式先測：

- 環形緩衝的取用邏輯（給一串 `(ts, ...)` 與 `before_ts`／`min_age_s`，驗證選到哪一筆、
  空的與全部太新時回 `None`）。
- 上升緣狀態機（給一串分數序列，驗證產生的上升緣／回落序列；含「連續多 tick 在門檻上
  只算一次上升緣」與「防掛機靜音期間不算」）。

不需要 Roblox、不需要裝置。裁圖與 log 的 I/O glue 用 `tests/fake_bot.py` 既有 harness。

## Further Notes

- **不要把 OCR 塞進快取路徑。** 之後救援只在 giveup 前跑一次，那時 OCR 兩張裁圖的成本
  （~1s）完全可接受；每 tick OCR 則會重演 H026。
- 記憶體上界是刻意選小的。要回溯更久就調 `prechill_cache_depth`，但要先確認差分不會
  因為納入太多無關挖掘而變髒。
- 快取只在 MINING 更新，所以「上一場採集剛結束、還沒回到 MINING 就又 chill」的情況會
  拿到較舊的參考。這是已知天花板，先觀察發生頻率再決定要不要處理。
