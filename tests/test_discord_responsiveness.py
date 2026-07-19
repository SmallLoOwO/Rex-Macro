import os

from miningbot import notify, reentry_remote
from miningbot.config import Config
from miningbot.main import Bot
from miningbot.states import State


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)


def _reaction_message(**counts):
    return {
        "reactions": [
            {"emoji": {"name": emoji}, "count": count}
            for emoji, count in counts.items()
        ]
    }


def _bare_reentry_bot():
    bot = Bot.__new__(Bot)
    bot.state = State.REENTRY
    bot._rr_embed_mid = "rr-message"
    bot._rr_reactions_seen = {emoji: 1 for emoji in reentry_remote.REENTRY_REACTIONS}
    bot._rr_busy = False
    bot._pending_reentry = None
    bot.log_discord = _LogRecorder()
    return bot


def test_reaction_increments_rearm_after_remove_and_readd():
    """單次訊息摘要要能辨識新增反應，取消後再點也必須重新觸發。"""
    previous = {"📷": 1}

    current, increments = notify.find_reaction_increments(
        _reaction_message(**{"📷": 2}), previous, ("📷",))
    assert current == {"📷": 2}
    assert increments == [("📷", 1)]

    current, increments = notify.find_reaction_increments(
        _reaction_message(**{"📷": 1}), current, ("📷",))
    assert current == {"📷": 1}
    assert increments == []

    current, increments = notify.find_reaction_increments(
        _reaction_message(**{"📷": 2}), current, ("📷",))
    assert current == {"📷": 2}
    assert increments == [("📷", 1)]


def test_reaction_summary_omission_keeps_positive_baseline():
    """Discord 暫時省略 reactions 欄時不可清成 0，否則 bot 自己的反應重現會假觸發。"""
    current, increments = notify.find_reaction_increments(
        {"reactions": []}, {"📷": 1}, ("📷",))

    assert current == {"📷": 1}
    assert increments == []


