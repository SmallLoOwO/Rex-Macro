"""診斷記錄：正式 logging（檔案＋主控台、自動輪替）＋ 關鍵時刻畫面截圖。

目的：稀有礦很久才出現一次、需要長時間盯著；一旦偵測出錯或出狀況，
能從 log 與截圖快速找出病因（機器人「當下看到什麼、判斷了什麼」）。
"""
import itertools
import json
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import cv2

LOGGER_NAME = "miningbot"
_SNAPSHOT_INDEX_LOCK = threading.Lock()
_SNAPSHOT_NAME_LOCK = threading.Lock()
_SNAPSHOT_NAME_SEQ = itertools.count()

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
    reentry  — 自動回礦（reentry_click/success/giveup，查傳錯層/回礦失敗）；
    review   — needs_human/d3_fire/d3_miss/stuck（誤射/漏抓/卡住，要人眼看）；
    events   — chill/rare_found/audio_no_text（chill 與稀有偵測）；
    trace    — 其餘暫態敘事（d3_chat、harvest_success、mine_reset…）。
    """
    if label.startswith("reentry"):
        return "reentry"
    if "sweep_confirmed" in label:
        return "trackers"
    if any(k in label for k in (
            "needs_human", "d3_fire", "d3_miss", "stuck",
            "sweep_empty", "sweep_seen_once", "sweep_accepted",
            "aim_", "d4_unknown", "boost_count")):
        return "review"
    if any(k in label for k in ("chill", "rare_found", "audio")):
        return "events"
    return "trace"


def snapshot_path(log_dir: str, label: str, ts: str = None):
    """算快照分流路徑（不寫檔），回傳 (資料夾, 完整路徑)。

    給非同步存圖用：主線即時拿到路徑（事件 log 用），實際 imwrite 丟背景執行緒。
    """
    snap_dir = os.path.join(log_dir, "snapshots", snapshot_subdir(label))
    if ts is None:
        now_ns = time.time_ns()
        with _SNAPSHOT_NAME_LOCK:
            sequence = next(_SNAPSHOT_NAME_SEQ)
        ts = time.strftime(
            "%Y%m%d_%H%M%S", time.localtime(now_ns // 1_000_000_000))
        ts += "_%09d_%06d" % (now_ns % 1_000_000_000, sequence)
    return snap_dir, os.path.join(snap_dir, f"{ts}_{label}.png")


def append_snapshot_index(log_dir: str, label: str, path: str,
                          written_at: float | None = None) -> str:
    """Append a searchable JSONL entry after a snapshot is fully written."""
    prefix = (label or "").split("_", 1)[0]
    record = {
        "written_at": time.time() if written_at is None else written_at,
        "label": label,
        "path": os.path.abspath(path),
        "harvest_id": prefix if prefix.isdigit() else None,
    }
    index_path = os.path.join(os.path.abspath(log_dir), "snapshot_index.jsonl")
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with _SNAPSHOT_INDEX_LOCK:
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return index_path

def tmp_snapshot_path(path: str) -> str:
    """原子寫入用的暫存檔路徑：在最後副檔名前插 .part（**保留副檔名**）。

    cv2.imwrite 依「檔名最後一個副檔名」挑編碼器；若暫存檔取 ``path + ".part"``，
    副檔名會變 ``.part`` → cv2 拋「could not find a writer for the specified
    extension」→ 檔案沒寫出 → Discord sink 的 _wait_for_file 必逾時 → 每則通知
    退回純文字（2026-06-30 回歸：discord.log 全 NOIMG(wait-timeout)）。
    ``foo.png`` → ``foo.part.png``（cv2 認得 .png）；``os.replace`` 後仍為 ``foo.png``。
    """
    root, ext = os.path.splitext(path)
    return f"{root}.part{ext}"


def save_snapshot(frame, log_dir: str, label: str) -> str:
    """把當下畫面存成 log_dir/snapshots/<分類>/<時間>_<label>.png，回傳路徑。

    依 label 自動分流到分類子資料夾（見 snapshot_subdir）——事後只需讀相關資料夾。
    """
    snap_dir, path = snapshot_path(log_dir, label)
    os.makedirs(snap_dir, exist_ok=True)
    if not cv2.imwrite(path, frame):
        raise RuntimeError("cv2.imwrite returned False")
    append_snapshot_index(log_dir, label, path)
    return path


def plan_snapshot_cleanup(entries, now_ts, max_age_days, max_total_mb):
    """快照保留決策：先刪過期，仍超容量上限就從最舊開始刪到達標。

    純函式（entries 由呼叫端 os.scandir 收集）；632MB/OneDrive 同步夾的實測痛點對策。
    """
    cutoff = now_ts - max_age_days * 86400.0
    doomed = [p for p, m, _ in entries if m < cutoff]
    keep = sorted(((p, m, s) for p, m, s in entries if m >= cutoff), key=lambda e: e[1])
    total = sum(s for _, _, s in keep)
    cap = max_total_mb * 1024 * 1024
    i = 0
    while total > cap and i < len(keep):
        doomed.append(keep[i][0])
        total -= keep[i][2]
        i += 1
    return doomed


def plan_snapshot_cleanup_tiered(entries, now_ts, max_age_days, max_total_mb,
                                 category_limits=None):
    """先套分類保留政策，再對剩餘檔案套全域期限/容量上限。"""
    category_limits = category_limits or {}
    doomed = set()
    for category, (age_days, total_mb) in category_limits.items():
        group = [entry for entry in entries
                 if os.path.basename(os.path.dirname(entry[0])).lower() == category.lower()]
        doomed.update(plan_snapshot_cleanup(group, now_ts, age_days, total_mb))
    remaining = [entry for entry in entries if entry[0] not in doomed]
    doomed.update(plan_snapshot_cleanup(
        remaining, now_ts, max_age_days, max_total_mb))
    return [path for path, _mtime, _size in entries if path in doomed]


def snapshot_priority(label: str) -> int:
    """數字越小越優先；trace 可丟，事件/人工/reentry 等先寫。"""
    return 1 if snapshot_subdir(label) == "trace" else 0


def snapshot_enqueue_allowed(label: str, qsize: int, maxsize: int,
                             critical_reserve: int) -> bool:
    """trace 不得占用保留槽；關鍵類別可使用完整有界佇列。"""
    if maxsize < 1 or qsize >= maxsize:
        return False
    reserve = min(max(0, critical_reserve), maxsize)
    if snapshot_priority(label) > 0 and qsize >= maxsize - reserve:
        return False
    return True
