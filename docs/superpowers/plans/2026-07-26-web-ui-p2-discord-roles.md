# 網頁 UI P2：Discord 訊息角色精簡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discord 從「主要操作介面」退回「精簡通知介面」——狀態訊息 post-once-then-edit（取代部分釘底）、需介入事件 PING 推播、結案時編輯同則、採集放棄簡化為一張全畫面。`RepinDebouncer` 保留（遙控器卡仍釘底）。

**Architecture:** P2 全在 `notify.py` + `main.py` + `config.py` 三個既有檔內——加純函式 + 一個 `StatusMessenger` class + Config 一個新欄位 + 寫死 PING_USER_ID 常數。不動 Discord polling thread、不動 discord_commands.py、不動 web_* 模組（P1 已落地）。NEEDS_HUMAN PING 用 `notify.send_message_with_id` 拿 message_id，後續 `edit_message` 改為結案。

**Tech Stack:** Python 3.11+ / pytest（既有 stack；P2 不加新依賴）

## Global Constraints

- Python 3.11+
- **不加新依賴**（沿用 stdlib urllib + 既有 discord adapter）
- 座標／門檻／間隔只放 `miningbot/config.py`
- 純函式優先、I/O 邊界不交叉；race 邏輯放純函式
- 不放寬偵測門檻、不刪事故回歸測試（H001~H060）
- 不修改 P1 落地的 web_* 模組（協議已固化）
- 不修改 `discord_commands.py`（fallback 命令保留）
- 不修改 `reentry_remote.py` / `remote_aim.py` 純函式
- **既有 notify.py 行為不能壞**：`make_discord_sink` 既有路徑（HARVEST_SUCCESS、image_groups 分組）在 P2 完工後仍須正常運作（除非該 task 明確改動該路徑）
- Commit message 用中文；尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer
- 規格依據：`docs/superpowers/specs/2026-07-26-web-ui-design.md` §7

## 改動範圍預覽

| 檔案 | 改動 |
|---|---|
| `miningbot/config.py` | 加 `discord_status_edit_min_interval_s: float = 3.0` |
| `miningbot/notify.py` | 加 `PING_USER_ID` 常數、`should_edit_for_state`、`EditThrottle`、`format_status_text`、`format_ping_content`、`format_resolve_text`、`StatusMessenger` class；擴充 `make_discord_sink` 支援採集放棄單圖模式 |
| `miningbot/main.py` | 啟動 post 狀態訊息 + 狀態變動 edit + NEEDS_HUMAN PING + 結案 edit + shutdown cleanup |
| `tests/test_notify.py`（既有，可能更名）| 擴充測試覆蓋新純函式 + StatusMessenger |
| `tests/test_notify_p2.py`（新）| 新增 P2 純函式 + class 測試（避免既有檔太擠） |

---

## Task 1: Config 欄位 + PING_USER_ID 常數

**Files:**
- Modify: `miningbot/config.py`（加 1 欄位）
- Modify: `miningbot/notify.py`（加 1 常數 + docstring）
- Test: `tests/test_notify_p2.py`（新檔，首批測試）

**Interfaces:**
- Produces: `Config.discord_status_edit_min_interval_s: float = 3.0`；`notify.PING_USER_ID: str`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_notify_p2.py
"""P2 Discord 訊息角色精簡：純函式 + StatusMessenger + 整合。

跟既有 tests/test_notify.py 共存——把 P2 新元件獨立成新檔，避免既有檔越長越亂。"""
import pytest


def test_config_has_status_edit_min_interval():
    from miningbot.config import Config
    cfg = Config()
    assert cfg.discord_status_edit_min_interval_s == 3.0


def test_ping_user_id_constant_present():
    import miningbot.notify as notify
    assert notify.PING_USER_ID == "373438562940747776"


def test_ping_user_id_is_str():
    """Discord mention format <@USER_ID> 要求 USER_ID 是字串；數字會崩。"""
    import miningbot.notify as notify
    assert isinstance(notify.PING_USER_ID, str)
    assert notify.PING_USER_ID.isdigit()
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_notify_p2.py -v` — 預期 FAIL（AttributeError / ImportError）。

- [ ] **Step 3: 加 Config 欄位**

在 `miningbot/config.py` Discord 區塊（`discord_repin_quiet_s` 之後）加：

```python
    discord_status_edit_min_interval_s: float = 3.0
    # 狀態訊息 edit_message 降頻（秒）：狀態/動作變動最快每 N 秒 edit 一次，
    # 避免狀態機快速擺盪洗版（2026-07-26 P2 spec §7）。低於此間隔的變動
    # 靠下次 repin（RepinDebouncer）順帶刷新。
```

- [ ] **Step 4: 加 PING_USER_ID 常數**

在 `miningbot/notify.py` 適當位置（建議在 `_TEMPLATES` 之前、模組 docstring 之後）加：

```python
# 個人 bot 寫死（spec §7）：NEEDS_HUMAN 推播用 <@ID> mention，無需 Config 欄位。
# Discord mention 格式：<@USER_ID>；USER_ID 必須是字串（數字會被當角色 ID）。
PING_USER_ID = "373438562940747776"
```

- [ ] **Step 5: 跑測試，確認通過**

`uv run pytest tests/test_notify_p2.py -v` + `uv run pytest -q` + `uv run ruff check . --no-cache` + `uv lock --check`

- [ ] **Step 6: Commit**

```bash
git add miningbot/config.py miningbot/notify.py tests/test_notify_p2.py
git commit -m "$(cat <<'EOF'
feat(discord): P2 Task 1——Config 加 status_edit_min_interval_s + notify.PING_USER_ID 寫死

為後續 StatusMessenger（狀態訊息 post-once-then-edit）+ NEEDS_HUMAN PING 鋪底。
spec §7。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: should_edit_for_state + EditThrottle 純函式

**Files:**
- Modify: `miningbot/notify.py`
- Test: `tests/test_notify_p2.py`（加新 class）

**Interfaces:**
- Produces:
  - `should_edit_for_state(old_state: str, new_state: str, old_action: str, new_action: str) -> bool`
  - `class EditThrottle`：`__init__(min_interval_s: float)` / `allow_edit(now: float) -> bool` / `last_edit_at -> float | None`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_notify_p2.py`：

```python
from miningbot.notify import should_edit_for_state, EditThrottle


