"""Discord 遠端瞄準（2026-07-11 spec）：giveup 附圖的近失候選編號／網格座標／
回覆解析／對齊計畫——全部純函式，I/O 在 main.Bot。"""
import re
from dataclasses import dataclass, field

GRID_COLS = "ABCDEF"
GRID_ROWS = "123456"


def dir_label(dir_idx: int) -> int:
    """內部 dir_idx（0-7）→ 使用者看到的方位編號（1-8）。

    H056：回礦介面 2026-07-18 起就是「方位 1-8」（`reentry_remote` 同名慣例），
    瞄準介面卻留在 0-7；使用者在兩邊之間換算而指錯方位（097 看 `DIR 4` 的圖打 `5`，
    腳本轉到 dir5 的另一個畫面）。此後**所有對外顯示與輸入一律 1-8**，
    內部 dir_idx 仍 0-based——轉換只在這裡與 parse_reply 發生。
    """
    return dir_idx + 1


@dataclass(frozen=True)
class AimCandidate:
    number: int      # 全域流水編號（跨層跨方位，1 起）
    layer: str       # "mid"/"up"/"down"
    dir_idx: int     # 0-7（sweep 方位＝相對挖礦原視角的淨右轉數）
    pos: tuple       # (cx, cy) 拍攝當時的螢幕座標（位置先驗，非實彈座標）
    score: float     # 排序鍵（edge 優先；無 edge 用 colored-1.0 墊底排 edge 後）
    reason: str      # find_tracker 被拒原因（診斷顯示）
    source: str = 'near_miss'
    status: str = 'rejected'
    snapshot_path: str = ''


@dataclass(frozen=True)
class TargetObservation:
    '''Episode-level evidence for a tracker that was accepted or fired at.

    dir_idx is the absolute direction relative to the episode origin, rather
    than the local index of a later resweep.
    '''

    layer: str
    dir_idx: int
    pos: tuple
    score: float
    status: str
    source: str
    snapshot_path: str


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
    # 放大手選退路（harvest 101 §5 步驟 5；限縮偵測未命中時進入）
    awaiting_fine: bool = False        # True＝等細格（玩家看放大圖選格子）
    fine_tgt_layer: str = "mid"        # 退路開火目標層（grid 對齊過的層）
    fine_tgt_dir: int = 0              # 退路開火目標方位（內部 0-based）
    fine_cell: str = ""                # 目前放大的粗格代碼
    zoom_region: tuple = ()            # 當前放大區域 (x, y, w, h)
    zoom_stack: list = field(default_factory=list)  # 連鎖放大層歷史 [{region, scale}]
    zoom_scale: int = 0                # 當前層渲染倍率
    fov_state0: bool = False           # 發圖時 boost 狀態（FOV 一致性守門基準）
    fov_rechecks: int = 0              # FOV 作廢重發次數（bounded by remote_aim_fov_recheck_max）


def _rank_key(rej: dict) -> float:
    """排序鍵：有 edge 用 edge；無 edge（margin/exclude/preexist）用 colored-1.0
    墊底——形狀有分數的候選比純 HSV 近失更可信，一律排前面。"""
    if rej.get("edge") is not None:
        return float(rej["edge"])
    return float(rej.get("colored", 0.0)) - 1.0


def _dedup_rejects(rejects, radius_px: int):
    """H056：同一張畫面內距離 < radius_px 的近失候選合併，只留最高分。

    HSV 會把同一塊大色面（097 是角色的紅武器＋彩虹碎片衣裝）切成數個 blob，
    097 實機 DIR1 三筆 (569,924)/(534,952)/(570,951) 相距 27~45px、分數同為 0.34，
    佔掉 9 個名額中的 3 個。半徑取 60 < 追蹤框寬（實機 100~207px）——兩個真框
    若靠這麼近，框身早已大幅重疊，不可能是兩個獨立目標。
    只在同一 (層,方位) 內合併：不同方位是不同畫面，同螢幕座標沒有意義。
    """
    if radius_px <= 0:
        return list(rejects)
    kept, kept_pos = [], []
    for r in sorted(rejects, key=_rank_key, reverse=True):
        x, y = r["pos"]
        if any((x - kx) ** 2 + (y - ky) ** 2 < radius_px ** 2 for kx, ky in kept_pos):
            continue
        kept.append(r)
        kept_pos.append((x, y))
    return kept


