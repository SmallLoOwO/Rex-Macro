# 釘底防抖安靜窗＋回礦收尾自動重貼遙控器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 遙控器／回礦卡釘底改「待重貼旗標＋頻道安靜窗」防抖；回礦收尾主動立旗標，修「回礦完成後遙控器要等使用者發話才出現」的競態。

**Architecture:** `notify.RepinDebouncer`（純邏輯零 I/O，時間注入）持有 pending 旗標與最後活動時間；`Bot._repin_tick(msgs, now)` 每輪輪詢立旗標＋執行到期重貼；`_rr_finalize` 收尾主動 `mark_pending()`；所有「貼回頻道底」的成功路徑 `clear()`。Spec：`docs/superpowers/specs/2026-07-19-remote-repin-debounce-design.md`。

**Tech Stack:** Python 3.11、stdlib urllib（既有 notify 層）、pytest、uv。

## Global Constraints

- 測試／lint 命令：`uv run pytest -q`、`uv run ruff check . --no-cache`（Windows，repo 根目錄執行）。
- 門檻只放 Config：新安靜窗 `discord_repin_quiet_s: float = 4.0` 進 `miningbot/config.py`。
- Discord 輪詢執行緒只做 Discord I/O（重貼在輪詢執行緒執行，現狀如此）；遊戲輸入仍由主迴圈消費。
- ⚠ **working tree 有使用者未提交的校準修改** `miningbot/config.py` 的 `reentry_pitch_back_px: 400 → 370`。只有 Task 2 動 config.py，必須照 Task 2 的 stash 步驟隔離；**這個 hunk 絕不可進任何 commit**，最後必須留在 working tree。
- 每個 Task 結尾 commit：全測試綠、只 stage 該任務檔案、中文訊息，訊息尾附：

  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_012dPaqNSzPEwFV8wEM1BeG4
  ```

- 不 push、不切 branch、不動與任務無關的檔案。
- `main.py` 無頂層 `notify` import（各方法 `from . import notify` 區域匯入是本檔慣例，照做）。

---

### Task 1: `notify.RepinDebouncer` 純邏輯

**Files:**
- Modify: `miningbot/notify.py`（在 `find_remote_messages` 函式定義前插入 class）
- Test: `tests/test_discord_responsiveness.py`（檔尾追加）

**Interfaces:**
- Produces: `notify.RepinDebouncer`，屬性 `pending: bool`、`last_activity: float`；方法 `note_activity(now: float)`、`mark_pending()`、`due(now: float, quiet_s: float) -> bool`、`clear()`。Task 2–4 都依賴這組簽名。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_discord_responsiveness.py` 檔尾追加：

```python
# ===== 2026-07-19：釘底防抖（安靜窗）＋回礦收尾自動重貼遙控器 =====
def test_repin_debouncer_waits_for_quiet_window():
    """防抖核心：mark 後未安靜滿不 due；滿了 due；note_activity 重置計時；clear 後不 due。"""
    d = notify.RepinDebouncer()
    assert d.due(100.0, 4.0) is False          # 未 mark 永不 due
    d.note_activity(100.0)
    d.mark_pending()
    assert d.due(103.9, 4.0) is False          # 距最後活動 3.9s < 4.0s
    assert d.due(104.0, 4.0) is True           # 安靜滿 4.0s
    d.note_activity(104.0)                     # 連發：又一則新訊息 → 重置計時
    assert d.due(107.9, 4.0) is False
    d.clear()
    assert d.due(999.0, 4.0) is False          # 已貼回頻道底
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_discord_responsiveness.py::test_repin_debouncer_waits_for_quiet_window -q`
Expected: FAIL，`AttributeError: module 'miningbot.notify' has no attribute 'RepinDebouncer'`

- [ ] **Step 3: 實作**

在 `miningbot/notify.py` 的 `def find_remote_messages(...)` 定義**前**插入：

