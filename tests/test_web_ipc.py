"""race routing key 與 PendingReplies（先到先贏規則）。"""
import pytest
from miningbot.web_ipc import routing_key, reply_matches, PendingReplies


class TestRoutingKey:
    def test_harvest_episode(self):
        assert routing_key("harvest", "007") == "harvest:007"

    def test_reentry_attempt(self):
        assert routing_key("reentry", "attempt_3") == "reentry:attempt_3"

    def test_empty_episode_id_still_formatted(self):
        # 防禦性：不該出現，但格式仍可建
        assert routing_key("harvest", "") == "harvest:"


class TestReplyMatches:
    def test_same_key_matches(self):
        assert reply_matches("harvest:007", "harvest:007") is True

    def test_different_episode_same_flow_no_match(self):
        # bot 等 harvest:007，送來 harvest:008 → 不匹配
        assert reply_matches("harvest:008", "harvest:007") is False

    def test_different_flow_no_match(self):
        assert reply_matches("reentry:attempt_3", "harvest:007") is False


class TestPendingRepliesFirstWins:
    def test_first_push_wins(self):
        q = PendingReplies()
        q.push("harvest:007", {"x": 100, "y": 200})
        q.push("harvest:007", {"x": 999, "y": 999})  # 太晚，丟棄
        reply = q.pop("harvest:007")
        assert reply == {"x": 100, "y": 200}

    def test_second_push_for_same_key_returns_none_immediately(self):
        # spec §8：同 key 第二個 reply 進來，立刻丟棄（不排隊）
        q = PendingReplies()
        assert q.push("harvest:007", {"x": 100, "y": 200}) is True   # 第一個收下
        assert q.push("harvest:007", {"x": 999, "y": 999}) is False  # 第二個拒絕

    def test_pop_returns_none_when_empty(self):
        q = PendingReplies()
        assert q.pop("harvest:007") is None

    def test_pop_clears_slot(self):
        q = PendingReplies()
        q.push("harvest:007", {"x": 100, "y": 200})
        assert q.pop("harvest:007") == {"x": 100, "y": 200}
        # 再 pop 一次也空
        assert q.pop("harvest:007") is None
        # pop 後可再 push 新 reply
        assert q.push("harvest:007", {"x": 300, "y": 400}) is True

    def test_different_keys_independent(self):
        q = PendingReplies()
        q.push("harvest:007", {"x": 100})
        q.push("reentry:attempt_3", {"x": 200})
        assert q.pop("harvest:007") == {"x": 100}
        assert q.pop("reentry:attempt_3") == {"x": 200}

    def test_pop_any_expired_removes_old_replies(self):
        # 用 monotonic clock injection 測過期
        q = PendingReplies()
        q._now = lambda: 0.0  # 注入時鐘
        q.push("harvest:007", {"x": 100}, ttl_s=30.0)
        q._now = lambda: 100.0  # 時間推 100s
        expired = q.pop_any_expired()
        assert len(expired) == 1
        assert expired[0][0] == "harvest:007"
        assert expired[0][1] == {"x": 100}
        # 過期後 slot 清空
        assert q.pop("harvest:007") is None

    def test_pop_any_expired_keeps_fresh(self):
        q = PendingReplies()
        q._now = lambda: 0.0
        q.push("harvest:007", {"x": 100}, ttl_s=30.0)
        q._now = lambda: 10.0  # 還新鮮
        assert q.pop_any_expired() == []
        assert q.pop("harvest:007") == {"x": 100}
