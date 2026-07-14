"""Discord 遠端回礦（2026-07-12 spec）：回覆解析／粗細網格座標換算／放大圖與
點擊標記疊圖／ledger 記錄建構——全部純函式，I/O 在 main.Bot。"""
import json
import re
from dataclasses import dataclass, field

from .remote_aim import GRID_COLS, GRID_ROWS, draw_grid, grid_cell_center


@dataclass(frozen=True)
class RemoteReply:
    kind: str        # "coarse"/"fine"/"walk"/"sweep"/"reroll"/"skip"/"confirm"/"void"/"layer"/"zoom_out"/"zoom_in"
    dir_idx: int = 0
    cell: str = ""
    layer: str = ""  # layer 指令的新層名；fine 的單次覆寫（空＝無）
    steps: int = 0   # zoom_out/zoom_in：使用者指定步數（0＝未指定，用 config 預設）


_KEYWORDS = {
    "掃": "sweep", "sweep": "sweep",
    "重骰": "reroll", "reroll": "reroll",
    "跳過": "skip", "skip": "skip",
    "好": "confirm", "ok": "confirm",
    "作廢": "void", "void": "void",
}
_ZOOM_WORDS = {"遠": "zoom_out", "far": "zoom_out", "近": "zoom_in", "near": "zoom_in"}
_FINE_CELL = re.compile(r"^[A-F][1-6]$")


def _valid_coarse(cell: str) -> bool:
    return grid_cell_center(cell) is not None            # 預設 6×4


def parse_reply(text: str):
    """REENTRY 等待時的一般訊息解析（無前綴；寧可不點不誤點，解析不出回 None）。

    phase 無關——`B3` 在「等細格」外收到＝時機不合法，由 Bot 回提示；解析只管語法。
    """
    t = (text or "").replace("　", " ").strip()
    if not t:
        return None
    low = t.lower()
    if low in _KEYWORDS:
        return RemoteReply(_KEYWORDS[low])
    parts = t.split()
    head = parts[0].lower()
    if head in _ZOOM_WORDS:
        if len(parts) == 1:
            return RemoteReply(_ZOOM_WORDS[head])
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
            return RemoteReply(_ZOOM_WORDS[head], steps=int(parts[1]))
        return None
    if head in ("層", "layer") and len(parts) >= 2:
        return RemoteReply("layer", layer=" ".join(parts[1:]))
    if head in ("走", "walk") and len(parts) == 2:
        cell = parts[1].upper()
        return RemoteReply("walk", cell=cell) if _valid_coarse(cell) else None
    if len(parts) == 2 and re.fullmatch(r"[0-7]", parts[0]):
        cell = parts[1].upper()
        return RemoteReply("coarse", dir_idx=int(parts[0]), cell=cell) \
            if _valid_coarse(cell) else None
    cell = parts[0].upper()
    if _FINE_CELL.fullmatch(cell):
        return RemoteReply("fine", cell=cell, layer=" ".join(parts[1:]))
    return None


def coarse_cell_region(cell: str, w: int = 1920, h: int = 1080,
                       cols: int = 6, rows: int = 4):
    """粗格代碼 → 原幀裁圖區域 (x, y, rw, rh)；不合法回 None。"""
    cell = (cell or "").strip().upper()
    if len(cell) != 2 or cell[0] not in GRID_COLS[:cols] or cell[1] not in GRID_ROWS[:rows]:
        return None
    cw, ch = w // cols, h // rows
    return (GRID_COLS.index(cell[0]) * cw, GRID_ROWS.index(cell[1]) * ch, cw, ch)


