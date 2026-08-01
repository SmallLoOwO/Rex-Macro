"""D2 掃描效果驗證守門（scan_confirm_mode enforce）的回歸測試。

背景（harvest 168, 2026-08-02）：進場 execute_scan 的 click 被吃掉／掃描沒觸發，
但 scan_confirm_mode="off" 使 _confirm_scan 永遠 return True → bot 無法分辨
「沒稀有礦」跟「掃描沒觸發」→ 白掃 8 方位全空 → giveup → 可能放生真稀有礦。

修復三層：
1. _confirm_scan enforce 模式重試後回傳實際結果（不再永遠 True）
2. 進場／重掃／歷史復原／俯仰層／remote-aim 呼叫端接住回傳值，False 時 abort
3. scan_confirm_mode 預設從 "off" 改 "enforce"
"""
import types

import pytest

from miningbot import main
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)

    def error(self, message, *args):
        self.records.append(message % args if args else message)


def _make_bot(**attrs):
    """Bot.__new__ 模型——只設掃描確認所需的屬性。"""
    bot = Bot.__new__(Bot)
    bot.log_harvest = _LogRecorder()
    bot.logger = _LogRecorder()
    for k, v in attrs.items():
        setattr(bot, k, v)
    return bot


# ---- _confirm_scan 回傳值（核心修復）-----------------------------------------

def test_confirm_scan_off_returns_true(monkeypatch):
    """off 模式：不檢查，永遠放行（向後相容）。"""
    monkeypatch.setattr(main.cfg, "scan_confirm_mode", "off")
    bot = _make_bot()
    assert bot._confirm_scan("test") is True


def test_confirm_scan_observe_returns_true_even_when_badge_absent(monkeypatch):
    """observe 模式：記錄但不改行為（收數據用）。"""
    monkeypatch.setattr(main.cfg, "scan_confirm_mode", "observe")
    bot = _make_bot(_scan_local_badge_present=lambda: False)
    assert bot._confirm_scan("test") is True


def test_confirm_scan_enforce_returns_true_when_badge_present(monkeypatch):
    """enforce 模式：badge 在 → 正常放行。"""
    monkeypatch.setattr(main.cfg, "scan_confirm_mode", "enforce")
    bot = _make_bot(_scan_local_badge_present=lambda: True)
    assert bot._confirm_scan("test") is True


def test_confirm_scan_enforce_returns_false_after_failed_retry(monkeypatch):
    """enforce 模式：重試後 badge 仍 False → 回傳 False（修復重點：不再永遠 True）。"""
    monkeypatch.setattr(main.cfg, "scan_confirm_mode", "enforce")
    bot = _make_bot(
        _scan_local_badge_present=lambda: False,
        _focus_roblox=lambda: None,
        _await_scan_ready=lambda where: True,
        _run_scan=lambda: None,
    )
    assert bot._confirm_scan("test") is False


def test_confirm_scan_enforce_retries_then_succeeds(monkeypatch):
    """enforce 模式：第一次 badge=False → refocus+重掃 → 第二次 True → 回傳 True。"""
    monkeypatch.setattr(main.cfg, "scan_confirm_mode", "enforce")
    badge_results = iter([False, True])
    retried = []
    bot = _make_bot(
        _scan_local_badge_present=lambda: next(badge_results),
        _focus_roblox=lambda: retried.append("focus"),
        _await_scan_ready=lambda where: retried.append(where),
        _run_scan=lambda: retried.append("run_scan"),
    )
    assert bot._confirm_scan("test") is True
    assert "focus" in retried
    assert "test-retry" in retried
    assert "run_scan" in retried


# ---- 呼叫端接住回傳值 --------------------------------------------------------

def test_reharvest_sweep_gives_up_when_scan_confirm_fails(monkeypatch):
    """重掃後 _confirm_scan=False → 不繼續 sweep，交人工（不再白掃 8 方位）。"""
    bot = _make_bot(
        harvest=types.SimpleNamespace(
            d3_attempts=3, net_rotations=0, pitch_layer="mid",
            harvest_id="168"),
        _pre_scan_ref="ref",
        _sweep_fov_shifted=False,
        _await_scan_ready=lambda where: True,
        _confirm_scan=lambda where: False,   # 掃描未生效
        _run_scan=lambda: None,
    )
    monkeypatch.setattr(main.harvester, "prepare_scan", lambda: None)
    giveup_calls = []
    bot._harvest_giveup = lambda reason, **kw: giveup_calls.append(reason)

    bot._reharvest_sweep()

    assert len(giveup_calls) == 1, "掃描未生效應立刻交人工，不繼續 sweep"
    assert "掃描" in giveup_calls[0] or "D2" in giveup_calls[0]


def test_reharvest_sweep_proceeds_when_scan_confirm_ok(monkeypatch):
    """掃確認 ok → 正常流程不變（不誤觸 giveup）。"""
    bot = _make_bot(
        harvest=types.SimpleNamespace(
            d3_attempts=3, net_rotations=0, pitch_layer="mid",
            harvest_id="168"),
        _pre_scan_ref="ref",
        _sweep_fov_shifted=True,
        _await_scan_ready=lambda where: True,
        _confirm_scan=lambda where: True,
        _run_scan=lambda: None,
    )
    monkeypatch.setattr(main.harvester, "prepare_scan", lambda: None)
    giveup_calls = []
    bot._harvest_giveup = lambda reason, **kw: giveup_calls.append(reason)

    bot._reharvest_sweep()

    assert giveup_calls == [], "掃描 ok 不該 giveup"


def test_recover_historical_target_skips_tracker_search_when_scan_confirm_fails(monkeypatch):
    """歷史復原：掃描未生效 → 不呼叫 find_tracker_near（直接 return False）。"""
    # 準備最小可到達 _confirm_scan 的 mock——旋轉/俯仰/聚焦全短路。
    obs = types.SimpleNamespace(
        status="accepted", layer="mid", dir_idx=0, pos=(960, 540), score=0.9)
    monkeypatch.setattr(main.remote_aim, "pick_recovery_observation", lambda obs_list: obs)
    find_calls = []
    monkeypatch.setattr(main.vision, "find_tracker_near",
                        lambda *a, **k: find_calls.append("called"))

    bot = _make_bot(
        harvest=types.SimpleNamespace(
            d3_attempts=0, net_rotations=0, pitch_layer="mid",
            harvest_id="168", pitch_touched=False),
        _target_recovery_attempts=0,
        _target_observations=[],
        _pre_scan_ref=None,
        _focus_roblox=lambda: True,
        _mine_resetting=False,
        _rotate_verified=lambda step: True,
        _pitch_drag_verified=lambda tag, fn: True,
        _await_scan_ready=lambda where: True,
        _confirm_scan=lambda where: False,   # 掃描未生效
        _run_scan=lambda: None,
        _harvest_boost_guard=lambda frame: False,
    )
    monkeypatch.setattr(main.harvester, "prepare_scan", lambda: None)
    monkeypatch.setattr(main.capture, "grab", lambda: None)

    result = bot._recover_historical_target(None)

    assert result is False, "掃描未生效應 return False"
    assert find_calls == [], "掃描未生效不該浪費時間找 tracker"
