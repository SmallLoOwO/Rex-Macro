import os

from miningbot.config import (Config, default_log_dir, resolve_log_dir,
                              resolve_runtime_log_path)


def test_default_log_dir_uses_localappdata(monkeypatch):
    monkeypatch.delenv("REX_MININGBOT_LOG_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")

    assert default_log_dir() == os.path.join(
        r"C:\Users\tester\AppData\Local", "RexMacro", "logs")


def test_default_log_dir_allows_explicit_override(monkeypatch):
    monkeypatch.setenv("REX_MININGBOT_LOG_DIR", r"D:\RexLogs")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\ignored")

    assert default_log_dir() == r"D:\RexLogs"


def test_default_log_dir_falls_back_when_localappdata_missing(monkeypatch):
    monkeypatch.delenv("REX_MININGBOT_LOG_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert default_log_dir() == "logs"


def test_resolve_log_dir_makes_relative_path_project_stable(tmp_path):
    assert resolve_log_dir("logs", project_root=str(tmp_path)) == os.path.join(
        str(tmp_path), "logs")


def test_resolve_log_dir_keeps_absolute_path(tmp_path):
    absolute = str(tmp_path / "RexLogs")
    assert resolve_log_dir(absolute, project_root="ignored") == os.path.normpath(absolute)


def test_harvest_recovery_and_cooldown_defaults_are_bounded():
    cfg = Config()
    assert cfg.d3_cooldown_s == 10.0
    assert cfg.harvest_target_recovery_max == 1
    assert cfg.snapshot_shutdown_drain_s == 5.0


def test_runtime_log_children_follow_active_log_root(tmp_path):
    log_dir = str(tmp_path / "active")
    assert resolve_runtime_log_path("logs/snapshots/manual", log_dir) == os.path.join(
        log_dir, "snapshots", "manual")
    assert resolve_runtime_log_path("logs/reentry_remote/ledger.jsonl", log_dir) == os.path.join(
        log_dir, "reentry_remote", "ledger.jsonl")
