import types

import cv2
import numpy as np

from miningbot import main, remote_aim
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


def test_shared_d3_cooldown_starts_immediately_before_hold_click(monkeypatch):
    bot = Bot.__new__(Bot)
    bot._last_d3_fire_at = None
    bot.log_harvest = _LogRecorder()
    now = [100.0]
    actions = []

    monkeypatch.setattr(main.cfg, "d3_cooldown_s", 10.0)
    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(main.time, "sleep", lambda seconds: actions.append(("sleep", seconds)))
    monkeypatch.setattr(main.ic, "key_press", lambda key: actions.append(("key", key)))

    def click(x, y, hold):
        assert bot._last_d3_fire_at == now[0]
        actions.append(("click", x, y, hold))

    monkeypatch.setattr(main.ic, "click_at", click)

    assert bot._fire_d3_at(640, 480) is True
    assert actions == [
        ("key", "2"), ("sleep", 0.15),
        ("key", "3"), ("sleep", 0.3),
        ("click", 640, 480, 0.4), ("sleep", 0.5),
    ]

    now[0] = 109.999
    assert bot._fire_d3_at(640, 480) is False
    assert len(actions) == 6

    now[0] = 110.0
    assert bot._fire_d3_at(640, 480) is True
    assert len(actions) == 12


def test_aim_renderer_matches_candidates_by_exact_snapshot_path(tmp_path, monkeypatch):
    first_path = str(tmp_path / "first.png")
    second_path = str(tmp_path / "second.png")
    black = np.zeros((400, 1000, 3), dtype=np.uint8)
    assert cv2.imwrite(first_path, black)
    assert cv2.imwrite(second_path, black)

    shots = [
        remote_aim.SweepShot("mid", 2, first_path, []),
        remote_aim.SweepShot("mid", 2, second_path, []),
    ]
    candidates = [
        remote_aim.AimCandidate(
            1, "mid", 2, (200, 180), 0.9, "first",
            status="accepted", snapshot_path=first_path),
        remote_aim.AimCandidate(
            2, "mid", 2, (750, 180), 0.8, "second",
            status="fired", snapshot_path=second_path),
    ]
    ctx = remote_aim.AimContext(
        candidates=candidates, shots=shots, pose_net_rotations=0,
        pose_pitch_layer="mid", harvest_id="079", created_at=1.0)
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    monkeypatch.setattr(main.cfg, "log_dir", str(tmp_path))
    monkeypatch.setattr(main.cfg, "remote_aim_snapshot_wait_s", 0.1)

    rendered = bot._render_aim_shots(ctx)

    assert len(rendered) == 2
    first_overlay = cv2.imread(first_path.replace(".png", "_aim.png"))
    assert tuple(first_overlay[180, 164]) == (0, 215, 255)
    assert tuple(first_overlay[180, 714]) != (0, 215, 255)


# --- H054（2026-07-20，harvest 094）：基準無聊天歷史 → 計數差確認必須被擋 ---
# 實機：episode 進場凍結的聊天裁圖落在 Roblox 聊天淡出時段 → 基準只讀到常駐面板
# "NORMAL"、0 條 has-found；sweep 期間事件訊息讓聊天整段重新淡入 → 計數差把開火前
# 早就在的舊採集行全當新增 → rare 0→2 + special 判 SUCCESS。鐵證：框未消失
# (gone=False)、開火前後聊天裁圖 MD5 相同＝這一發沒產生任何新行，礦其實沒挖到。
from tests.test_ocr import (H054_BASELINE_HIDDEN, H054_AFTER_094,
                            H054_BASELINE_VISIBLE_082, H054_AFTER_082,
                            H054_COMMON)


class _WarnRecorder(_LogRecorder):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)
        super().warning(message, *args)

    def debug(self, message, *args):
        pass


def _verify_bot(monkeypatch, after_text):
    bot = Bot.__new__(Bot)
    bot.log_harvest = _WarnRecorder()
    bot._chat_ledger = None
    monkeypatch.setattr(main.ocr, "read_text_multi",
                        lambda *args, **kwargs: [after_text])
    monkeypatch.setattr(main.cfg, "found_keywords", ("has found", "found a"))
    monkeypatch.setattr(main.cfg, "special_keywords", ("ionized", "spectral"))
    monkeypatch.setattr(Bot, "_log_rapid_diag", lambda self, hid, why: None)
    return bot


def test_h054_hidden_baseline_suppresses_count_diff_confirmation(monkeypatch):
    bot = _verify_bot(monkeypatch, H054_AFTER_094)
    _, confirmed, special = bot._verify_chat_ocr(
        None, [H054_BASELINE_HIDDEN], H054_COMMON, (), "094", "poll")

    assert confirmed is False and special is False
    assert any("H054 基準閘" in w for w in bot.log_harvest.warnings)


def test_h054_visible_baseline_still_confirms_real_success(monkeypatch):
    # 兩側夾另一側：082 真成功（基準看得到 10 條歷史）不可被閘擋掉
    bot = _verify_bot(monkeypatch, H054_AFTER_082)
    _, confirmed, _ = bot._verify_chat_ocr(
        None, [H054_BASELINE_VISIBLE_082], H054_COMMON, (), "082", "poll")

    assert confirmed is True
    assert bot.log_harvest.warnings == []