def test_rr_reaction_uses_one_message_fetch_and_sends_immediate_ack(monkeypatch):
    """H044：📷 被偵測後要立刻確認，不可等八方位掃描完成才第一次回覆。"""
    bot = _bare_reentry_bot()
    fetches = []
    sent = []

    def fake_fetch_message(token, channel_id, message_id):
        fetches.append((token, channel_id, message_id))
        return _reaction_message(**{"🎲": 1, "⏭️": 1, "📷": 2})

    monkeypatch.setattr(notify, "fetch_message", fake_fetch_message)
    monkeypatch.setattr(
        notify, "get_reactions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("反應輪詢不應再逐 emoji 發 GET")))
    monkeypatch.setattr(
        notify, "send_message",
        lambda token, channel_id, content: sent.append(content) or (True, "HTTP 200"))
    monkeypatch.setattr("miningbot.main.cfg.discord_bot_token", "token")
    monkeypatch.setattr("miningbot.main.cfg.discord_channel_id", "channel")

    bot._poll_rr_reactions()

    assert fetches == [("token", "channel", "rr-message")]
    assert bot._pending_reentry is not None
    raw, reply = bot._pending_reentry
    assert raw == "reaction:📷"
    assert reply.kind == "sweep"
    assert len(sent) == 1
    assert "收到" in sent[0] and "重新掃描" in sent[0] and "執行中" in sent[0]


def test_text_reentry_reply_shares_immediate_ack(monkeypatch):
    bot = _bare_reentry_bot()
    sent = []
    monkeypatch.setattr(
        notify, "send_message",
        lambda token, channel_id, content: sent.append(content) or (True, "HTTP 200"))
    monkeypatch.setattr("miningbot.main.cfg.discord_bot_token", "token")
    monkeypatch.setattr("miningbot.main.cfg.discord_channel_id", "channel")

    bot._handle_reentry_reply("掃")

    assert bot._pending_reentry[0] == "掃"
    assert bot._pending_reentry[1].kind == "sweep"
    assert len(sent) == 1 and "重新掃描" in sent[0]


def test_remote_control_reactions_use_one_message_fetch(monkeypatch):
    bot = Bot.__new__(Bot)
    bot._remote_message_id = "remote-message"
    bot._remote_reactions_seen = {"▶️": 1, "⏸️": 1, "⚡": 1}
    bot.state = State.MINING
    bot.paused = False
    bot.human_cleared = False
    bot._pending_ability = False
    bot._calib_session = None
    bot.log_discord = _LogRecorder()
    reposted = []

    monkeypatch.setattr(
        notify, "fetch_message",
        lambda *_args: _reaction_message(**{"▶️": 1, "⏸️": 2, "⚡": 1}))
    monkeypatch.setattr(
        notify, "get_reactions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("遙控器不應再逐 emoji 發 GET")))
    bot._pause = lambda: setattr(bot, "paused", True)
    bot._repost_remote_control = lambda: reposted.append(True)

    bot._poll_remote_reactions()

    assert bot.paused is True
    assert reposted == [True]


def _bare_remote_bot(state=State.MINING):
    """遙控器輪詢用最小 Bot（比照 test_remote_control_reactions_use_one_message_fetch）。"""
    bot = Bot.__new__(Bot)
    bot._remote_message_id = "remote-message"
    bot._remote_reactions_seen = {"▶️": 1, "⏸️": 1, "⚡": 1, "📷": 1, "🏠": 1}
    bot.state = state
    bot.paused = False
    bot.human_cleared = False
    bot._pending_ability = False
    bot._manual_reentry = False
    bot._calib_session = None
    bot.log_discord = _LogRecorder()
    return bot


def test_remote_control_home_reaction_queues_manual_reentry(monkeypatch):
    """遙控器 🏠＝手動回礦：只寫旗標（主迴圈消費），守門走 can_accept_manual_reentry。"""
    bot = _bare_remote_bot()
    sent, reposted = [], []
    monkeypatch.setattr(
        notify, "fetch_message",
        lambda *_args: _reaction_message(**{"▶️": 1, "⏸️": 1, "⚡": 1, "📷": 1, "🏠": 2}))
    monkeypatch.setattr(
        notify, "send_message",
        lambda token, channel_id, content: sent.append(content) or (True, "HTTP 200"))
    monkeypatch.setattr("miningbot.main.cfg.discord_bot_token", "token")
    monkeypatch.setattr("miningbot.main.cfg.discord_channel_id", "channel")
    bot._reentry_active = lambda: True
    bot._repost_remote_control = lambda: reposted.append(True)

    bot._poll_remote_reactions()

    assert bot._manual_reentry is True
    assert reposted == [True]
    assert any("回礦已排入" in m for m in sent)


def test_remote_control_home_reaction_rejected_in_harvesting(monkeypatch):
    """採集中 🏠 必須被守門拒絕（插回礦會亂時序），旗標不可寫。"""
    bot = _bare_remote_bot(state=State.HARVESTING)
    sent, reposted = [], []
    monkeypatch.setattr(
        notify, "fetch_message",
        lambda *_args: _reaction_message(**{"▶️": 1, "⏸️": 1, "⚡": 1, "📷": 1, "🏠": 2}))
    monkeypatch.setattr(
        notify, "send_message",
        lambda token, channel_id, content: sent.append(content) or (True, "HTTP 200"))
    monkeypatch.setattr("miningbot.main.cfg.discord_bot_token", "token")
    monkeypatch.setattr("miningbot.main.cfg.discord_channel_id", "channel")
    bot._reentry_active = lambda: True
    bot._repost_remote_control = lambda: reposted.append(True)

    bot._poll_remote_reactions()

    assert bot._manual_reentry is False
    assert any("未接受" in m for m in sent)


def test_remote_control_snap_reaction_sends_screenshot(monkeypatch):
    """遙控器 📷＝即時截圖：唯讀觀測可在輪詢執行緒直接抓（不碰遊戲輸入）。

    R 取樣視窗退役（2026-07-17）後 📷 落「編號樣本」（sampler.save_sample）——
    calibrate_surface --import NNN 的素材來源就是這裡。
    """
    bot = _bare_remote_bot()
    bot._pitch_offset_px = 400
    sent, reposted, saved = [], [], []
    monkeypatch.setattr("miningbot.main.capture.grab", lambda: "FRAME")
    monkeypatch.setattr(
        "miningbot.main.sampler.save_sample",
        lambda frame, out_dir, pitch: saved.append((frame, out_dir, pitch)) or "012")
    monkeypatch.setattr("miningbot.main.cfg.manual_snapshot_dir", "snap")
    monkeypatch.setattr(
        notify, "send_images_message",
        lambda token, channel_id, content, paths: sent.append((content, paths)) or (True, "HTTP 200"))
    monkeypatch.setattr(
        notify, "fetch_message",
        lambda *_args: _reaction_message(**{"▶️": 1, "⏸️": 1, "⚡": 1, "📷": 2, "🏠": 1}))
    monkeypatch.setattr("miningbot.main.cfg.discord_bot_token", "token")
    monkeypatch.setattr("miningbot.main.cfg.discord_channel_id", "channel")
    bot._repost_remote_control = lambda: reposted.append(True)

    bot._poll_remote_reactions()

    assert saved == [("FRAME", "snap", 400)]
    assert sent and sent[0][1] == [os.path.join("snap", "012.png")]
    assert "#012" in sent[0][0]
    assert reposted == [True]


# ===== 2026-07-19：REENTRY 中遙控器凍結釘底、換回礦卡接手＝釘底 =====
def _poll_bot(monkeypatch, state):
    bot = Bot.__new__(Bot)
    bot.state = state
    bot.paused = False
    bot._rr_embed_mid = None
    bot._rr_ctx = None
    bot._rr_busy = False
    bot._stuck_alert_mid = None
    bot._calib_session = None
    bot._list_message_id = None
    bot._remote_message_id = "remote-message"
    bot._remote_last_shown = (True, "stale")     # 與現況不符 → 必觸發單次 PATCH
    bot._last_discord_msg_id = "old"
    bot.log_discord = _LogRecorder()
    bot._poll_remote_reactions = lambda: None
    bot._poll_rr_reactions = lambda: None
    calls = {"edit": 0, "repost": 0, "rr_repost": 0}
    bot._edit_remote_control = lambda: calls.__setitem__("edit", calls["edit"] + 1)
    bot._repost_remote_control = lambda: calls.__setitem__("repost", calls["repost"] + 1)
    bot._rr_repost_embed = lambda: calls.__setitem__("rr_repost", calls["rr_repost"] + 1)
    monkeypatch.setattr(
        notify, "fetch_messages",
        lambda *a, **kw: [{"id": "newest", "author": {"bot": True}, "content": ""}])
    monkeypatch.setattr("miningbot.main.cfg.discord_bot_token", "token")
    monkeypatch.setattr("miningbot.main.cfg.discord_channel_id", "channel")
    return bot, calls


def test_remote_control_repost_frozen_during_reentry(monkeypatch):
    """回礦中：狀態 PATCH 只發一次（換成指引卡），釘底重貼凍結（發圖每輪重貼＝洗版）。"""
    bot, calls = _poll_bot(monkeypatch, State.REENTRY)
    bot._poll_discord()
    assert calls["edit"] == 1                    # (paused, state) 變化＝進 REENTRY 的單次 PATCH
    assert calls["repost"] == 0


def test_remote_control_syncs_outside_reentry(monkeypatch):
    """離開 REENTRY 後第一輪輪詢自動補上：狀態 PATCH＋被新訊息擠上去就重貼回頻道底。"""
    bot, calls = _poll_bot(monkeypatch, State.MINING)
    bot._poll_discord()
    assert calls == {"edit": 1, "repost": 1, "rr_repost": 0}


def test_rr_embed_takes_over_pinning_during_reentry(monkeypatch):
    """回礦卡接手釘底（2026-07-19 使用者反映卡片被照片埋住）：被擠上去就刪舊貼新。"""
    bot, calls = _poll_bot(monkeypatch, State.REENTRY)
    bot._rr_embed_mid = "rr-card"
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=2, created_at=0.0, sticky_layer="L")
    bot._poll_discord()
    assert calls["rr_repost"] == 1
    assert calls["repost"] == 0


def test_rr_embed_pinning_waits_out_busy_execution(monkeypatch):
    """_rr_busy（開場/八方位發圖中）不搬卡，掃完下一輪一次到位（避免發圖途中彈跳）。"""
    bot, calls = _poll_bot(monkeypatch, State.REENTRY)
    bot._rr_embed_mid = "rr-card"
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=2, created_at=0.0, sticky_layer="L")
    bot._rr_busy = True
    bot._poll_discord()
    assert calls["rr_repost"] == 0


