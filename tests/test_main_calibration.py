from miningbot import main, calibrate_pitch
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


def _calib_bot(monkeypatch, paused=False):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot.log_discord = _LogRecorder()
    bot.paused = paused
    bot._calib_session = None
    bot._pending_calib_start = None
    bot._pending_calib_action = None
    bot._pending_calib_px = 0
    bot._pitch_offset_px = 0
    bot._pause = lambda: setattr(bot, "paused", True)
    bot._sampler_pitch_prepare = lambda: None
    bot._post_calib_embed = lambda warn="": None
    bot._calib_snapshot = lambda: None
    monkeypatch.setattr(main.cfg, "sweep_pitch_center_back_px", 300)
    monkeypatch.setattr(main.cfg, "sweep_pitch_clamp_px", 1500)
    monkeypatch.setattr(main.cfg, "reentry_pitch_back_px", 400)
    monkeypatch.setattr(main.cfg, "reentry_pitch_clamp_px", 1500)
    return bot


def test_calib_start_records_prev_paused_then_pauses(monkeypatch):
    bot = _calib_bot(monkeypatch, paused=False)
    resets = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: resets.append((down, back)))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._calib_start("mining")
    sess = bot._calib_session
    assert sess.prev_paused is False          # 在 _pause() 之前捕捉
    assert bot.paused is True                 # 進場即強制暫停
    assert sess.target == "mining"
    assert sess.offset == 300                 # 從 config 現值起算（不歸零）
    assert resets == [(1500, 300)]
    assert bot._pitch_offset_px == 300


def test_calib_start_from_reentry_target_uses_reentry_fields(monkeypatch):
    bot = _calib_bot(monkeypatch, paused=True)
    resets = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: resets.append((down, back)))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._calib_start("reentry")
    assert bot._calib_session.prev_paused is True
    assert bot._calib_session.offset == 400
    assert resets == [(1500, 400)]


def test_calib_exit_restores_prev_paused_and_reports_unsaved(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch, paused=True)
    sent = []
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    monkeypatch.setattr(notify_mod, "delete_message",
                        lambda token, ch, mid, **kw: (True, "ok"))
    resumed = []
    bot._resume = lambda: resumed.append(1)
    sess = calibrate_pitch.CalibSession(target="mining", offset=435,
                                        prev_paused=False, message_id="m1")
    bot._calib_session = sess
    bot._calib_exit(sess)
    assert bot._calib_session is None
    assert resumed == [1]                     # 原本沒暫停 → 離場恢復挖礦
    assert any("未存檔" in m and "435" in m for m in sent)   # offset≠config 現值(300)


def test_calib_exit_stays_paused_when_prev_paused(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch, paused=True)
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: (True, "ok"))
    resumed = []
    bot._resume = lambda: resumed.append(1)
    sess = calibrate_pitch.CalibSession(target="mining", offset=300,
                                        prev_paused=True, message_id=None)
    bot._calib_session = sess
    bot._calib_exit(sess)
    assert resumed == []                      # 原本就暫停 → 維持暫停