```python
class RepinDebouncer:
    """釘底防抖：看到新訊息只立旗標，頻道安靜滿 quiet_s 秒才真的刪舊貼新。

    2026-07-19 spec：舊釘底「一看到新訊息就刪舊貼新」在連發（稀有礦通知＋截圖、
    八方位發圖空檔）時反覆刪貼；改為安靜窗到期一次到位。純邏輯零 I/O：時間一律
    由呼叫端注入（time.monotonic()），可直接單元測試。遙控器與回礦卡各持一個
    實例。旗標／時間都是單一指派，GIL 下原子——主迴圈 mark_pending（回礦收尾）
    與輪詢執行緒 due/clear 的競態最壞多等一輪或多重貼一次，無正確性問題。
    """

    def __init__(self):
        self.pending = False        # 需要重貼（卡片被擠上去／回礦收尾主動要求）
        self.last_activity = 0.0    # 頻道最後一則新訊息的時刻（monotonic）

    def note_activity(self, now: float):
        """頻道出現任何新訊息（含 bot 自己發的）就刷新活動時間。"""
        self.last_activity = now

    def mark_pending(self):
        """卡片需要重貼到頻道底（先立旗標，等安靜窗到期才動手）。"""
        self.pending = True

    def due(self, now: float, quiet_s: float) -> bool:
        """該重貼了嗎：旗標立著且距最後活動已安靜滿 quiet_s。"""
        return self.pending and (now - self.last_activity) >= quiet_s

    def clear(self):
        """卡片已重新貼到頻道底，殘留 pending 清掉（防剛貼完又多刪貼一次）。"""
        self.pending = False
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_discord_responsiveness.py::test_repin_debouncer_waits_for_quiet_window -q`
Expected: PASS

- [ ] **Step 5: 全套綠＋lint＋commit**

Run: `uv run pytest -q` → 全綠；`uv run ruff check . --no-cache` → 無報錯。

```bash
git add miningbot/notify.py tests/test_discord_responsiveness.py
git commit -m "feat(discord): RepinDebouncer 釘底防抖純邏輯（安靜窗）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012dPaqNSzPEwFV8wEM1BeG4"
```

---

### Task 2: Config 安靜窗＋`Bot._repin_tick`＋貼底 clear 鉤子

**Files:**
- Modify: `miningbot/config.py`（`discord_poll_interval_s` 下一行；⚠ 有使用者未提交 hunk，見 Step 0/6）
- Modify: `miningbot/main.py`（`Bot.__init__` 的 `_remote_last_shown` 之後；`_repost_remote_control` 之後新增 `_repin_tick`；`_post_remote_control` 與 `_rr_post_embed` 成功路徑加 `clear()`）
- Test: `tests/test_discord_responsiveness.py`（檔尾追加）

**Interfaces:**
- Consumes: `notify.RepinDebouncer`（Task 1 簽名）。
- Produces: `cfg.discord_repin_quiet_s: float`；`Bot._remote_repin`、`Bot._rr_repin`（RepinDebouncer 實例）；`Bot._repin_tick(msgs: list, now: float)`——Task 3 的收尾旗標與 Task 4 的 `_poll_discord` 接線都依賴這些名字。

- [ ] **Step 0: 隔離使用者的 config.py 校準修改**

```bash
git stash push -m "使用者 pitch 校準 reentry_pitch_back_px=370（Task 2 結尾 pop 回來）" -- miningbot/config.py
git diff --stat   # 確認 config.py 已乾淨
```

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_discord_responsiveness.py` 檔尾追加（檔頂 `import os` 旁補 `import time`）：

```python
def _bare_repin_bot(monkeypatch, state=State.MINING):
    """_repin_tick 專用最小 Bot；repost stub 模擬真品「貼底成功後 clear」語意。"""
    monkeypatch.setattr("miningbot.main.cfg.discord_repin_quiet_s", 4.0)
    bot = Bot.__new__(Bot)
    bot.state = state
    bot._remote_message_id = "remote-message"
    bot._rr_embed_mid = None
    bot._rr_ctx = None
    bot._rr_busy = False
    bot._remote_repin = notify.RepinDebouncer()
    bot._rr_repin = notify.RepinDebouncer()
    bot.reposted = []

    def _fake_remote_repost():
        bot.reposted.append("remote")
        bot._remote_repin.clear()      # 模擬 _post_remote_control 成功後 clear

    def _fake_rr_repost():
        bot.reposted.append("rr")
        bot._rr_repin.clear()          # 模擬 _rr_post_embed 成功後 clear

    bot._repost_remote_control = _fake_remote_repost
    bot._rr_repost_embed = _fake_rr_repost
    return bot


