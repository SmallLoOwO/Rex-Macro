"""重置後自動回礦（REENTRY）的純決策邏輯。

設計：docs/superpowers/specs/2026-07-08-mine-reentry-design.md。
比照 harvester：這裡只有可單測的純函式與狀態資料，所有 I/O 在 main._tick_reentry。
核心原則「寧漏勿誤」：低信心寧可 reroll（按回到地表換重生點，幾十秒）也不亂點
（點錯層級按鈕＝傳錯層，浪費一整輪還可能沒發現）。
"""
from dataclasses import dataclass
from difflib import SequenceMatcher

# 單輪 attempt 內的階段（str 比照 harvester 的輕量風格）
SURFACE_WAIT = "surface_wait"    # 已按回到地表，等傳送完成（幀差大變化）
PITCH_RESET = "pitch_reset"      # 俯仰歸位（拖到底夾限→回拉校準量）
SWEEP = "sweep"                  # 八方位掃面板
NAVIGATE = "navigate"            # 右鍵 click-to-move 走向面板
READ_PANEL = "read_panel"        # OCR 找目標層文字框（含遮擋階梯）
CLICK_VERIFY = "click_verify"    # 已點層級按鈕，等傳送＋礦內驗證


@dataclass
class ReentryState:
    attempts: int = 0            # 已失敗的 reroll 輪數
    phase: str = SURFACE_WAIT
    occlusion_tried: tuple = ()  # 本輪已試過的遮擋手段
    phase_started: float = 0.0   # time.time()，I/O 端維護
    attempt_started: float = 0.0


def pick_panel_direction(scores, threshold):
    """八方位掃描結果選方向。scores: [(dir_idx, score, center_xy)]。

    取最高分且 >= threshold；全部低於門檻回 None（呼叫端 reroll）——
    不取「矮子裡的高個」：門檻以下的匹配點下去多半不是面板。
    """
    best = None
    for item in scores:
        if item[1] >= threshold and (best is None or item[1] > best[1]):
            best = item
    return best


def movement_status(diffs, moving_thresh, stable_ticks):
    """click-to-move 途中判斷角色停了沒。diffs＝連續幀平均差序列。

    連續 stable_ticks 筆都低於 moving_thresh ＝ 停下（到位或卡住，交 OCR 分辨）；
    樣本不足一律 "moving"——剛點完就判停會提早進 OCR、把走到一半的模糊幀當遮擋。
    """
    if len(diffs) < stable_ticks:
        return "moving"
    recent = diffs[-stable_ticks:]
    return "stopped" if all(d <= moving_thresh for d in recent) else "moving"


_OCCLUSION_LADDER = ("orbit", "renavigate")


def next_occlusion_action(tried):
    """OCR 找不到目標層文字時的遮擋處理階梯（便宜→貴）：
    orbit（, 轉 45°，角色離開面板與鏡頭之間）→ renavigate（再右鍵重導航一次，
    實測有時能讓角色站到側邊）→ reroll。
    """
    for a in _OCCLUSION_LADDER:
        if a not in tried:
            return a
    return "reroll"


def should_giveup(attempts, max_attempts):
    return attempts >= max_attempts


def _norm(s):
    return " ".join(s.lower().split())


def pick_layer_button(records, target_name, decoy_names, min_ratio):
    """從 OCR 文字框挑目標層按鈕，回 center 座標或 None。

    records: ocr.read_text_boxes 輸出 [{'text','score','center',...}]。
    命中條件（寧漏勿誤，比照 rare vs common 雙向最近鄰）：
    對 target 的相似度 >= min_ratio 且 **嚴格大於** 對任一 decoy（其他按鈕含
    Back to pre-reset location）的相似度——打平＝分不清＝不點。
    """
    tgt = _norm(target_name)
    decoys = [_norm(d) for d in decoy_names]
    best = None
    for r in records:
        t = _norm(r["text"])
        tr = SequenceMatcher(None, t, tgt).ratio()
        if tr < min_ratio:
            continue
        dr = max((SequenceMatcher(None, t, d).ratio() for d in decoys), default=0.0)
        if tr > dr and (best is None or tr > best[0]):
            best = (tr, r["center"])
    return best[1] if best else None
