"""診斷記錄：正式 logging（檔案＋主控台、自動輪替）＋ 關鍵時刻畫面截圖。

目的：稀有礦很久才出現一次、需要長時間盯著；一旦偵測出錯或出狀況，
能從 log 與截圖快速找出病因（機器人「當下看到什麼、判斷了什麼」）。
"""
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

import cv2

LOGGER_NAME = "miningbot"


def setup_logging(log_dir: str, level: str) -> logging.Logger:
    """設定 miningbot logger：輸出到 log_dir/miningbot.log（輪替）與主控台。

    重複呼叫不會重複加 handler。level 例如 "INFO"、"DEBUG"。
    """
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if logger.handlers:                      # 已設定過就直接回傳
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(os.path.join(log_dir, "miningbot.log"),
                             maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    try:                                     # 讓主控台也能正確顯示中文（Windows 預設非 UTF-8）
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def save_snapshot(frame, log_dir: str, label: str) -> str:
    """把當下畫面存成 log_dir/snapshots/<時間>_<label>.png，回傳路徑。"""
    snap_dir = os.path.join(log_dir, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(snap_dir, f"{ts}_{label}.png")
    cv2.imwrite(path, frame)
    return path
