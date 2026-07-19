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


# ===== H050：放大圖漂移守門（2026-07-19 ep7 實錄裁圖）=====
# sweep 快照（19:35:44 dir1）與 `1 E2` 現場截圖（19:38:33）面向差 ~6°：使用者按
# 快照選的 E2 格（傳送板）在現場放大圖裡跑到右緣外——「放大圖不是指定的放大圖」。
# 兩側夾（E2 粗格 320×270，vision 實作重現）：真漂移 29.66（F2 側 21.6）vs
# 同面向差 3 秒 E2 0.04、idle 晃動最大格 D2 3.14。門檻沿用 reentry_remote_drift_diff
# =12.0（_rr_click 點擊守門同語意同區域大小）。

def test_h050_zoom_drift_detected_on_facing_offset():
    snap, live = _pair("h050_zoom_dir1_e2_snap.png", "h050_zoom_dir1_e2_live_drift.png")
    from miningbot import reentry_remote
    assert reentry_remote.zoom_drifted(snap, live, cfg.reentry_remote_drift_diff) is True


def test_h050_zoom_no_drift_on_static_cell_3s_apart():
    snap, later = _pair("h050_zoom_dir1_e2_snap.png", "h050_zoom_dir1_e2_snap_3s.png")
    from miningbot import reentry_remote
    assert reentry_remote.zoom_drifted(snap, later, cfg.reentry_remote_drift_diff) is False


def test_h050_zoom_no_drift_on_idle_wobble_cell():
    # D2＝角色 idle 晃動所在格（無漂移側最高 3.14）——不可誤判成漂移
    snap, later = _pair("h050_zoom_dir1_d2_snap.png", "h050_zoom_dir1_d2_snap_3s.png")
    from miningbot import reentry_remote
    assert reentry_remote.zoom_drifted(snap, later, cfg.reentry_remote_drift_diff) is False


def test_h050_zoom_drift_none_snapshot_is_not_drift():
    # 快照讀不到（檔案被清/佇列滿沒寫）→ 不守門，照現行行為發圖
    live = _read("h050_zoom_dir1_e2_live_drift.png")
    from miningbot import reentry_remote
    assert reentry_remote.zoom_drifted(None, live, cfg.reentry_remote_drift_diff) is False