def test_resume_guarded_during_calibration(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._calib_session = calibrate_pitch.CalibSession(target="mining", offset=0)
    bot._resume()                             # 不炸、不動 paused（守門直接 return）
    assert any("校準中" in r for r in bot.logger.records)


_CFG_TEXT = (
    "    sweep_pitch_clamp_px: int = 1500            # 飽和拖曳量\n"
    "    sweep_pitch_center_back_px: int = 0         # 0=未校準＝停用\n"
)


def _save_bot(monkeypatch, tmp_path, sent):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    p = tmp_path / "config.py"
    p.write_text(_CFG_TEXT, encoding="utf-8")
    return bot, p


def test_calib_save_writes_file_and_syncs_cfg(monkeypatch, tmp_path):
    sent = []
    bot, p = _save_bot(monkeypatch, tmp_path, sent)
    sess = calibrate_pitch.CalibSession(target="mining", offset=435)
    assert bot._calib_save(sess, path=str(p)) is True
    assert "sweep_pitch_center_back_px: int = 435" in p.read_text(encoding="utf-8")
    assert main.cfg.sweep_pitch_center_back_px == 435   # 記憶體同步：本次執行立即生效
    assert any("300 → 435" in m for m in sent)   # 舊值＝記憶體 cfg 現值（_calib_bot 設 300），非檔案裡的 0


def test_calib_save_missing_anchor_keeps_cfg_untouched(monkeypatch, tmp_path):
    sent = []
    bot, p = _save_bot(monkeypatch, tmp_path, sent)
    p.write_text("nothing here\n", encoding="utf-8")
    sess = calibrate_pitch.CalibSession(target="mining", offset=435)
    assert bot._calib_save(sess, path=str(p)) is False
    assert main.cfg.sweep_pitch_center_back_px == 300   # 檔案與記憶體不分岔：cfg 不動
    assert p.read_text(encoding="utf-8") == "nothing here\n"
    assert any("435" in m and "手抄" in m for m in sent)


def test_calib_save_oserror_reports_value(monkeypatch, tmp_path):
    sent = []
    bot, _ = _save_bot(monkeypatch, tmp_path, sent)
    sess = calibrate_pitch.CalibSession(target="mining", offset=435)
    assert bot._calib_save(sess, path=str(tmp_path / "no_dir" / "x.py")) is False
    assert main.cfg.sweep_pitch_center_back_px == 300
    assert any("手抄" in m for m in sent)


def _tick_bot(monkeypatch):
    bot = _calib_bot(monkeypatch)
    bot.paused = True
    bot._calib_session = calibrate_pitch.CalibSession(
        target="mining", offset=300, message_id="m1")
    bot._repost_calib_embed = lambda warn="": bot._reposts.append(warn)
    bot._reposts = []
    bot._snaps = []
    bot._calib_snapshot = lambda: bot._snaps.append(1)
    return bot


def test_tick_calibration_up_down_accounting(monkeypatch):
    bot = _tick_bot(monkeypatch)
    nudges = []
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: nudges.append(dy))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._pending_calib_action = "up"
    bot._tick_calibration()
    assert nudges == [-5]                     # 上＝dy<0（沿用取樣視窗語意）；初始幅度 5
    assert bot._calib_session.offset == 305
    assert bot._pitch_offset_px == 305
    assert bot._snaps == [1]                  # 調完自動截圖
    bot._pending_calib_action = "down"
    bot._tick_calibration()
    assert nudges == [-5, 5]
    assert bot._calib_session.offset == 300


def test_tick_calibration_down_saturates_at_zero(monkeypatch):
    bot = _tick_bot(monkeypatch)
    bot._calib_session.offset = 3
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: None)
    bot._pitch_drag_verified = lambda label, drag: True
    bot._pending_calib_action = "down"
    bot._tick_calibration()
    assert bot._calib_session.offset == 0     # 夾限飽和記帳夾 0（apply_calib_step 語意）


def test_tick_calibration_step_cycles_without_game_input(monkeypatch):
    bot = _tick_bot(monkeypatch)
    called = []
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: called.append(dy))
    monkeypatch.setattr(main.ic, "pitch_reset", lambda d, b: called.append((d, b)))
    bot._pending_calib_action = "step"
    bot._tick_calibration()
    assert bot._calib_session.step == 10      # 5 → 10
    assert called == []                       # 🔁 不碰遊戲
    assert bot._snaps == []                   # 也不截圖


def test_tick_calibration_home_resets_offset(monkeypatch):
    bot = _tick_bot(monkeypatch)
    resets = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: resets.append((down, back)))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._pending_calib_action = "home"
    bot._tick_calibration()
    assert resets == [(1500, 0)]              # 歸位到夾限（絕對重定位）
    assert bot._calib_session.offset == 0
    assert bot._pitch_offset_px == 0


def test_tick_calibration_eaten_warns_but_accounts(monkeypatch):
    bot = _tick_bot(monkeypatch)
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: None)
    bot._pitch_drag_verified = lambda label, drag: False   # 被吃
    bot._pending_calib_action = "up"
    bot._tick_calibration()
    assert bot._calib_session.offset == 305   # 記帳照調（比照 仰角 慣例）
    assert any("被吃" in w for w in bot._reposts)


