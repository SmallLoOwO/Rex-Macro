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

# 子系統 logger（propagate=False，訊息只進自己檔，不污染主 log）
# key=子系統名（ miningbot.<key>），value=輸出檔名
_SUBLOGGERS = {
    "heartbeat": "heartbeat.log",   # 心跳噪音隔離
    "mining":    "actions.log",     # boost/D4 重複動作隔離
    "harvest":   "harvest.log",     # 採集 sweep/D3 verify 細節（除錯重點）
    "discord":   "discord.log",     # Discord 通知送出記錄（哪些事件送了、成敗）
}


def _make_file_handler(log_dir: str, filename: str, fmt: logging.Formatter) -> RotatingFileHandler:
    fh = RotatingFileHandler(os.path.join(log_dir, filename),
                             maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    return fh


def setup_logging(log_dir: str, level: str) -> logging.Logger:
    """設定 miningbot logger：主檔 miningbot.log（主敘事）+ stdout + 三個子系統分檔。

    主檔收啟動/狀態切換/里程碑/alert/error；心跳、重複 mining 動作、採集細節各自獨立檔
    （heartbeat.log / actions.log / harvest.log），靠 propagate=False 隔離不冒泡到主檔。
    重複呼叫不會重複加 handler（root 與子 logger 皆冪等）。
    """
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if logger.handlers:                      # root 已設定過就直接回傳（子 logger 同步冪等）
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    # 主檔 + stdout（主敘事）；pythonw 無 console（sys.stdout is None）→ 跳過 stdout handler
    logger.addHandler(_make_file_handler(log_dir, "miningbot.log", fmt))
    if sys.stdout is not None:
        try:                                 # 讓主控台也能正確顯示中文（Windows 預設非 UTF-8）
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    # 子系統 logger（隔離噪音；各自獨立檔，不冒泡到 root）
    for sub_name, filename in _SUBLOGGERS.items():
        sub = logging.getLogger(f"{LOGGER_NAME}.{sub_name}")
        if sub.handlers:                     # 已設定過，跳過（冪等）
            continue
        sub.propagate = False                # 不冒泡到 root，只寫自己檔
        sub.setLevel(logging.DEBUG)          # 子檔收全量，過濾靠呼叫端路由
        sub.addHandler(_make_file_handler(log_dir, filename, fmt))
    return logger


def get_logger(subsystem: str) -> logging.Logger:
    """取得子系統 logger（例如 get_logger('harvest') → miningbot.harvest）。

    subsystem 必須是 _SUBLOGGERS 的 key 之一；否則回傳的 logger 沒有專屬 handler
    （訊息會因 propagate=False 而被丟棄）。
    """
    return logging.getLogger(f"{LOGGER_NAME}.{subsystem}")


def snapshot_subdir(label: str) -> str:
    """依 label 決定快照分類子資料夾，讓事後篩選只需讀相關資料夾（不必全部載入）。

    trackers — sweep_confirmed 真追蹤框（建模板的金礦）；
    review   — needs_human/d3_fire/d3_miss/stuck（誤射/漏抓/卡住，要人眼看）；
    events   — chill/rare_found/audio_no_text（chill 與稀有偵測）；
    trace    — 其餘暫態敘事（d3_chat、harvest_success、mine_reset…）。
    """
    if "sweep_confirmed" in label:
        return "trackers"
    if any(k in label for k in ("needs_human", "d3_fire", "d3_miss", "stuck")):
        return "review"
    if any(k in label for k in ("chill", "rare_found", "audio")):
        return "events"
    return "trace"


def save_snapshot(frame, log_dir: str, label: str) -> str:
    """把當下畫面存成 log_dir/snapshots/<分類>/<時間>_<label>.png，回傳路徑。

    依 label 自動分流到分類子資料夾（見 snapshot_subdir）——事後只需讀相關資料夾。
    """
    snap_dir = os.path.join(log_dir, "snapshots", snapshot_subdir(label))
    os.makedirs(snap_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(snap_dir, f"{ts}_{label}.png")
    cv2.imwrite(path, frame)
    return path
