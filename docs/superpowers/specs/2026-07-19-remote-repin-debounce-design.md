# 釘底防抖（安靜窗）＋回礦收尾自動重貼遙控器（2026-07-19）

## 背景與問題

2026-07-19 使用者反映兩個釘底（把控制卡刪舊貼新到頻道底）問題：

1. **回礦完成後遙控器不會馬上出現**：期望「⛏ 回礦完成，開挖」之後
   遙控器按鈕自動回到頻道底，實際要等使用者自己發一則新訊息才出現。
   根因：遙控器釘底唯一觸發條件是 `_poll_discord` 2a「本輪輪詢抓到
   新訊息且 newest ≠ 遙控器 mid」。REENTRY 中釘底凍結、輪詢照樣消費
   訊息推進 `_last_discord_msg_id`；「回礦完成」那則若在狀態仍是
   REENTRY 的輪次被消費掉，解凍後頻道再無新訊息，重貼永遠不觸發。
   這是收尾（主迴圈）與輪詢（背景執行緒）之間的競態，輸了就卡住。
2. **連發訊息造成反覆刪貼**：訊息分批到達（如稀有礦通知＋截圖、回礦
   八方位發圖的空檔）時，每一輪「看到新訊息」都立刻刪舊貼新一次，
   中間多次無意義的刪除與重貼。期望：連發期間暫停釘底，等全部訊息
   出完（頻道安靜）才一次重貼到位。

兩個需求用同一機制解決：**待重貼旗標＋頻道安靜窗**。看到新訊息只立
旗標不動手；距頻道最後活動超過安靜窗才真的刪舊貼新；回礦收尾主動立
旗標，不再依賴「輪詢剛好看到新訊息」。

使用者已裁決：

- 重貼時機採**統一安靜窗**（回礦完成後等頻道安靜幾秒才重貼，不做
  「完成事件立即重貼」特例）。
- 回礦卡釘底**一併套用**同一防抖（與遙控器行為一致）。

## 設計

### 1. `RepinDebouncer`（notify.py，純邏輯零 I/O）

```python
class RepinDebouncer:
    def __init__(self): ...          # pending=False, last_activity=0.0
    def note_activity(self, now): ...  # 頻道有任何新訊息（含 bot 自己發的）
    def mark_pending(self): ...        # 卡片被擠上去，需要重貼
    def due(self, now, quiet_s): ...   # pending 且 now-last_activity >= quiet_s
    def clear(self): ...               # 卡片已重新貼到頻道底
```

- 時間一律由呼叫端注入（`time.monotonic()`），類本身不取時間、
  不碰 Discord API——可直接單元測試。
- 遙控器與回礦卡各持一個實例（`Bot._remote_repin`、`Bot._rr_repin`），
  行為一致；兩者的 `note_activity` 都在同一個輪詢點刷新。

### 2. `_poll_discord` 流程調整

現行 `if not msgs: return` 擋在釘底檢查前面——「沒有新訊息的輪次」
正是防抖要執行重貼的時機，必須改序。目標順序：

1. （不變）反應輪詢、狀態同步 PATCH（`_edit_remote_control`）。
2. `fetch_messages(after=...)`。
3. **msgs 非空**：兩個 debouncer 都 `note_activity(now)`（首次輪詢
   建基準那輪也算活動）。再依狀態立旗標：
   - 非 REENTRY 且 `_remote_message_id` 存在且
     `msgs[0]["id"] != _remote_message_id` → `_remote_repin.mark_pending()`。
   - REENTRY 且 `_rr_embed_mid` 存在且 `_rr_ctx` 存活且
     `msgs[0]["id"] != _rr_embed_mid` → `_rr_repin.mark_pending()`。
   -（REENTRY 中不因新訊息立遙控器旗標；遙控器旗標在 REENTRY 中
     由收尾事件立，見第 3 節。）
4. **每輪都執行**（不論 msgs 是否為空）的到期重貼：
   - 非 REENTRY 且 `_remote_repin.due(now, cfg.discord_repin_quiet_s)`
     → `_repost_remote_control()`。執行條件**不再**要求
     `_remote_message_id` 非空——重貼失敗後 mid 可能是 None，pending
     保留讓下輪重試；`_repost_remote_control` 對 old=None 本就只貼
     新不刪舊。
   - REENTRY 且 `_rr_ctx` 存活且非 `_rr_busy` 且
     `_rr_repin.due(now, cfg.discord_repin_quiet_s)` → `_rr_repost_embed()`。
