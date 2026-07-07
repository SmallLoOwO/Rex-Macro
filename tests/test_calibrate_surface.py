"""calibrate_surface 純 helper 測試（CLI 本體是互動 I/O，不在此測）。"""
from miningbot.calibrate_surface import clamp_roi


def test_clamp_roi_inside_unchanged():
    assert clamp_roi((10, 20, 50, 40), 200, 100) == (10, 20, 50, 40)


def test_clamp_roi_clipped_to_frame():
    assert clamp_roi((-5, 90, 300, 40), 200, 100) == (0, 90, 200, 10)
