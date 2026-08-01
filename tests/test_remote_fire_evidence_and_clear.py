"""遠端開火成功證據回饋＋pickup 動畫等待＋手動清空指令（2026-08-01）。

三項改動的回歸測試：

1. ``_remote_fire_success`` 補上 pickup 動畫等待（``time.sleep(1.0)``）——
   舊版直接調 ``_resume_mining_tail``，動畫期間 ``_clear_panel_filter`` 的點擊全被
   吃掉 → 使用者看到「背包沒刷新」。

2. ``_remote_fire_success`` 補上背包/聊天前後對比裁圖＋HARVEST_SUCCESS log＋
   ``_episode_succeeded`` / ``stats["rares"]`` ——舊版只送純文字「🎉 採集成功」，
   使用者要求「如同背包（前/後）聊天框（前/後）一樣給予回饋」。

3. ``清空`` / ``clearpanel`` 指令（Discord＋網頁）——手動觸發 ``_clear_panel_filter``，
   避免 H070/H071 的自動清空失敗後路 B 用到上一場殘留 → 假陽性。
"""
from unittest.mock import MagicMock

import numpy as np
import pytest

from miningbot import main
from miningbot.config import DEFAULT as cfg
from miningbot.main import Bot, State
from miningbot.states import decide_transition

from tests.fake_bot import make_fake_bot, FakeHarvestCtx


# ── 共用 fixtures ──────────────────────────────────────────────────────────

def _frame():
    return np.zeros((1080, 1920, 3), dtype=np.uint8)


class _Ctx:
    """_remote_fire_success 的 ctx 替身（只需 harvest_id + pose_net_rotations）。"""
    def __init__(self):
        self.harvest_id = "155"
        self.pose_net_rotations = 0


# ── 1. _remote_fire_success：pickup 動畫等待 ───────────────────────────────