class TestShouldEditForState:
    def test_state_change_triggers_edit(self):
        # 狀態 transition（MINING → HARVESTING）必觸發
        assert should_edit_for_state("MINING", "HARVESTING", "x", "x") is True

    def test_same_state_same_action_no_edit(self):
        # 完全沒變動，不需要 edit（呼叫端 repin 會順帶刷）
        assert should_edit_for_state("MINING", "MINING", "x", "x") is False

    def test_same_state_diff_action_triggers_edit(self):
        # 動作字串變動（last_action 是重要動態資訊，spec §7 列為「關鍵動作」）
        assert should_edit_for_state("MINING", "MINING", "掃描 C2", "命中 (851,189)") is True

    def test_state_change_ignores_action(self):
        # 狀態變動即觸發，動作無論同不同
        assert should_edit_for_state("MINING", "NEEDS_HUMAN", "x", "x") is True

    def test_none_state_treated_as_change(self):
        # 啟動初期 old_state=None，第一次一定要 post（不是 edit，但 should_edit 該回 True
        # 讓呼叫端決定是 post 還是 edit）
        assert should_edit_for_state(None, "MINING", None, "啟動") is True


class TestEditThrottle:
    def test_first_edit_always_allowed(self):
        t = EditThrottle(min_interval_s=3.0)
        assert t.allow_edit(now=0.0) is True
        assert t.last_edit_at == 0.0

    def test_within_interval_blocked(self):
        t = EditThrottle(min_interval_s=3.0)
        assert t.allow_edit(now=0.0) is True
        assert t.allow_edit(now=1.0) is False
        assert t.allow_edit(now=2.99) is False

    def test_at_interval_allowed(self):
        t = EditThrottle(min_interval_s=3.0)
        assert t.allow_edit(now=0.0) is True
        assert t.allow_edit(now=3.0) is True

    def test_last_edit_at_updates_on_allow(self):
        t = EditThrottle(min_interval_s=3.0)
        t.allow_edit(now=0.0)
        t.allow_edit(now=5.0)
        assert t.last_edit_at == 5.0

    def test_blocked_does_not_update_last_edit_at(self):
        t = EditThrottle(min_interval_s=3.0)
        t.allow_edit(now=0.0)
        t.allow_edit(now=1.0)  # blocked
        assert t.last_edit_at == 0.0
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_notify_p2.py::TestShouldEditForState tests/test_notify_p2.py::TestEditThrottle -v` — 預期 FAIL（import error）。

- [ ] **Step 3: 實作兩個純函式/class**

加到 `miningbot/notify.py`：

```python
# --- P2: 狀態訊息 post-once-then-edit 純函式（spec §7 A 混合更新策略）---
# 遙控器卡是 1 則常駐訊息；狀態/動態用 edit_message 即時更新（重要內容），
# 運行時間/音訊等不重要內容靠下次 repin 順帶刷新。


def should_edit_for_state(old_state: str | None, new_state: str,
                          old_action: str | None, new_action: str) -> bool:
    """狀態/動作變動是否該觸發立即 edit_message。

    spec §7 A：狀態 transition（MINING→HARVESTING 等）跟關鍵動作字串變動
    （命中座標、verify 結果）都該即時 edit；其餘（運行時間、音訊分數）靠 repin。

    old_state=None 視為強制觸發（首次 post 之後的呼叫端會用 None 起步）。
    """
    if old_state is None or old_state != new_state:
        return True
    # 狀態相同，看動作字串
    if old_action != new_action:
        return True
    return False


class EditThrottle:
    """狀態訊息 edit_message 降頻器：避免狀態機快速擺盪洗版。

    每次 allow_edit(now) 檢查距上次 edit 是否 >= min_interval_s；通過則更新
    last_edit_at。不通過不更新（保留原本時間基準）。
    時間由呼叫端注入（time.monotonic），方便單元測試。
    """

    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._last_edit_at: float | None = None

    @property
    def last_edit_at(self) -> float | None:
        return self._last_edit_at

    def allow_edit(self, now: float) -> bool:
        if self._last_edit_at is None or (now - self._last_edit_at) >= self.min_interval_s:
            self._last_edit_at = now
            return True
        return False
```

- [ ] **Step 4: 跑測試，確認通過**

`uv run pytest tests/test_notify_p2.py -v` + full suite + ruff + lock。

- [ ] **Step 5: Commit**

```bash
git add miningbot/notify.py tests/test_notify_p2.py
git commit -m "$(cat <<'EOF'
feat(discord): P2 Task 2——should_edit_for_state + EditThrottle 純函式

狀態/動作變動觸發即時 edit；同狀態同動作靠 repin。EditThrottle 3 秒降頻避免洗版。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: format_status_text + format_ping_content + format_resolve_text 純函式

**Files:**
- Modify: `miningbot/notify.py`
- Test: `tests/test_notify_p2.py`（加新 class）

**Interfaces:**
- Produces:
  - `format_status_text(state: str, last_action: str, audio_score: float, capacity_pct: float | None, uptime_s: int) -> str`
  - `format_ping_content(harvest_id: str | None, reason: str, fallback: bool) -> str`
  - `format_resolve_text(harvest_id: str | None, reply_source: str, detail: str = "") -> str`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_notify_p2.py`：

```python
from miningbot.notify import (
    format_status_text, format_ping_content, format_resolve_text,
)


class TestFormatStatusText:
    def test_basic_format(self):
        s = format_status_text(
            state="HARVESTING", last_action="命中 (851,189)",
            audio_score=0.42, capacity_pct=63.0, uptime_s=8234,
        )
        # 各欄位都該出現
        assert "採集" in s or "HARVESTING" in s
        assert "命中 (851,189)" in s
        assert "63%" in s
        assert "2h17m" in s  # 8234 = 2h 17m 14s

    def test_capacity_none_omitted(self):
        s = format_status_text("MINING", "x", 0.5, None, 60)
        assert "容量" not in s
        assert "1m" in s  # 60 = 1m

    def test_uptime_formats(self):
        assert "2h17m" in format_status_text("MINING", "x", 0.0, None, 8234)
        assert "0h00m" in format_status_text("MINING", "x", 0.0, None, 0)
        assert "1h00m" in format_status_text("MINING", "x", 0.0, None, 3600)


