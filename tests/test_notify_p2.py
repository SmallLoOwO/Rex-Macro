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
