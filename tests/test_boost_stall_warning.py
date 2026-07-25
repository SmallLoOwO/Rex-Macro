"""Boost 沒到期警報（2026-07-25 使用者要求）。

實機 18:40-19:00 場才從 heartbeat audio 靜止看出問題，但當時缺直接訊號無法立刻歸因。
此警報在 MINING 且未暫停時 boost 連續 > boost_stall_warn_s 沒重上 就警告——不同於
STUCK 偵測（靠 frame diff，frame 還在動就 pass），這條直接看 boost 是否到期。
"""
import logging

from miningbot.config import DEFAULT as cfg
from miningbot.main import Bot
from miningbot.states import State


class _Recorder:
    def __init__(self):
        self.records = []

    def warning(self, msg, *args):
        self.records.append(("WARNING", msg % args if args else msg))

    def info(self, msg, *args):
        self.records.append(("INFO", msg % args if args else msg))


def _bot():
    bot = Bot.__new__(Bot)
    bot.logger = _Recorder()
    bot.paused = False
    bot.state = State.MINING
    bot._last_boost = 0.0
    bot._boost_present = False
    bot._peak_audio_since_hb = 0.0
    bot._boost_stall_notified = False
    return bot


def test_warns_when_mining_not_paused_and_boost_long_expired():
    bot = _bot()
    # _last_boost 設為 (now - 100s)，超過 boost_stall_warn_s=90
    import time as _t
    now = _t.time()
    bot._last_boost = now - 100.0
    bot._check_boost_stall(now)
    warnings = [r for r in bot.logger.records if r[0] == "WARNING"]
    assert len(warnings) == 1
    assert "boost-stall" in warnings[0][1]
    assert bot._boost_stall_notified is True


def test_does_not_warn_when_paused():
    """暫停時 boost 本來就不會到期（遊戲時間不流動）——不可誤報。"""
    import time as _t
    bot = _bot()
    bot.paused = True
    bot._last_boost = _t.time() - 1000.0
    bot._check_boost_stall(_t.time())
    assert bot.logger.records == []
    assert bot._boost_stall_notified is False


def test_does_not_warn_when_not_mining():
    """HARVESTING/RESET_WAIT/REENTRY 不靠 boost 偵測 MINING 進度，不可誤報。"""
    import time as _t
    for state in (State.HARVESTING, State.RESET_WAIT, State.REENTRY,
                  State.NEEDS_HUMAN):
        bot = _bot()
        bot.state = state
        bot._last_boost = _t.time() - 1000.0
        bot._check_boost_stall(_t.time())
        assert bot.logger.records == [], f"state={state} 不該警報"
        assert bot._boost_stall_notified is False


def test_warns_once_until_boost_recovers():
    """警報後鎖住，恢復（boost 重上、elapsed < cooldown）才解鎖——避免洗頻道。"""
    import time as _t
    bot = _bot()
    now = _t.time()
    bot._last_boost = now - 100.0      # 早已過警報門檻

    bot._check_boost_stall(now)        # 第一次 → 警報
    assert len([r for r in bot.logger.records if r[0] == "WARNING"]) == 1
    assert bot._boost_stall_notified is True

    bot._check_boost_stall(now + 10)   # 又 tick，仍過門檻 → 不重複警報
    assert len([r for r in bot.logger.records if r[0] == "WARNING"]) == 1

    # boost 被重上：_last_boost 更新到剛剛、elapsed < cooldown → 解鎖
    bot._last_boost = now + 10
    bot._check_boost_stall(now + 11)
    assert bot._boost_stall_notified is False

    # 之後若又長時間沒重上 → 可再警報
    bot._last_boost = (now + 11) - 100.0
    bot._check_boost_stall(now + 11)
    assert len([r for r in bot.logger.records if r[0] == "WARNING"]) == 2


def test_does_not_warn_below_threshold():
    import time as _t
    bot = _bot()
    bot._last_boost = _t.time() - (cfg.boost_stall_warn_s - 5.0)
    bot._check_boost_stall(_t.time())
    assert bot.logger.records == []


def test_threshold_is_longer_than_typical_boost_cycle():
    """boost 自然 ~50s 到期、cooldown 5s，警報門檻必須 > 兩者之和才不會假警報。"""
    assert cfg.boost_stall_warn_s > 60.0
    assert cfg.boost_stall_warn_s > cfg.boost_cooldown_s