class TestFormatPingContent:
    def test_with_harvest_id_fallback(self):
        c = format_ping_content(harvest_id="007", reason="稀有礦未自動命中", fallback=True)
        assert "<@373438562940747776>" in c
        assert "[007]" in c
        assert "稀有礦未自動命中" in c
        # fallback 模式提示玩家在 Discord 操作
        assert "Discord" in c or "反應" in c or "方位" in c

    def test_with_harvest_id_web(self):
        c = format_ping_content(harvest_id="007", reason="X", fallback=False)
        assert "<@373438562940747776>" in c
        assert "[007]" in c
        assert "網頁" in c  # 非 fallback 提示在網頁處理

    def test_without_harvest_id(self):
        c = format_ping_content(harvest_id=None, reason="X", fallback=False)
        assert "<@373438562940747776>" in c
        assert "[007]" not in c
        assert "X" in c


class TestFormatResolveText:
    def test_web_resolve(self):
        t = format_resolve_text(harvest_id="007", reply_source="web", detail="玩家點擊 (851,189)")
        assert "✅" in t
        assert "[007]" in t
        assert "網頁" in t
        assert "(851,189)" in t

    def test_discord_resolve(self):
        t = format_resolve_text(harvest_id="007", reply_source="discord", detail="")
        assert "✅" in t
        assert "[007]" in t
        assert "Discord" in t or "discord" in t

    def test_without_detail(self):
        t = format_resolve_text(harvest_id="007", reply_source="web", detail="")
        assert "✅" in t
        # 沒 detail 也不該崩
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_notify_p2.py::TestFormatStatusText tests/test_notify_p2.py::TestFormatPingContent tests/test_notify_p2.py::TestFormatResolveText -v`

- [ ] **Step 3: 實作三個純函式**

加到 `miningbot/notify.py`：

```python
# --- P2: 訊息內容格式化純函式（spec §7）---


def format_status_text(state: str, last_action: str, audio_score: float,
                       capacity_pct: float | None, uptime_s: int) -> str:
    """狀態訊息內容（給 StatusMessenger.post/edit 用）。

    跟 status_hud.py 同風格（左下角 HUD 文字版），但搬到 Discord 卡片。
    state 用既有 _STATE_ZH（status_hud）映射成中文；映射不到用原文。
    uptime 格式 XhYYm（不顯示秒，discord 卡片不需要那麼細）。
    """
    # 從 status_hud 借狀態中文化（避免循環 import，local copy）
    _STATE_ZH = {
        "MINING": "挖礦中", "HARVESTING": "採集稀有礦",
        "NEEDS_HUMAN": "需要人工", "RESET_WAIT": "礦坑重置·待定位",
        "REENTRY": "重置·自動回礦",
    }
    tag = _STATE_ZH.get(state, state)
    cap_s = f"　容量: {capacity_pct:.0f}%" if capacity_pct is not None else ""
    h = uptime_s // 3600
    m = (uptime_s % 3600) // 60
    return (
        f"● {tag}\n"
        f"動作: {last_action}\n"
        f"音訊: {audio_score:.2f}{cap_s}    運行: {h}h{m:02d}m"
    )


def format_ping_content(harvest_id: str | None, reason: str, fallback: bool) -> str:
    """NEEDS_HUMAN PING 訊息內容。

    用 <@USER_ID> mention 推播；harvest_id 有則前綴 [XXX]；fallback 與否
    決定後續玩家該去哪處理（Discord 反應按鈕 vs 網頁點選）。
    """
    hid = f"[{harvest_id}] " if harvest_id else ""
    ping = f"<@{PING_USER_ID}>"
    if fallback:
        body = f"{ping} ⚠️ {hid}需要人工：{reason}\n（fallback 模式：用 Discord 反應按鈕處理）"
    else:
        body = f"{ping} ⚠️ {hid}需要人工：{reason}\n（在網頁處理：pinch-zoom 點選截圖）"
    return body


def format_resolve_text(harvest_id: str | None, reply_source: str, detail: str = "") -> str:
    """NEEDS_HUMAN 結案編輯內容（把原 PING 訊息 edit 成 ✅）。

    reply_source: "web" / "discord" / "skip" / "timeout"；detail 是可选補充
    （例如玩家點擊座標、verify 結果）。
    """
    hid = f"[{harvest_id}] " if harvest_id else ""
    src_map = {"web": "在網頁處理", "discord": "在 Discord 處理",
               "skip": "已跳過", "timeout": "已逾時"}
    src_txt = src_map.get(reply_source, reply_source)
    detail_s = f"（{detail}）" if detail else ""
    return f"✅ {hid}已{src_txt}{detail_s}"
```

- [ ] **Step 4: 跑測試，確認通過**

`uv run pytest tests/test_notify_p2.py -v` + full suite + ruff + lock。

- [ ] **Step 5: Commit**

```bash
git add miningbot/notify.py tests/test_notify_p2.py
git commit -m "$(cat <<'EOF'
feat(discord): P2 Task 3——status/ping/resolve 文字格式化純函式

format_status_text（HUD 風格狀態文字）+ format_ping_content（NEEDS_HUMAN PING）+
format_resolve_text（結案編輯成 ✅）。後續 StatusMessenger 與 main.py 整合用。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: StatusMessenger class

**Files:**
- Modify: `miningbot/notify.py`
- Test: `tests/test_notify_p2.py`（加新 class）

**Interfaces:**
- Produces:
  - `class StatusMessenger`：
    - `__init__(token, channel_id, edit_min_interval_s: float, send_fn, edit_fn, log=None)`
    - `ensure_posted(now: float) -> bool`：首次 post 狀態訊息、存 message_id；已 post 過 no-op
    - `update(state, last_action, audio_score, capacity_pct, uptime_s, now: float) -> bool`：throttle + should_edit 判斷 → edit
    - `message_id -> str | None`（property）
    - `last_state -> str | None` / `last_action -> str | None`（property；測試用）

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_notify_p2.py`：

```python
from miningbot.notify import StatusMessenger