def fine_cell_to_screen(region, cell: str, cols: int = 6, rows: int = 6):
    """細格代碼＋粗格區域 → 絕對螢幕座標（子格中心）；不合法回 None。"""
    cell = (cell or "").strip().upper()
    if len(cell) != 2 or cell[0] not in GRID_COLS[:cols] or cell[1] not in GRID_ROWS[:rows]:
        return None
    x, y, rw, rh = region
    sw, sh = rw // cols, rh // rows
    return (x + GRID_COLS.index(cell[0]) * sw + sw // 2,
            y + GRID_ROWS.index(cell[1]) * sh + sh // 2)


def effective_zoom_steps(requested: int, default: int, max_steps: int) -> int:
    """`遠 [n]` 的實際步數：0＝未指定→default；超上限 clamp（寧可少拉不擋操作）。"""
    n = requested if requested > 0 else default
    return min(n, max_steps)


def plan_zoom_restore(net_zoom: int, saturate: int, pullback: int):
    """絕對歸位按鍵計畫：I 飽和進第一人稱（冪等）→ O 回拉 K 步＝標準挖礦距離。

    沒碰過（net_zoom=0）或未校準（pullback<=0）回空。記帳誤差/步進不對稱
    都不影響歸位正確性——這是選絕對基準而非反向記帳的理由（spec 第 3 節）。
    """
    if net_zoom == 0 or pullback <= 0:
        return []
    return [("i", saturate), ("o", pullback)]


def render_zoom(frame_bgr, region, scale: int = 3, cols: int = 6, rows: int = 6):
    """裁粗格 → 放大 scale 倍 → 疊細網格（純函式，不改輸入）。"""
    import cv2
    x, y, rw, rh = region
    crop = frame_bgr[y:y + rh, x:x + rw]
    out = cv2.resize(crop, (rw * scale, rh * scale), interpolation=cv2.INTER_CUBIC)
    draw_grid(out, cols, rows)
    return out


def draw_click_marker(frame_bgr, pos):
    """紅圈＋十字標出實際點擊座標（回報「沒點歪」核對用；不改輸入）。"""
    import cv2
    out = frame_bgr.copy()
    x, y = int(pos[0]), int(pos[1])
    cv2.circle(out, (x, y), 24, (0, 0, 255), 3)
    cv2.line(out, (x - 36, y), (x + 36, y), (0, 0, 255), 2)
    cv2.line(out, (x, y - 36), (x, y + 36), (0, 0, 255), 2)
    return out


# ===== Task 3：context 與 ledger 建構純函式 =====
@dataclass
class RemoteReentryContext:
    episode_id: int
    created_at: float
    sticky_layer: str            # 黏性目標層（層指令改；純使用者宣告、bot 不驗證）
    cur_dir: int = 0             # 目前面向（相對開場 sweep 起始面向的淨右轉 mod 8）
    phase: str = "awaiting_cmd"  # awaiting_cmd / awaiting_fine / awaiting_confirm
    attempt: int = 1             # reroll 次數記帳（human-driven，無上限）
    zoom_dir: int = 0            # 等細格時：目標方位
    zoom_region: tuple = ()      # 等細格時：粗格原幀區域 (x, y, w, h)
    zoom_base: str = ""          # 等細格時：漂移守門基準圖路徑（Task 5 _rr_zoom 寫、_rr_click 讀）
    shots: list = field(default_factory=list)    # [(dir_idx, snapshot_path)]
    log: list = field(default_factory=list)      # 指令流水
    clicks: list = field(default_factory=list)   # 點擊記錄（ground truth 本體）
    walked: bool = False         # 本 episode 用過 `走`（movement mode 已切、收尾要切回）
    net_zoom: int = 0            # 淨 zoom 步數（+＝遠）；重骰不清（鏡頭距離跨重生點持續）


def next_episode_id(last_ledger_line):
    """ledger 末行 episode+1；無檔/壞行回 1（編號只求人眼可對，不求嚴格連續）。"""
    if not last_ledger_line:
        return 1
    try:
        return int(json.loads(last_ledger_line).get("episode", 0)) + 1
    except (ValueError, KeyError, TypeError):
        return 1


def log_command(ctx, raw, reply, now):
    ctx.log.append({"t": now, "raw": raw, "kind": reply.kind if reply else None,
                    "pose_dir": ctx.cur_dir, "zoom": ctx.net_zoom})


def record_click(ctx, pos, layer, region, now):
    ctx.clicks.append({"t": now, "pos": tuple(pos), "layer": layer,
                       "dir": ctx.cur_dir, "region": tuple(region),
                       "zoom": ctx.net_zoom, "invalid": False})


def ledger_entry(ctx, outcome, world, duration_s):
    """episode 收尾行（append-only；快照路徑在 shots/clicks 內，離線可回放）。"""
    return {"episode": ctx.episode_id, "t": ctx.created_at, "world": world,
            "outcome": outcome, "attempt": ctx.attempt,
            "sticky_layer": ctx.sticky_layer, "shots": list(ctx.shots),
            "log": list(ctx.log), "clicks": list(ctx.clicks),
            "duration_s": round(duration_s, 1)}


def void_entry(episode_id, click_index, now):
    """作廢追加行：資料消費端讀到後把該 episode 第 click_index 筆點擊視為 invalid。"""
    return {"type": "void", "episode": episode_id, "click_index": click_index, "t": now}


# ===== Task 4：REENTRY 互動 embed 純函式（2026-07-13 spec；比照遙控器）=====
# 反應鈕 emoji 只進 Discord embed，絕不進 Tk/HUD——astral emoji（>U+FFFF）在 Tcl/Tk 8.6
# 會無聲卡死事件迴圈（實機二分驗證 2026-07-10）。Discord 沒此限制。
REENTRY_REACTIONS: tuple[str, ...] = ("🎲", "⏭️", "📷")

_REENTRY_PHASE_LABEL = {
    "awaiting_cmd": "等指令",
    "awaiting_fine": "等細格",
    "awaiting_confirm": "等確認",
}
_REENTRY_PHASE_COLOR = {
    "awaiting_cmd": 0x5865F2,      # Blurple
    "awaiting_fine": 0xFEE75C,     # 黃
    "awaiting_confirm": 0x57F287,  # 綠
}
_REACTION_KIND = {"🎲": "reroll", "⏭️": "skip", "📷": "sweep"}


def build_reentry_embed(ctx, sticky_layer: str, now: float, evac_done: bool) -> dict:
    """組 REENTRY episode 互動 embed（照片訊息獨立發、此卡隨進度原地 PATCH 更新）。

    sticky_layer 顯式傳入（session 黏性層 _rr_sticky_layer；與 ctx.sticky_layer 同步但取
    session 來源，reroll 過渡期 ctx 剛清掉時也能讀）。evac_done 僅 footer 標注是否已撤離
    至地表（開場鏈本來就要再按一次換重生點，evac 結果不改流程）。
    """
    mins = int((now - ctx.created_at) // 60)
    phase_label = _REENTRY_PHASE_LABEL.get(ctx.phase, ctx.phase)
    color = _REENTRY_PHASE_COLOR.get(ctx.phase, 0x5865F2)
    evac_tag = "（已撤離至地表）" if evac_done else ""
    return {
        "title": f"⛏ 回礦 #{ctx.episode_id}",
        "description": (
            f"**attempt**：{ctx.attempt}\n"
            f"**目標層**：{sticky_layer}\n"
            f"**已等**：{mins} 分鐘\n"
            f"**階段**：{phase_label}{evac_tag}\n"
            f"\n"
            f"指令：`方位 粗格`（如 `3 C2`）、`走 C2`、`層 <名>`、`遠/近 [n]`；"
            f"文字 `重骰`/`跳過` 也可\n"
            f"反應鈕：🎲 重骰　⏭️ 跳過　📷 重新掃描"
        ),
        "color": color,
        "footer": {"text": "照片訊息在上方；此卡會隨進度原地更新"},
    }


def reaction_to_reentry_reply(emoji: str):
    """反應鈕 emoji → RemoteReply；非 REENTRY_REACTIONS 已知反應回 None。

    回的 kind 與 parse_reply 的關鍵字一致（reroll/skip/sweep），主迴圈消費路徑零改動。
    """
    kind = _REACTION_KIND.get(emoji)
    if kind is None:
        return None
    return RemoteReply(kind)
