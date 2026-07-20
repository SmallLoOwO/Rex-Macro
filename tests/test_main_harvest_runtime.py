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
