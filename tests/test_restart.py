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


def test_consume_pending_restart_spawns_and_returns_true(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.Popen",
                        lambda *a, **k: calls.append(k) or types.SimpleNamespace())
    monkeypatch.setattr("miningbot.notify.send_message", lambda *a, **k: None)
    bot = make_fake_bot(
        bind=["_consume_pending_restart", "_schedule_restart"],
        _pending_restart=True,
    )
    result = bot._consume_pending_restart()
    assert result is True
    assert bot._pending_restart is False
    assert len(calls) == 1
    # DETACHED_PROCESS (0x8) 必須在 creationflags 裡——relauncher 才能在父行程結束後存活
    assert calls[0].get("creationflags", 0) & 0x00000008


def test_consume_pending_restart_noop_when_flag_clear(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.Popen",
                        lambda *a, **k: calls.append(k))
    bot = make_fake_bot(
        bind=["_consume_pending_restart", "_schedule_restart"],
        _pending_restart=False,
    )
    result = bot._consume_pending_restart()
    assert result is False
    assert calls == []   # 旗標沒設 → 不 spawn


def test_consume_pending_restart_spawn_fail_keeps_running(monkeypatch):
    def boom(*a, **k):
        raise OSError("spawn denied")
    monkeypatch.setattr("subprocess.Popen", boom)
    monkeypatch.setattr("miningbot.notify.send_message", lambda *a, **k: None)
    bot = make_fake_bot(
        bind=["_consume_pending_restart", "_schedule_restart"],
        _pending_restart=True,
    )
    result = bot._consume_pending_restart()
    assert result is False              # spawn 失敗 → 不關機
    assert bot._pending_restart is False  # 旗標已清（不會重試）
