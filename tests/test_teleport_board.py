"""傳送板偵測器 v0（`miningbot/teleport_board.py`）。

真素材迴歸用 tracked 的 `tests/fixtures/reentry/teleport_board/auto_27_success.*`
（fresh checkout 有；本機語料夾 corpus/ 沒有，不可依賴）。兩側夾：真板子要中，
夜空／發光 UI 這類同色相干擾物不可中。
"""

import json
import os

import cv2
import numpy as np
import pytest

from miningbot import teleport_board
from miningbot.config import DEFAULT as cfg

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "reentry",
                            "teleport_board")


def _hsv_patch(img, box, hsv):
    x, y, w, h = box
    patch = np.zeros((h, w, 3), dtype=np.uint8)
    patch[:, :] = hsv
    img[y:y + h, x:x + w] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)


def _synthetic_board(box=(900, 400, 200, 95)):
    """合成一塊「紫框 + 深色內部」的板子：外框走實測 HSV 中心 (133, 110, 120)。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    x, y, w, h = box
    _hsv_patch(img, box, (133, 110, 120))                     # 外框整塊先塗紫
    inner = (x + 14, y + 20, w - 28, h - 30)
    _hsv_patch(img, inner, (128, 180, 40))                    # 深藍黑面板
    return img


# ---- 分數（純函式）---------------------------------------------------------

def test_candidate_score_peaks_at_measured_centre():
    got = teleport_board.candidate_score(
        cfg.teleport_board_aspect_center, cfg.teleport_board_fill_center,
        cfg.teleport_board_dark_ref)
    assert got == pytest.approx(1.0)


def test_candidate_score_collapses_when_one_feature_is_off():
    """幾何平均：任一項明顯偏離就整體塌下來，不會被另外兩項救回。"""
    off_aspect = teleport_board.candidate_score(
        cfg.teleport_board_aspect_center + cfg.teleport_board_aspect_tolerance,
        cfg.teleport_board_fill_center, cfg.teleport_board_dark_ref)
    assert off_aspect < 0.01              # 立方根把浮點殘差放大到 1e-6，不用 ==0


def test_candidate_score_stays_in_unit_range():
    assert 0.0 <= teleport_board.candidate_score(1.9, 0.30, 0.9) <= 1.0


# ---- 真素材迴歸 ------------------------------------------------------------

def test_detects_board_in_tracked_real_frame():
    """實機 ep27 全幀：預測要落在玩家點擊座標的 hit radius 內。"""
    png = os.path.join(_FIXTURE_DIR, "auto_27_success.png")
    meta = json.load(open(os.path.join(_FIXTURE_DIR, "auto_27_success.json"),
                          encoding="utf-8"))
    frame = cv2.imdecode(np.fromfile(png, dtype=np.uint8), cv2.IMREAD_COLOR)
    got = teleport_board.detect(frame)
    assert got is not None, "tracked 真素材裡的傳送板沒被偵測到"
    x, y, score = got
    truth = (meta["annotation"]["cx"], meta["annotation"]["cy"])
    dist = ((x - truth[0]) ** 2 + (y - truth[1]) ** 2) ** 0.5
    assert dist <= cfg.reentry_dataset_hit_radius_px, f"偏 {dist:.0f}px"
    assert score >= cfg.reentry_predict_min_score, f"分數 {score:.3f} 低於畫圈門檻"


# ---- 合成正樣本 ------------------------------------------------------------

def test_detects_synthetic_board_near_its_centre():
    got = teleport_board.detect(_synthetic_board())
    assert got is not None
    assert abs(got[0] - 1000) <= 20 and abs(got[1] - 447) <= 20


# ---- 合成負樣本（同色相但更暗／更飽和／形狀不對）--------------------------

def test_ignores_dark_saturated_night_sky():
    """夜空與板子同色相帶，靠 V 下界與 S 上界分開（實測夜空 V 中位 48、S 157）。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _hsv_patch(img, (300, 200, 900, 300), (129, 157, 48))
    assert teleport_board.detect(img) is None


def test_ignores_bright_glowing_ui_block():
    """發光 UI 元件實測 S 254 / V 190，板子外框 S~110 / V~120。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _hsv_patch(img, (700, 400, 200, 95), (127, 254, 190))
    assert teleport_board.detect(img) is None


def test_ignores_wide_banner_shaped_blob():
    """頂端橫幅那種長寬比 13 的東西不是板子（實測板子 1.68~2.21）。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _hsv_patch(img, (350, 300, 1200, 90), (133, 110, 120))
    assert teleport_board.detect(img) is None


def test_ignores_solid_purple_rectangle_without_dark_interior():
    """整塊實心紫（fill≈1、內部不暗）是 UI 疊層，不是板子。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _hsv_patch(img, (700, 400, 200, 95), (133, 110, 120))
    assert teleport_board.detect(img) is None


def test_ignores_board_sized_blob_outside_roi():
    """ROI 只排螢幕空間 UI 邊緣（左側礦物面板／右側圖示欄／頂橫幅／底工具列）。"""
    img = _synthetic_board(box=(40, 950, 200, 95))
    assert teleport_board.detect(img) is None


def test_empty_frame_returns_none():
    assert teleport_board.detect(None) is None
    assert teleport_board.detect(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_all_black_frame_returns_none():
    assert teleport_board.detect(np.zeros((1080, 1920, 3), dtype=np.uint8)) is None


# ---- 門檻都在 config -------------------------------------------------------

def test_thresholds_live_in_config():
    from miningbot.config import Config
    c = Config()
    for name in ("teleport_board_hue_range", "teleport_board_sat_range",
                 "teleport_board_val_range", "teleport_board_roi",
                 "teleport_board_min_area", "teleport_board_aspect_range",
                 "teleport_board_fill_range", "reentry_predict_min_score"):
        assert hasattr(c, name), name


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