def test_h054_gate_does_not_veto_ledger_confirmation(monkeypatch):
    # 帳本自帶錨點、規則等效，基準閘不可連它一起擋（否則 H032 晚到行救不回）
    bot = _verify_bot(monkeypatch, H054_AFTER_094)
    bot._chat_ledger = main.ocr.ChatLedger([H054_BASELINE_HIDDEN])
    monkeypatch.setattr(type(bot._chat_ledger), "confirmed", property(lambda self: True))
    monkeypatch.setattr(Bot, "_maybe_detect_world_from_ore_lines", lambda self, lines: None)

    _, confirmed, _ = bot._verify_chat_ocr(
        None, [H054_BASELINE_HIDDEN], H054_COMMON, (), "094", "poll")

    assert confirmed is True


# --- H118（2026-07-28）：_harvest_boost_guard 中途補 D5 讓 ref 對不上新 FOV -----
#
# 118 實錄：01:07:45 sweep 中途補 D5（FOV 收縮/展開）；01:07:57 轉回去 verify
# 剛才看過的框卻找不到了；緊接的重掃（_reharvest_sweep，H026 對策不重拍 ref）
# 沿用同一份已經跟新 FOV 對不上的 ref，結果 8 方位全空。


def _harvest_state():
    return types.SimpleNamespace(harvest_id="118", net_rotations=0, pitch_layer="mid")


def test_sweep_for_tracker_flags_fov_shift_when_boost_guard_fires(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.harvest = _harvest_state()
    bot.log_harvest = _LogRecorder()
    bot._tracker_log = None
    bot._find_tracker = lambda *a, **kw: None       # 118 第二輪重掃實錄：全 8 方位都沒找到
    bot._rotate_verified = lambda step: True
    monkeypatch.setattr(main.cfg, "remote_aim_enabled", False)
    monkeypatch.setattr(main.cfg, "sweep_empty_snapshot", False)
    monkeypatch.setattr(main.capture, "grab", lambda: np.zeros((4, 4, 3), np.uint8))

    guard_calls = []

    def guard(frame):
        guard_calls.append(1)
        return len(guard_calls) == 3            # 第 3 個方位補 D5，其餘不用補

    bot._harvest_boost_guard = guard

    pos, had = bot._sweep_for_tracker([], None)

    assert pos is None and had is False
    assert bot._sweep_fov_shifted is True, "本輪掃描中補過 D5，旗標該立起來"


def test_sweep_for_tracker_no_flag_when_boost_guard_never_fires(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.harvest = _harvest_state()
    bot.log_harvest = _LogRecorder()
    bot._tracker_log = None
    bot._find_tracker = lambda *a, **kw: None
    bot._rotate_verified = lambda step: True
    bot._harvest_boost_guard = lambda frame: False
    monkeypatch.setattr(main.cfg, "remote_aim_enabled", False)
    monkeypatch.setattr(main.cfg, "sweep_empty_snapshot", False)
    monkeypatch.setattr(main.capture, "grab", lambda: np.zeros((4, 4, 3), np.uint8))

    bot._sweep_for_tracker([], None)

    assert bot._sweep_fov_shifted is False, "沒補過 D5，不該誤報 FOV 換過"


def test_reharvest_sweep_refresh_ref_recaptures_after_boost_settle(monkeypatch):
    """refresh_ref=True：捨棄舊 ref，比照進場邏輯——先確認 FOV 展開，按 D2 之前重拍。"""
    bot = Bot.__new__(Bot)
    bot.harvest = types.SimpleNamespace(d3_attempts=3)
    bot._pre_scan_ref = "舊的、FOV 已經對不上的 ref"
    bot._sweep_fov_shifted = True
    bot._await_scan_ready = lambda where: True
    bot._confirm_scan = lambda where: True
    scan_calls = []
    bot._run_scan = lambda: scan_calls.append("run_scan")
    monkeypatch.setattr(main.harvester, "prepare_scan", lambda: None)

    fresh_frame = "新 FOV 底下的乾淨畫面"
    monkeypatch.setattr(main.capture, "grab", lambda: fresh_frame)
    bot._harvest_boost_guard = lambda frame: False   # 已經展開，guard 這次不用再補

    bot._reharvest_sweep(refresh_ref=True)

    assert bot._pre_scan_ref == fresh_frame
    assert bot._sweep_fov_shifted is False
    assert scan_calls == ["run_scan"]


def test_reharvest_sweep_default_keeps_existing_ref(monkeypatch):
    """refresh_ref=False（預設）——H026 對策不變，既有 ref 原封不動、完全不碰畫面。"""
    bot = Bot.__new__(Bot)
    bot.harvest = types.SimpleNamespace(d3_attempts=3)
    bot._pre_scan_ref = "既有 ref（框可能已在畫面上，不能重拍）"
    bot._sweep_fov_shifted = True   # 防禦性驗證：即使漏傳也不該殘留舊旗標到下一輪
    bot._await_scan_ready = lambda where: True
    bot._confirm_scan = lambda where: True
    bot._run_scan = lambda: None
    monkeypatch.setattr(main.harvester, "prepare_scan", lambda: None)

    def _boom():
        raise AssertionError("refresh_ref=False 不該碰畫面/guard")
    monkeypatch.setattr(main.capture, "grab", lambda: _boom())
    bot._harvest_boost_guard = lambda frame: _boom()

    bot._reharvest_sweep()

    assert bot._pre_scan_ref == "既有 ref（框可能已在畫面上，不能重拍）"
    assert bot._sweep_fov_shifted is False
