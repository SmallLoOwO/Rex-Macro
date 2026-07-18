"""Discord 遠端回礦（2026-07-12 spec）：回覆解析／粗細網格座標換算／放大圖與
點擊標記疊圖／ledger 記錄建構——全部純函式，I/O 在 main.Bot。"""
import json
import re
from dataclasses import dataclass, field

from .remote_aim import GRID_COLS, GRID_ROWS, draw_grid, grid_cell_center


@dataclass(frozen=True)
class RemoteReply:
    kind: str        # "coarse"/"fine"/"magnify"/"sweep"/"reroll"/"skip"/"confirm"/"void"/
                     # "layer"/"zoom_out"/"zoom_in"/"pitch_reset"/"pitch"
    dir_idx: int = 0  # coarse：內部 0-based（訊息面 1-8，parse 時 -1）
    cell: str = ""   # coarse/fine/magnify：格代碼；pitch：方向 "up"/"down"
    layer: str = ""  # layer 指令的新層名；fine 的單次覆寫（空＝無）
    steps: int = 0   # zoom_out/zoom_in：步數；pitch：像素量（0＝未指定，用 config 預設）


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
    if head in ("仰角", "pitch") and len(parts) >= 2:
        # 仰角控制（2026-07-17：R 取樣視窗退役，俯仰歸位/微調移進 Discord）。
        # 方向語意沿用取樣視窗 ▲/▼：上＝向上拖（dy<0）、下＝向下拖（dy>0）。
        sub = parts[1].lower()
        if sub in ("歸位", "reset") and len(parts) == 2:
            return RemoteReply("pitch_reset")
        direction = {"上": "up", "up": "up", "下": "down", "down": "down"}.get(sub)
        if direction is None:
            return None
        if len(parts) == 2:
            return RemoteReply("pitch", cell=direction)
        if len(parts) == 3 and parts[2].isdigit() and int(parts[2]) > 0:
            return RemoteReply("pitch", cell=direction, steps=int(parts[2]))
        return None
    if head in ("層", "layer") and len(parts) >= 2:
        return RemoteReply("layer", layer=" ".join(parts[1:]))
    if head in ("放大", "magnify") and len(parts) == 2:
        # 再放大（2026-07-18）：等細格時把細格子區域再裁一層，可連鎖
        cell = parts[1].upper()
        return RemoteReply("magnify", cell=cell) if _FINE_CELL.fullmatch(cell) else None
    if len(parts) == 2 and re.fullmatch(r"[1-8]", parts[0]):
        # 方位 1-8（2026-07-18 使用者要求 1 起算）；內部仍 0-based
        cell = parts[1].upper()
        return RemoteReply("coarse", dir_idx=int(parts[0]) - 1, cell=cell) \
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


def fine_cell_subregion(region, cell: str, cols: int = 6, rows: int = 6):
    """細格代碼＋現行放大區域 → 該細格的原幀子區域 (x, y, w, h)；不合法回 None。

    `放大 <細格>` 用：子區域成為新的 zoom_region，可連鎖逐層逼近小目標（D5 傳送板）。
    """
    cell = (cell or "").strip().upper()
    if not region or len(cell) != 2 or cell[0] not in GRID_COLS[:cols] \
            or cell[1] not in GRID_ROWS[:rows]:
        return None
    x, y, rw, rh = region
    sw, sh = rw // cols, rh // rows
    return (x + GRID_COLS.index(cell[0]) * sw,
            y + GRID_ROWS.index(cell[1]) * sh, sw, sh)


def magnify_scale(region_w: int, target_w: int, base_scale: int, cap: int = 24) -> int:
    """再放大的縮放倍率：輸出寬貼齊首次放大（target_w），上限 cap 防爆圖；異常回 base。"""
    if region_w <= 0 or target_w <= 0:
        return base_scale
    return max(base_scale, min(cap, round(target_w / region_w)))


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
    net_zoom: int = 0            # 淨 zoom 步數（+＝遠）；重骰不清（鏡頭距離跨重生點持續）
    trigger: str = "reset"       # 本 episode 觸發來源：reset（礦坑重置）/ manual（回礦 指令、🏠）


def next_episode_id(last_ledger_line):
    """ledger 末行 episode+1；無檔/壞行回 1（編號只求人眼可對，不求嚴格連續）。"""
    if not last_ledger_line:
        return 1
    try:
        return int(json.loads(last_ledger_line).get("episode", 0)) + 1
    except (ValueError, KeyError, TypeError):
        return 1