def test_repin_tick_debounces_until_channel_quiet(monkeypatch):
    """連發期間不刪貼；安靜滿 quiet_s 才重貼；clear 後不重複。"""
    bot = _bare_repin_bot(monkeypatch)
    bot._repin_tick([{"id": "newer"}], 100.0)          # 新訊息：只立旗標
    assert bot.reposted == []
    bot._repin_tick([{"id": "even-newer"}], 102.0)     # 連發：重置計時
    assert bot.reposted == []
    bot._repin_tick([], 105.9)                          # 距最後活動 3.9s，還不到
    assert bot.reposted == []
    bot._repin_tick([], 106.0)                          # 安靜滿 4.0s → 重貼
    assert bot.reposted == ["remote"]
    bot._repin_tick([], 120.0)                          # clear 後不再重複
    assert bot.reposted == ["remote"]


def test_repin_tick_ignores_when_remote_already_bottom(monkeypatch):
    """頻道最新一則就是遙控器自己 → 不立旗標、永不重貼。"""
    bot = _bare_repin_bot(monkeypatch)
    bot._repin_tick([{"id": "remote-message"}], 50.0)
    bot._repin_tick([], 999.0)
    assert bot.reposted == []


def test_repin_tick_reentry_rr_card_and_busy_gate(monkeypatch):
    """REENTRY：回礦卡走同一安靜窗；_rr_busy 中即使 due 也不搬；遙控器旗標不因新訊息立。"""
    bot = _bare_repin_bot(monkeypatch, state=State.REENTRY)
    bot._rr_embed_mid = "rr-message"
    bot._rr_ctx = object()
    bot._repin_tick([{"id": "photo-1"}], 200.0)
    assert bot.reposted == []
    bot._rr_busy = True
    bot._repin_tick([], 210.0)                          # due 但發圖/指令執行中
    assert bot.reposted == []
    bot._rr_busy = False
    bot._repin_tick([], 211.0)
    assert bot.reposted == ["rr"]
    assert bot._remote_repin.pending is False           # REENTRY 中遙控器旗標由收尾立
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_discord_responsiveness.py -q -k repin_tick`
Expected: 3 FAIL，`AttributeError: ... no attribute 'discord_repin_quiet_s'` 或 `'Bot' object has no attribute '_repin_tick'`

- [ ] **Step 3: 實作**

3a. `miningbot/config.py`——`discord_poll_interval_s` 那行的**下一行**插入：

```python
    discord_repin_quiet_s: float = 4.0          # 釘底防抖安靜窗（秒）：頻道最後一則新訊息後安靜滿此秒數，才把遙控器/回礦卡刪舊貼新到頻道底（輪詢 1s ≈ 4 輪安靜；2026-07-19 spec）
```

3b. `miningbot/main.py` `Bot.__init__`——`self._remote_last_shown: tuple | None = None` 那行之後插入：

```python
        # 釘底防抖（2026-07-19 spec）：看到新訊息只立旗標，頻道安靜滿
        # cfg.discord_repin_quiet_s 才刪舊貼新（_repin_tick）；回礦收尾由 _rr_finalize
        # 主動立遙控器旗標——修「回礦完成後要等使用者發話遙控器才出現」的消費競態。
        from . import notify as _notify
        self._remote_repin = _notify.RepinDebouncer()   # 遙控器（非 REENTRY 時作用）
        self._rr_repin = _notify.RepinDebouncer()       # 回礦卡（REENTRY 中作用）