def test_remote_fire_success_waits_for_pickup_animation(monkeypatch):
    """舊版 _remote_fire_success 直接調 _resume_mining_tail，沒有等 pickup 動畫。
    動畫 1-2s 期間所有按鍵/點擊被遊戲吞掉 → _clear_panel_filter 全滅 → 背包沒刷新。
    """
    sleeps = []
    monkeypatch.setattr(main.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(main.capture, "grab", lambda: _frame())
    monkeypatch.setattr(main.notify, "send_message", lambda *a, **k: None)
    monkeypatch.setattr(main.notify, "send_images_message", lambda *a, **k: None)
    monkeypatch.setattr(main.notify, "format_group_messages",
                        lambda content, groups: [(content, [])])

    bot = make_fake_bot(
        bind=["_remote_fire_success"],
        _harvest_origin_ref=_frame(),
        _pre_scan_ref=_frame(),
        _episode_succeeded=False,
        stats={"boosts": 0, "rerolls": 0, "rares": 0, "stuck": 0},
        last_action="",
        _focus_roblox=lambda: True,
        _pitch_drag_verified=lambda *a, **k: True,
        _resume_mining_tail=lambda net: None,
        _hsnap=lambda *a, **k: None,
        _hsnap_crop=lambda *a, **k: "/tmp/fake.png",
        log=MagicMock(),
    )
    bot._remote_fire_success(_Ctx(), "155")

    assert 1.0 in sleeps, (
        "pickup 動畫等待（time.sleep(1.0)）必須在 _resume_mining_tail 之前"
    )


# ── 2. _remote_fire_success：證據裁圖＋成功記帳 ─────────────────────────────

def test_remote_fire_success_captures_evidence_and_logs_success(monkeypatch):
    """證據回饋：背包/聊天 前後對比裁圖＋HARVEST_SUCCESS log＋旗標。
    舊版只送純文字，使用者要求「如同背包（前/後）聊天框（前/後）一樣給予回饋」。
    """
    crops = []
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(main.capture, "grab", lambda: _frame())
    sent_images = []
    monkeypatch.setattr(main.notify, "send_images_message",
                        lambda *a, **k: sent_images.append(a))
    monkeypatch.setattr(main.notify, "send_message", lambda *a, **k: None)

    def fake_format(content, groups):
        # 記錄哪些 region 有被裁圖
        for region, paths in groups:
            crops.append(region)
        return [(content, [])]

    monkeypatch.setattr(main.notify, "format_group_messages", fake_format)

    bot = make_fake_bot(
        bind=["_remote_fire_success"],
        _harvest_origin_ref=_frame(),
        _pre_scan_ref=None,
        _episode_succeeded=False,
        stats={"boosts": 0, "rerolls": 0, "rares": 0, "stuck": 0},
        last_action="",
        _focus_roblox=lambda: True,
        _pitch_drag_verified=lambda *a, **k: True,
        _resume_mining_tail=lambda net: None,
        _hsnap=lambda *a, **k: None,
        _hsnap_crop=lambda *a, **k: "/tmp/fake.png",
        log=MagicMock(),
    )
    bot._remote_fire_success(_Ctx(), "155")

    # 背包＋聊天 兩組都要有
    assert "chat" in crops, "聊天前後對比裁圖必須產出"
    assert "backpack" in crops, "背包前後對比裁圖必須產出"
    # 成功記帳
    assert bot._episode_succeeded is True, "_episode_succeeded 必須設 True（救援路 B 閘門）"
    assert bot.stats["rares"] == 1, "stats['rares'] 必須 +1"
    # HARVEST_SUCCESS log
    logged_events = [c.kwargs.get("event") or c.args[0] if c.args else None
                     for c in bot.log.log.call_args_list]
    # log.log 第一個 positional arg 是事件名
    assert any("HARVEST_SUCCESS" in str(a) for a in logged_events), (
        "必須記 HARVEST_SUCCESS event"
    )


def test_remote_fire_success_sends_evidence_images_via_discord(monkeypatch):
    """send_images_message 至少被呼叫一次（帶前後對比裁圖路徑）。"""
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(main.capture, "grab", lambda: _frame())
    images_sent = []
    monkeypatch.setattr(main.notify, "send_images_message",
                        lambda *a, **k: images_sent.append(a))
    monkeypatch.setattr(main.notify, "send_message", lambda *a, **k: None)
    monkeypatch.setattr(main.notify, "format_group_messages",
                        lambda content, groups: [(content, ["/fake/before.png",
                                                              "/fake/after.png"])])

    bot = make_fake_bot(
        bind=["_remote_fire_success"],
        _harvest_origin_ref=_frame(),
        _pre_scan_ref=_frame(),
        _episode_succeeded=False,
        stats={"boosts": 0, "rerolls": 0, "rares": 0, "stuck": 0},
        last_action="",
        _focus_roblox=lambda: True,
        _pitch_drag_verified=lambda *a, **k: True,
        _resume_mining_tail=lambda net: None,
        _hsnap=lambda *a, **k: None,
        _hsnap_crop=lambda *a, **k: "/tmp/fake.png",
        log=MagicMock(),
    )
    bot._remote_fire_success(_Ctx(), "155")

    assert len(images_sent) > 0, "必須透過 send_images_message 送出證據圖"


def test_remote_fire_success_gives_up_on_focus_loss(monkeypatch):
    """聚焦失敗 → 走 _harvest_giveup（同 _harvest_success 6612-6614 慣例）。"""
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(main.capture, "grab", lambda: _frame())
    monkeypatch.setattr(main.notify, "send_message", lambda *a, **k: None)
    monkeypatch.setattr(main.notify, "send_images_message", lambda *a, **k: None)
    monkeypatch.setattr(main.notify, "format_group_messages",
                        lambda content, groups: [(content, [])])
    giveup_called = []

    bot = make_fake_bot(
        bind=["_remote_fire_success"],
        _harvest_origin_ref=_frame(),
        _episode_succeeded=False,
        stats={"boosts": 0, "rerolls": 0, "rares": 0, "stuck": 0},
        last_action="",
        _focus_roblox=lambda: False,
        _harvest_giveup=lambda reason, **k: giveup_called.append(reason),
        _pitch_drag_verified=lambda *a, **k: True,
        _resume_mining_tail=lambda net: None,
        _hsnap=lambda *a, **k: None,
        _hsnap_crop=lambda *a, **k: "/tmp/fake.png",
        log=MagicMock(),
    )
    bot._remote_fire_success(_Ctx(), "155")

    assert len(giveup_called) == 1, "聚焦失敗必須走 _harvest_giveup"


# ── 3. _consume_clear_panel：MINING 時放開 W/滑鼠 → 清空 → 重 init ──────────

def test_consume_clear_panel_mining_releases_keys_then_clears(monkeypatch):
    """MINING 時 W/滑鼠按住中——清空前必須先放開，清完重新 init。"""
    from miningbot import miner
    keys = []
    monkeypatch.setattr(main.ic, "key_up", lambda k: keys.append("-" + k))
    monkeypatch.setattr(main.ic, "key_down", lambda k: keys.append("+" + k))
    monkeypatch.setattr(main.ic, "mouse_up", lambda: keys.append("-mouse"))
    monkeypatch.setattr(main.ic, "mouse_down", lambda: keys.append("+mouse"))
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(miner, "init_mining_sequence", lambda **k: keys.append("init"))
    monkeypatch.setattr(main.notify, "send_message", lambda *a, **k: None)

    clear_called = []
    bot = make_fake_bot(
        bind=["_consume_clear_panel"],
        state=State.MINING,
        _panel_zeroed_at=None,
        _clear_panel_filter=lambda: (clear_called.append(True),
                                     setattr(bot, "_panel_zeroed_at", 9999.0)),
        _rotate_verified=lambda *a, **k: True,
    )
    bot._consume_clear_panel()

    assert clear_called, "_clear_panel_filter 必須被呼叫"
    # 先放開 W + 滑鼠
    assert "-w" in keys, "MINING 時必須先 key_up('w')"
    assert "-mouse" in keys, "MINING 時必須先 mouse_up()"
    # init 在清空之後
    assert "init" in keys, "清空後必須重新 init_mining_sequence"
    # 重新按住 W + 滑鼠
    assert "+w" in keys, "清空後必須重新 key_down('w')"
    assert "+mouse" in keys, "清空後必須重新 mouse_down()"


def test_consume_clear_panel_needs_human_skips_key_release(monkeypatch):
    """NEEDS_HUMAN 時沒按住 W/滑鼠——不必放開也不必 init。"""
    from miningbot import miner
    keys = []
    monkeypatch.setattr(main.ic, "key_up", lambda k: keys.append("-" + k))
    monkeypatch.setattr(main.ic, "key_down", lambda k: keys.append("+" + k))
    monkeypatch.setattr(main.ic, "mouse_up", lambda: keys.append("-mouse"))
    monkeypatch.setattr(main.ic, "mouse_down", lambda: keys.append("+mouse"))
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(miner, "init_mining_sequence", lambda **k: keys.append("init"))
    monkeypatch.setattr(main.notify, "send_message", lambda *a, **k: None)

    clear_called = []
    bot = make_fake_bot(
        bind=["_consume_clear_panel"],
        state=State.NEEDS_HUMAN,
        _panel_zeroed_at=None,
        _clear_panel_filter=lambda: clear_called.append(True),
        _rotate_verified=lambda *a, **k: True,
    )
    bot._consume_clear_panel()

    assert clear_called, "_clear_panel_filter 必須被呼叫"
    assert not any("init" in k for k in keys), "NEEDS_HUMAN 不該跑 init_mining_sequence"
    assert "-w" not in keys, "NEEDS_HUMAN 不該 key_up（本來就沒按住）"


def test_consume_clear_panel_reports_result(monkeypatch):
    """清空結果要回報 Discord：成功→路B可信任；失敗→路B將跳過。"""
    monkeypatch.setattr(main.ic, "key_up", lambda k: None)
    monkeypatch.setattr(main.ic, "key_down", lambda k: None)
    monkeypatch.setattr(main.ic, "mouse_up", lambda: None)
    monkeypatch.setattr(main.ic, "mouse_down", lambda: None)
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    from miningbot import miner
    monkeypatch.setattr(miner, "init_mining_sequence", lambda **k: None)

    messages = []
    monkeypatch.setattr(main.notify, "send_message",
                        lambda *a, **k: messages.append(a[2]))  # a = (token, ch, text)

    # 成功
    bot = make_fake_bot(
        bind=["_consume_clear_panel"],
        state=State.NEEDS_HUMAN,
        _panel_zeroed_at=None,
        _clear_panel_filter=lambda: setattr(bot, "_panel_zeroed_at", 9999.0),
        _rotate_verified=lambda *a, **k: True,
    )
    bot._consume_clear_panel()
    assert any("已清空" in m for m in messages), "清空成功要回報「已清空」"
    assert any("可信任" in m for m in messages), "成功要附「路B可信任」"

    # 失敗
    messages.clear()
    bot2 = make_fake_bot(
        bind=["_consume_clear_panel"],
        state=State.NEEDS_HUMAN,
        _panel_zeroed_at=None,
        _clear_panel_filter=lambda: None,  # 不設 _panel_zeroed_at → None
        _rotate_verified=lambda *a, **k: True,
    )
    bot2._consume_clear_panel()
    assert any("未確認" in m or "清空" in m for m in messages), "清空失敗也要回報"
    assert any("將跳過" in m for m in messages), "失敗要附「路B將跳過」"


# ── 4. _tick 消費 _pending_clear_panel（狀態閘）─────────────────────────────

def test_tick_consumes_pending_clear_panel_in_mining(monkeypatch):
    """_tick 在 MINING/NEEDS_HUMAN/RESET_WAIT 時消費 _pending_clear_panel。"""
    consumed = []
    bot = make_fake_bot(
        bind=["_tick"],
        state=State.MINING,
        _pending_clear_panel=True,
        _pending_ability=False,
        _pending_rotate=None,
        _consume_clear_panel=lambda: consumed.append(True),
        _update_reset_chime_active=lambda: None,
        _consume_web_pending=lambda: None,
        _tick_mining=lambda frame: None,
    )
    # stub 掉所有 _tick 可能呼叫的狀態分支
    bot._consume_pending_rotate = lambda: None
    bot._tick_harvest = lambda frame: None
    bot._tick_reentry = lambda frame: None
    bot._pending_aim = None
    bot._can_consume_ability = lambda s: False

    monkeypatch.setattr(main, "can_consume_ability", lambda s: False)

    bot._tick(_frame())

    assert consumed, "_tick 必須在 MINING 消費 _pending_clear_panel"
    assert bot._pending_clear_panel is False, "旗標必須被清掉"


def test_tick_does_not_consume_clear_panel_in_harvesting(monkeypatch):
    """HARVESTING 中不該清空（有視角記帳＋輸入序列）。"""
    consumed = []
    bot = make_fake_bot(
        bind=["_tick"],
        state=State.HARVESTING,
        _pending_clear_panel=True,
        _pending_ability=False,
        _pending_rotate=None,
        _consume_clear_panel=lambda: consumed.append(True),
        _update_reset_chime_active=lambda: None,
        _consume_web_pending=lambda: None,
        _consume_pending_rotate=lambda: None,
        _tick_harvest=lambda frame: None,
        _tick_mining=lambda frame: None,
        _tick_reentry=lambda frame: None,
        _pending_aim=None,
    )
    monkeypatch.setattr(main, "can_consume_ability", lambda s: False)

    bot._tick(_frame())

    assert not consumed, "HARVESTING 中不得消費 _pending_clear_panel"
    assert bot._pending_clear_panel is True, "旗標必須保留等回 MINING"


# ── 5. 網頁 control:clearpanel → _pending_clear_panel ──────────────────────

def test_web_clearpanel_control_sets_pending_flag(monkeypatch):
    """網頁 🧹 按鈕送 control:clearpanel → _consume_web_pending 設旗標。"""
    from miningbot.web_ipc import PendingReplies

    pr = PendingReplies()
    pr.push("control:clearpanel", {"cmd": "clearpanel"}, ttl_s=999)

    notes = []
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        state=State.MINING,
        _web_pending=pr,
        _mine_resetting=False,
        _manual_reentry=False,
        _paused=False,
        _pending_clear_panel=False,
        _pending_ability=False,
        _broadcast_status_note=lambda msg: notes.append(msg),
        _reentry_active=lambda: False,
        _rr_skip_on_pause_resume=lambda *a, **k: None,
        _pause=lambda: None,
        _resume=lambda: None,
        _apply_layer_change=lambda *a, **k: None,
        human_cleared=False,
    )
    bot._consume_web_pending()

    assert bot._pending_clear_panel is True, "control:clearpanel 必須設 _pending_clear_panel"
    assert any("清空" in n for n in notes), "必須透過 _broadcast_status_note 回報"


