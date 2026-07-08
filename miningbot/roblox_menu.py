"""Roblox 內建設定選單的 OCR 錨定驅動——純決策邏輯。

設計：docs/superpowers/specs/2026-07-08-menu-preflight-boost-design.md 第 1 節。
比照 reentry.py：這裡只有可單測的純函式（吃 OCR 文字框列表，回決策），所有 I/O
（Esc/點擊/捲動/截圖/OCR 呼叫本身）在 main.Bot._set_movement_mode。
核心原則「寧漏勿誤」：模糊比對必須嚴格贏過其他候選才算命中（比照
reentry.pick_layer_button 的雙向最近鄰），打平/都低分一律回「沒找到」，
交呼叫端走 Esc 回中性＋重試，而非用猜的硬點下去。
"""
from difflib import SequenceMatcher

# 選單分頁列固定會出現的文字（用於判斷 Esc 後選單是否真的開了）
_TAB_LABELS = ("people", "settings", "gallery", "report", "help")


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def menu_open(records, min_ratio: float) -> bool:
    """OCR 文字框裡看不看得到分頁列（People/Settings/...）任一個——選單開了的訊號。

    records 為空或找不到任何分頁字樣 → False（呼叫端判定 Esc 沒開成功或選單已關）。
    """
    for r in records:
        t = _norm(r["text"])
        for label in _TAB_LABELS:
            if SequenceMatcher(None, t, label).ratio() >= min_ratio:
                return True
    return False


def find_tab_center(records, tab_name: str, min_ratio: float):
    """找分頁文字框中心（點擊用）。取最高分且達門檻者；找不到回 None。"""
    tgt = _norm(tab_name)
    best = None
    for r in records:
        ratio = SequenceMatcher(None, _norm(r["text"]), tgt).ratio()
        if ratio >= min_ratio and (best is None or ratio > best[0]):
            best = (ratio, r["center"])
    return best[1] if best else None


def find_label_row_y(records, label: str, min_ratio: float):
    """找標籤（如 "Movement Mode"）所在列的螢幕 y 座標。取最高分且達門檻者；找不到回 None。"""
    tgt = _norm(label)
    best = None
    for r in records:
        ratio = SequenceMatcher(None, _norm(r["text"]), tgt).ratio()
        if ratio >= min_ratio and (best is None or ratio > best[0]):
            best = (ratio, r["center"][1])
    return best[1] if best else None


def read_row_value(records, row_y: int, value_x_range, y_tol: int):
    """在同一列（|y - row_y| <= y_tol）且 x 落在 value_x_range 內取值文字。找不到回 None。

    只回第一個符合的文字框——選單一列的值欄只會有一段文字，多個符合代表 OCR
    把值切成多段（目前遇到的實機案例都是單一文字框），暫不處理合併。
    """
    lo, hi = value_x_range
    for r in records:
        cx, cy = r["center"]
        if abs(cy - row_y) <= y_tol and lo <= cx <= hi:
            return r["text"]
    return None


def value_matches_target(value_text, target: str, other_options, min_ratio: float) -> bool:
    """value_text 是否等於 target——模糊比對且嚴格贏過 other_options 裡的每一個。

    value_text 為 None（該列沒讀到值）一律 False。打平或都低分＝分不清，回 False
    （寧漏勿誤：呼叫端會判斷「還沒到目標」而繼續點右箭頭，而不是誤判成功提早收工）。
    """
    if value_text is None:
        return False
    t = _norm(value_text)
    tgt_ratio = SequenceMatcher(None, t, _norm(target)).ratio()
    if tgt_ratio < min_ratio:
        return False
    other_ratio = max((SequenceMatcher(None, t, _norm(o)).ratio() for o in other_options),
                      default=0.0)
    return tgt_ratio > other_ratio
