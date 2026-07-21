"""harvest 101 手動瞄準精定位：_detect_core_in_cell 編排邏輯（Phase 2）。

驗證 grid 路徑限縮偵測的座標映射、命中/未命中分流、素材 log label、預算與格無效守門。
純邏輯——capture/vision/_hsnap 全 monkeypatch，不碰真實 I/O。
"""
import numpy as np

from miningbot import main
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, msg, *a):
        self.records.append(msg % a if a else msg)

    def warning(self, msg, *a):
        self.records.append(msg % a if a else msg)


def _bare_bot():
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    return bot


def _patch_io(monkeypatch, detect_result, frame=None):
    """統一 monkeypatch：grab 回固定幀、detect_tracker_core 回可控結果、放大圖＋快照 no-op。"""
    monkeypatch.setattr(main.cfg, "remote_aim_zoom_margin_frac", 0.0)   # C1→(640,0,320,270)
    monkeypatch.setattr(main.cfg, "remote_aim_fine_grid", 6)
    monkeypatch.setattr(main.cfg, "reentry_remote_zoom_scale", 3)
    frame = np.zeros((1080, 1920, 3), np.uint8) if frame is None else frame
    monkeypatch.setattr(main.capture, "grab", lambda: frame)
    monkeypatch.setattr(main.vision, "detect_tracker_core",
                        lambda crop, profiles, **kw: detect_result)
    monkeypatch.setattr(main.reentry_remote, "render_zoom",
                        lambda f, r, **k: np.zeros((10, 10, 3), np.uint8))
    return frame


def test_detect_core_hit_maps_region_origin_to_absolute(monkeypatch):
    # 101 真值：框在 C1、偵測回相對 (211,189) → +原點 (640,0) = (851,189)、0px 誤差
    bot = _bare_bot()
    _patch_io(monkeypatch, (211, 189, "green", 0.35))
    snapped = []
    monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: snapped.append(("crop", l)))
    monkeypatch.setattr(bot, "_hsnap", lambda f, l: snapped.append(("big", l)))

    pos, score, detail = bot._detect_core_in_cell("C1", 4, deadline=1e12, hid="101")

    assert pos == (851, 189)
    assert score == 0.35
    assert detail == ""
    # 命中：記裁格＋放大圖，但不記 miss label
    assert ("crop", "aim_cell_dir4_C1") in snapped
    assert any("zoom" in l for _, l in snapped)
    assert not any("miss" in l for _, l in snapped)


def test_detect_core_crop_region_matches_grid_cell(monkeypatch):
    # cell_crop 尺寸＝region 大小：C1 margin 0 → (270, 320, 3)
    bot = _bare_bot()
    seen = {}
    monkeypatch.setattr(main.cfg, "remote_aim_zoom_margin_frac", 0.0)
    monkeypatch.setattr(main.capture, "grab",
                        lambda: np.zeros((1080, 1920, 3), np.uint8))

    def spy(crop, profiles, **kw):
        seen["shape"] = crop.shape
        return (100, 100, "green", 0.2)

    monkeypatch.setattr(main.vision, "detect_tracker_core", spy)
    monkeypatch.setattr(main.reentry_remote, "render_zoom",
                        lambda f, r, **k: np.zeros((10, 10, 3), np.uint8))
    monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: None)
    monkeypatch.setattr(bot, "_hsnap", lambda f, l: None)
    bot._detect_core_in_cell("C1", 4, deadline=1e12, hid="101")
    assert seen["shape"] == (270, 320, 3)


def test_detect_core_miss_logs_miss_label_and_no_blind_fire(monkeypatch):
    # 未命中：不盲打、回 detail；另記 aim_core_miss label（補色系 profile fixture 來源）
    bot = _bare_bot()
    _patch_io(monkeypatch, None)
    snapped = []
    monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: snapped.append(l))
    monkeypatch.setattr(bot, "_hsnap", lambda f, l: snapped.append(l))

    pos, score, detail = bot._detect_core_in_cell("C1", 4, deadline=1e12, hid="101")

    assert pos is None and score == -1.0
    assert "未命中" in detail and "C1" in detail
    assert "aim_cell_dir4_C1" in snapped       # 每次裁格都記
    assert "aim_core_miss_dir4_C1" in snapped  # miss 額外記


def test_detect_core_invalid_cell(monkeypatch):
    bot = _bare_bot()
    _patch_io(monkeypatch, (10, 10, "green", 0.2))
    monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: None)
    monkeypatch.setattr(bot, "_hsnap", lambda f, l: None)
    pos, score, detail = bot._detect_core_in_cell("Z9", 4, deadline=1e12, hid="101")
    assert pos is None and "無效" in detail


def test_detect_core_deadline_exhausted(monkeypatch):
    bot = _bare_bot()
    monkeypatch.setattr(main.time, "time", lambda: 100.0)
    pos, score, detail = bot._detect_core_in_cell("C1", 4, deadline=50.0, hid="101")
    assert pos is None and detail == "預算用盡"
