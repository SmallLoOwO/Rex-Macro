# 背包定期截圖 + 面板色檢比較圖 + spawn chill 抑制

> **日期**：2026-08-05
> **狀態**：已批准（brainstorming），待實作
> **背景**：使用者回報兩個問題——(1) 進場面板色檢命中時只有純文字通知，玩家無從判斷
> 礦是否真的入帳；(2) 面板色檢短路把 state 設成 NEEDS_HUMAN 後，同一波 chill 觸發
> spawn chill 假警報。

## 問題

### 問題 1：面板色檢短路缺圖證據

`_harvest_entry_panel_check`（main.py:7383）命中時，`_on_enter(HARVESTING)` 走短路
（main.py:3698-3711）直接 `return State.NEEDS_HUMAN`。通知文字為：

> 進場面板已有稀有 礦（faedrine），可能 chill 前已被鎬子挖到 → 請確認後按 Q 繼續

但只發純文字（走 line 3817-3824 的 else 分支 = 單張全螢幕截圖），玩家無法判讀
NORMAL 面板——需要背包裁圖才能看到礦名和數量。

### 問題 2：spawn chill 假警報

主迴圈 line 3150 在 state commit 後呼叫 `_check_spawn_chill`。面板色檢短路把 state
設成 NEEDS_HUMAN 後，chill 音效仍在響（就是觸發進場的同一波）→
`should_notify_spawn_chill` 回 True → 發出 "💎 spawn chill！" 訊息。同一波 chill 被
報了兩次：一次是正常 harvest 進場，一次是 spawn chill 假警報。

## 設計

### §1 MINING 期間定期截背包

**觸發點**：`_tick_mining` 加計時器。每 `backpack_snapshot_interval_s`（預設 30s）截
一次 `cfg.backpack_review_region`，存到 `<log_dir>/snapshots/backpack/bp_<epoch>_<HHMMSS>.png`。

**存儲 & 清理**：保留最近 `backpack_snapshot_max_keep`（預設 6）張。新截圖寫入前掃
目錄清除超量舊檔（按檔名 epoch 排序，刪最舊）。截圖走現有 `_enqueue_snapshot` 非同步
佇列（不卡主迴圈）。

**不發 Discord**：純本地存檔，只在 panel-check 短路時才取用。

**生命週期**：
- MINING 進場時（`_panel_zeroed_at` 設定後）重置計時器，截第一張作為「歸零後基準」
- 每次 interval 到就截一張
- 離開 MINING（chill → HARVESTING）後停止截圖
- NEEDS_HUMAN / RESET_WAIT 等待期間不截

### §2 Panel-check 短路時附比較圖

**觸發點**：`_on_enter(HARVESTING)` 裡 `_entry_panel_gains` 命中時（main.py:3698-3711）。

**取圖邏輯**：
1. 掃 `<log_dir>/snapshots/backpack/` 目錄，取檔名 timestamp 最新的那張——「chill 前
   最後一次背包狀態」
2. 截一張當下 `backpack_review_region` 裁圖——「當下面板」
3. 兩張透過 `_needs_human_extra_meta["image_groups"]` 附到 NEEDS_HUMAN（同
   `_harvest_giveup` 的前後對比模式）

**分組格式**：
```python
groups = [("背包比對（chill前 → 進場）", [pre_chill_path, current_path])]
self._needs_human_extra_meta["image_groups"] = groups
```

**通知文字**不變；玩家收到 Discord PING 後緊接著收到兩張比較圖。

**降級**：
- 定期截圖目錄為空（MINING 太短沒截到）→ 只附當下面板一張，通知文字不變
- 截圖檔案讀取失敗 → 跳過附圖，走現有單張截圖路徑（line 3817-3824 else 分支）

**不影響觀察期記帳**：`_panel_check_observed.json` 照舊記錄，附圖是額外證據不改流程。

### §3 Spawn chill 誤觸發修復

在短路路徑 `return State.NEEDS_HUMAN` 之前加：
```python
self._spawn_chill_notified = True  # 抑制同一波 chill 的 spawn chill 假警報
```

**安全性**：
- `_spawn_chill_notified` 已是 `should_notify_spawn_chill` 的去抖動旗標（states.py:84-85）
- chill 音效結束時 `_check_spawn_chill` 重置它（main.py:1374），不影響下一波真正的 spawn chill
- 面板色檢命中表示「這個 chill 的礦已經在面板上」——不是 spawn chill（礦在預設方塊）

**純函式 `should_notify_spawn_chill` 不需改**：呼叫端設旗標即可。

### §4 Config 參數

```python
# config.py 新增
backpack_snapshot_interval_s: float = 30.0   # MINING 期間定期截背包的間隔
backpack_snapshot_max_keep: int = 6          # ring buffer 保留張數（~3 分鐘歷史）
```

### §5 Log

| 事件 | 級別 | 訊息 |
|---|---|---|
| 定期截圖 happy path | `info` | `背包定期截圖 -> %s` |
| ring buffer 清理 | `debug` | `背包截圖清理舊檔 %d -> %d` |
| 短路附圖成功 | `info` (log_harvest) | `[%s] 面板色檢命中 → 附背包比對圖（chill前=%s）` |
| 短路附圖降級 | `warning` (log_harvest) | `[%s] 背包比對圖取不到 → 只附當下面板` |
| spawn chill 抑制 | `info` | `面板色檢短路 → 抑制同一波 chill 的 spawn chill 通知` |

### §6 測試

1. **定期截圖計時**：MINING tick 時間到 → 呼叫截圖、路徑含 timestamp、ring buffer 清理超量舊檔
2. **短路附圖**：`_harvest_entry_panel_check` 命中 → `_needs_human_extra_meta["image_groups"]` 有兩張路徑（chill前 + 當下）；目錄為空時降級只附一張
3. **spawn chill 抑制**：面板色檢短路後 `_spawn_chill_notified` 為 True → `should_notify_spawn_chill` 回 False

純決策（計時器是否到期、ring buffer 清理邏輯、短路取圖路徑選擇）抽成可測函式；
I/O（實際截圖、Discord）用 fake bot 打。

## 不做的事

- 不修改 `should_notify_spawn_chill` 純函式（呼叫端設旗標即可）
- 不改面板色檢的觀察期機制（`_panel_check_observed.json`）
- 不發定期截圖到 Discord（純本地）
- 不在 NEEDS_HUMAN 等待期間截背包
