import logging
import os
import numpy as np
from miningbot.diagnostics import (setup_logging, save_snapshot, LOGGER_NAME,
                                   tmp_snapshot_path, plan_snapshot_cleanup)

def test_setup_logging_creates_dir_and_handlers(tmp_path):
    logger = setup_logging(str(tmp_path / "logs"), "DEBUG")
    assert logger.name == LOGGER_NAME
    assert logger.handlers            # 有掛上 handler
    assert (tmp_path / "logs").is_dir()
    assert logger.level == logging.DEBUG

def test_setup_logging_idempotent(tmp_path):
    d = str(tmp_path / "logs2")
    a = setup_logging(d, "INFO")
    n = len(a.handlers)
    b = setup_logging(d, "INFO")
    assert a is b
    assert len(b.handlers) == n        # 重複呼叫不重複加 handler

def test_save_snapshot_writes_png(tmp_path):
    frame = np.zeros((20, 30, 3), np.uint8)
    path = save_snapshot(frame, str(tmp_path / "logs"), "rare_found")
    assert os.path.exists(path)
    assert path.endswith(".png")
    assert "rare_found" in os.path.basename(path)


def test_tmp_snapshot_path_keeps_png_extension_for_cv2(tmp_path):
    # ★ 回歸：2026-06-30 非同步快照 worker 用 path+".part" 當暫存檔，cv2.imwrite 看
    #   .part 副檔名拋「could not find a writer for the specified extension」→ 快照
    #   沒寫出 → notify.py 的 _wait_for_file 全逾時 → discord.log 每 則 NOIMG(wait-timeout)。
    #   暫存檔必須保留 .png 副檔名；cv2.imwrite(tmp) 在舊邏輯下會直接拋錯。
    import cv2
    final = str(tmp_path / "20260630_113255_H004_needs_human.png")
    tmp = tmp_snapshot_path(final)
    assert tmp != final
    assert tmp.endswith(".png")                     # cv2 靠檔名副檔名挑編碼器
    assert ".part" in tmp                           # 仍是原子寫入暫存檔
    frame = np.zeros((20, 30, 3), np.uint8)
    assert cv2.imwrite(tmp, frame)                  # 舊 path+".part" 會在此拋 cv2.error
    os.replace(tmp, final)                          # 模擬 worker 的原子改名
    assert os.path.exists(final) and not os.path.exists(tmp)


DAY = 86400.0

def test_cleanup_deletes_only_expired_when_under_cap():
    entries = [("old.png", 0.0, 10), ("new.png", 40 * DAY, 10)]
    assert plan_snapshot_cleanup(entries, now_ts=41 * DAY,
                                 max_age_days=30, max_total_mb=1000) == ["old.png"]

def test_cleanup_evicts_oldest_first_to_meet_cap():
    mb = 1024 * 1024
    entries = [("a.png", 1 * DAY, 600 * mb), ("b.png", 2 * DAY, 600 * mb),
               ("c.png", 3 * DAY, 600 * mb)]
    got = plan_snapshot_cleanup(entries, now_ts=4 * DAY, max_age_days=365, max_total_mb=1024)
    assert got == ["a.png", "b.png"]   # 刪到 ≤1GB，留最新

def test_cleanup_noop_when_fresh_and_small():
    entries = [("a.png", 9 * DAY, 100)]
    assert plan_snapshot_cleanup(entries, now_ts=10 * DAY,
                                 max_age_days=30, max_total_mb=1000) == []
