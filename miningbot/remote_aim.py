"""Discord 遠端瞄準（2026-07-11 spec）：giveup 附圖的近失候選編號／網格座標／
回覆解析／對齊計畫——全部純函式，I/O 在 main.Bot。"""
import re
from dataclasses import dataclass, field

GRID_COLS = "ABCDEF"
GRID_ROWS = "1234"


@dataclass(frozen=True)
class AimCandidate:
    number: int      # 全域流水編號（跨層跨方位，1 起）
    layer: str       # "mid"/"up"/"down"
    dir_idx: int     # 0-7（sweep 方位＝相對挖礦原視角的淨右轉數）
    pos: tuple       # (cx, cy) 拍攝當時的螢幕座標（位置先驗，非實彈座標）
    score: float     # 排序鍵（edge 優先；無 edge 用 colored-1.0 墊底排 edge 後）
    reason: str      # find_tracker 被拒原因（診斷顯示）


@dataclass
class SweepShot:
    layer: str
    dir_idx: int
    snapshot_path: str
    rejects: list    # vision.find_tracker collect_rejects 的 dict list


@dataclass
class AimContext:
    candidates: list          # [AimCandidate] 依 score 降冪、編號 1..n
    shots: list               # [SweepShot]
    pose_net_rotations: int   # giveup 收尾後的實際淨旋轉（絕對姿態；restore 過＝0）
    pose_pitch_layer: str     # giveup 收尾後俯仰層（歸位過＝"mid"）
    harvest_id: str
    created_at: float


def _rank_key(rej: dict) -> float:
    """排序鍵：有 edge 用 edge；無 edge（margin/exclude/preexist）用 colored-1.0
    墊底——形狀有分數的候選比純 HSV 近失更可信，一律排前面。"""
    if rej.get("edge") is not None:
        return float(rej["edge"])
    return float(rej.get("colored", 0.0)) - 1.0


def build_aim_context(shots, pose_net_rotations: int, pose_pitch_layer: str,
                      harvest_id: str, now: float, max_candidates: int = 9) -> AimContext:
    """把各 (層,方位) 的近失候選攤平、依分數降冪編號 1..n（上限 max_candidates 防洗版）。"""
    flat = []
    for s in shots:
        for r in s.rejects or []:
            flat.append((_rank_key(r), s.layer, s.dir_idx, r))
    flat.sort(key=lambda t: t[0], reverse=True)
    cands = [AimCandidate(number=i + 1, layer=layer, dir_idx=d,
                          pos=tuple(r["pos"]), score=key, reason=r["reason"])
             for i, (key, layer, d, r) in enumerate(flat[:max_candidates])]
    return AimContext(candidates=cands, shots=list(shots),
                      pose_net_rotations=pose_net_rotations,
                      pose_pitch_layer=pose_pitch_layer,
                      harvest_id=harvest_id, created_at=now)


def grid_cell_center(cell: str, w: int = 1920, h: int = 1080,
                     cols: int = 6, rows: int = 4):
    """網格代碼（如 "C3"）→ 格中心螢幕座標；不合法回 None。"""
    cell = (cell or "").strip().upper()
    if len(cell) != 2 or cell[0] not in GRID_COLS[:cols] or cell[1] not in GRID_ROWS[:rows]:
        return None
    ci = GRID_COLS.index(cell[0])
    ri = GRID_ROWS.index(cell[1])
    cw, ch = w // cols, h // rows
    return (ci * cw + cw // 2, ri * ch + ch // 2)


def draw_overlay(frame_bgr, candidates, grid: bool = True):
    """把候選框編號＋淡色網格疊到快照上（純函式，copy 後畫、不改輸入）。

    延遲 import cv2/np：解析/座標函式在無 OpenCV 環境也可測。
    """
    import cv2
    out = frame_bgr.copy()
    h, w = out.shape[:2]
    if grid:
        cols, rows = len(GRID_COLS), len(GRID_ROWS)
        cw, ch = w // cols, h // rows
        for i in range(1, cols):
            cv2.line(out, (i * cw, 0), (i * cw, h), (90, 90, 90), 1)
        for j in range(1, rows):
            cv2.line(out, (0, j * ch), (w, j * ch), (90, 90, 90), 1)
        for i in range(cols):
            for j in range(rows):
                cv2.putText(out, f"{GRID_COLS[i]}{GRID_ROWS[j]}",
                            (i * cw + 6, j * ch + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 140, 140), 1)
    for c in candidates:
        x, y = c.pos
        cv2.rectangle(out, (x - 36, y - 36), (x + 36, y + 36), (0, 215, 255), 3)
        cv2.putText(out, str(c.number), (x - 30, y - 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 215, 255), 3)
    return out
