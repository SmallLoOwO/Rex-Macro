"""Discord 重開指令的暫停閘 + relauncher 測試。"""
import types

from miningbot.discord_commands import DiscordCommand
from miningbot.states import State
from tests.fake_bot import make_fake_bot


def _make_bot(**kwargs):
    defaults = dict(
        bind=["_handle_discord_command"],
        paused=False,
        state=State.MINING,
        _pending_restart=False,
        _calib_session=None,
    )
    defaults.update(kwargs)
    return make_fake_bot(**defaults)


def test_restart_sets_flag_when_paused(monkeypatch):
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = _make_bot(paused=True)
    bot._handle_discord_command(DiscordCommand(name="重開", args=()))
    assert bot._pending_restart is True
    assert any("重開" in m or "重啟" in m for m in sent)


def test_restart_alias_english(monkeypatch):
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = _make_bot(paused=True)
    bot._handle_discord_command(DiscordCommand(name="restart", args=()))
    assert bot._pending_restart is True


def test_restart_rejected_when_not_paused(monkeypatch):
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = _make_bot(paused=False)
    bot._handle_discord_command(DiscordCommand(name="重開", args=()))
    assert bot._pending_restart is False
    assert any("暫停" in m for m in sent)
