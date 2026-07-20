"""Discord `轉` 指令（2026-07-21）：遠端手動轉 45°，供使用者自行校正斜向面向。

背景：回礦每輪 attempt 都按「回到地表」換重生點＝遊戲隨機化 yaw，落地後約一半
機率是對角（H059）。自動視覺判定經六種特徵量測皆無法兩側夾（見
docs/superpowers/specs/2026-07-21-reentry-yaw-investigation-findings.md），
使用者裁決改為手動校正——本指令即該人工介面。
"""

from miningbot import discord_commands, main
from miningbot.main import Bot
from miningbot.states import State, can_consume_rotate
import miningbot.notify as notify_mod


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


# ===== 純函式 =====
def test_rotate_is_a_known_command():
    assert discord_commands.parse_command("轉").name == "轉"
    assert discord_commands.parse_command("rotate").name == "rotate"
    assert discord_commands.parse_command("轉 左").args == ("左",)


def test_parse_rotate_direction():
    """無參數＝右轉（使用者要求的預設：點一下 `.`）。"""
    p = discord_commands.parse_rotate_direction
    assert p(()) == 1
    assert p(("右",)) == 1 and p(("right",)) == 1 and p(("r",)) == 1
    assert p(("左",)) == -1 and p(("left",)) == -1 and p(("l",)) == -1
    assert p(("亂打",)) is None            # 看不懂寧可不轉
    assert p(("左", "右")) is None


def test_can_consume_rotate_blocks_bookkeeping_states():
    """HARVESTING/REENTRY 有 net_rotations／ctx.cur_dir 記帳，中途插 45° 會讓記帳與
    實際角度脫節（H048/H052 家族）——一律不轉。"""
    assert can_consume_rotate(State.MINING) is True
    assert can_consume_rotate(State.NEEDS_HUMAN) is True
    assert can_consume_rotate(State.RESET_WAIT) is True
    assert can_consume_rotate(State.HARVESTING) is False
    assert can_consume_rotate(State.REENTRY) is False


# ===== 指令接收（Discord 輪詢執行緒；只寫旗標，絕不碰 input_control）=====
def _bot(monkeypatch, sent, state=State.MINING):
    bot = Bot.__new__(Bot)
    bot.state = state
    bot.paused = False
    bot._calib_session = None
    bot._pending_rotate = 0
    bot.log_discord = _LogRecorder()
    bot.logger = _LogRecorder()
    monkeypatch.setattr(notify_mod, "send_message",
                        lambda token, ch, msg, **kw: sent.append(msg) or (True, "ok"))
    monkeypatch.setattr(main.cfg, "discord_bot_token", "t")
    monkeypatch.setattr(main.cfg, "discord_channel_id", "c")
    return bot


def test_rotate_accepted_in_mining_sets_flag_only(monkeypatch):
    sent = []
    bot = _bot(monkeypatch, sent)
    bot._handle_discord_command(discord_commands.DiscordCommand("轉", ()))
    assert bot._pending_rotate == 1
    assert any("轉" in m for m in sent)


def test_rotate_left_sets_negative_flag(monkeypatch):
    sent = []
    bot = _bot(monkeypatch, sent)
    bot._handle_discord_command(discord_commands.DiscordCommand("轉", ("左",)))
    assert bot._pending_rotate == -1


def test_rotate_rejected_during_harvesting(monkeypatch):
    """不排隊：使用者是看著畫面手動校正，延遲數分鐘才轉比不轉更糟
    （比照 can_accept_manual_reentry 的「不排隊，避免舊指令補刀」）。"""
    sent = []
    bot = _bot(monkeypatch, sent, state=State.HARVESTING)
    bot._handle_discord_command(discord_commands.DiscordCommand("轉", ()))
    assert bot._pending_rotate == 0
    assert any("採集" in m or "❌" in m for m in sent)


def test_rotate_rejected_on_bad_direction(monkeypatch):
    sent = []
    bot = _bot(monkeypatch, sent)
    bot._handle_discord_command(discord_commands.DiscordCommand("轉", ("亂打",)))
    assert bot._pending_rotate == 0


def test_rotate_rejected_during_calibration(monkeypatch):
    """校準中一律拒絕遊戲輸入指令（同 回礦/ability）。"""
    from miningbot import calibrate_pitch
    sent = []
    bot = _bot(monkeypatch, sent)
    bot._calib_session = calibrate_pitch.CalibSession(
        target="mining", offset=300, prev_paused=False)
    bot._handle_discord_command(discord_commands.DiscordCommand("轉", ()))
    assert bot._pending_rotate == 0
    assert any("校準中" in m for m in sent)


# ===== 主迴圈消費（輸入只在這裡送）=====
def _consume_bot(state=State.MINING, pending=1):
    bot = Bot.__new__(Bot)
    bot.state = state
    bot._pending_rotate = pending
    bot.log_discord = _LogRecorder()
    bot.logger = _LogRecorder()
    bot.last_action = ""
    bot.rotations = []
    bot._rotate_verified = lambda d: bot.rotations.append(d) or True
    return bot


def test_consume_rotates_and_clears_flag():
    bot = _consume_bot()
    bot._consume_pending_rotate()
    assert bot.rotations == [1]
    assert bot._pending_rotate == 0


def test_consume_left():
    bot = _consume_bot(pending=-1)
    bot._consume_pending_rotate()
    assert bot.rotations == [-1]


def test_consume_drops_when_state_changed_after_accept():
    """接收後才進 HARVESTING（例如 chill 觸發）→ 丟棄不排隊，免得使用者早已離開螢幕
    才突然轉一次。"""
    bot = _consume_bot(state=State.HARVESTING)
    bot._consume_pending_rotate()
    assert bot.rotations == []
    assert bot._pending_rotate == 0
    assert any("丟棄" in r for r in bot.log_discord.records)


def test_consume_noop_without_pending():
    bot = _consume_bot(pending=0)
    bot._consume_pending_rotate()
    assert bot.rotations == []


def test_consume_warns_when_rotation_eaten():
    """旋轉被吃（H048/H052 家族）必須讓使用者知道，否則會以為自己按錯。"""
    bot = _consume_bot()
    bot._rotate_verified = lambda d: False
    bot._consume_pending_rotate()
    assert any("未生效" in r for r in bot.logger.records + bot.log_discord.records)


# ===== 玩家可見訊息（07-20 `退` 指令漏更新的教訓）=====
def test_help_mentions_rotate(monkeypatch):
    sent = []
    bot = _bot(monkeypatch, sent)
    bot._handle_discord_command(discord_commands.DiscordCommand("help", ()))
    assert any("轉" in m for m in sent)
