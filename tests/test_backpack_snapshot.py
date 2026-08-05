"""背包定期截圖 + 面板色檢比較圖 + spawn chill 抑制（2026-08-05）。

測三項：
1. 定期截圖計時 + ring buffer 清理
2. 面板色檢短路附比較圖（含降級）
3. spawn chill 抑制（短路後 _spawn_chill_notified=True → should_notify 回 False）
"""
import os
import time
import types
import logging
from unittest.mock import patch, MagicMock

import pytest

from miningbot.main import Bot
from miningbot.config import DEFAULT as cfg
from miningbot.states import should_notify_spawn_chill, State


# ── helpers ────────────────────────────────────────────────────────────

def _make_fake_bot(*, bind=(), **attrs):
    """縮水版 fake bot（只掛本測試會碰的屬性）。"""
    bot = Bot.__new__(Bot)
    bot.logger = logging.getLogger("test.bp")
    bot.log_harvest = logging.getLogger("test.bp.harvest")
    bot.log_discord = logging.getLogger("test.bp.discord")
    bot._snap_q = __import__("queue").Queue()
    import itertools
    bot._snap_seq = itertools.count()
    for name in bind:
        setattr(bot, name, types.MethodType(getattr(Bot, name), bot))
    for key, value in attrs.items():
        setattr(bot, key, value)
    return bot


def _seed_backpack_dir(tmp_path, count):
    """在 tmp_path 下造 count 張假 bp_*.png。"""
    d = tmp_path / "snapshots" / "backpack"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (d / f"bp_{1700000000 + i}_{i:06d}.png").write_bytes(b"x")
    return d


# ── 1. 定期截圖計時 ────────────────────────────────────────────────────

class TestBackpackSnapMaybe:
    def test_first_call_always_captures(self, tmp_path, monkeypatch):
        """_backpack_snap_last=0（MINING 進場初始值）→ 第一 tick 立刻拍。"""
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        monkeypatch.setattr(cfg, "backpack_snapshot_interval_s", 30.0)
        bot = _make_fake_bot(
            bind=["_backpack_snap_maybe"],
            _backpack_snap_last=0.0,
        )
        captured = []
        monkeypatch.setattr(bot, "_enqueue_raw_snapshot",
                            lambda frame, path: (captured.append(path), path)[1])
        bot._backpack_snap_maybe(MagicMock())
        assert len(captured) == 1
        assert captured[0].startswith(str(tmp_path))

    def test_within_interval_skips(self, tmp_path, monkeypatch):
        """間隔未到 → 不拍。"""
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        monkeypatch.setattr(cfg, "backpack_snapshot_interval_s", 30.0)
        bot = _make_fake_bot(
            bind=["_backpack_snap_maybe"],
            _backpack_snap_last=time.time() - 10.0,  # 10s ago < 30s
        )
        called = []
        monkeypatch.setattr(bot, "_enqueue_raw_snapshot",
                            lambda frame, path: called.append(path) or path)
        bot._backpack_snap_maybe(MagicMock())
        assert called == []

    def test_past_interval_captures(self, tmp_path, monkeypatch):
        """間隔已到 → 拍。"""
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        monkeypatch.setattr(cfg, "backpack_snapshot_interval_s", 30.0)
        bot = _make_fake_bot(
            bind=["_backpack_snap_maybe"],
            _backpack_snap_last=time.time() - 31.0,  # 31s ago > 30s
        )
        called = []
        monkeypatch.setattr(bot, "_enqueue_raw_snapshot",
                            lambda frame, path: called.append(path) or path)
        bot._backpack_snap_maybe(MagicMock())
        assert len(called) == 1

    def test_interval_zero_disables(self, tmp_path, monkeypatch):
        """interval_s=0 → 完全不拍。"""
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        monkeypatch.setattr(cfg, "backpack_snapshot_interval_s", 0.0)
        bot = _make_fake_bot(
            bind=["_backpack_snap_maybe"],
            _backpack_snap_last=0.0,
        )
        called = []
        monkeypatch.setattr(bot, "_enqueue_raw_snapshot",
                            lambda frame, path: called.append(path) or path)
        bot._backpack_snap_maybe(MagicMock())
        assert called == []


# ── 2. Ring buffer 清理 ────────────────────────────────────────────────