```

3c. `miningbot/main.py`——`_repost_remote_control` 方法定義結束後新增方法：

```python
    def _repin_tick(self, msgs: list, now: float):
        """釘底防抖一輪：立旗標＋執行到期重貼（只做 Discord I/O，輪詢執行緒呼叫）。

        看到新訊息（含 bot 自己發的）只刷活動時間、立「待重貼」旗標；距頻道最後
        活動安靜滿 cfg.discord_repin_quiet_s 才真的刪舊貼新（RepinDebouncer）——
        連發期間不反覆刪貼，安靜後一次到位。REENTRY 中遙控器旗標不因新訊息立
        （釘底由回礦卡接手），改由 _rr_finalize 收尾主動立；回礦卡照舊受
        _rr_busy 擋（發圖/指令執行中不搬卡，掃完下一輪一次到位）。
        """
        frozen = self.state is State.REENTRY
        if msgs:
            self._remote_repin.note_activity(now)
            self._rr_repin.note_activity(now)
            newest = msgs[0]["id"]
            if (not frozen and self._remote_message_id
                    and newest != self._remote_message_id):
                self._remote_repin.mark_pending()
            if (frozen and self._rr_embed_mid and self._rr_ctx is not None
                    and newest != self._rr_embed_mid):
                self._rr_repin.mark_pending()
        quiet = cfg.discord_repin_quiet_s
        if not frozen and self._remote_repin.due(now, quiet):
            self._repost_remote_control()
        if (frozen and self._rr_ctx is not None and not self._rr_busy
                and self._rr_repin.due(now, quiet)):
            self._rr_repost_embed()
```

3d. `miningbot/main.py` `_post_remote_control`——成功路徑的
`self._remote_last_shown = (self.paused, self.state.value)` 之後（同段、`log_discord.info` 之前）插入：

```python
        self._remote_repin.clear()   # 已貼到頻道底：清殘留 pending，防剛貼完又被防抖多刪貼一次
