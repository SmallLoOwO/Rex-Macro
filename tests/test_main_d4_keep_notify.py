"""D4 keep 清單事件的 Discord 一次性通知 + ⏭️ 跳過反應（2026-08-08）。

需求：D4 骰到已在 keep 清單的事件時通知玩家（只通知一次，同一顆事件持續被
D4 加強不重複發），訊息附說明骰到什麼；玩家可點 ⏭️ 對這次跳過（右鍵刷新一次），
不會把該事件從 keep 清單移除——下次骰到同一顆事件仍照樣保留。

純函式（plan_d4 keep/reroll/hold 分流）在 test_miner.py；本檔驗接線：
_notify_d4_keep／_poll_d4_keep_reaction 兩支新方法，以及 _handle_use_d4
何時呼叫通知、何時消費 ⏭️ pending flag。
"""
import logging

from miningbot import main
from tests.fake_bot import make_fake_bot

# game_data._AESTERIA_EVENTS 裡穩定存在的一筆：match="fluttering" -> ore="Mythical Hive"
_EVENT_TEXT = "fluttering"
_EVENT_ORE = "Mythical Hive"


class _Rec(logging.Logger):
    """收 log 字串，讓測試能斷言走了哪條分支。"""

    def __init__(self):
        super().__init__("tests.d4_keep_notify")
        self.lines = []

    def info(self, msg, *args, **kw):
        self.lines.append(msg % args if args else msg)

    warning = info


def _d4_bot(monkeypatch, *, keep=True, skip_pending=False, notified_ore=None,
            banner_text=_EVENT_TEXT, **attrs):
    monkeypatch.setattr(main.time, "time", lambda: 10_000.0)
    keep_ores = {_EVENT_ORE} if keep else set()
    keep_calls, reroll_calls = [], []
    monkeypatch.setattr(main.miner, "use_activity_keep",
                        lambda: keep_calls.append(True))
    monkeypatch.setattr(main.miner, "use_activity",
                        lambda: reroll_calls.append(True))
    notify_calls = []
    bot = make_fake_bot(
        bind=["_handle_use_d4"],
        _d4_unknown_at=0.0,
        _banner_text=banner_text,
        _banner_text_at=10_000.0,
        _last_activity=9_990.0,
        _mine_resetting=False,
        _keep_ores=keep_ores,
        stats={"rerolls": 0},
        last_action="",
        log_act=_Rec(),
        logger=_Rec(),
        log_discord=_Rec(),
        _d4_keep_notified_ore=notified_ore,
        _d4_keep_alert_mid=None,
        _d4_keep_seen={},
        _d4_skip_pending=skip_pending,
        _notify_d4_keep=lambda ev: notify_calls.append(ev["ore"]),
        **attrs)
    return bot, keep_calls, reroll_calls, notify_calls


def test_handle_use_d4_notifies_once_for_new_kept_event(monkeypatch):
    """第一次骰到 keep 清單事件 -> 加強 + 通知一次。"""
    bot, keep_calls, reroll_calls, notify_calls = _d4_bot(monkeypatch)
    bot._handle_use_d4(frame="fake_frame")
    assert keep_calls == [True]
    assert reroll_calls == []
    assert notify_calls == [_EVENT_ORE]
    assert bot._d4_keep_notified_ore == _EVENT_ORE
    assert bot.stats["rerolls"] == 1


def test_handle_use_d4_does_not_renotify_same_event(monkeypatch):
    """同一顆事件持續被加強（下一輪 D4 冷卻好又進來）只通知第一次。"""
    bot, keep_calls, reroll_calls, notify_calls = _d4_bot(
        monkeypatch, notified_ore=_EVENT_ORE)
    bot._handle_use_d4(frame="fake_frame")
    assert keep_calls == [True]
    assert notify_calls == [], "同一顆事件已通知過，不該再發"


def test_handle_use_d4_renotifies_after_event_changes_back(monkeypatch):
    """事件變過（notified_ore 被清）後同一顆 ore 再度出現要重新通知。"""
    bot, keep_calls, reroll_calls, notify_calls = _d4_bot(
        monkeypatch, notified_ore=None)  # 模擬已被非 keep 事件清空過
    bot._handle_use_d4(frame="fake_frame")
    assert notify_calls == [_EVENT_ORE]


