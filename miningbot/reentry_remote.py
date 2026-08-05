"""Discord 遠端回礦（2026-07-12 spec）：回覆解析／粗細網格座標換算／放大圖與
點擊標記疊圖／ledger 記錄建構——全部純函式，I/O 在 main.Bot。"""
import json
import re
from dataclasses import dataclass, field

from .remote_aim import GRID_COLS, GRID_ROWS, draw_grid, grid_cell_center


@dataclass(frozen=True)
class RemoteReply:
    kind: str        # "coarse"/"fine"/"magnify"/"sweep"/"reroll"/"skip"/"confirm"/"void"/
                     # "layer"/"zoom_out"/"zoom_in"/"pitch_reset"/"pitch"/"back"
    dir_idx: int = 0  # coarse：內部 0-based（訊息面 1-8，parse 時 -1）
    cell: str = ""   # coarse/fine/magnify：格代碼；pitch：方向 "up"/"down"
    layer: str = ""  # layer 指令的新層名；fine 的單次覆寫（空＝無）
    steps: int = 0   # zoom_out/zoom_in：步數；pitch：像素量（0＝未指定，用 config 預設）


_KEYWORDS = {
    "掃": "sweep", "sweep": "sweep",
    "重骰": "reroll", "reroll": "reroll",
    "跳過": "skip", "skip": "skip",
    "好": "confirm", "ok": "confirm",
    # 2026-08-03：作廢退役——實機經驗層不對就重骰，從不單獨作廢資料；
    # void_entry/ledger 追加保留供 build_reentry_dataset 處理歷史語料。
    # 2026-07-19：回礦中調好的仰角直接寫回 config 標準角（校準卡在 REENTRY 被拒，
    # 過去只能事後重校）。裸 `存檔` 比照校準卡詞彙；`仰角 存檔` 同義。
    "存檔": "pitch_save", "save": "pitch_save",
    "退": "back", "back": "back",
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
        if sub in ("存檔", "save") and len(parts) == 2:
            return RemoteReply("pitch_save")
        direction = {"上": "up", "up": "up", "下": "down", "down": "down"}.get(sub)
        if direction is None:
            return None
        if len(parts) == 2:
            return RemoteReply("pitch", cell=direction)
        if len(parts) == 3 and parts[2].isdigit() and int(parts[2]) > 0:
            return RemoteReply("pitch", cell=direction, steps=int(parts[2]))
        return None
    if head == "歸位" and len(parts) == 1:
        # 裸「歸位」＝仰角歸位（2026-07-19：使用者照卡面 `上|下 [px]` 簡寫打、沒帶前綴）
        return RemoteReply("pitch_reset")
    bare_dir = {"上": "up", "up": "up", "下": "down", "down": "down"}.get(head)
    if bare_dir is not None:
        # 裸 `上|下 [px]`＝`仰角 上|下 [px]` 同義（多 token 的一般聊天不會進到這裡）
        if len(parts) == 1:
            return RemoteReply("pitch", cell=bare_dir)
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
            return RemoteReply("pitch", cell=bare_dir, steps=int(parts[1]))
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


def zoom_drifted(snap_crop, live_crop, threshold: float) -> bool:
    """放大守門（H050）：sweep 快照同格 vs 現場同格的平均差超標＝畫面已偏離方位圖。

    八方位轉滿一圈的殘差/斜坡滑移可讓現場面向偏 ~6°（ep7 實錄 170px），使用者按
    快照選的格子在現場已是別的內容——放大圖照發（點擊座標以現況為準），但要警告。
    兩側夾（E2 粗格）：真漂移 29.66/21.6 vs 同面向 3 秒後 0.04、idle 晃動格 3.14；
    門檻沿用 reentry_remote_drift_diff（_rr_click 點擊守門同語意同區域大小）。
    快照讀不到（檔案被清/佇列滿沒寫）回 False＝不守門，照現行行為發圖。
    """
    from . import vision
    diff = vision.frames_mean_diff(snap_crop, live_crop)   # None-safe/尺寸不合回 None
    return diff is not None and diff >= threshold


def magnify_scale(region_w: int, target_w: int, base_scale: int, cap: int = 24) -> int:
    """再放大的縮放倍率：輸出寬貼齊首次放大（target_w），上限 cap 防爆圖；異常回 base。"""
    if region_w <= 0 or target_w <= 0:
        return base_scale
    return max(base_scale, min(cap, round(target_w / region_w)))


def pop_zoom_layer(ctx):
    """退一層純邏輯（2026-07-20）：主迴圈執行 I/O，此處只決定退到哪。

    回 ("awaiting_cmd", None)：stack 空 or pop 出 None（退過首層＝回等指令）；
    回 ("awaiting_fine", layer)：pop 出某層 dict（region/base/scale），主迴圈重渲染該層；
    回 ("noop", None)：phase 不是 awaiting_fine（呼叫端應先擋，防禦值；stack 不動）。
    """
    if ctx.phase != "awaiting_fine":
        return ("noop", None)
    if not ctx.zoom_stack:
        return ("awaiting_cmd", None)
    layer = ctx.zoom_stack.pop()
    if layer is None:
        return ("awaiting_cmd", None)
    return ("awaiting_fine", layer)


def effective_sticky_layer(world, mapping, fallback):
    """每世界黏性層查值（2026-07-20）：mapping 命中 → 該世界的層；否則 fallback。
    world=None（世界尚未偵測）→ fallback（config 預設 reentry_target_layer）。
    """
    if world is None:
        return fallback
    return mapping.get(world, fallback)


def remember_layer(mapping, world, layer):
    """功能性記層（2026-07-20）：回 {**mapping, world: layer}（已存在→覆蓋），**不改輸入**。
    world=None 或 layer 空 → 回 None（呼叫端據此不寫檔、只改 session）。
    """
    if world is None or not layer:
        return None
    return {**mapping, world: layer}


def parse_sticky_layers(raw_text):
    """讀 sticky_layers.json（2026-07-20）：None／空／壞 JSON／頂層非 dict → {}（容錯）。"""
    if not raw_text:
        return {}
    try:
        obj = json.loads(raw_text)
    except (ValueError, TypeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def serialize_sticky_layers(mapping):
    """寫 sticky_layers.json（2026-07-20）：ensure_ascii=False（中文層名可讀）、sort_keys（diff 友善）。"""
    return json.dumps(mapping, ensure_ascii=False, sort_keys=True)


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


def effective_pitch_back(session_back, default_back: int, clamp_px: int) -> int:
    """開場/重骰俯仰歸位的回拉量（2026-07-19 使用者反映：重骰後被拉回 config 標準角）。

    歸位本身不能省——夾限飽和是唯一絕對角度基準、拖曳兼任凍結探針（H044/H046）——
    但回拉量要沿用 episode 內 `上|下 [px]` 的記帳值（session_back；None＝本 episode
    沒調過→config 標準角）。記帳可能被 `下` 調成負值（實際已飽和在夾限）或超過
    飽和拖曳量，clamp 到 [0, clamp_px] 保持可重現。
    """
    if session_back is None:
        return default_back
    return max(0, min(session_back, clamp_px))


def plan_zoom_normalize(saturate: int, pullback: int):
    """無條件鏡頭距離歸位計畫：I 飽和進第一人稱（冪等）→ O 回拉 K 步＝標準距離。

    不看 net_zoom——boost FOV 隨使用次數累積漂移（2026-07-19 使用者確認：作用中
    變大/到期變小、重進才重製），拍照/開挖前的鏡頭距離要每次重定，與有沒有下過
    `遠`/`近` 指令無關。未校準（pullback<=0）回空＝跳過。
    """
    if pullback <= 0:
        return []
    return [("i", saturate), ("o", pullback)]


def plan_zoom_restore(net_zoom: int, saturate: int, pullback: int):
    """絕對歸位按鍵計畫：碰過 zoom（net_zoom≠0）才歸位版本。

    沒碰過（net_zoom=0）或未校準（pullback<=0）回空。記帳誤差/步進不對稱
    都不影響歸位正確性——這是選絕對基準而非反向記帳的理由（spec 第 3 節）。
    """
    if net_zoom == 0:
        return []
    return plan_zoom_normalize(saturate, pullback)


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
    zoom_stack: list = field(default_factory=list)  # 放大層歷史（2026-07-20）：None=空層(回 awaiting_cmd)、dict=上一層 {region,base,scale}
    zoom_scale: int = 0          # 當前層渲染倍率（首層=reentry_remote_zoom_scale；連鎖=magnify_scale 算出）
    shots: list = field(default_factory=list)    # [(dir_idx, snapshot_path)]
    log: list = field(default_factory=list)      # 指令流水
    clicks: list = field(default_factory=list)   # 點擊記錄（ground truth 本體）
    predictions: dict = field(default_factory=dict)  # {dir_idx: (x, y, score)}；每次 sweep 重算
    net_zoom: int = 0            # 淨 zoom 步數（+＝遠）；重骰不清（鏡頭距離跨重生點持續）
    trigger: str = "reset"       # 本 episode 觸發來源：reset（礦坑重置）/ manual（回礦 指令、🏠）


def next_episode_id(last_ledger_line):
    """ledger 末行 episode+1；無檔/壞行回 1（編號只求人眼可對，不求嚴格連續）。

    ⚠ 只看末行，故**只在 ledger 每個 episode 都留得下一行時才正確**。實機路徑請改用
    `next_episode_id_from_ledger`——見該函式說明的 2026-07-26 編號重複事故。
    保留本函式是為了既有呼叫端與測試。
    """
    if not last_ledger_line:
        return 1
    try:
        return int(json.loads(last_ledger_line).get("episode", 0)) + 1
    except (ValueError, KeyError, TypeError):
        return 1


def next_episode_id_from_ledger(lines):
    """掃**全部** ledger 行取 max(episode)+1；無檔/全壞行回 1。

    2026-07-26 實機事故：同一天 13:15 與 18:34 兩場回礦都拿到 `#26`，快照因此都叫
    `reentry_ep26_dir1..8`，網頁歷史把兩場併成一個 episode、時間軸出現整組重複。
    根因＝`ledger_entry` 只在 episode **有結果時**才寫（confirmed_by_user／skip），
    而 26 這場兩次都在收尾前就結束（重啟／逾時），末行永遠停在 25 →
    `next_episode_id` 每次都回 26。

    修法兩層，本函式是第二層：
    (1) 建 ctx 時先寫一行佔號（main._rr_ensure_ctx），未收尾也推進編號；
    (2) 取號改掃全檔取最大值——佔號行與結果行同號並存時仍然正確，且對任何
        「末行不是最大號」的排列（手動編修、亂序 append）都免疫。

    壞行靜默略過：ledger 是 append-only，尾端可能是寫到一半的 partial line
    （比照 web_history._iter_snapshot_records 的容忍度）。
    """
    max_id = 0
    for line in lines or ():
        if isinstance(line, bytes):
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError:
                continue
        if not isinstance(line, str) or not line.strip():
            continue
        try:
            episode = json.loads(line).get("episode")
        except (ValueError, TypeError):
            continue
        if isinstance(episode, bool) or not isinstance(episode, int):
            continue
        max_id = max(max_id, episode)
    return max_id + 1


def episode_reservation_entry(episode_id, trigger, now):
    """建 ctx 當下寫進 ledger 的「佔號」行（outcome="started"）。

    只帶足以推進編號與事後對帳的欄位；結果欄位（world/clicks/duration_s）留給
    真正收尾的 `ledger_entry`。同一個 episode 因此在 ledger 留兩行——`started`
    一行、結果一行——這是刻意的：沒有結果行才是異常，能一眼看出哪幾場沒收尾
    （2026-07-26 之前這種場次在 ledger 完全隱形）。
    """
    return {
        "episode": int(episode_id),
        "t": float(now),
        "outcome": "started",
        "trigger": str(trigger),
    }


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


def capacity_blocks_opening(trigger: str, capacity_pct,
                            capacity_max_pct: float) -> bool:
    """開場前容量預檢（H058）：重置收尾中容量仍高 → True（阻塞、被動等候）。

    與 plan_opening_gate 的 capacity 分支同條件（trigger=="reset" 且容量 > 門檻），
    但在「點回到地表＋俯仰拖曳」之前提前判斷——避免重置收尾的遊戲卡頓吃掉這些
    輸入。H058（2026-07-20 RR#8~12）實錄：REENTRY 因「banner 消失＋5s 沉澱」即
    起跑，此時重置第二階段（容量從 60~76% 排到 ≤門檻）還在進行、約需 90s；
    _rr_open_episode 每 20s 一輪「點回到地表＋俯仰拖曳＋容量 OCR」全卡在卡頓裡
    被吃（pitch/zoom 屢判疑似被吃），直到容量自然排到門檻才放行。預檢讓這段
    期「不點擊、不拖曳」，只被動 OCR 容量等下一探——容量 ≤ 門檻才開始真正的
    回礦行動。

    手動回礦（trigger!="reset"）容量本來就非 0、不擋（比照 plan_opening_gate
    manual 分支）；讀不到（None）放行，交給 plan_opening_gate 的 capacity_unread
    分支處理（保留下游既有保守判定）。
    """
    if trigger != "reset":
        return False
    if capacity_pct is None:
        return False
    return capacity_pct > capacity_max_pct


def plan_reset_drain(capacity_pct, prev_capacity_pct, stall_rounds: int,
                     waited_s: float, budget_s: float) -> tuple[str, int]:
    """重置收尾等候的收口（H066 2026-07-29）：回 `(verdict, 新 stall_rounds)`。

    `capacity_blocks_opening` 只回答「現在該不該動」，沒有任何收口——H058 把這段
    被動等候掛在開場探測預算（`reentry_open_budget_s` 300s）上，於是「等遊戲排容量」
    和「探測畫面有沒有凍結」共用同一個預算。實機兩次撞牆（同一天）：
      * RR#31 16:02（97→88,88→82,82→72×8→48,48）容量**一直在降**、只是慢，300s
        用完時還在 48%（實測 ~0.165 個百分點/s，排到 ≤5% 需 ~575s）；
      * RR#30 03:34（99→93→87→81×10）容量在 81% 就沒再降過，同樣等到預算耗盡。
    兩者都走同一條 give_up、印同一句「pitch 0.00/0.0000＝凍結」——而那組讀值來自
    `_rr_last_probe` 的**初始值**，這條路徑一次都沒探過。

    `stall_rounds`＝連續「沒再降」的輪數，**只當診斷資訊回報給人，不參與判決**。
    想拿它當「凍結」門檻的兩側夾湊不出來：健康場次最長連 1 輪（RR#16/17/26/27/28），
    RR#31 慢但會動連 **7** 輪後續降，RR#30 連 **9** 輪——而 RR#30 的 9 是被舊 300s
    預算截斷的，沒人知道它第 11 輪會不會恢復。7 vs 9 只差兩輪、上界還是截斷值，
    寫門檻等於不可否證（H059 教訓）。要寫，得先有「久到確定不會恢復」的負樣本。

    "wait"＝仍在等（下一輪再探）；"timeout"＝超過等候預算，交人工並附上容量軌跡
    （最後讀值＋連續沒再降輪數），讓人自己分辨是慢還是凍。
    容量讀不到（None）不計 stall——OCR 掉一幀不是「沒再降」的證據。
    """
    if capacity_pct is None or prev_capacity_pct is None:
        stall_rounds = 0
    elif capacity_pct < prev_capacity_pct:
        stall_rounds = 0
    else:
        stall_rounds += 1
    if waited_s >= budget_s:
        return "timeout", stall_rounds
    return "wait", stall_rounds


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
    """`attempt` 是語料配對的關鍵（2026-07-28 加）：`ctx.shots` 每次 sweep 清空、
    `ctx.clicks` 卻整個 episode 累積，不記 attempt 就無從判斷這個座標對應哪一組圖。
    """
    ctx.clicks.append({"t": now, "pos": tuple(pos), "layer": layer,
                       "dir": ctx.cur_dir, "region": tuple(region),
                       "zoom": ctx.net_zoom, "invalid": False,
                       "attempt": ctx.attempt})


def record_prediction(ctx, predicted) -> bool:
    """把偵測器當時的猜測補寫進最後一筆點擊；沒有點擊可補時回 False。

    玩家點在別的地方＝否定了預測，這一筆帶著「模型當時怎麼想」進語料，迴圈自己
    就會長大：每確認一次就多一筆 (預測, 真實) 比對，標註成本是零。
    沒有預測就寫 None——照實記錄，不補值。
    """
    if not ctx.clicks:
        return False
    ctx.clicks[-1]["predicted_xy"] = (
        [int(predicted[0]), int(predicted[1])] if predicted else None)
    ctx.clicks[-1]["predicted_score"] = (
        round(float(predicted[2]), 3) if predicted else None)
    return True


def record_landing(ctx, depth_m, layer_seen) -> bool:
    """把落地量到的深度與層別補寫進最後一筆點擊；沒有點擊可補時回 False。

    為什麼要這兩欄：既有的 `layer` 欄是**使用者宣告**的字串（`層 <名>` 指令留下、
    bot 從不驗證），實測 20 筆點擊有 5 筆標成 "Mantle Layer" 但落地畫面實為
    Shamrock。`depth_m` 是畫面實測、`layer_seen` 由 `game_data.layer_for_depth`
    以 (世界, 深度) 反推——遊戲不顯示層數，深度是唯一可機讀的位置訊號。

    兩者都可能是 None（Depth OCR 讀不到、世界未偵測到、深度落在層表外例如
    H043 虛空墜落），照實寫入不補值——**寫 None 才看得出當時量不到**，
    事後分析語料時才不會把「沒量到」誤當成「量到某層」。
    """
    if not ctx.clicks:
        return False
    ctx.clicks[-1]["depth_m"] = depth_m
    ctx.clicks[-1]["layer_seen"] = layer_seen
    return True


def format_landing_evidence(declared_layer, depth_m, layer_seen) -> str:
    """落地實測一行字（awaiting_confirm 通知用）。

    為什麼要這行（2026-08-01 使用者反映）：確認訊息過去只印**使用者宣告**的
    `sticky_layer`，等於把「有沒有點錯層」原封不動丟回去問人——但 bot 在
    `record_landing` 當下已經量到 `depth_m` 與反推的 `layer_seen`，那正是玩家
    要判斷的東西，卻只寫進 ledger 沒給人看。玩家因此只能猜，一猜錯就按 `重骰`
    ＝回地表換重生點整輪重來。

    `layer_seen is None` 的兩種成因（世界沒偵測到／深度落在層表外，如 H043 虛空
    墜落）都不足以斷定「點錯層」——照實說反推不到，不寫成不符。
    """
    if depth_m is None:
        return f"深度讀不到（目標層：{declared_layer}）"
    if layer_seen is None:
        return f"實測深度 {depth_m}m，反推不到層別（目標層：{declared_layer}）"
    if layer_seen == declared_layer:
        return f"實測 {depth_m}m＝{layer_seen}，與目標層相符"
    return f"⚠ 實測 {depth_m}m＝{layer_seen}，與目標層 {declared_layer} 不符"


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
    'skip': '跳過回挖礦',
    'reroll': '重新擲點',
    'sweep': '重新掃描',
    'zoom_out': '拉遠鏡頭',
    'zoom_in': '拉近鏡頭',
    'pitch': '仰角微調',
    'pitch_reset': '仰角歸位',
    'pitch_save': '仰角存檔',
    'magnify': '再放大',
    'back': '退一層',
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
                  else f"**俯仰**：夾限上 {pitch_offset_px}px\n")
    return {
        "title": f"⛏ 回礦 #{ctx.episode_id}",
        "description": (
            f"**attempt**：{ctx.attempt}\n"
            f"**目標層**：{sticky_layer}\n"
            f"{pitch_line}"
            f"**已等**：{mins} 分鐘\n"
            f"**階段**：{phase_label}{evac_tag}\n"
            f"\n"
            f"📐 **指位**（等指令）：`方位 粗格`（如 `3 C2`）、`層 <名>` 改目標層\n"
            f"🎯 **點擊**（等細格）：`B3`、換層 `B3 <層名>`、`放大 <細格>`、`退` 退一層\n"
            f"🔭 **視角**：`遠/近 [n]`、`上|下 [px]`、`歸位`、`存檔`\n"
            f"🔄 **流程**：`重骰`、`跳過`（回挖礦）、`📷` 重掃\n"
            f"反應鈕：🎲 重骰　⏭️ 跳過　📷 重新掃描"
        ),
        "color": color,
        "footer": {"text": ("手動觸發｜" if ctx.trigger == "manual" else "")
                           + "照片訊息在上方；此卡會隨進度原地更新"},
    }


def should_warn_attempts(attempt: int, every: int) -> bool:
    """人工重骰次數提醒（2026-07-19）：every>0 且 attempt 為其倍數才提醒。

    attempt 無上限設計不變（human-driven）；提醒只是「重生點一直不理想，可
    `跳過` 或先調視角」的提示。H044 探測 reroll 也會累加 attempt（卡面同一數字），
    但提醒只掛在使用者 🎲/`重骰` 的執行路徑上，探測不觸發。
    """
    return every > 0 and attempt > 0 and attempt % every == 0


def reaction_to_reentry_reply(emoji: str):
    """反應鈕 emoji → RemoteReply；非 REENTRY_REACTIONS 已知反應回 None。

    回的 kind 與 parse_reply 的關鍵字一致（reroll/skip/sweep），主迴圈消費路徑零改動。
    """
    kind = _REACTION_KIND.get(emoji)
    if kind is None:
        return None
    return RemoteReply(kind)


# awaiting_confirm 證據訊息專用反應鈕（2026-08-03 使用者要求）。
# ⭕＝好（放行開挖）、🎲＝重骰（回地表換重生點）。🎲 與 embed 卡的 reroll 同語意——
# 兩張是不同訊息、各自輪詢，不會互相干擾。
CONFIRM_REACTIONS: tuple[str, ...] = ("⭕", "🎲")
_CONFIRM_REACTION_KIND = {"⭕": "confirm", "🎲": "reroll"}


def reaction_to_confirm_reply(emoji: str):
    """確認階段反應鈕 → RemoteReply；非 CONFIRM_REACTIONS 回 None。

    kind 與 parse_reply 的好/重骰一致，主迴圈消費路徑零改動。
    """
    kind = _CONFIRM_REACTION_KIND.get(emoji)
    if kind is None:
        return None
    return RemoteReply(kind)