def plan_open_retry(first_open_ts: float, now: float, wait_s: float,
                    budget_s: float, last_probe_ts: float) -> str:
    """開場探測節奏（H044）：上一擊判「未傳送」後的下一步。

    "probe"＝間隔已到且預算未盡（再點一次「回到地表」當探針）；
    "wait"＝間隔未到（主迴圈下 tick 再問）；"give_up"＝預算用盡（通知一次、等人工）。
    預算從 episode 第一擊（first_open_ts）起算——凍結 1~2.5 分鐘是常態，探測本身無害
    （點了沒反應＝什麼都沒發生），預算只是「該告訴人類了」的收口。
    """
    if now - first_open_ts >= budget_s:
        return "give_up"
    if now - last_probe_ts >= wait_s:
        return "probe"
    return "wait"


def probe_frozen(mean_diff: float, changed_frac: float,
                 mean_max: float, frac_max: float) -> bool:
    """俯仰探針的凍結判定（H046）：前後幀「幾乎逐位元相同」才算凍結。

    H046 教訓：不可拿 pitch_eaten_*（「拖曳有沒有生效」門檻，被吃 ≤3.29 vs
    生效 ≥32.5）當凍結判定——夜間地表場景暗、拖曳真的動了 mean 也只有
    0.93~5.13（2026-07-17 ep1 實錄），被誤判凍結整整 300s 直到預算用盡。
    凍結的定義是渲染停格：兩側夾＝凍結 **0.00/0.0000**（逐位元相同，H044＋
    2026-07-17 17:23 實錄）vs 活著靜止（無輸入）0.09/0.0004 vs 今日夜間地表
    拖曳後最小 0.93/0.018。AND 語意：兩個訊號都趴在地板上才判凍結。
    """
    return mean_diff <= mean_max and changed_frac <= frac_max


def plan_opening_gate(frozen: bool, on_surface, trigger: str, capacity_pct,
                      capacity_max_pct: float) -> str:
    """開場守門（H045/H046）：條件是「狀態」不是「點擊有沒有造成幀差」。

    H046 兩型實錄：(a) 誤用 pitch_eaten 門檻當凍結判定，夜間地表活人被鎖 300s；
    (b) 人已真的在地表（Depth: Surface、Capacity 0%），但點擊「回到地表」不再
    造成畫面變化 → 轉移式驗證永遠失敗、卡死重骰/跳過。修正＝點擊幀差降為
    輔助訊號，開場成立與否全看三個狀態錨：

    "frozen"＝渲染停格（probe_frozen；凍結 0.00 vs 活著最小 0.09）；
    "not_surface"＝Depth 讀到 NNNm（礦內/虛空墜落中）→ 繼續探測點擊；
    "depth_unread"＝Depth OCR 讀不到（區域被蓋/全黑）→ 保守等下一探；
    "capacity"/"capacity_unread"＝容量未歸零/讀不到（兩側夾：凍結舊幀 78~100%
    vs 真重置後 0%；僅 trigger="reset"——手動回礦容量本來就非 0）；
    "proceed"＝拍照發圖。全部 defer 都回 H044 探測迴圈（預算 300s 收口）。
    俯仰「被吃但沒凍結」不擋拍照（只警告；`仰角` 指令可遠端修正）。
    """
    if frozen:
        return "frozen"
    if on_surface is None:
        return "depth_unread"
    if on_surface is False:
        return "not_surface"
    if trigger == "reset":
        if capacity_pct is None:
            return "capacity_unread"
        if capacity_pct > capacity_max_pct:
            return "capacity"
    return "proceed"


def plan_click_verdict(on_surface, frame_changed: bool, timed_out: bool) -> str:
    """細格點擊後的成功判定（H046(c) 預防性修正：狀態錨取代轉移式幀差）。

    下礦成功的定義是「Depth 從 Surface 翻成 NNNm」（狀態），不是「點擊造成
    幀差」（轉移）——重複點擊已成功的傳送板時畫面可能毫無變化，地表→地表
    換重生點時畫面大動但根本沒下礦（diff ≥26.8，舊驗證假成功）。兩側夾證據
    沿用 h046_depth_* fixtures（真實引擎 Surface/488m/25790m 3/3）。

    "descended"＝Depth 讀到 NNNm→真的下礦（幀差、窗口都不是條件）；
    "wait"＝窗內未確認（Surface/讀不到都繼續輪詢）；
    "still_surface"＝窗盡 Depth 仍 Surface→沒下礦（畫面有動也不算成功）；
    "moved_unconfirmed"＝窗盡、Depth 讀不到但畫面大動→交人工確認
    （降級路徑：OCR 失效時退回舊幀差訊號，寧問勿假成功）；
    "no_change"＝窗盡、Depth 讀不到且畫面沒動→點擊無效。
    """
    if on_surface is False:
        return "descended"
    if not timed_out:
        return "wait"
    if on_surface is True:
        return "still_surface"
    if frame_changed:
        return "moved_unconfirmed"
    return "no_change"