def test_web_clearpanel_rejected_in_harvesting(monkeypatch):
    """HARVESTING 中網頁清空被拒——同 Discord 指令守門。"""
    from miningbot.web_ipc import PendingReplies

    pr = PendingReplies()
    pr.push("control:clearpanel", {"cmd": "clearpanel"}, ttl_s=999)

    notes = []
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        state=State.HARVESTING,
        _web_pending=pr,
        _mine_resetting=False,
        _manual_reentry=False,
        _paused=False,
        _pending_clear_panel=False,
        _pending_ability=False,
        _broadcast_status_note=lambda msg: notes.append(msg),
        _reentry_active=lambda: False,
        _rr_skip_on_pause_resume=lambda *a, **k: None,
        _pause=lambda: None,
        _resume=lambda: None,
        _apply_layer_change=lambda *a, **k: None,
        human_cleared=False,
    )
    bot._consume_web_pending()

    assert bot._pending_clear_panel is False, "HARVESTING 中不得設旗標"
    assert any("清空未接受" in n for n in notes), "必須回報拒絕原因"


# ── 6. Discord 遙控器 🧹 反應鈕 ─────────────────────────────────────────────

def _reaction_msg(**counts):
    """假 Discord Message Object（dict，同 test_discord_responsiveness._reaction_message）。"""
    return {
        "reactions": [
            {"emoji": {"name": e}, "count": c} for e, c in counts.items()
        ]
    }