def build_aim_context(shots, pose_net_rotations: int, pose_pitch_layer: str,
                      harvest_id: str, now: float, max_candidates: int = 9,
                      observations=None, dedup_radius_px: int = 60) -> AimContext:
    """把各 (層,方位) 的近失候選攤平、依分數降冪編號 1..n（上限 max_candidates 防洗版）。

    攤平前先做同層同方位的空間去重（H056），避免一塊衣裝吃掉多個編號名額。
    """
    shot_list = list(shots)
    observation_list = list(observations or ())

    # Accepted/fired evidence is more actionable than a detector near miss, even
    # when its numeric score is lower. Rank within each evidence class by score.
    observed = sorted(observation_list, key=lambda o: o.score, reverse=True)
    rejected = []
    for s in shot_list:
        for r in _dedup_rejects(s.rejects or [], dedup_radius_px):
            rejected.append((_rank_key(r), s.layer, s.dir_idx,
                             s.snapshot_path, r))
    rejected.sort(key=lambda t: t[0], reverse=True)

    ranked = [AimCandidate(number=0, layer=o.layer, dir_idx=o.dir_idx,
                           pos=tuple(o.pos), score=float(o.score),
                           reason=o.source, source=o.source, status=o.status,
                           snapshot_path=o.snapshot_path)
              for o in observed]
    ranked.extend(
        AimCandidate(number=0, layer=layer, dir_idx=d,
                     pos=tuple(r["pos"]), score=key, reason=r["reason"],
                     source=r.get("source", "near_miss"),
                     status=r.get("status", "rejected"),
                     snapshot_path=snapshot_path)
        for key, layer, d, snapshot_path, r in rejected
    )
    cands = [AimCandidate(number=i + 1, layer=c.layer, dir_idx=c.dir_idx,
                          pos=c.pos, score=c.score, reason=c.reason,
                          source=c.source, status=c.status,
                          snapshot_path=c.snapshot_path)
             for i, c in enumerate(ranked[:max_candidates])]

    # The current renderer operates on AimContext.shots. Mirror observation
    # snapshots there so accepted/fired evidence is immediately renderable.
    shot_keys = {(s.layer, s.dir_idx, s.snapshot_path) for s in shot_list}
    for o in observation_list:
        key = (o.layer, o.dir_idx, o.snapshot_path)
        if o.snapshot_path and key not in shot_keys:
            shot_list.append(SweepShot(layer=o.layer, dir_idx=o.dir_idx,
                                       snapshot_path=o.snapshot_path, rejects=[]))
            shot_keys.add(key)

    return AimContext(candidates=cands, shots=shot_list,
                      pose_net_rotations=pose_net_rotations,
                      pose_pitch_layer=pose_pitch_layer,
                      harvest_id=harvest_id, created_at=now)



def pick_recovery_observation(observations):
    """Pick the newest strongest evidence class for one bounded recovery.

    A fired target outranks an accepted target, which outranks a one-frame sighting.
    Within the same class the newest observation wins because it best reflects the
    latest FOV and tracker position.
    """
    priority = {"seen_once": 1, "accepted": 2, "fired": 3}
    eligible = [(index, observation) for index, observation in enumerate(observations)
                if observation.status in priority]
    if not eligible:
        return None
    return max(eligible,
               key=lambda item: (priority[item[1].status], item[0]))[1]

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


