"""俯仰拖曳「被吃」判定獨立門檻回歸（2026-07-11）。

背景：R 取樣視窗的俯仰歸位右鍵拖曳在焦點剛切回遊戲時被吃（攝影機完全沒動），
但 _pitch_drag_verified 沿用旋轉的被吃門檻 rotation_eaten_mean_diff=2.0 /
rotation_eaten_changed_frac=0.02（AND 條件）。地表場景有粒子特效，沒動的畫面
frac 也有 0.022~0.045，恰好超過 0.02 → 全部誤判「生效」→ 歸位重試從未觸發。

實機兩側夾（rotation_verify_region 裁圖，已與 log 對到小數第 4 位）：
- 被吃樣本 7 筆：mean 1.13~3.29、frac 0.0220~0.0448
- 真生效樣本 3 筆（最小 40px 微調）：mean ≥32.49、frac ≥0.6270
→ 新門檻 pitch_eaten_mean_diff=8.0、pitch_eaten_changed_frac=0.15（取中間）。
方向安全：歸位是冪等操作（拖到夾限飽和再回拉），誤判被吃而重做無害。
旋轉門檻與行為一律不動（旋轉取捨是「寧漏判勿誤重送」，門檻低是刻意的）。

fixtures 是 1920×1080 全幀裁 cfg.rotation_verify_region 後的 800×320 裁圖，
測試直接對 before/after 整張算，不需再裁。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import vision  # noqa: E402
from miningbot import harvester  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pitch")


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def _diffs(before_name, after_name):
    before = _load(before_name)
    after = _load(after_name)
    mean = vision.frames_mean_diff(before, after)
    frac = vision.frames_changed_frac(before, after, cfg.rotation_changed_pixel_thresh)
    return mean, frac


def test_eaten_reset_detected_as_eaten():
    mean, frac = _diffs("eaten_reset_before.png", "eaten_reset_after.png")
    assert harvester.rotation_looks_eaten(
        mean, frac, cfg.pitch_eaten_mean_diff, cfg.pitch_eaten_changed_frac)


def test_eaten_reset_hi_detected_as_eaten():
    mean, frac = _diffs("eaten_reset_hi_before.png", "eaten_reset_hi_after.png")
    assert harvester.rotation_looks_eaten(
        mean, frac, cfg.pitch_eaten_mean_diff, cfg.pitch_eaten_changed_frac)


def test_eaten_nudge_hi_detected_as_eaten():
    # 被吃樣本最高值（mean=3.29 frac=0.045），仍在 pitch 門檻以下
    mean, frac = _diffs("eaten_nudge_hi_before.png", "eaten_nudge_hi_after.png")
    assert harvester.rotation_looks_eaten(
        mean, frac, cfg.pitch_eaten_mean_diff, cfg.pitch_eaten_changed_frac)


def test_real_nudge_lo_not_eaten():
    # 真生效最低值（mean=32.49 frac=0.63），須判「生效」不可誤判被吃
    mean, frac = _diffs("real_nudge_lo_before.png", "real_nudge_lo_after.png")
    assert not harvester.rotation_looks_eaten(
        mean, frac, cfg.pitch_eaten_mean_diff, cfg.pitch_eaten_changed_frac)


def test_pitch_thresholds_bracket_eaten_and_real():
    """兩側夾：pitch 門檻落在被吃最高值與真生效最低值之間的 gap。"""
    eaten_mean, eaten_frac = _diffs("eaten_nudge_hi_before.png", "eaten_nudge_hi_after.png")
    real_mean, real_frac = _diffs("real_nudge_lo_before.png", "real_nudge_lo_after.png")
    assert eaten_mean < cfg.pitch_eaten_mean_diff < real_mean
    assert eaten_frac < cfg.pitch_eaten_changed_frac < real_frac


def test_eaten_reset_would_pass_old_rotation_threshold():
    # 回歸鎖 bug：舊旋轉門檻(2.0/0.02)讓被吃樣本誤判「生效」(frac 0.022>0.02 翻成 False)
    # 防止未來有人把 pitch 驗證改回共用旋轉門檻
    mean, frac = _diffs("eaten_reset_before.png", "eaten_reset_after.png")
    assert not harvester.rotation_looks_eaten(
        mean, frac, cfg.rotation_eaten_mean_diff, cfg.rotation_eaten_changed_frac)


def test_rotation_thresholds_unchanged():
    assert cfg.rotation_eaten_mean_diff == 2.0
    assert cfg.rotation_eaten_changed_frac == 0.02
