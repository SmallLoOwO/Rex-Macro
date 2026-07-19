import logging
import os
import numpy as np
from miningbot.diagnostics import (setup_logging, save_snapshot, LOGGER_NAME,
                                   tmp_snapshot_path, plan_snapshot_cleanup,
                                   plan_snapshot_cleanup_tiered,
                                   snapshot_enqueue_allowed, snapshot_priority,
                                   snapshot_path, snapshot_subdir,
                                   append_snapshot_index)

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


def test_tiered_cleanup_expires_trace_before_review():
    entries = [
        (os.path.join("snapshots", "trace", "old.png"), 0.0, 10),
        (os.path.join("snapshots", "review", "old.png"), 0.0, 10),
    ]

    got = plan_snapshot_cleanup_tiered(
        entries,
        now_ts=8 * DAY,
        max_age_days=30,
        max_total_mb=1024,
        category_limits={"trace": (7, 256)},
    )

    assert got == [os.path.join("snapshots", "trace", "old.png")]


def test_snapshot_queue_reserves_capacity_for_critical_categories():
    assert snapshot_enqueue_allowed("routine", qsize=12, maxsize=16, critical_reserve=4) is False
    assert snapshot_enqueue_allowed("rare_found", qsize=12, maxsize=16, critical_reserve=4) is True
    assert snapshot_enqueue_allowed("rare_found", qsize=16, maxsize=16, critical_reserve=4) is False
    assert snapshot_priority("rare_found") < snapshot_priority("routine")


def test_harvest_recovery_snapshots_use_critical_review_storage():
    assert snapshot_subdir("079_sweep_empty_dir0") == "review"
    assert snapshot_subdir("079_sweep_seen_once_dir3") == "review"
    assert snapshot_subdir("079_aim_fire_500x400") == "review"


def test_d4_unknown_snapshot_goes_to_review():
    # D4 未知文字 hold 快照要人眼核對（誤讀樣本＝下次 fuzzy 修復的證據），
    # 落 trace 會被清檔政策掃掉（079 教訓）
    assert snapshot_subdir("d4_unknown") == "review"
    assert snapshot_priority("079_sweep_empty_dir0") == 0


def test_boost_count_unreadable_goes_to_review():
    # 計數器讀不出的全幀＝數字模板增補素材（缺 5/7 類的字元證據），
    # 同 d4_unknown 理由不可落 trace 被清
    assert snapshot_subdir("boost_count_unreadable") == "review"


def test_snapshot_path_default_does_not_overwrite_same_label(tmp_path):
    _, first = snapshot_path(str(tmp_path), "079_d3_fire")
    _, second = snapshot_path(str(tmp_path), "079_d3_fire")
    assert first != second


def test_snapshot_index_records_absolute_path_and_harvest_id(tmp_path):
    import json

    image_path = tmp_path / "snapshots" / "review" / "079_d3_fire.png"
    index_path = append_snapshot_index(
        str(tmp_path), "079_d3_fire_500x400", str(image_path), written_at=123.0)
    with open(index_path, encoding="utf-8") as f:
        record = json.loads(f.readline())
    assert record == {
        "written_at": 123.0,
        "label": "079_d3_fire_500x400",
        "path": os.path.abspath(image_path),
        "harvest_id": "079",
    }


def test_snapshot_path_sequence_survives_identical_windows_clock_ticks(
        tmp_path, monkeypatch):
    monkeypatch.setattr("miningbot.diagnostics.time.time_ns", lambda: 1234567890000000000)
    _, first = snapshot_path(str(tmp_path), "079_d3_fire")
    _, second = snapshot_path(str(tmp_path), "079_d3_fire")
    assert first != second