```

3e. `miningbot/main.py` `_rr_post_embed`——成功路徑的
`self._rr_last_min = int((time.time() - ctx.created_at) // 60)` 之後（`log_discord.info` 之前）插入：

```python
        self._rr_repin.clear()       # 已貼到頻道底：清殘留 pending（同 _post_remote_control）
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_discord_responsiveness.py -q`
Expected: 全 PASS（新 3 條＋既有全部；`_repin_tick` 此時尚未被 `_poll_discord` 呼叫，舊行為不變）

- [ ] **Step 5: 全套綠＋lint**

Run: `uv run pytest -q` → 全綠；`uv run ruff check . --no-cache` → 無報錯。

- [ ] **Step 6: commit＋還原使用者校準**

```bash
git add miningbot/config.py miningbot/main.py tests/test_discord_responsiveness.py
git commit -m "feat(discord): _repin_tick 釘底防抖＋discord_repin_quiet_s＋貼底成功清旗標

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012dPaqNSzPEwFV8wEM1BeG4"
git stash pop    # 使用者的 reentry_pitch_back_px=370 疊回 working tree（兩處相距 70+ 行，應乾淨合併）
git diff -- miningbot/config.py   # 確認只剩 400→370 那個 hunk
```

若 `stash pop` 衝突（不應發生）：手動保留「370 那行＋新 `discord_repin_quiet_s` 行」兩者，`git stash drop` 收尾，並在回報中註明。

---

### Task 3: `_rr_finalize` 收尾主動立遙控器旗標

**Files:**
- Modify: `miningbot/main.py`（`_rr_finalize` 開頭）
- Test: `tests/test_discord_responsiveness.py`（檔尾追加）

**Interfaces:**
- Consumes: `Bot._remote_repin`（Task 2）、`notify.RepinDebouncer`（Task 1）、`Bot._repin_tick`（Task 2）。
- Produces: 「`_rr_finalize` 一定 `_remote_repin.mark_pending()`」的行為保證（成功／跳過／中止都走 `_rr_finalize`）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_discord_responsiveness.py` 檔尾追加：

```python
def test_rr_finalize_marks_remote_repin_pending():
    """回礦收尾必須主動立遙控器重貼旗標——完成訊息被 REENTRY 輪次消費後頻道
    再無新訊息，舊「看到新訊息才重貼」永不觸發（2026-07-19 使用者實測）。"""
    bot = Bot.__new__(Bot)
    bot._rr_open_first_ts = 1.0
    bot._rr_embed_mid = None                  # 無殘留卡 → 不走 delete_message
    bot._rr_reactions_seen = {}
    bot._rr_last_min = 3
    bot._rr_ctx = None                        # ctx=None 防禦路徑也要立旗標
    bot._pending_reentry = None
    bot._remote_repin = notify.RepinDebouncer()
    bot.log_discord = _LogRecorder()

    bot._rr_finalize("success")

    assert bot._remote_repin.pending is True


def test_remote_reposts_after_reentry_finalize_without_new_message(monkeypatch):
    """收尾旗標＋安靜窗：完成後即使頻道再無新訊息，安靜滿也自動重貼遙控器。"""
    bot = _bare_repin_bot(monkeypatch)                 # state=MINING（已離開 REENTRY）
    bot._remote_repin.note_activity(300.0)             # 「⛏ 回礦完成」被輪詢看到的那輪
    bot._remote_repin.mark_pending()                   # ＝_rr_finalize 立的旗標
    bot._repin_tick([], 303.9)
    assert bot.reposted == []
    bot._repin_tick([], 304.0)
    assert bot.reposted == ["remote"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_discord_responsiveness.py -q -k finalize`
Expected: `test_rr_finalize_marks_remote_repin_pending` FAIL（`assert False is True`——旗標沒立）；`test_remote_reposts_after_reentry_finalize_without_new_message` PASS（純 Task 2 行為，作收尾時序回歸鎖）

- [ ] **Step 3: 實作**

`miningbot/main.py` `_rr_finalize`——docstring 後、`self._rr_open_first_ts = 0.0` 那行**之前**插入：

```python
        # 收尾主動立遙控器重貼旗標（2026-07-19 spec）：完成訊息若在狀態仍是 REENTRY
        # 的輪次被輪詢消費，解凍後頻道再無新訊息、「看到新訊息才重貼」永不成立——
        # 遙控器一直埋在上面。旗標制不依賴輪詢看到哪則訊息，競態消失。
        self._remote_repin.mark_pending()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_discord_responsiveness.py -q`
Expected: 全 PASS（注意 `tests/test_main_pitch_home.py` 是 stub 掉 `_rr_finalize`，不受影響）

- [ ] **Step 5: 全套綠＋lint＋commit**

Run: `uv run pytest -q` → 全綠；`uv run ruff check . --no-cache` → 無報錯。

```bash
git add miningbot/main.py tests/test_discord_responsiveness.py
git commit -m "feat(reentry/discord): 回礦收尾主動立遙控器重貼旗標——完成後不再等新訊息才出現

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012dPaqNSzPEwFV8wEM1BeG4"
```

---

### Task 4: `_poll_discord` 改接防抖＋更新既有釘底測試

**Files:**
- Modify: `miningbot/main.py`（`_poll_discord` 的 2a 區段）
- Modify: `tests/test_discord_responsiveness.py`（`_poll_bot` helper 與 3 條既有釘底測試）

**Interfaces:**
- Consumes: `Bot._repin_tick(msgs, now)`（Task 2）。
- Produces: 最終行為——立即刪貼路徑只剩「反應點擊後」；其餘重貼全走安靜窗。

- [ ] **Step 1: 先改既有測試成新語意（此時會 FAIL）**

`tests/test_discord_responsiveness.py`：

1a. `_poll_bot` helper——`bot._last_discord_msg_id = "old"` 那行之後加兩行：

```python
    bot._remote_repin = notify.RepinDebouncer()
    bot._rr_repin = notify.RepinDebouncer()
```

1b. 整條替換 `test_remote_control_syncs_outside_reentry`：

```python
def test_remote_control_syncs_outside_reentry(monkeypatch):
    """離開 REENTRY 後：狀態 PATCH 補上；新訊息當輪只立旗標，安靜窗滿才重貼回頻道底。"""
    bot, calls = _poll_bot(monkeypatch, State.MINING)
    bot._poll_discord()
    assert calls == {"edit": 1, "repost": 0, "rr_repost": 0}   # 防抖：當輪不刪貼
    assert bot._remote_repin.pending is True
    bot._repin_tick([], time.monotonic() + 999.0)              # 安靜窗必然已滿
    assert calls["repost"] == 1
```

1c. 整條替換 `test_rr_embed_takes_over_pinning_during_reentry`：

```python
def test_rr_embed_takes_over_pinning_during_reentry(monkeypatch):
    """回礦卡接手釘底：被擠上去先立旗標，安靜窗滿刪舊貼新；遙控器凍結不動。"""
    bot, calls = _poll_bot(monkeypatch, State.REENTRY)
    bot._rr_embed_mid = "rr-card"
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=2, created_at=0.0, sticky_layer="L")
    bot._poll_discord()
    assert calls["rr_repost"] == 0 and bot._rr_repin.pending is True
    bot._repin_tick([], time.monotonic() + 999.0)
    assert calls["rr_repost"] == 1
    assert calls["repost"] == 0
```

1d. 整條替換 `test_rr_embed_pinning_waits_out_busy_execution`：

```python
def test_rr_embed_pinning_waits_out_busy_execution(monkeypatch):
    """_rr_busy（開場/八方位發圖中）即使安靜窗滿也不搬卡，掃完下一輪一次到位。"""
    bot, calls = _poll_bot(monkeypatch, State.REENTRY)
    bot._rr_embed_mid = "rr-card"
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=2, created_at=0.0, sticky_layer="L")
    bot._rr_busy = True
    bot._poll_discord()
    bot._repin_tick([], time.monotonic() + 999.0)
    assert calls["rr_repost"] == 0
    bot._rr_busy = False
    bot._repin_tick([], time.monotonic() + 999.0)
    assert calls["rr_repost"] == 1
