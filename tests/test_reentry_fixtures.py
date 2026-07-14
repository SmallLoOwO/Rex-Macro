"""H044 fixture 回歸：傳送驗證區域化的兩側夾（2026-07-14 實錄裁圖）。

fixture 已是 reentry_game_region(1100,200,690,650) 的 690×650 裁圖；
若日後改 region 座標，fixture 必須從 logs/snapshots 原幀重裁。
量測紀錄（vision 實作重現）：真傳送 mean 57.73/frac 0.9966；
活著靜止 mean 0.09/frac 0.0004；凍結 0.00/0.0000。
"""
import os

import cv2
import numpy as np
import pytest

from miningbot import vision
from miningbot.config import DEFAULT as cfg

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "reentry")


def _read(name):
    # cv2.imread 在 Windows 吃不了非 ASCII 路徑（專案資料夾是中文名）→ fromfile+imdecode
    data = np.fromfile(os.path.join(FIX, name), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _pair(a, b):
    ia, ib = _read(a), _read(b)
    assert ia is not None and ib is not None
    return ia, ib


def test_frozen_pair_below_both_thresholds():
    a, b = _pair("h044_frozen_a.png", "h044_frozen_b.png")
    assert vision.frame_mean_diff(a, b) < cfg.reentry_teleport_diff
    assert vision.frames_changed_frac(a, b) < cfg.reentry_teleport_frac
    # 凍結＝逐位元相同（H044 核心事實）
    assert vision.frame_mean_diff(a, b) == pytest.approx(0.0, abs=0.01)


def test_alive_static_pair_below_both_thresholds():
    a, b = _pair("h044_alive_static_a.png", "h044_alive_static_b.png")
    assert vision.frame_mean_diff(a, b) < cfg.reentry_teleport_diff
    assert vision.frames_changed_frac(a, b) < cfg.reentry_teleport_frac


def test_teleport_pair_above_both_thresholds():
    a, b = _pair("h044_teleport_a.png", "h044_teleport_b.png")
    assert vision.frame_mean_diff(a, b) >= cfg.reentry_teleport_diff
    assert vision.frames_changed_frac(a, b) >= cfg.reentry_teleport_frac