def test_remote_embed_shows_reentry_guidance():
    """進 REENTRY 的單次 PATCH 內容＝指引卡：指向回礦卡、說明 ▶️/⏸️＝跳過。"""
    bot = Bot.__new__(Bot)
    bot.state = State.REENTRY
    embed = bot._build_remote_embed()
    assert "回礦卡" in embed["description"]
    assert "跳過" in embed["description"]


def test_rr_execute_reroll_warns_every_n_attempts(monkeypatch):
    """重骰無上限不變；attempt 達 N 倍數時提醒可跳過/調視角（2026-07-19）。"""
    bot = _skipish_bot()
    bot._rr_ctx.attempt = 5
    sent = []
    bot._rr_open_episode = lambda reroll: None
    bot._rr_notify = lambda msg, **kw: sent.append(msg)
    monkeypatch.setattr("miningbot.main.cfg.reentry_attempt_warn_every", 5)
    bot._rr_execute(reentry_remote.RemoteReply("reroll"))
    assert any("已重骰 5 次" in m for m in sent)

    bot._rr_ctx.attempt = 6                      # 非倍數不提醒
    sent.clear()
    bot._rr_execute(reentry_remote.RemoteReply("reroll"))
    assert sent == []


def test_discord_poll_default_targets_one_second_response_window():
    assert Config().discord_poll_interval_s <= 1.0