def grid_cell_of(pos, w: int = 1920, h: int = 1080,
                 cols: int = 6, rows: int = 4):
    """螢幕座標 → 網格代碼（如 "C3"）；grid_cell_center 的逆函式。畫面外回 None。

    候選總表用它把已存座標反算成「約C3」，操作者不用自己對格線。
    """
    x, y = int(pos[0]), int(pos[1])
    if not (0 <= x < w and 0 <= y < h):
        return None
    ci = min(x * cols // w, cols - 1)
    ri = min(y * rows // h, rows - 1)
    return f"{GRID_COLS[ci]}{GRID_ROWS[ri]}"


def grid_cell_region(cell: str, margin_frac: float = 0.0, w: int = 1920, h: int = 1080,
                     cols: int = 6, rows: int = 4):
    """粗格代碼 → 原幀裁圖區域 (x, y, rw, rh)，可加對稱餘裕並 clamp 在畫面內；不合法回 None。

    harvest 101 手動瞄準精定位用：玩家選的粗格只給偵測器掃那一格（限縮偵測範圍＝避開
    全幀干擾與假陽性）。margin_frac>0 時往四周各擴 margin_frac×格寬/格高，邊界格頂/底緣
    clamp 到 0/w/h（C1 頂緣 y0=0）。與 reentry_remote.coarse_cell_region 同格大小但多餘裕。
    """
    cell = (cell or "").strip().upper()
    if len(cell) != 2 or cell[0] not in GRID_COLS[:cols] or cell[1] not in GRID_ROWS[:rows]:
        return None
    cw, ch = w // cols, h // rows
    ox = GRID_COLS.index(cell[0]) * cw
    oy = GRID_ROWS.index(cell[1]) * ch
    mx = int(margin_frac * cw)
    my = int(margin_frac * ch)
    x0 = max(0, ox - mx)
    y0 = max(0, oy - my)
    x1 = min(w, ox + cw + mx)
    y1 = min(h, oy + ch + my)
    return (x0, y0, x1 - x0, y1 - y0)


def fov_state_consistent(state0, state1) -> bool:
    """退路（放大手選）FOV 一致性守門（harvest 101 spec §4）：兩 boost 狀態相等→True。

    退路有人延遲窗（發圖→玩家思考→回細格），窗內 boost 若到期/作用變 FOV → 框位移、
    放大圖作廢。state0＝發圖時 boost 在否、state1＝開火前重讀 boost 在否；不一致即作廢重發。
    自動路徑（偵測幀→開火背靠背）FOV 天然一致，不走此閘。
    """
    return bool(state0) == bool(state1)


_CIRCLED = "①②③④⑤⑥⑦⑧⑨"


def circled(n: int) -> str:
    """候選編號顯示字：1..9 → ①..⑨；超出回 "(n)"（防禦，現行上限 9）。"""
    return _CIRCLED[n - 1] if 1 <= n <= 9 else f"({n})"


# 原因/狀態代碼 → 中文短語（總表與 caption 用；圖上標頭仍英文——cv2 無中文字型）。
# near-miss 用 reason（vision.find_tracker collect_rejects）；觀測證據用 status。
REASON_LABELS = {
    "hard_rej": "形狀分不足", "soft": "形狀弱訊號", "margin": "太靠邊",
    "exclude": "在排除區", "preexist": "掃描前已存在",
    "fired": "射過未確認", "accepted": "曾鎖定", "seen_once": "單幀目擊",
}

_OBS_STATUSES = ("fired", "accepted", "seen_once")


def format_candidate_summary(candidates) -> str:
    """候選總表（一行一候選）：編號↔方位↔格子↔分數↔原因，一眼可對圖。

    - ① 是觀測證據（掃到過但沒採到）→「（最優）…回 1 快速重採」提示行。
    - score ≥ 0（有 edge）顯示「分數x.xx」；< 0（HSV-only，排序鍵 colored−1.0）
      顯示「色x.xx」，不出現負數。
    - 未知代碼原樣顯示（清單漂移要浮出來，不吞）。
    """
    lines = []
    for c in candidates:
        cell = grid_cell_of(c.pos) or "?"
        key = c.status if c.status in _OBS_STATUSES else c.reason
        label = REASON_LABELS.get(key, key)
        if c.number == 1 and c.status in _OBS_STATUSES:
            lines.append(f"①（最優）方位{dir_label(c.dir_idx)}・約{cell}・{label}"
                         f"——回 1 快速重採")
        else:
            score = (f"分數{c.score:.2f}" if c.score >= 0
                     else f"色{c.score + 1.0:.2f}")
            lines.append(f"{circled(c.number)} 方位{dir_label(c.dir_idx)}・約{cell}・"
                         f"{score}・{label}")
    return "\n".join(lines)


AIM_GROUP_HEADER = ("🎯 近失候選——回編號（如 `2`）腳本自動對齊射擊；"
                    "`跳過` 回挖礦；`手動` 最後手段（重掃＋全方位圖）")
MANUAL_SURVEY_HELP = ("🧭 手動瞄準（D2 已重掃、效果窗內實況）——回 `方位 格子` 射擊（方位 1-8）："
                      "`5 C3`＝圖上 DIR5 的 C3 格；`5U C3`/`5D C3`＝上/下層（盲射）；"
                      "`跳過` 回挖礦。選格後會先自動抓框中心，抓不到再放大讓你點")


def aim_unknown_help(awaiting_fine: bool = False) -> str:
    """解析不出時的指引（純函式）：只列**當下 `parse_reply` 真的收得到**的指令。

    細格模式（放大手選退路）與粗格模式的可用集互斥——細格模式收不到候選編號與 grid 語法。
    列到收不到的指令＝把玩家導向必定失敗的輸入，看起來像 bot 壞掉（harvest 101）。
    """
    if awaiting_fine:
        return ("❓ 看不懂。放大手選中，可用：`B3`（打該細格中心）、`放大 B3`（再放大一層）、"
                "`退`（退一層／回選粗格）、`跳過`（回挖礦）、`手動`（重掃＋全方位圖）")
    return ("❓ 看不懂。可用：`2`（射候選②）、`5 C3`（方位 1-8＋粗格，先 `手動` 拿方位圖）、"
            "`跳過`（回挖礦）、`手動`（最後手段：重掃＋全方位圖＋格子瞄準說明）")


def build_aim_groups(rendered, summary: str, batch: int = 4) -> list:
    """疊圖批次切分（4 張/組）＋caption 組字（純函式）。

    rendered = [(candidate_numbers, dir_idx, layer, path), ...]（numbers 非空）。
    依各圖最小候選編號升冪——① 的圖必在首組首張。首組 caption＝群標題＋總表
    （notify.format_group_messages 的 fallback 直接把組名當 caption 用），
    續組列出該批編號與方位，解決「不知道哪個數字是哪張圖」。
    """
    items = sorted(rendered, key=lambda r: min(r[0]))
    out = []
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        if i == 0:
            caption = AIM_GROUP_HEADER + (f"\n{summary}" if summary else "")
        else:
            nums = "".join(circled(n) for r in chunk for n in sorted(r[0]))
            dirs = "・".join(f"方位{dir_label(r[1])}" for r in chunk)
            caption = f"🎯 近失候選（續）：{nums}｜{dirs}"
        out.append((caption, [r[3] for r in chunk]))
    return out


def draw_grid(img, cols: int = 6, rows: int = 4) -> None:
    """in-place 疊半透明格線＋格代碼（A1..）。draw_overlay 與 reentry_remote 共用。"""
    import cv2
    h, w = img.shape[:2]
    cw, ch = w // cols, h // rows
    for i in range(1, cols):
        cv2.line(img, (i * cw, 0), (i * cw, h), (90, 90, 90), 1)
    for j in range(1, rows):
        cv2.line(img, (0, j * ch), (w, j * ch), (90, 90, 90), 1)
    for i in range(cols):
        for j in range(rows):
            cv2.putText(img, f"{GRID_COLS[i]}{GRID_ROWS[j]}",
                        (i * cw + 6, j * ch + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 140, 140), 1)


def draw_overlay(frame_bgr, candidates, grid: bool = True):
    """把候選框編號＋淡色網格疊到快照上（純函式，copy 後畫、不改輸入）。

    延遲 import cv2/np：解析/座標函式在無 OpenCV 環境也可測。
    """
    out = frame_bgr.copy()
    if grid:
        draw_grid(out, len(GRID_COLS), 4)
    import cv2
    for c in candidates:
        x, y = c.pos
        cv2.rectangle(out, (x - 36, y - 36), (x + 36, y + 36), (0, 215, 255), 3)
        cv2.putText(out, str(c.number), (x - 30, y - 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 215, 255), 3)
    return out


# ===== B1：回覆解析（無前綴；寧可不射不誤射，解析不出回 None）=====
@dataclass(frozen=True)
class AimReply:
    kind: str        # "candidate" / "grid" / "skip" / "manual" / "fine" / "magnify" / "back"
    number: int = 0
    dir_idx: int = 0
    layer: str = "mid"
    cell: str = ""


_LAYER_SUFFIX = {"U": "up", "D": "down"}
_FINE_CELL = re.compile(r"^[A-F][1-6]$")   # 放大圖細網格 6×6（同 reentry_remote）


def parse_reply(text: str, num_candidates: int, layers_available=("mid",),
                awaiting_fine: bool = False):
    """NEEDS_HUMAN 待命時的一般訊息解析（無前綴；寧可不射不誤射，解析不出回 None）。

    - "2" → 候選編號（1..num_candidates 內才收）
    - "5 C3" / "5U C3" / "5d c3" → 網格（**方位 1-8**，同回礦介面；內部轉 0-based。
      H056：097 使用者看標頭 `DIR 4` 的圖打 `5`，舊 0-7 解析轉到別的方位而失手。
      U/D 需該層存在 layers_available）
    - "跳過"/"skip" → skip；"手動"/"全部" → manual（重掃＋全方位圖）

    awaiting_fine=True（放大手選退路，harvest 101 §5）：只收細格系列——
    - "B3" → fine（打該細格中心）
    - "放大 B3"/"magnify B3" → magnify（細格再放大一層）
    - "退"/"back" → back（退一層）
    - "跳過"/"手動" 同上；其他（含 grid 語法）→ None（先 `退` 回等格子再重選粗格）
    """
    t = (text or "").replace("　", " ").strip()
    if not t:
        return None
    low = t.lower()
    if low in ("skip", "跳過"):
        return AimReply("skip")
    if low in ("manual", "手動", "all", "全部"):
        # 最後手段：現場重掃＋全方位圖（`全部`/`all` 為 2026-07-11 舊別名）
        return AimReply("manual")
    if awaiting_fine:
        if low in ("back", "退"):
            return AimReply("back")
        parts = t.split()
        if len(parts) == 2 and parts[0].lower() in ("放大", "magnify"):
            cell = parts[1].upper()
            return AimReply("magnify", cell=cell) if _FINE_CELL.fullmatch(cell) else None
        if len(parts) == 1:
            cell = parts[0].upper()
            return AimReply("fine", cell=cell) if _FINE_CELL.fullmatch(cell) else None
        return None
    parts = t.split()
    if len(parts) == 1 and parts[0].isdigit():
        n = int(parts[0])
        if 1 <= n <= num_candidates:
            return AimReply("candidate", number=n)
        return None
    if len(parts) == 2:
        m = re.fullmatch(r"([1-8])([UuDd]?)", parts[0])
        if not m:
            return None
        layer = _LAYER_SUFFIX.get(m.group(2).upper(), "mid") if m.group(2) else "mid"
        if layer not in layers_available:
            return None
        cell = parts[1].upper()
        if grid_cell_center(cell) is None:
            return None
        # 使用者輸入 1-8 → 內部 dir_idx 0-7（dir_label 的逆；`0` 不再是合法方位）
        return AimReply("grid", dir_idx=int(m.group(1)) - 1, layer=layer, cell=cell)
    return None


# ===== B2：對齊計畫純函式（目前絕對姿態 → 目標 層/方位）=====
def plan_alignment(cur_net_rotations: int, cur_layer: str,
                   tgt_dir: int, tgt_layer: str):
    """目前絕對姿態 →（目標方位, 目標層）的對齊計畫（純函式）。

    方位＝相對挖礦原視角的淨右轉數 mod 8（sweep dir 與 net_rotations 同一座標系）。
    回 (帶號最短旋轉步數, None|目標層)。層不同才動俯仰（Bot 端一律 pitch_reset→nudge，
    "mid" 層 nudge=0＝純歸位）。
    """
    from .harvester import plan_return_rotations
    steps = plan_return_rotations(cur_net_rotations % 8, tgt_dir % 8)
    pitch = None if cur_layer == tgt_layer else tgt_layer
    return steps, pitch