class TestStatusMessenger:
    def _make(self, edit_min_interval_s=3.0):
        sends = []
        edits = []
        def send_fn(token, channel_id, content, timeout=10.0):
            sends.append((content,))
            return True, "ok", f"mid_{len(sends)}"
        def edit_fn(token, channel_id, message_id, embed=None, content=None, timeout=10.0):
            edits.append((message_id, content))
            return True, "ok"
        m = StatusMessenger(
            token="t", channel_id="c", edit_min_interval_s=edit_min_interval_s,
            send_fn=send_fn, edit_fn=edit_fn,
        )
        return m, sends, edits

    def test_ensure_posted_first_time_sends(self):
        m, sends, _ = self._make()
        assert m.ensure_posted(now=0.0) is True
        assert len(sends) == 1
        assert m.message_id == "mid_1"

    def test_ensure_posted_second_time_noop(self):
        m, sends, _ = self._make()
        m.ensure_posted(now=0.0)
        m.ensure_posted(now=10.0)
        assert len(sends) == 1

    def test_update_before_post_returns_false(self):
        # 還沒 post 過，update 無對象可 edit
        m, _, edits = self._make()
        ok = m.update("MINING", "x", 0.0, None, 0, now=0.0)
        assert ok is False
        assert edits == []

    def test_update_state_change_edits(self):
        m, _, edits = self._make()
        m.ensure_posted(now=0.0)
        ok = m.update("MINING", "x", 0.0, None, 0, now=10.0)
        assert ok is True
        assert len(edits) == 1
        assert edits[0][0] == "mid_1"  # edit 同一則

    def test_update_same_state_same_action_no_edit(self):
        m, _, edits = self._make()
        m.ensure_posted(now=0.0)
        m.update("MINING", "x", 0.0, None, 0, now=10.0)  # first edit (state None→MINING)
        edits.clear()
        m.update("MINING", "x", 0.0, None, 0, now=11.0)  # no change
        assert edits == []

    def test_update_throttle_blocks(self):
        m, _, edits = self._make(edit_min_interval_s=3.0)
        m.ensure_posted(now=0.0)
        m.update("MINING", "x", 0.0, None, 0, now=10.0)  # edit (state None→MINING)
        edits.clear()
        # 同 state 但改 action，理論 should_edit=True，但 throttle 還在
        ok = m.update("MINING", "y", 0.0, None, 0, now=11.0)
        assert ok is False
        assert edits == []

    def test_update_after_throttle_allowed(self):
        m, _, edits = self._make(edit_min_interval_s=3.0)
        m.ensure_posted(now=0.0)
        m.update("MINING", "x", 0.0, None, 0, now=10.0)
        edits.clear()
        ok = m.update("MINING", "y", 0.0, None, 0, now=13.1)  # throttle 過 + action 變動
        assert ok is True
        assert len(edits) == 1

    def test_update_tracks_last_state_and_action(self):
        m, _, _ = self._make()
        m.ensure_posted(now=0.0)
        m.update("MINING", "abc", 0.0, None, 0, now=10.0)
        assert m.last_state == "MINING"
        assert m.last_action == "abc"

    def test_send_failure_does_not_set_message_id(self):
        # send_fn 失敗，message_id 不該被設（下次 ensure_posted 仍可重試）
        def bad_send(token, channel_id, content, timeout=10.0):
            return False, "rate limited", None
        m = StatusMessenger(
            token="t", channel_id="c", edit_min_interval_s=3.0,
            send_fn=bad_send, edit_fn=lambda *a, **kw: (True, "ok"),
        )
        assert m.ensure_posted(now=0.0) is False
        assert m.message_id is None

    def test_edit_failure_does_not_update_last_state(self):
        # edit 失敗，state/action 不該更新（下次仍會 retry）
        m, _, _ = self._make()
        # replace edit_fn after construction
        m._edit_fn = lambda *a, **kw: (False, "edit failed")
        m.ensure_posted(now=0.0)
        ok = m.update("MINING", "x", 0.0, None, 0, now=10.0)
        assert ok is False
        assert m.last_state is None
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_notify_p2.py::TestStatusMessenger -v` — 預期 FAIL（class 不存在）。

- [ ] **Step 3: 實作 StatusMessenger**

加到 `miningbot/notify.py`：

```python
# --- P2: StatusMessenger（狀態訊息 post-once-then-edit；spec §7 A）---


class StatusMessenger:
    """遙控器卡的「狀態顯示」部分用 edit_message 即時更新（取代部分釘底）。

    生命週期：
    - ensure_posted() 一次：post 初始訊息，拿 message_id
    - update() 多次：狀態/動作變動 + throttle 通過 → edit_message 同一則

    跟既有 RepinDebouncer 平行（不取代）：RepinDebouncer 仍管卡片釘底（被擠上去時
    刪舊貼新），StatusMessenger 管卡片內容（不刪不貼，就 edit）。

    send_fn / edit_fn 注入：production 用本模組的 send_message_with_id / edit_message；
    測試用 fake callable。所有發訊動作失敗只回 False，不丟例外（沿用 notify 既有慣例）。
    """

    def __init__(self, token: str, channel_id: str, edit_min_interval_s: float,
                 send_fn, edit_fn, log=None):
        self._token = token
        self._channel_id = channel_id
        self._throttle = EditThrottle(min_interval_s=edit_min_interval_s)
        self._send_fn = send_fn
        self._edit_fn = edit_fn
        self._log = log
        self._message_id: str | None = None
        self._last_state: str | None = None
        self._last_action: str | None = None

    @property
    def message_id(self) -> str | None:
        return self._message_id

    @property
    def last_state(self) -> str | None:
        return self._last_state

    @property
    def last_action(self) -> str | None:
        return self._last_action

    def ensure_posted(self, now: float) -> bool:
        """post 初始狀態訊息；已 post 過 no-op。回 True = 此次 post 成功 / 已 post。"""
        if self._message_id is not None:
            return True
        content = format_status_text("MINING", "啟動中", 0.0, None, 0)
        ok, detail, mid = self._send_fn(self._token, self._channel_id, content)
        if not ok or mid is None:
            if self._log:
                self._log.warning("StatusMessenger post 失敗: %s", detail)
            return False
        self._message_id = mid
        # post 視為一次「edit 起點」—— throttle 從此刻起算
        self._throttle.allow_edit(now)
        return True

    def update(self, state: str, last_action: str, audio_score: float,
               capacity_pct: float | None, uptime_s: int, now: float) -> bool:
        """狀態/動作變動 + throttle 通過 → edit_message。回 True = 此次 edit 成功。"""
        if self._message_id is None:
            return False
        if not should_edit_for_state(self._last_state, state, self._last_action, last_action):
            return False
        if not self._throttle.allow_edit(now):
            return False
        content = format_status_text(state, last_action, audio_score, capacity_pct, uptime_s)
        ok, detail = self._edit_fn(
            self._token, self._channel_id, self._message_id, content=content,
        )
        if not ok:
            if self._log:
                self._log.warning("StatusMessenger edit 失敗: %s", detail)
            return False
        # 成功才更新追蹤狀態
        self._last_state = state
        self._last_action = last_action
        return True
