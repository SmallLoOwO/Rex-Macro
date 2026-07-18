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
