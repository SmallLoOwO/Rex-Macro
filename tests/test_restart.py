"""Discord 重開指令的暫停閘 + relauncher 測試。"""
import subprocess
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
    # DETACHED_PROCESS 必須在 creationflags 裡——relauncher 才能在父行程結束後存活
    assert calls[0].get("creationflags", 0) & subprocess.DETACHED_PROCESS


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


def test_restart_marker_written_on_success(monkeypatch, tmp_path):
    monkeypatch.setattr("subprocess.Popen",
                        lambda *a, **k: types.SimpleNamespace())
    monkeypatch.setattr("miningbot.config.DEFAULT.log_dir", str(tmp_path))
    monkeypatch.setattr("miningbot.notify.send_message", lambda *a, **k: None)
    bot = make_fake_bot(bind=["_schedule_restart"])
    bot._schedule_restart()
    assert (tmp_path / "restart_marker").exists()


def test_check_restart_marker_notifies_and_deletes(monkeypatch, tmp_path):
    marker = tmp_path / "restart_marker"
    marker.write_text("2026-08-03 12:00:00", encoding="utf-8")
    monkeypatch.setattr("miningbot.config.DEFAULT.log_dir", str(tmp_path))
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = make_fake_bot(bind=["_check_restart_marker"])
    bot._check_restart_marker()
    assert not marker.exists()
    assert any("重開完成" in m for m in sent)


def test_check_restart_marker_noop_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr("miningbot.config.DEFAULT.log_dir", str(tmp_path))
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = make_fake_bot(bind=["_check_restart_marker"])
    bot._check_restart_marker()
    assert sent == []   # 沒 marker → 不發訊息