def test_handle_use_d4_skip_pending_rerolls_instead_of_keep(monkeypatch):
    """玩家已按 ⏭️（_d4_skip_pending=True）-> 這次改右鍵刷新，不加強、不重通知。"""
    bot, keep_calls, reroll_calls, notify_calls = _d4_bot(
        monkeypatch, notified_ore=_EVENT_ORE, skip_pending=True)
    bot._handle_use_d4(frame="fake_frame")
    assert reroll_calls == [True]
    assert keep_calls == []
    assert notify_calls == []
    assert bot._d4_skip_pending is False, "一次性：消費後要歸位"
    assert bot._d4_keep_notified_ore is None, "事件即將改變，通知記帳歸零"
    assert bot._d4_keep_alert_mid is None


def test_handle_use_d4_non_keep_event_clears_notify_bookkeeping(monkeypatch):
    """事件不在 keep 清單（reroll 分支）要清掉通知記帳＋作廢殘留的 ⏭️ 意圖。"""
    bot, keep_calls, reroll_calls, notify_calls = _d4_bot(
        monkeypatch, keep=False, notified_ore="某上一顆不相干的事件",
        skip_pending=True)
    bot._handle_use_d4(frame="fake_frame")
    assert reroll_calls == [True]
    assert bot._d4_keep_notified_ore is None
    assert bot._d4_keep_alert_mid is None
    assert bot._d4_skip_pending is False, \
        "離開 keep 語境要作廢殘留 ⏭️ 意圖，避免晚點誤套到不相干的未來事件"


# ── _notify_d4_keep / _poll_d4_keep_reaction 接線（送訊息＋輪詢反應） ──────────

def test_notify_d4_keep_sends_message_and_arms_reaction(monkeypatch):
    sent = {}

    def fake_send(token, ch, content, timeout=10.0):
        sent["content"] = content
        return True, "HTTP 200", "msg789"

    def fake_add_reaction(token, ch, mid, emoji):
        sent["reaction"] = (mid, emoji)
        return True, "ok"

    monkeypatch.setattr(main.notify, "send_message_with_id", fake_send)
    monkeypatch.setattr(main.notify, "add_reaction", fake_add_reaction)
    bot = make_fake_bot(
        bind=["_notify_d4_keep"],
        log_discord=_Rec(),
        _d4_keep_alert_mid=None,
        _d4_keep_seen={})
    ev = {"ore": _EVENT_ORE, "duration_s": 26.6 * 60}
    bot._notify_d4_keep(ev)
    assert _EVENT_ORE in sent["content"]
    assert main._D4_SKIP_EMOJI in sent["content"]
    assert sent["reaction"] == ("msg789", main._D4_SKIP_EMOJI)
    assert bot._d4_keep_alert_mid == "msg789"
    assert bot._d4_keep_seen == {main._D4_SKIP_EMOJI: 1}


def test_poll_d4_keep_reaction_sets_skip_pending_and_invalidates_mid(monkeypatch):
    def fake_fetch(token, ch, mid, timeout=10.0):
        return {"reactions": [{"emoji": {"name": main._D4_SKIP_EMOJI}, "count": 2}]}

    monkeypatch.setattr(main.notify, "fetch_message", fake_fetch)
    bot = make_fake_bot(
        bind=["_poll_d4_keep_reaction"],
        log_discord=_Rec(),
        _d4_keep_alert_mid="msg789",
        _d4_keep_seen={main._D4_SKIP_EMOJI: 1},
        _d4_skip_pending=False)
    bot._poll_d4_keep_reaction()
    assert bot._d4_skip_pending is True
    assert bot._d4_keep_alert_mid is None, "一次性：觸發後 mid 作廢"


def test_poll_d4_keep_reaction_noop_without_mid(monkeypatch):
    """沒有活躍通知（mid=None）時輪詢是 no-op——呼叫端本該先擋（見 _poll_discord）。"""
    monkeypatch.setattr(main.notify, "fetch_message",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("不該打 API")))
    bot = make_fake_bot(
        bind=["_poll_d4_keep_reaction"],
        log_discord=_Rec(),
        _d4_keep_alert_mid=None,
        _d4_keep_seen={},
        _d4_skip_pending=False)
    bot._poll_d4_keep_reaction()
    assert bot._d4_skip_pending is False