```

（`test_remote_control_repost_frozen_during_reentry` 不動——凍結語意不變。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_discord_responsiveness.py -q`
Expected: 上述 3 條 FAIL（舊 `_poll_discord` 仍立即重貼 → `calls["repost"] == 1` 撞新斷言）

- [ ] **Step 3: 改 `_poll_discord`**

`miningbot/main.py` `_poll_discord`——把這整段（從 `remote_frozen = ...` 到回礦卡釘底 if 區塊結束、`newest_id = msgs[0]["id"]` 之前）：

```python
        remote_frozen = self.state is State.REENTRY
        if self._remote_message_id and self._remote_last_shown != (self.paused, self.state.value):
            self._edit_remote_control()
        # 2. 新訊息命令輪詢
        msgs = notify.fetch_messages(
            cfg.discord_bot_token, cfg.discord_channel_id,
            after=self._last_discord_msg_id, limit=10)
        if not msgs:
            return
        # 2a. 釘底（混合設計 2026-07-09）：狀態更新/按鈕點擊都原地編輯（不產生新訊息），
        # **只有**被其他訊息擠上去時才刪舊重貼回頻道底——重貼次數從「每次狀態變」降到
        # 「每次頻道有新訊息」，兼顧「滑到最底就是遙控器」與不洗版。
        if (self._remote_message_id and not remote_frozen
                and msgs[0]["id"] != self._remote_message_id):
            self._repost_remote_control()
        # 回礦卡釘底（2026-07-19 使用者反映「回礦卡沒看到出現」）：卡片過去只原地
        # PATCH，八方位照片/通知一直往下疊＝卡片被埋在頻道上方。REENTRY 中換回礦卡
        # 接手釘底：被新訊息擠上去就刪舊貼新。_rr_busy（開場/指令執行、發圖中）不搬，
        # 掃完後下一輪輪詢一次到位，避免發圖途中卡片反覆彈跳。
        if (remote_frozen and self._rr_embed_mid and self._rr_ctx is not None
                and not self._rr_busy and msgs[0]["id"] != self._rr_embed_mid):
            self._rr_repost_embed()
```