def format_gate_readings(on_surface, capacity_pct, pitch_mean: float,
                         pitch_frac: float) -> str:
    """開場探測讀值一行字（give_up 通知附帶；全 None 也不可拋例外）。

    遠端一眼分型：depth=NNNm/讀不到＋pitch 有動＝虛空墜落中；pitch 0.00/0.0000
    ＝凍結（H044/H045）；depth=Surface＋容量非 0＝重置未完成或按鈕失效。
    """
    depth_s = {True: "Surface", False: "NNNm(礦內/墜落)", None: "讀不到"}[on_surface]
    cap_s = "讀不到" if capacity_pct is None else f"{capacity_pct:.0f}%"
    return (f"depth={depth_s}｜capacity={cap_s}"
            f"｜pitch幀差={pitch_mean:.2f}/{pitch_frac:.4f}")


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
            "duration_s": round(duration_s, 1),
            "trigger": ctx.trigger}


def void_entry(episode_id, click_index, now):
    """作廢追加行：資料消費端讀到後把該 episode 第 click_index 筆點擊視為 invalid。"""
    return {"type": "void", "episode": episode_id, "click_index": click_index, "t": now}


# ===== Task 4：REENTRY 互動 embed 純函式（2026-07-13 spec；比照遙控器）=====
# 反應鈕 emoji 只進 Discord embed，絕不進 Tk/HUD——astral emoji（>U+FFFF）在 Tcl/Tk 8.6
# 會無聲卡死事件迴圈（實機二分驗證 2026-07-10）。Discord 沒此限制。
REENTRY_REACTIONS: tuple[str, ...] = ("🎲", "⏭️", "📷")

_PENDING_LABELS = {
    'layer': '更新目標層',
    'void': '作廢上一筆',
    'skip': '跳過回挖礦',
    'reroll': '重新擲點',
    'sweep': '重新掃描',
    'zoom_out': '拉遠鏡頭',
    'zoom_in': '拉近鏡頭',
    'magnify': '再放大',
    'coarse': '轉向並放大',
    'fine': '點擊並驗證',
    'confirm': '確認回礦',
}


def format_pending_ack(reply) -> str:
    '''回礦指令排入主迴圈後的即時確認；長操作不能等做完才第一次回覆。'''
    label = _PENDING_LABELS.get(reply.kind, reply.kind)
    return f'⏳ 已收到（{label}），主迴圈執行中…'


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


def build_reentry_embed(ctx, sticky_layer: str, now: float, evac_done: bool,
                        pitch_offset_px=None) -> dict:
    """組 REENTRY episode 互動 embed（照片訊息獨立發、此卡隨進度原地 PATCH 更新）。

    sticky_layer 顯式傳入（session 黏性層 _rr_sticky_layer；與 ctx.sticky_layer 同步但取
    session 來源，reroll 過渡期 ctx 剛清掉時也能讀）。evac_done 僅 footer 標注是否已撤離
    至地表（開場鏈本來就要再按一次換重生點，evac 結果不改流程）。
    pitch_offset_px＝目前俯仰記帳（距夾限回拉量；2026-07-18 使用者要求在回礦卡顯示
    目前角度，配合 `仰角` 指令調整）；None＝不顯示該行。
    """
    mins = int((now - ctx.created_at) // 60)
    phase_label = _REENTRY_PHASE_LABEL.get(ctx.phase, ctx.phase)
    color = _REENTRY_PHASE_COLOR.get(ctx.phase, 0x5865F2)
    evac_tag = "（已撤離至地表）" if evac_done else ""
    pitch_line = ("" if pitch_offset_px is None
                  else f"**俯仰**：夾限上 {pitch_offset_px}px（`仰角 上/下 [px]` 調）\n")
    return {
        "title": f"⛏ 回礦 #{ctx.episode_id}",
        "description": (
            f"**attempt**：{ctx.attempt}\n"
            f"**目標層**：{sticky_layer}\n"
            f"{pitch_line}"
            f"**已等**：{mins} 分鐘\n"
            f"**階段**：{phase_label}{evac_tag}\n"
            f"\n"
            f"指令：`方位 粗格`（如 `3 C2`，方位 1-8）、`放大 <細格>`、`層 <名>`、"
            f"`遠/近 [n]`、`仰角 歸位|上|下`；文字 `重骰`/`跳過`（跳過＝回挖礦）也可\n"
            f"反應鈕：🎲 重骰　⏭️ 跳過　📷 重新掃描"
        ),
        "color": color,
        "footer": {"text": ("手動觸發｜" if ctx.trigger == "manual" else "")
                           + "照片訊息在上方；此卡會隨進度原地更新"},
    }


def reaction_to_reentry_reply(emoji: str):
    """反應鈕 emoji → RemoteReply；非 REENTRY_REACTIONS 已知反應回 None。

    回的 kind 與 parse_reply 的關鍵字一致（reroll/skip/sweep），主迴圈消費路徑零改動。
    """
    kind = _REACTION_KIND.get(emoji)
    if kind is None:
        return None
    return RemoteReply(kind)
