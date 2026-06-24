import logging
import os
import numpy as np
from miningbot.diagnostics import setup_logging, save_snapshot, LOGGER_NAME

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
