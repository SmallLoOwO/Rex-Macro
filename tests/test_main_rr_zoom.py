"""H050：`方位 粗格` 放大的漂移守門（2026-07-19 ep7 實錄）。

sweep 快照（使用者選格依據）與放大現場截圖之間面向可偏 ~6°（八方位轉滿一圈
的殘差/斜坡滑移），放大圖誠實反映現場、卻與使用者在快照上指的格子內容不符，
且全程無警示——「放大圖不是指定的放大圖」。守門＝比對快照同格 vs 現場同格
（門檻沿用 reentry_remote_drift_diff，兩側夾見 test_reentry_fixtures H050 組），
超標時訊息前置警告＋提示 📷 重掃；照發現場放大圖（點擊座標以現況為準）。
"""
import re

import numpy as np

from miningbot import main
from miningbot.main import Bot
from miningbot import reentry_remote


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


def _frame(gray: int):
    return np.full((1080, 1920, 3), gray, dtype=np.uint8)


def _write_png(path, img):
    import cv2
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))


def _zoom_bot(monkeypatch, tmp_path, snap_frame, live_frame):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._focus_roblox = lambda: True
    bot._rotate_verified = lambda direction: True
    bot._rr_snap_dir = lambda: str(tmp_path)
    bot.notes = []
    bot._rr_notify = lambda msg, **kw: bot.notes.append((msg, kw))
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=9, created_at=0.0, sticky_layer="L")
    ctx.cur_dir = 0
    if snap_frame is not None:
        spath = tmp_path / "reentry_ep9_dir1.png"
        _write_png(spath, snap_frame)
        ctx.shots = [(0, str(spath))]
    else:
        ctx.shots = [(0, "")]              # 快照沒寫成（佇列滿/被清）
    monkeypatch.setattr(main.capture, "grab", lambda: live_frame)
    return bot, ctx


def test_rr_zoom_warns_when_live_drifted_from_sweep_shot(monkeypatch, tmp_path):
    # 快照 E2 全暗 vs 現場 E2 全亮（diff >> 12.0）→ 警告＋照發現場放大圖
    bot, ctx = _zoom_bot(monkeypatch, tmp_path, _frame(20), _frame(200))
    bot._rr_zoom(ctx, 0, "E2")
    assert bot.notes, "應發出放大圖訊息"
    msg, kw = bot.notes[-1]
    assert "偏離" in msg                   # 前置警告：畫面已偏離八方位圖
    assert "🔍 方位 1 的 E2 格放大" in msg  # 原放大訊息仍在（照發）
    assert kw.get("image_paths")
    assert ctx.phase == "awaiting_fine"    # 流程不因警告中斷


def test_rr_zoom_no_warning_when_live_matches_shot(monkeypatch, tmp_path):
    same = _frame(128)
    bot, ctx = _zoom_bot(monkeypatch, tmp_path, same, same.copy())
    bot._rr_zoom(ctx, 0, "E2")
    msg, _kw = bot.notes[-1]
    assert "偏離" not in msg
    assert "🔍 方位 1 的 E2 格放大" in msg


def test_rr_zoom_missing_snapshot_skips_gate(monkeypatch, tmp_path):
    bot, ctx = _zoom_bot(monkeypatch, tmp_path, None, _frame(200))
    bot._rr_zoom(ctx, 0, "E2")
    msg, _kw = bot.notes[-1]
    assert "偏離" not in msg               # 讀不到快照＝不守門，照現行行為
    assert "🔍 方位 1 的 E2 格放大" in msg


def test_rr_zoom_filename_timestamped_no_overwrite(monkeypatch, tmp_path):
    # 同格重複放大不可互相覆蓋（ep7 實錄 E2 重放大只剩一份，事後無從比對）
    same = _frame(128)
    bot, ctx = _zoom_bot(monkeypatch, tmp_path, same, same.copy())
    bot._rr_zoom(ctx, 0, "E2")
    first = bot.notes[-1][1]["image_paths"][0]
    assert re.search(r"ep9_zoom_1E2_\d+\.png$", first)


def _sweep_bot(monkeypatch, tmp_path, rotate_results):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._mine_resetting = False
    calls = {"n": 0}

    def rotate(direction):
        calls["n"] += 1
        return rotate_results[calls["n"] - 1]
    bot._rotate_verified = rotate
    # 鏡頭距離歸位與本測試無關，但沒樁掉會掉進真 Win32：_zoom_normalize →
    # _zoom_key_verified → _focus_roblox 用 FindWindowW 找 "Roblox"。後果有二：
    # ① 測試結果取決於桌面上有沒有開著遊戲（找不到時走 logger.error 分支，本檔
    #    的 _LogRecorder 樁沒有 .error → AttributeError，紅在無關的地方）；
    # ② 遊戲開著時反而更糟——會真的送滾輪事件進遊戲。
    # 回 False＝視同沒動過距離，ctx.net_zoom 保持不變（同 _rr_sweep_and_send 原邏輯）。
    bot._zoom_normalize = lambda tag: False
    bot._snapshot = lambda f, label: str(tmp_path / f"{label}.png")
    bot._rr_sync_write = lambda img, label: str(tmp_path / f"{label}.png")
    bot.notes = []
    bot._rr_notify = lambda msg, **kw: bot.notes.append((msg, kw))
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=9, created_at=0.0, sticky_layer="L")
    ctx.cur_dir = 0
    bot._rr_ctx = ctx
    monkeypatch.setattr(main.capture, "grab", lambda: _frame(128))
    monkeypatch.setattr(main.remote_aim, "draw_grid", lambda img, c, r: None)
    return bot


def test_rr_sweep_warns_when_rotation_never_lands(monkeypatch, tmp_path):
    # H050：sweep 中旋轉重試用盡（回 False）→ 標籤錯位，head 必須帶警告
    bot = _sweep_bot(monkeypatch, tmp_path, [True] * 7 + [False])
    bot._rr_sweep_and_send()
    head_msg = bot.notes[0][0]
    assert "旋轉未生效" in head_msg


def test_rr_sweep_no_warning_when_all_rotations_land(monkeypatch, tmp_path):
    bot = _sweep_bot(monkeypatch, tmp_path, [True] * 8)
    bot._rr_sweep_and_send()
    head_msg = bot.notes[0][0]
    assert "旋轉未生效" not in head_msg