def _remote_bot(state=State.MINING):
    """遙控器輪詢用最小 Bot（比照 test_discord_responsiveness 的 _bare_remote_bot）。"""
    bot = Bot.__new__(Bot)
    bot._remote_message_id = "mid"
    bot._remote_reactions_seen = {
        "▶️": 1, "⏸️": 1, "⚡": 1, "📷": 1, "🏠": 1, "🧹": 1,
    }
    bot.state = state
    bot.paused = False
    bot.human_cleared = False
    bot._pending_ability = False
    bot._pending_clear_panel = False
    bot._manual_reentry = False
    bot._calib_session = None
    bot._reaction_clear_ok = True
    bot._reentry_active = lambda: False
    bot._repost_remote_control = lambda: None
    bot._resume = lambda: None
    bot._pause = lambda: None
    bot._rr_skip_on_pause_resume = lambda *a, **k: None
    import logging
    bot.log_discord = logging.getLogger("test")
    return bot


def test_remote_clear_reaction_queues_pending(monkeypatch):
    """遙控器 🧹＝手動清空：只寫旗標（主迴圈消費），MINING 中接受。"""
    from miningbot import notify
    bot = _remote_bot(state=State.MINING)
    sent = []
    monkeypatch.setattr(notify, "fetch_message",
                        lambda *_a: _reaction_msg(
                            **{"▶️": 1, "⏸️": 1, "⚡": 1, "📷": 1, "🏠": 1, "🧹": 2}))
    monkeypatch.setattr(notify, "send_message",
                        lambda *a, **k: sent.append(a[2]) or (True, "OK"))
    monkeypatch.setattr(notify, "remove_user_reactions",
                        lambda *a, **k: (True, "OK"))
    monkeypatch.setattr(main, "can_consume_ability", lambda s: False)
    monkeypatch.setattr(main, "is_blocked_from_mining", lambda *a: False)

    bot._poll_remote_reactions()

    assert bot._pending_clear_panel is True, "🧹 必須設 _pending_clear_panel"
    assert any("清空" in m and "排入" in m for m in sent), "必須回報排入訊息"


def test_remote_clear_reaction_rejected_in_harvesting(monkeypatch):
    """採集中 🧹 必須被拒絕（有輸入序列），旗標不可寫。"""
    from miningbot import notify
    bot = _remote_bot(state=State.HARVESTING)
    sent = []
    monkeypatch.setattr(notify, "fetch_message",
                        lambda *_a: _reaction_msg(
                            **{"▶️": 1, "⏸️": 1, "⚡": 1, "📷": 1, "🏠": 1, "🧹": 2}))
    monkeypatch.setattr(notify, "send_message",
                        lambda *a, **k: sent.append(a[2]) or (True, "OK"))
    monkeypatch.setattr(notify, "remove_user_reactions",
                        lambda *a, **k: (True, "OK"))
    monkeypatch.setattr(main, "can_consume_ability", lambda s: False)
    monkeypatch.setattr(main, "is_blocked_from_mining", lambda *a: False)

    bot._poll_remote_reactions()

    assert bot._pending_clear_panel is False, "HARVESTING 中 🧹 不得設旗標"
    assert any("未接受" in m for m in sent), "必須回報拒絕原因"