5. （不變）`if not msgs: return` → 首次輪詢基準分支 → 命令迴圈。

### 3. 回礦收尾事件旗標（修「不會馬上出來」）

`_rr_finalize`（成功／跳過／中止都會走）直接
`_remote_repin.mark_pending()`。時序：完成訊息發出 → 輪詢看到它刷新
活動時間 → 頻道安靜 `quiet_s` 秒 → 遙控器自動重貼到底。旗標由收尾
主動立，與輪詢是否看到哪則訊息無關，競態消失。若完成訊息發送失敗
（網路），旗標仍在、活動時間停留在更早，解凍後很快 due——一樣會重貼。

### 4. `clear()` 的歸位點

任何把卡片貼回頻道底的動作都要清旗標，避免剛貼完又因殘留 pending
多刪貼一次：

- `_post_remote_control` 成功（拿到新 mid）→ `_remote_repin.clear()`。
  涵蓋：防抖重貼、按鈕點擊後的即時重貼（`_poll_remote_reactions`）、
  `_edit_remote_control` 404 重貼、啟動 `_ensure_remote_control`。
  失敗不清——pending 保留，下輪安靜窗重試。
- `_rr_post_embed` 成功（拿到新 mid）→ `_rr_repin.clear()`。

### 5. Config 新增

```python
discord_repin_quiet_s: float = 4.0  # 釘底防抖安靜窗（秒）：頻道最後一則新訊息後安靜這麼久，才把遙控器/回礦卡刪舊貼新到頻道底
```

輪詢間隔 1.0s，4 秒 ≈ 4 輪安靜才動手。

## 不變的部分

- **按鈕點擊後的即時刪貼維持立即**（表情歸零讓使用者能馬上再點），
  不走安靜窗；貼完 `clear()` 即可。
- `_rr_busy` 擋發圖／指令執行途中重貼照舊；安靜窗疊在其上。
- 狀態同步 PATCH（原地編輯、不產生新訊息）機制與觸發條件不變。
- REENTRY 進場把遙控器 PATCH 成指引卡、離場 PATCH 回一般遙控器的
  行為不變（PATCH 後幾秒防抖重貼會再把它搬到底部，一次到位）。
- 連發不停（每 < quiet_s 就一則新訊息）期間卡片一直待在上面，安靜
  後才一次重貼——這正是需求要的行為，不是餓死 bug。

## 執行緒與競態

- 旗標／活動時間讀寫都是單一 float/bool 指派，GIL 下原子，與既有
  `_pending_*` 旗標同模式。`mark_pending`（主迴圈 `_rr_finalize`）與
  輪詢執行緒的 `due`/`clear` 競態最壞情況＝多一輪才重貼或多一次重
  貼，無正確性問題。
- 重貼一律在 Discord 輪詢執行緒執行（現狀如此），只做 Discord I/O
  不碰遊戲輸入，符合「遊戲輸入由主迴圈消費」鐵律。

## 測試（tests/test_discord_responsiveness.py 增補）

1. `RepinDebouncer` 純邏輯：mark 後未滿安靜窗不 due；滿了 due；
   `note_activity` 重置計時；`clear` 後不 due；未 mark 永不 due。
2. `_rr_finalize` 立遙控器 pending（bare-bot＋monkeypatch
   `notify.delete_message`；`_rr_ctx=None` 防禦路徑不炸、旗標照立）。
3. 輪詢防抖行為（bare-bot＋monkeypatch `notify.fetch_messages`）：
   - 挖礦中：有新訊息那輪**不**呼叫 `_repost_remote_control`（只立
     旗標）；之後無新訊息且超過安靜窗的輪次呼叫**恰一次**。
   - 連發（每輪都有新訊息）期間永不重貼。
   - REENTRY：回礦卡同模式；`_rr_busy=True` 時即使 due 也不重貼。
   - 實作若整隻 `_poll_discord` 難以 bare-bot 驅動，可把第 2 節
     步驟 3/4 抽成小方法（如 `_repin_tick(msgs, now)`）單獨測，
     `_poll_discord` 只負責呼叫。

## 不做的事

- 不做「完成事件立即重貼」特例（使用者已選統一安靜窗）。
- 不動狀態同步 PATCH 的觸發條件、反應輪詢頻率、`fetch_messages`
  參數。
- 不持久化旗標（跨重啟由 `_ensure_remote_control` 重貼解決）。