替換為：

```python
        if self._remote_message_id and self._remote_last_shown != (self.paused, self.state.value):
            self._edit_remote_control()
        # 2. 新訊息命令輪詢
        msgs = notify.fetch_messages(
            cfg.discord_bot_token, cfg.discord_channel_id,
            after=self._last_discord_msg_id, limit=10)
        # 2a. 釘底防抖（2026-07-19 spec，取代「一看到新訊息就刪舊貼新」）：看到新訊息
        # 只立旗標＋刷活動時間，頻道安靜滿 cfg.discord_repin_quiet_s 才刪舊貼新——
        # 連發（稀有礦通知＋截圖、八方位發圖空檔）期間不反覆刪貼，安靜後一次到位。
        # msgs 為空的輪次也要跑（到期重貼正是發生在安靜輪），所以放在 early return
        # 之前。REENTRY 凍結／回礦卡接手／_rr_busy 語意都在 _repin_tick 內；回礦收尾
        # 由 _rr_finalize 主動立遙控器旗標，不再依賴「輪詢剛好看到新訊息」。
        self._repin_tick(msgs, time.monotonic())
        if not msgs:
            return
```

（上一段行首 1350–1357 的舊註解區塊裡「REENTRY 中釘底凍結…回礦卡接手（見下）」字樣改指向 `_repin_tick`：把「（見下）」改成「（見 _repin_tick）」，其餘不動。`remote_frozen` 變數已無使用者，必須刪除，否則 ruff F841。）

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_discord_responsiveness.py -q`
Expected: 全 PASS

- [ ] **Step 5: 全套綠＋lint＋commit**

Run: `uv run pytest -q` → 全綠；`uv run ruff check . --no-cache` → 無報錯。
確認 `git status --short` 中 `miningbot/config.py` 仍是未 stage 的使用者校準（400→370），**不要 add**。

```bash
git add miningbot/main.py tests/test_discord_responsiveness.py
git commit -m "feat(discord): _poll_discord 釘底改防抖安靜窗——連發不反覆刪貼、回礦完成後自動重貼遙控器

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012dPaqNSzPEwFV8wEM1BeG4"
```

---

## 驗收對照（spec ↔ tasks）

| Spec 節 | Task |
|---|---|
| §1 RepinDebouncer 純邏輯 | Task 1 |
| §2 `_poll_discord` 流程調整（含 early return 改序、執行條件不再要求 mid 非空） | Task 2（`_repin_tick` 本體）＋ Task 4（接線） |
| §3 回礦收尾事件旗標 | Task 3 |
| §4 clear() 歸位點 | Task 2（3d/3e；404 重貼與啟動路徑都經 `_post_remote_control`／`_rr_post_embed`，天然涵蓋） |
| §5 Config `discord_repin_quiet_s=4.0` | Task 2 |
| 不變：反應點擊立即重貼／`_rr_busy`／狀態 PATCH | Task 4 不動 `_poll_remote_reactions`；`_rr_busy` 檢查搬進 `_repin_tick`；PATCH 行保留 |
| 測試（debouncer 純邏輯／finalize 立旗標／輪詢防抖） | Task 1／Task 3／Task 2＋4 |

實機驗證（計畫外、使用者下輪掛機）：回礦完成 → 頻道安靜 ~4s → 遙控器自動重貼到底；採集稀有礦連發訊息期間遙控器不反覆刪貼。
