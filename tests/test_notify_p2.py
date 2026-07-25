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


# --- Task 2：should_edit_for_state + EditThrottle 純函式 ---

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


# --- Task 3：format_status_text + format_ping_content + format_resolve_text 純函式 ---

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


# --- Task 4：StatusMessenger（post-once-then-edit 生命週期）---

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
