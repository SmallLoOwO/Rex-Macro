"""D2 掃描效果驗證守門（scan_confirm_mode enforce + sweep guard）的回歸測試。

背景（harvest 168, 2026-08-02）：進場 execute_scan 的 click 被吃掉／掃描沒觸發，
但 scan_confirm_mode="off" 使 _confirm_scan 永遠 return True → bot 無法分辨
「沒稀有礦」跟「掃描沒觸發」→ 白掃 8 方位全空 → giveup → 可能放生真稀有礦。

修復設計（比照 D5 boost guard 的 self-heal 模式，使用者指定）：
1. _confirm_scan enforce 模式重試後回傳實際結果（不再永遠 True）
2. scan_confirm_mode 預設從 "off" 改 "enforce"
3. _harvest_scan_guard：sweep 每方位檢查效果列 Local 徽章，缺了就補掃再繼續（不交人工）
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


# ---- _confirm_scan 回傳值 ---------------------------------------------------

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
    """enforce 模式：重試後 badge 仍 False → 回傳 False（不再永遠 True）。"""
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


# ---- _harvest_scan_guard（self-heal，比照 _harvest_boost_guard）---------------

def test_scan_guard_passes_when_badge_present(monkeypatch):
    """效果列有 Local 徽章 → 守門放行（不補掃）。"""
    bot = _make_bot(
        harvest=types.SimpleNamespace(harvest_id="168"),
        _scan_local_badge_present=lambda: True,
    )
    assert bot._harvest_scan_guard() is False


def test_scan_guard_retriggers_when_badge_missing(monkeypatch):
    """效果列無 Local 徽章 → 補掃 D2 再繼續（self-heal，不交人工）。"""
    retriggered = []
    bot = _make_bot(
        harvest=types.SimpleNamespace(harvest_id="168"),
        _scan_local_badge_present=lambda: False,
        _await_scan_ready=lambda where: retriggered.append(where),
        _run_scan=lambda: retriggered.append("run_scan"),
    )
    monkeypatch.setattr(main.cfg, "radar_repeat_interval_s", 999)
    assert bot._harvest_scan_guard() is True
    assert "scan-guard" in retriggered
    assert "run_scan" in retriggered


def test_scan_guard_throttles_repeat_retrigger(monkeypatch):
    """剛補過 → throttle 內不重複（防 OCR 假陰性 spam 冷卻等待）。"""
    bot = _make_bot(
        harvest=types.SimpleNamespace(harvest_id="168"),
        _scan_local_badge_present=lambda: False,
        _await_scan_ready=lambda where: None,
        _run_scan=lambda: None,
    )
    monkeypatch.setattr(main.cfg, "radar_repeat_interval_s", 999)
    monkeypatch.setattr(main.time, "time", lambda: 1000.0)

    assert bot._harvest_scan_guard() is True   # 第一次：補掃
    monkeypatch.setattr(main.time, "time", lambda: 1001.0)
    assert bot._harvest_scan_guard() is False  # 1s 後：throttle 擋住
    monkeypatch.setattr(main.time, "time", lambda: 2000.0)
    assert bot._harvest_scan_guard() is True   # 1000s 後：throttle 過 → 再補


# ---- 補掃後的 sweep 預算（code review 2026-08-02）--------------------------

def test_scan_guard_resets_sweep_budget_after_retrigger(monkeypatch):
    """補掃後 _harvest_start 重置：_await_scan_ready 最長等 36s，不重置則下個 tick
    必定 elapsed_s > sweep_timeout_s(30s) → self-heal 剛救回掃描就被判 sweep 超時。"""
    harvest = types.SimpleNamespace(harvest_id="168", elapsed_s=28.0)
    bot = _make_bot(
        harvest=harvest,
        _harvest_start=1000.0,
        _scan_local_badge_present=lambda: False,
        # 補掃真的很花時間：等冷卻 36s
        _await_scan_ready=lambda where: monkeypatch.setattr(
            main.time, "time", lambda: 1036.0),
        _run_scan=lambda: None,
    )
    monkeypatch.setattr(main.cfg, "radar_repeat_interval_s", 999)
    monkeypatch.setattr(main.time, "time", lambda: 1000.0)

    assert bot._harvest_scan_guard() is True
    assert bot._harvest_start == 1036.0, "預算須從補掃完成之後起算"
    assert harvest.elapsed_s == 0.0
    # 沒重置的話這裡會是 28.0 + 36 = 64s > sweep_timeout_s(30) → 誤判超時


def test_scan_guard_survives_missing_harvest(monkeypatch):
    """harvest 為 None（非採集情境）仍可補掃，不因重置預算而爆 AttributeError。"""
    bot = _make_bot(
        harvest=None,
        _scan_local_badge_present=lambda: False,
        _await_scan_ready=lambda where: None,
        _run_scan=lambda: None,
    )
    monkeypatch.setattr(main.cfg, "radar_repeat_interval_s", 999)
    assert bot._harvest_scan_guard() is True


def test_scan_guard_at_initialised_in_init():
    """_scan_guard_at 必須在 __init__ 宣告（對照 _last_boost_check），不靠 getattr 預設：
    跨 episode 殘留會讓新一輪前 34s 守門形同關閉。"""
    import inspect
    src = inspect.getsource(Bot.__init__)
    assert "self._scan_guard_at" in src