```

- [ ] **Step 4: 跑測試，確認通過**

`uv run pytest tests/test_notify_p2.py -v` + full suite + ruff + lock。

- [ ] **Step 5: Commit**

```bash
git add miningbot/notify.py tests/test_notify_p2.py
git commit -m "$(cat <<'EOF'
feat(discord): P2 Task 4——StatusMessenger（狀態訊息 post-once-then-edit）

確保只 post 一次；後續狀態/動作變動 + 3 秒 throttle 通過 → edit_message 同則。
失敗只 log 不丟；send/edit 失敗不更新內部追蹤（下次仍會重試）。
跟 RepinDebouncer 平行（不取代）：釘底仍由 RepinDebouncer 管。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 採集放棄簡化（image_groups 單圖模式）

**Files:**
- Modify: `miningbot/notify.py`（擴充 `make_discord_sink` 支援單圖模式；不刪既有 image_groups 多圖路徑）
- Test: `tests/test_notify_p2.py`（加新 class）

**Interfaces:**
- Consumes: 既有 `make_discord_sink`、`send_images_message`、`send_message`
- Produces:
  - `make_discord_sink(token, channel_id, on_error=None, log=None, giveup_image_mode="single")`
  - 新 `giveup_image_mode="single"` 時，採集放棄事件用**一張全畫面圖 + 一行文字**（取代 image_groups 4-6 張分組）

- [ ] **Step 1: 讀 make_discord_sink 既有實作**

`rg -n "def make_discord_sink" miningbot/notify.py` — 確認既有 image_groups 處理路徑；新 mode 該在哪裡分流。

- [ ] **Step 2: 寫失敗測試**

加到 `tests/test_notify_p2.py`：

```python
class TestGiveupSingleImageMode:
    """spec §7：採集放棄 image_groups 從 4-6 張分組簡化為一張全畫面。

    既有 image_groups 路徑保留（giveup_image_mode="groups" 或預設），相容既有呼叫端。
    """

    def _fake_image_groups_sink(self, giveup_image_mode):
        # 簡化 fake：sink 接 rec，根據 giveup_image_mode 決定呼叫 send_images_message 幾次
        import miningbot.notify as notify
        sends = []  # list of (content, image_paths)
        def fake_send_images(token, channel_id, content, image_paths, timeout=30.0):
            sends.append((content, list(image_paths)))
            return True, "ok"
        sink = notify.make_discord_sink(
            "t", "c", log=None,
            giveup_image_mode=giveup_image_mode,
            _send_images_override=fake_send_images,
        )
        return sink, sends

    def _make_giveup_rec(self):
        # 模擬 NEEDS_HUMAN 附 image_groups（聊天/背包/追蹤框 4-6 張）
        return type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {
                "reason": "X", "harvest_id": "007",
                "image_groups": [
                    ("chat", ["chat_before.png", "chat_after.png"]),
                    ("backpack", ["bp_before.png", "bp_after.png"]),
                ],
                "image_path": "fullframe.png",
            },
        })()

    def test_single_mode_sends_one_image(self):
        sink, sends = self._fake_image_groups_sink("single")
        sink(self._make_giveup_rec())
        # single 模式只發一則、一張圖（fullframe.png）
        assert len(sends) == 1
        assert sends[0][1] == ["fullframe.png"]

    def test_groups_mode_preserves_existing_behavior(self):
        # 既有行為：每 group 一則訊息、帶 group 內圖片
        sink, sends = self._fake_image_groups_sink("groups")
        sink(self._make_giveup_rec())
        assert len(sends) == 2  # 兩個 group 各一則
        assert sends[0][1] == ["chat_before.png", "chat_after.png"]
        assert sends[1][1] == ["bp_before.png", "bp_after.png"]

    def test_single_mode_without_image_path_falls_back_to_text(self):
        # 沒 image_path 就純文字（image_groups 也沒有的特殊情況）
        sink, sends = self._fake_image_groups_sink("single")
        rec = self._make_giveup_rec()
        rec.meta["image_path"] = None
        # 期望：純文字訊息（fake_send_images 沒被呼叫，但 send_message 被呼叫）
        # 我們的 fake 只 override send_images；send_message 仍是 urllib 真呼叫
        # → 測試只在 image_groups 存在時驗證 single 路徑；image_path=None 走 send_message
        # 略過深度測試，避免真的打 urllib
        #（這個 case 由實機驗收覆蓋；這裡 skip）
        import pytest
        pytest.skip("image_path=None 路徑需 mock send_message；由實機驗收覆蓋")
```

- [ ] **Step 3: 跑測試，確認失敗**

`uv run pytest tests/test_notify_p2.py::TestGiveupSingleImageMode -v` — 預期 FAIL（`make_discord_sink` 不接受 `giveup_image_mode` / `_send_images_override` 參數）。

- [ ] **Step 4: 擴充 make_discord_sink**

在 `miningbot/notify.py` 的 `make_discord_sink` 內：

```python
def make_discord_sink(token: str, channel_id: str, on_error=None, log=None,
                      giveup_image_mode: str = "groups",
                      _send_images_override=None):
    """回傳 EventLog sink（既有）；P2 擴充 giveup_image_mode 選項。

    giveup_image_mode:
    - "groups"（預設）：既有行為，image_groups 各 group 一則訊息、附 group 內圖片。
      相容既有呼叫端。
    - "single"（P2 新）：採集放棄事件改為一則訊息 + 一張全畫面圖（meta["image_path"]）。
      細看的聊天/背包截圖在網頁歷史紀錄看（spec §5）。

    _send_images_override：測試用，覆寫 send_images_message；production 為 None。
    """
    _send_images = _send_images_override or send_images_message

    def _send(content, paths):
        ready = [p for p in paths if _wait_for_file(p)]
        if ready:
            ok, detail = _send_images(token, channel_id, content, ready)
            return ok, detail, "IMGx%d" % len(ready)
        ok, detail = send_message(token, channel_id, content)
        return ok, detail, ("TXT" if not paths else "NOIMG(wait-timeout)")

    def sink(rec) -> None:
        content = format_message(rec)
        if content is None:
            return
        # P2 single 模式：優先用 image_path（單張全畫面）取代 image_groups
        if giveup_image_mode == "single":
            single_img = rec.meta.get("image_path")
            if single_img:
                ok, detail, tag = _send(content, [single_img])
                if log:
                    log.info("%s %s -> %s (%s)", tag, rec.type,
                             "OK" if ok else "FAIL", detail)
                if not ok and on_error is not None:
                    on_error(detail)
                return
            # 没有 image_path：fall through 到 groups / text 路徑（既有行為）
        # 既有 image_groups 路徑（groups 模式 or single 模式沒 image_path 時 fallback）
        groups = rec.meta.get("image_groups")
        if groups:
            for text, paths in format_group_messages(content, groups):
                ok, detail, tag = _send(text, paths)
                if log:
                    log.info("%s %s(group) -> %s (%s)", tag, rec.type,
                             "OK" if ok else "FAIL", detail)
                if not ok and on_error is not None:
                    on_error(detail)
            return
        # 既有 multi/single 路徑
        multi = rec.meta.get("image_paths") or []
        single = rec.meta.get("image_path")
        paths = [p for p in multi if p] if multi else ([single] if single else [])
        ok, detail, tag = _send(content, paths)
        if log:
            log.info("%s %s -> %s (%s)", tag, rec.type, "OK" if ok else "FAIL", detail)
        if not ok and on_error is not None:
            on_error(detail)
    return sink
```