class TestBackpackSnapCleanup:
    def test_removes_oldest_when_over_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        monkeypatch.setattr(cfg, "backpack_snapshot_max_keep", 3)
        d = _seed_backpack_dir(tmp_path, 5)
        bot = _make_fake_bot(bind=["_backpack_snap_cleanup"])
        bot._backpack_snap_cleanup()
        remaining = sorted(f for f in os.listdir(d) if f.startswith("bp_"))
        assert len(remaining) == 3
        # 最舊 2 張被刪、最新 3 張保留
        assert remaining[0] == "bp_1700000002_000002.png"
        assert remaining[-1] == "bp_1700000004_000004.png"

    def test_no_op_when_under_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        monkeypatch.setattr(cfg, "backpack_snapshot_max_keep", 6)
        d = _seed_backpack_dir(tmp_path, 3)
        bot = _make_fake_bot(bind=["_backpack_snap_cleanup"])
        bot._backpack_snap_cleanup()
        remaining = [f for f in os.listdir(d) if f.startswith("bp_")]
        assert len(remaining) == 3

    def test_clear_removes_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        d = _seed_backpack_dir(tmp_path, 4)
        Bot._backpack_snap_clear()
        remaining = [f for f in os.listdir(d) if f.startswith("bp_")]
        assert remaining == []

    def test_latest_returns_most_recent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        _seed_backpack_dir(tmp_path, 3)
        latest = Bot._latest_backpack_snap()
        assert latest is not None
        assert latest.endswith("bp_1700000002_000002.png")

    def test_latest_empty_dir_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        (tmp_path / "snapshots" / "backpack").mkdir(parents=True, exist_ok=True)
        assert Bot._latest_backpack_snap() is None


# ── 3. 面板色檢短路附比較圖 ────────────────────────────────────────────

class TestBuildPanelCheckImages:
    def test_both_images_when_pre_exists(self, tmp_path, monkeypatch):
        """有 chill 前截圖 → 兩張圖（pre + current）。"""
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        _seed_backpack_dir(tmp_path, 1)
        bot = _make_fake_bot(
            bind=["_build_panel_check_images"],
            harvest=MagicMock(harvest_id="H123"),
        )
        monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: "/fake/cur.png")
        groups = bot._build_panel_check_images(MagicMock())
        assert len(groups) == 1
        caption, paths = groups[0]
        assert len(paths) == 2
        assert paths[1] == "/fake/cur.png"      # 當下面板在最後

    def test_only_current_when_no_pre(self, tmp_path, monkeypatch):
        """沒有 chill 前截圖 → 降級只附一張。"""
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        # 不建任何檔案 → _latest_backpack_snap() 回 None
        bot = _make_fake_bot(
            bind=["_build_panel_check_images"],
            harvest=MagicMock(harvest_id="H123"),
        )
        monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: "/fake/cur.png")
        groups = bot._build_panel_check_images(MagicMock())
        assert len(groups) == 1
        _, paths = groups[0]
        assert len(paths) == 1

    def test_empty_when_both_fail(self, tmp_path, monkeypatch):
        """兩張都取不到 → 空 list（呼叫端走既有單張截圖路徑）。"""
        monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
        bot = _make_fake_bot(
            bind=["_build_panel_check_images"],
            harvest=MagicMock(harvest_id="H123"),
        )
        monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: None)
        groups = bot._build_panel_check_images(MagicMock())
        assert groups == []


# ── 4. Spawn chill 抑制 ────────────────────────────────────────────────

class TestSpawnChillSuppression:
    def test_flag_set_means_no_notify(self):
        """_spawn_chill_notified=True → should_notify_spawn_chill 回 False。"""
        # 模擬短路後的狀態：NEEDS_HUMAN + chill 活躍 + flag 已設
        assert should_notify_spawn_chill(
            State.NEEDS_HUMAN, chill_audio=True, chill_text=True,
            already_notified=True) is False

    def test_flag_reset_after_chill_ends(self):
        """chill 回落後 flag 重置 → 下一波真正的 spawn chill 可再通知。"""
        # 這裡只驗決策函式：flag=False + 新的 chill → 通知
        assert should_notify_spawn_chill(
            State.NEEDS_HUMAN, chill_audio=True, chill_text=True,
            already_notified=False) is True