def test_tick_calibration_noop_without_pending(monkeypatch):
    bot = _tick_bot(monkeypatch)
    bot._pending_calib_action = None
    bot._tick_calibration()                   # 不炸、不動任何東西
    assert bot._calib_session.offset == 300


def test_poll_calib_reactions_only_sets_pending(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    bot._calib_session = calibrate_pitch.CalibSession(
        target="mining", offset=300, message_id="m1",
        reactions_seen={e: 1 for e in calibrate_pitch.CALIB_EMOJIS})
    monkeypatch.setattr(notify_mod, "fetch_message",
                        lambda token, ch, mid, **kw: {"reactions": [
                            {"emoji": {"name": "⬆️"}, "count": 2}]})
    bot._poll_calib_reactions()
    assert bot._pending_calib_action == "up"
    # pending 佔用中不覆蓋（一次一動作）
    monkeypatch.setattr(notify_mod, "fetch_message",
                        lambda token, ch, mid, **kw: {"reactions": [
                            {"emoji": {"name": "❌"}, "count": 2}]})
    bot._poll_calib_reactions()
    assert bot._pending_calib_action == "up"


from miningbot import discord_commands
from miningbot.states import State


def _guard_bot(monkeypatch, sent):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    bot.state = State.MINING
    bot._calib_session = calibrate_pitch.CalibSession(
        target="mining", offset=300, prev_paused=False)
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    monkeypatch.setattr(main.cfg, "discord_bot_token", "t")
    monkeypatch.setattr(main.cfg, "discord_channel_id", "c")
    return bot


def test_pause_resume_during_calib_records_intent_only(monkeypatch):
    sent = []
    bot = _guard_bot(monkeypatch, sent)
    bot._handle_discord_command(discord_commands.DiscordCommand("pause", ()))
    assert bot._calib_session.prev_paused is True     # 只記離場後意圖
    assert bot._calib_session is not None             # 不解除校準
    bot._handle_discord_command(discord_commands.DiscordCommand("resume", ()))
    assert bot._calib_session.prev_paused is False
    assert all("校準中" in m for m in sent)


def test_game_input_commands_rejected_during_calib(monkeypatch):
    sent = []
    bot = _guard_bot(monkeypatch, sent)
    bot._handle_discord_command(discord_commands.DiscordCommand("回礦", ()))
    bot._handle_discord_command(discord_commands.DiscordCommand("ability", ()))
    assert len(sent) == 2 and all("校準中" in m for m in sent)
    assert getattr(bot, "_manual_reentry", False) is False


def test_calib_start_invalidates_stuck_alert(monkeypatch):
    bot = _calib_bot(monkeypatch, paused=False)
    bot._stuck_alert_mid = "stuck1"
    resets = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: resets.append((down, back)))
    bot._pitch_drag_verified = lambda label, drag: True
    bot._calib_start("mining")
    assert bot._stuck_alert_mid is None       # 進校準＝STUCK 🏠 作廢（繞過守門的路堵死）