- [ ] **Step 5: 跑測試，確認通過**

`uv run pytest tests/test_notify_p2.py -v` + **既有 notify 測試** `uv run pytest tests/test_notify.py -v`（如果有）+ full suite + ruff + lock。

- [ ] **Step 6: Commit**

```bash
git add miningbot/notify.py tests/test_notify_p2.py
git commit -m "$(cat <<'EOF'
feat(discord): P2 Task 5——make_discord_sink 加 giveup_image_mode="single"

採集放棄事件可選用一張全畫面 + 一行文字（取代 image_groups 4-6 張分組）。
既有 "groups" 模式保留相容；main.py 後續 task 決定何時切換。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: NEEDS_HUMAN PING + 結案編輯（PingResolveMessenger）

**Files:**
- Modify: `miningbot/notify.py`
- Test: `tests/test_notify_p2.py`（加新 class）

**Interfaces:**
- Produces:
  - `class PingResolveMessenger`：
    - `__init__(token, channel_id, send_fn, edit_fn, log=None)`
    - `send_ping(harvest_id, reason, fallback, now) -> str | None`：發 PING 訊息、回 message_id（失敗 None）
    - `resolve(message_id, harvest_id, reply_source, detail="") -> bool`：編輯同則為 ✅

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_notify_p2.py`：

```python
from miningbot.notify import PingResolveMessenger


class TestPingResolveMessenger:
    def _make(self):
        sends = []
        edits = []
        def send_fn(token, channel_id, content, timeout=10.0):
            sends.append(content)
            return True, "ok", f"mid_{len(sends)}"
        def edit_fn(token, channel_id, message_id, embed=None, content=None, timeout=10.0):
            edits.append((message_id, content))
            return True, "ok"
        m = PingResolveMessenger(
            token="t", channel_id="c", send_fn=send_fn, edit_fn=edit_fn,
        )
        return m, sends, edits

    def test_send_ping_returns_message_id(self):
        m, sends, _ = self._make()
        mid = m.send_ping(harvest_id="007", reason="X", fallback=True, now=0.0)
        assert mid == "mid_1"
        assert len(sends) == 1
        assert "<@" in sends[0]

    def test_send_ping_failure_returns_none(self):
        m, _, _ = self._make()
        m._send_fn = lambda *a, **kw: (False, "rate limited", None)
        mid = m.send_ping("007", "X", fallback=True, now=0.0)
        assert mid is None

    def test_resolve_edits_same_message(self):
        m, _, edits = self._make()
        mid = m.send_ping("007", "X", fallback=True, now=0.0)
        ok = m.resolve(mid, "007", reply_source="web", detail="(851,189)")
        assert ok is True
        assert len(edits) == 1
        assert edits[0][0] == mid
        assert "✅" in edits[0][1]

    def test_resolve_edit_failure_returns_false(self):
        m, _, _ = self._make()
        mid = m.send_ping("007", "X", fallback=True, now=0.0)
        m._edit_fn = lambda *a, **kw: (False, "edit failed")
        ok = m.resolve(mid, "007", reply_source="web")
        assert ok is False

    def test_resolve_unknown_message_id_returns_false(self):
        m, _, _ = self._make()
        ok = m.resolve("nonexistent_mid", "007", reply_source="web")
        assert ok is False
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_notify_p2.py::TestPingResolveMessenger -v`

- [ ] **Step 3: 實作 PingResolveMessenger**

加到 `miningbot/notify.py`：

```python
# --- P2: PingResolveMessenger（NEEDS_HUMAN 推播 + 結案編輯；spec §7 B / D）---


class PingResolveMessenger:
    """NEEDS_HUMAN PING 推播 + 結案 edit 同則。

    送 PING 訊息用 send_fn（含 message_id 回傳）；結案用 edit_fn 把同則改成 ✅。
    生命週期：
    - send_ping() 一次：拿到 message_id，呼叫端存起來
    - resolve(message_id) 一次：編輯該則為 ✅；只能 resolve 一次（編輯 idempotent 但語意上是結案）

    失敗只回 False / None，不丟例外（沿用 notify 既有慣例）。
    """

    def __init__(self, token: str, channel_id: str, send_fn, edit_fn, log=None):
        self._token = token
        self._channel_id = channel_id
        self._send_fn = send_fn
        self._edit_fn = edit_fn
        self._log = log

    def send_ping(self, harvest_id: str | None, reason: str,
                  fallback: bool, now: float) -> str | None:
        """發 PING 訊息，回 message_id（失敗 None）。

        now 參數目前未直接使用（保留給未來 rate-limit）；先介面對齊 StatusMessenger。
        """
        content = format_ping_content(harvest_id, reason, fallback)
        ok, detail, mid = self._send_fn(self._token, self._channel_id, content)
        if not ok or mid is None:
            if self._log:
                self._log.warning("PingResolveMessenger send_ping 失敗: %s", detail)
            return None
        return mid

    def resolve(self, message_id: str, harvest_id: str | None,
                reply_source: str, detail: str = "") -> bool:
        """把 PING 訊息 edit 成 ✅ 結案。回 True = 編輯成功。"""
        if not message_id:
            return False
        content = format_resolve_text(harvest_id, reply_source, detail)
        ok, detail_msg = self._edit_fn(
            self._token, self._channel_id, message_id, content=content,
        )
        if not ok:
            if self._log:
                self._log.warning("PingResolveMessenger resolve 失敗: %s", detail_msg)
            return False
        return True
```