# ===== 2026-07-18：跳過改直接回挖礦＋暫停/繼續中途視同跳過 =====
def _skipish_bot():
    bot = Bot.__new__(Bot)
    bot.log_discord = _LogRecorder()
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=5, created_at=0.0, sticky_layer="Mantle Layer")
    bot._pending_reentry = None
    return bot


def test_rr_execute_skip_returns_to_mining():
    # 遠端已是人工，`跳過` 不再交 NEEDS_HUMAN——finalize 後直接回 MINING
    bot = _skipish_bot()
    outcomes, sent = [], []
    bot._rr_finalize = lambda outcome: outcomes.append(outcome)
    bot._rr_notify = lambda msg, **kw: sent.append(msg)
    bot._reentry_done = False
    bot._reentry_failed = False
    bot._rr_execute(reentry_remote.RemoteReply("skip"))
    assert outcomes == ["skip"]
    assert bot._reentry_done is True
    assert bot._reentry_failed is False          # 不再走 NEEDS_HUMAN
    assert sent and "回正常挖礦" in sent[0]


def test_pause_resume_mid_reentry_queues_skip():
    # 暫停/繼續指令在 episode 進行中＝視同跳過（主迴圈消費後回正常挖礦）
    bot = _skipish_bot()
    bot._rr_skip_on_pause_resume("pause")
    assert bot._pending_reentry is not None
    assert bot._pending_reentry[1].kind == "skip"


def test_pause_resume_without_episode_is_noop():
    bot = Bot.__new__(Bot)
    bot.log_discord = _LogRecorder()
    bot._rr_ctx = None
    bot._pending_reentry = None
    bot._rr_skip_on_pause_resume("resume")
    assert bot._pending_reentry is None


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