def test_poll_stuck_reaction_guarded_during_calib(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    bot._calib_session = calibrate_pitch.CalibSession(target="mining", offset=300)
    bot._stuck_alert_mid = "stuck1"
    fetched = []
    monkeypatch.setattr(notify_mod, "fetch_message",
                        lambda *a, **kw: fetched.append(1) or None)
    bot._poll_stuck_reaction()
    assert fetched == []                      # 校準中完全不碰 STUCK 卡（守門在最前）


def test_consume_calib_start_revalidates_reentry(monkeypatch):
    import miningbot.notify as notify_mod
    from miningbot.states import State
    sent = []
    bot = _calib_bot(monkeypatch)
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    monkeypatch.setattr(main.cfg, "discord_bot_token", "t")
    monkeypatch.setattr(main.cfg, "discord_channel_id", "c")
    started = []
    bot._calib_start = lambda target: started.append(target)
    bot.state = State.REENTRY
    bot._pending_calib_start = "mining"
    bot._consume_calib_start()
    assert started == []                      # 消費點重驗：REENTRY 中不進場
    assert bot._pending_calib_start is None
    assert any("校準取消" in m for m in sent)
    bot.state = State.MINING
    bot._pending_calib_start = "reentry"
    bot._consume_calib_start()
    assert started == ["reentry"]


def test_ensure_no_stale_calib_deletes_all(monkeypatch):
    import miningbot.notify as notify_mod
    bot = _calib_bot(monkeypatch)
    monkeypatch.setattr(main.cfg, "discord_bot_token", "t")
    monkeypatch.setattr(main.cfg, "discord_channel_id", "c")
    msgs = [
        {"id": "1", "author": {"bot": True},
         "embeds": [{"title": calibrate_pitch.CALIB_TITLE}]},
        {"id": "2", "author": {"bot": True},
         "embeds": [{"title": calibrate_pitch.CALIB_TITLE}]},
        {"id": "3", "author": {"bot": True}, "embeds": [{"title": "別的卡"}]},
    ]
    monkeypatch.setattr(notify_mod, "fetch_messages",
                        lambda token, ch, **kw: msgs)
    deleted = []
    monkeypatch.setattr(notify_mod, "delete_message",
                        lambda token, ch, mid, **kw: deleted.append(mid) or (True, "ok"))
    bot._ensure_no_stale_calib()
    assert sorted(deleted) == ["1", "2"]      # 殘留卡全刪不認領（session 不跨重啟）


# ---- 校準卡文字指令 wiring（2026-07-19：文字與反應等價；px 可覆寫幅度）----
def test_tick_calibration_text_px_overrides_step(monkeypatch):
    bot = _tick_bot(monkeypatch)
    nudges = []
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: nudges.append(dy))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    bot._pending_calib_action = "up"
    bot._pending_calib_px = 12                # 文字 `上 12`：像素覆寫現行幅度 5
    bot._tick_calibration()
    assert nudges == [-12]
    assert bot._calib_session.offset == 312
    assert bot._pending_calib_px == 0         # 消費後清零（反應路徑不受污染）


def test_handle_calib_text_sets_pending(monkeypatch):
    sent = []
    bot = _guard_bot(monkeypatch, sent)
    bot._handle_calib_text("上 10")
    assert (bot._pending_calib_action, bot._pending_calib_px) == ("up", 10)
    assert sent == []                         # 正常入列不回嘴（動作後會重貼卡）


def test_handle_calib_text_busy_replies_wait(monkeypatch):
    sent = []
    bot = _guard_bot(monkeypatch, sent)
    bot._pending_calib_action = "up"
    bot._handle_calib_text("下 5")
    assert bot._pending_calib_action == "up"  # 不覆蓋（一次一動作，與反應輪詢同語意）
    assert any("稍候" in m for m in sent)


def test_handle_calib_text_ignores_chatter(monkeypatch):
    sent = []
    bot = _guard_bot(monkeypatch, sent)
    bot._handle_calib_text("今天狀況如何")
    assert bot._pending_calib_action is None
    assert sent == []


# ---- 挖礦中俯仰指令回指引不靜默（2026-07-19 使用者反映打了沒反應）----
def test_pitch_guidance_outside_reentry_and_calib(monkeypatch):
    import miningbot.notify as notify_mod
    sent = []
    bot = _calib_bot(monkeypatch)
    bot.state = State.MINING
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    monkeypatch.setattr(main.cfg, "discord_bot_token", "t")
    monkeypatch.setattr(main.cfg, "discord_channel_id", "c")
    bot._maybe_pitch_guidance("仰角 上 20")
    bot._maybe_pitch_guidance("上 20")
    assert len(sent) == 2 and all("校準" in m for m in sent)
    sent.clear()
    bot._maybe_pitch_guidance("B3")           # 非俯仰指令不回（避免誤嘴一般聊天）
    bot._maybe_pitch_guidance("今天狀況如何")
    assert sent == []