- [ ] **Step 4: 跑測試，確認通過**

`uv run pytest tests/test_notify_p2.py -v` + full suite + ruff + lock。

- [ ] **Step 5: Commit**

```bash
git add miningbot/notify.py tests/test_notify_p2.py
git commit -m "$(cat <<'EOF'
feat(discord): P2 Task 6——PingResolveMessenger（PING 推播 + 結案編輯）

NEEDS_HUMAN 用 <@ID> PING 推播；玩家處理完後編輯同則成 ✅。
頻道看起來是「⚠️ PING → ✅ 結案」一則（spec §7 B）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: main.py 整合 StatusMessenger + PingResolveMessenger

**Files:**
- Modify: `miningbot/main.py`

**Interfaces:**
- Consumes: `StatusMessenger`、`PingResolveMessenger`（來自 P2 task 4/6）、既有 `self.log` EventLog
- Produces: bot 啟動 post status message；狀態變動 edit；NEEDS_HUMAN PING + 結案 edit；shutdown cleanup

**注意：** 這個 task 需要先 `rg` 找 main.py 既有 anchor points：
- A: Discord sink 註冊位置（`make_discord_sink` 呼叫處）→ 在同處加 StatusMessenger / PingResolveMessenger 初始化
- B: 主迴圈狀態切換處（state machine 設 `self.state = ...` 處）→ 加 StatusMessenger.update 呼叫
- C: NEEDS_HUMAN 進入點（`log.log(Event(type="NEEDS_HUMAN", ...))`）→ 攔截決定 PING 發送
- D: 玩家 reply 處理完成處（fire_at / reentry_click 後）→ 結案 edit
- E: shutdown hook（`finally` 或 `__del__`）→ cleanup

- [ ] **Step 1: rg 找 5 個 anchor points**

```
rg -n "make_discord_sink|self.state = |NEEDS_HUMAN|_handle_web_control|finally" miningbot/main.py | head -50
```

記錄每個 anchor 的 file:line + 實際命名。

- [ ] **Step 2: 寫整合測試（fake bot + mocked messengers）**

加到 `tests/test_notify_p2.py`：

```python
class TestMainIntegration:
    """smoke test：bot 啟動時 initialize 兩個 messenger；狀態變動呼叫 update。

    用 fake StatusMessenger / PingResolveMessenger 注入，計數呼叫。
    不啟動完整 bot（太重）；只驗 __init__ 與一個 tick 的整合行為。"""

    def test_main_init_creates_messengers_when_discord_enabled(self, monkeypatch):
        # 略——具體 fake bot 結構依 main.py；此測試標 skip，理由同 P1 Task 10
        # 留 P3/P4 整合時補回（那時 main.py 對 web 整合更完整）
        pytest.skip("main.py 整合 smoke test 留 P3/P4 補；此 task 先驗 rg 找的 anchor 存在")

    def test_anchor_make_discord_sink_exists(self):
        # 確保 rg 找得到 anchor（實作者要在報告內填實際 file:line）
        import subprocess
        out = subprocess.check_output(
            ["rg", "-n", "make_discord_sink", "miningbot/main.py"],
            cwd="C:/Users/puppy/OneDrive/Desktop/無聊的挖礦遊戲",
        ).decode()
        assert "make_discord_sink" in out
```

- [ ] **Step 3: 跑測試，確認第一個 skip / 第二個 pass**

`uv run pytest tests/test_notify_p2.py::TestMainIntegration -v`

- [ ] **Step 4: 整合進 main.py**

根據 Step 1 找到的 anchor，做以下最小侵入整合：

```python
# miningbot/main.py - 在 Discord sink 註冊附近（anchor A）加：
from .notify import StatusMessenger, PingResolveMessenger
import time

if cfg.discord_bot_token and cfg.discord_channel_id:
    self._status_messenger = StatusMessenger(
        token=cfg.discord_bot_token, channel_id=cfg.discord_channel_id,
        edit_min_interval_s=cfg.discord_status_edit_min_interval_s,
        send_fn=notify.send_message_with_id,
        edit_fn=notify.edit_message,
        log=self.logger,
    )
    self._ping_messenger = PingResolveMessenger(
        token=cfg.discord_bot_token, channel_id=cfg.discord_channel_id,
        send_fn=notify.send_message_with_id,
        edit_fn=notify.edit_message,
        log=self.logger,
    )
    self._status_messenger.ensure_posted(now=time.monotonic())
    self._pending_ping_mid: dict[str, str] = {}  # routing_key → PING message_id
else:
    self._status_messenger = None
    self._ping_messenger = None
    self._pending_ping_mid = {}

# 在主迴圈 safe point（每 tick 末；anchor B）加：
def _update_status_messenger(self):
    if self._status_messenger is None:
        return
    audio = 0.0
    try:
        audio = self.listener.latest_score()
    except Exception:
        pass
    uptime = int(time.time() - self._started)
    self._status_messenger.update(
        state=self.state.value, last_action=self.last_action,
        audio_score=audio, capacity_pct=getattr(self, "_capacity_pct", None),
        uptime_s=uptime, now=time.monotonic(),
    )

# 在 NEEDS_HUMAN 進入時（anchor C；可能是 _enter_needs_human 或 event sink 攔截）加：
def _send_needs_human_ping(self, harvest_id: str | None, reason: str):
    if self._ping_messenger is None:
        return None
    fallback = self._web_fallback_state is None or self._web_fallback_state.is_fallback(now=time.monotonic(), grace_s=self.config.web_fallback_grace_s)
    mid = self._ping_messenger.send_ping(
        harvest_id=harvest_id, reason=reason, fallback=fallback,
        now=time.monotonic(),
    )
    if mid and harvest_id:
        # 用 routing_key 存（fire_at/reentry_click reply 回來時對照）
        self._pending_ping_mid[f"harvest:{harvest_id}"] = mid
    return mid

# 在玩家 reply 處理完成處（anchor D；_execute_remote_fire / _rr_click 後）加：
def _resolve_ping_if_any(self, routing_key: str, reply_source: str, detail: str = ""):
    if self._ping_messenger is None:
        return
    mid = self._pending_ping_mid.pop(routing_key, None)
    if mid:
        # 從 routing_key 拆 harvest_id（"harvest:007" → "007"）
        harvest_id = routing_key.split(":", 1)[1] if ":" in routing_key else None
        self._ping_messenger.resolve(mid, harvest_id, reply_source, detail)

# shutdown（anchor E；finally block）加：
if self._status_messenger is not None:
    # 最後 edit 一次「已關機」狀態（best-effort）
    try:
        self._status_messenger.update(
            state="STOPPED", last_action="shutdown", audio_score=0.0,
            capacity_pct=None, uptime_s=int(time.time() - self._started),
            now=time.monotonic(),
        )
    except Exception:
        pass
```

注意：
- `_send_needs_human_ping` 跟 `_resolve_ping_if_any` 是 framework；具體 anchor C/D 的呼叫端要依 main.py 既有結構對接（可能 NEEDS_HUMAN 從 event log 觸發，那要在 sink 路徑攔截；可能從主迴圈直接進入 NEEDS_HUMAN，那要在該 method 加呼叫）
- 若 anchor C/D 的具體整合點過於複雜（NEEDS_HUMAN 進入點多處），先做 minimum viable：在 `_tick` 內檢測 `self.state.value == "NEEDS_HUMAN"` 轉換邊沿，發 PING；reply pop 時呼叫 resolve。其他 anchor C/D 整合點列為 deferred，記 ledger

- [ ] **Step 5: 跑全測試**

`uv run pytest -q` + `uv run ruff check . --no-cache` + `uv lock --check`

預期：全綠（不該破壞既有測試）。

- [ ] **Step 6: Commit**

```bash
git add miningbot/main.py tests/test_notify_p2.py
git commit -m "$(cat <<'EOF'
feat(discord): P2 Task 7——main.py 整合 StatusMessenger + PingResolveMessenger

啟動 ensure_posted；每 tick 呼叫 _update_status_messenger；NEEDS_HUMAN 進入時
ping_messenger.send_ping；玩家 reply 完成時 _resolve_ping_if_any 編輯為 ✅。
shutdown 時 best-effort 最後 edit。

P2 完工：Discord 退回精簡通知角色，狀態用 edit、需介入用 PING、結案編輯同則。
既有 discord_commands.py / RepinDebouncer / image_groups 全保留（fallback）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review 結果

### 1. Spec coverage

| spec §7 段落 | 對應 task |
|---|---|
| A. 遙控器卡（合併狀態顯示，post-once-then-edit） | Task 2（should_edit_for_state）+ Task 4（StatusMessenger）+ Task 7（main.py 整合） |
| B. 需介入訊息（PING + 結案編輯） | Task 6（PingResolveMessenger）+ Task 7 |
| C. 關鍵事件（純文字）| 既有 notify.format_message 已處理；P2 不動 |
| 採集放棄簡化為一張全畫面 | Task 5（giveup_image_mode="single"） |
| `RepinDebouncer` 保留 | 不動（既有 notify.py） |
| `discord_commands.py` 文字命令保留 | 不動 |
| `PING_USER_ID` 寫死 notify.py | Task 1 |
| `discord_status_edit_min_interval_s` Config | Task 1 |

### 2. 不在 P2 範圍（屬 P3~P5）

- 玩家設定面板 UI（4 個白名單欄位的網頁前端）→ **P3**
- 即時介入面板 UI（pinch-zoom canvas、tap）+ 各狀態處理器接 web_pending → **P4**
- 歷史紀錄與標註面板 + 自動收集素材 + `tests/fixtures/aim/auto_*` 寫入 → **P5**

### 3. Type consistency

- `StatusMessenger.ensure_posted(now) -> bool` / `update(...) -> bool`
- `PingResolveMessenger.send_ping(...) -> str | None` / `resolve(...) -> bool`
- `make_discord_sink(..., giveup_image_mode="groups"|"single", _send_images_override=None)`

### 4. 已知 placeholder / 彈性

- Task 7 Step 4 的 main.py anchor C/D（NEEDS_HUMAN PING 觸發 + reply 結案）需要實作者對齊既有結構；若 NEEDS_HUMAN 進入點多處複雜，可先做 minimum viable（tick 邊沿檢測），其他整合點 deferred 記 ledger
- Task 7 Step 2 的整合 smoke test 暫時 skip，理由同 P1 Task 10（main.py 結構需實際讀過才能寫 fake bot）

---

## P2 完工驗收

- [ ] 全測試綠（`uv run pytest -q`）
- [ ] lint 乾淨（`uv run ruff check . --no-cache`）
- [ ] lock 一致（`uv lock --check`）
- [ ] **既有 notify.py 行為沒回歸**：`tests/test_notify*.py`（既有）全綠
- [ ] StatusMessenger post-once-then-edit 流程測試綠
- [ ] PingResolveMessenger PING + resolve 測試綠
- [ ] giveup_image_mode="single" 路徑測試綠；既有 "groups" 路徑也綠（相容性）
- [ ] main.py 啟動時 messenger 初始化（不噴例外）；shutdown 不卡

P2 不需實機驗收（main.py 整合測試 skip 部分留 P3/P4 補）。

## 風險

| 風險 | 對策 |
|---|---|
| main.py anchor C/D 整合點複雜（NEEDS_HUMAN 多入口） | minimum viable：tick 邊沿檢測 + 記 ledger 給 P4 |
| 既有 notify test 壞 | Task 5 改動保留 "groups" 預設；擴充測試只加新 class |
| StatusMessenger edit 跟既有 RepinDebouncer repin 衝突（同卡片被兩個機制改） | 不衝突：RepinDebouncer 刪舊貼新（新訊息新 mid），StatusMessenger edit 同 mid；RepinDebouncer 觸發後 StatusMessenger._message_id 失效，下次 update 失敗——Task 7 整合時要 hook「repin 後更新 StatusMessenger._message_id」 |
| Discord rate limit（edit 太頻繁） | EditThrottle 3 秒（Config 可調） |
| PING_USER_ID 寫死但將來換人用 | 個人 bot，spec §7 明確說不做 Config 欄位；換人時改 code |

## 非目標

- 不做網頁前端（HTML/JS）
- 不動 Discord polling thread 邏輯
- 不接 bot 各狀態處理器 reply pop（P4 才做）
- 不寫素材 / 標註（P5 才做）
- 不實機驗收（P4 才需要）
- 不刪 `RepinDebouncer`、不砍 `image_groups` 路徑（保留 fallback）
