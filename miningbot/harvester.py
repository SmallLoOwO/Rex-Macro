import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from .geometry import aim_decision
from . import input_control as ic
from . import vision, capture
from .config import DEFAULT as cfg

@dataclass
class HarvestState:
    rotations: int          # 總轉動次數（給 max_aim_rotations 上限用）
    elapsed_s: float
    net_rotations: int = 0  # 淨轉動（右+1、左-1），用來挖完後轉回原角度
    d3_attempts: int = 0    # D3 連續未命中次數（達 max_harvest_attempts 自動重掃）
    harvest_id: str = ""    # 本輪採集編號（如 "007"）；貫穿 log/快照檔名/Discord 供事後一鍵搜查
    verify_fail_resweeps: int = 0  # 「掃到框但 verify 失敗」已重掃次數（decide_sweep_failure 上限用，H019）
    extra_targets: int = 0  # 本 episode 採集成功後已續採顆數（incident 072：同畫面第二顆礦）
    # 註：環繞一次找不到即交人工（2026-06-29 偵測已準，移除二次重掃），故不再記 sweep_attempts
    pitch_layer: str = "mid"        # 目前俯仰層（"mid"/"up"/"down"；快照 label／log 用）
    pitch_layers_left: list = field(default_factory=list)  # 尚未掃的 PitchLayer（失敗路徑逐層 pop）
    pitch_touched: bool = False     # 任一層轉換「嘗試過」（含失敗）→ 收尾必須 pitch_reset 歸位


def sweep_snapshot_label(pitch_layer: str, dir_idx: int) -> str:
    """sweep 全空診斷快照 label（純函式）。標準層維持舊名 sweep_empty_dirN（排錯習慣不變），
    俯仰層加層標記 sweep_empty_<layer>_dirN。"""
    if pitch_layer == "mid":
        return "sweep_empty_dir%d" % dir_idx
    return "sweep_empty_%s_dir%d" % (pitch_layer, dir_idx)


def yaw_sample_label(episode_id, dir_idx: int) -> str:
    """回礦落地 yaw 取樣快照 label（純函式；H059 語料收集）。

    dir_idx 0-based（與 range(8) 迴圈對齊），檔名輸出 1 起算——同
    reentry_ep{N}_dir{i+1} 慣例（2026-07-18 使用者要求）。以 reentry 開頭
    → snapshot_subdir 分流到 snapshots/reentry，不汙染 review 的排錯視野。
    """
    return "reentry_ep%s_yaw%d" % (episode_id, dir_idx + 1)


@dataclass(frozen=True)
class PitchLayer:
    """失敗路徑俯仰掃描的一層（純資料）。nudge_px＝pitch_reset 置中後的拖曳量（正=向下拖）。"""
    name: str       # "up" / "down"（快照 label、log 用）
    nudge_px: int


def plan_pitch_layers(enabled: bool, step_px: int, center_back_px: int) -> list:
    """回失敗路徑要補掃的俯仰層序列（不含已掃過的標準層；純函式）。

    未校準（step=0 或 center_back<=0）視同停用——與 reentry「無模板視同關閉」同慣例。
    順序固定上→下：實機經驗礦多在壁上高處，H026 證實下方也會漏，兩層都掃。
    """
    if not enabled or step_px == 0 or center_back_px <= 0:
        return []
    return [PitchLayer("up", -step_px), PitchLayer("down", step_px)]


def mining_pitch_home_enabled(center_back_px: int) -> bool:
    """挖礦標準角歸位是否啟用（純函式；spec 2026-07-17 兩套具名標準俯角）。

    與 plan_pitch_layers 同慣例：center_back_px <= 0＝未校準＝停用——缺校準
    不靜默改變行為（維持現狀角度，呼叫端記警告）。
    """
    return center_back_px > 0


def format_startup_pitch_status(center_back_px: int, homed: bool, offset_px: int) -> str:
    """啟動仰角一行字（2026-07-18 使用者要求：啟動時在 log＋Discord 顯示目前仰角）。

    homed＝啟動歸位是否成功；成功時 offset_px＝距夾限回拉量（可重現的絕對角度）。
    未校準＝角度不明（沿用啟動前角度，_pitch_home_mining 已記警告不靜默）。
    """
    if homed:
        return f"夾限上 {offset_px}px（挖礦標準角）"
    if mining_pitch_home_enabled(center_back_px):
        return "歸位疑似被吃，角度可能不受控"
    return "挖礦標準角未校準（沿用啟動前角度，角度不明）"


def format_harvest_id(seq: int) -> str:
    """把採集流水號格式化成可搜尋編號 "007"（純數字、零填充三位；純函式）。

    零填充三位讓 grep 精準（"007" 不會誤中 "070"）、又好唸（你說「7 號」＝007）。
    log 判定行、快照檔名、Discord 訊息共用同一個編號 → 事後說「7 號似乎誤判」即可一鍵搜出
    該輪全部證據（截圖＋判斷文字＋通知）。超過 999（單次執行採超過 999 顆稀有礦，極罕見）
    自然進位成 1000，不截斷。
    **不加 "H" 前綴**（2026-07-07 使用者回饋）：舊格式 "H064" 與 docs/incidents.md 的事故
    編號 Hxxx 視覺/語意撞名，看到 "H064" 分不清是事故還是第 64 輪採集 → 改純數字消歧義。
    """
    return f"{seq:03d}"

@dataclass
class HarvestStep:
    action: str   # WAIT_SCAN | ROTATE_LEFT | ROTATE_RIGHT | MOUSE_AIM | FIRE_D3 | HUMAN
    dx: int = 0
    dy: int = 0

def next_harvest_step(marker, state: HarvestState, cfg) -> HarvestStep:
    if state.elapsed_s > cfg.harvest_verify_timeout_s:
        return HarvestStep("HUMAN")
    if state.rotations > cfg.max_aim_rotations:
        return HarvestStep("HUMAN")
    if marker is None:
        return HarvestStep("WAIT_SCAN")

    center = (cfg.screen_w // 2, cfg.screen_h // 2)
    d = aim_decision(marker, center, cfg.aim_center_tolerance_px,
                     cfg.vertical_extreme_ratio, cfg.screen_h // 2)
    mapping = {
        "HUMAN": "HUMAN", "FIRE": "FIRE_D3",
        "ROTATE_LEFT": "ROTATE_LEFT", "ROTATE_RIGHT": "ROTATE_RIGHT",
        "MOUSE_AIM": "MOUSE_AIM",
    }
    return HarvestStep(mapping[d.action], dx=d.dx, dy=d.dy)

def decide_harvest_result(gone: bool, confirmed: bool) -> str:
    """D3 開火後的成功判定（純函式）。

    回傳 "SUCCESS" / "RESWEEP" / "RETRY"。

    核心原則：**「追蹤框消失」不等於「我們採到」**。框會因 D2 掃描到期（框自己淡掉）、
    雷達(Z)自動開採等與我方 D3 無關的原因消失。唯一能歸因到我方這一發的證據是聊天框
    出現新的 has found（confirmed；採集期間鎬子已停，視窗內不會有普通挖礦的 has found）。

    - confirmed=True              → SUCCESS（確實採到，不論框在不在）
    - 框消失但未確認 (gone, ~conf) → RESWEEP（掃描到期/被雷達搶採，原地再射也射不到 → 重掃）
    - 框還在且未確認 (~gone,~conf) → RETRY（D3 沒打中、礦還在，原地重試）

    背景bug：2026-06-29 trace 20260629_022126——真追蹤框疊在角色身上 D3 打不到，
    D2 掃描到期框自己淡掉 → 舊邏輯 `gone or confirmed` 把 gone 當成功、聊天 5→5 沒變仍誤報。
    """
    if confirmed:
        return "SUCCESS"
    if gone:
        return "RESWEEP"
    return "RETRY"

def d3_cooldown_remaining(now_s: float, last_fire_s: float | None,
                          cooldown_s: float) -> float:
    """Return seconds remaining before D3 may fire again.

    ``last_fire_s`` is recorded when the shot is actually fired. Callers supply
    monotonic timestamps and the configured cooldown duration; this decision does
    no sleeping or I/O.
    """
    if last_fire_s is None:
        return 0.0
    return max(0.0, cooldown_s - (now_s - last_fire_s))


def pick_sweep_candidate(candidates, screen_w: int):
    """sweep 多方位候選中選「x 最接近畫面中心」者（純函式，H019 對策）。

    candidates = [(dir_idx, (x, y)), ...]；空 list 回 None。

    同一顆追蹤框常橫跨相鄰 2~3 個方位都被看到（45° 旋轉有視野重疊）。舊版取
    candidates[0]（最先看到的方位）——H019 取到離中心 533px 的 dir=3，轉回期間
    D5 boost 到期 FOV 收縮把框往外推 ~390px → 撞進 find_tracker 的畫面邊緣排除帶
    （margin_frac=0.1，外緣 10% 一律拒收）→ verify 整幀找不到 → 誤判「未找到」。
    選最居中者（H019 的 dir=4 離中心僅 21px）天然留足邊緣餘裕：同樣的 FOV 位移
    後仍在偵測區內，D3 點擊也更不易受後續位移影響。
    """
    if not candidates:
        return None
    cx = screen_w // 2
    return min(candidates, key=lambda c: abs(c[1][0] - cx))


def decide_sweep_failure(had_candidates: bool, resweeps_done: int,
                         max_resweeps: int = 1, pitch_layers_left: int = 0,
                         extra_mode: bool = False) -> str:
    """sweep 失敗分流（純函式）。回 "RESWEEP" / "NEXT_LAYER" / "HUMAN" / "EXIT_SUCCESS"。

    - 看到過穩定框、轉回後 verify 失敗 → RESWEEP（H019；框在本層，重掃上限 max_resweeps）。
    - 全空 ∧ 尚有俯仰層未掃 → NEXT_LAYER（2026-07-11 spec：yaw 只改 x 不改 y，
      標準層看不到的框換俯仰層才有機會；只掛全空分支，verify 失敗跳層無益）。
    - 其餘 → HUMAN（偵測已準，2026-06-29 決策）。
    - extra_mode=True（episode 已有成功入帳、續採途中；incident 072）：原本回 HUMAN/NEXT_LAYER
      的情況改回 EXIT_SUCCESS——bonus 框淡掉≠失敗，絕不可把成功 episode 轉成交人工/換層，
      正常收尾回 MINING 即可。RESWEEP 條件成立時仍 RESWEEP（框還在、值得重定位）。
    """
    if had_candidates and resweeps_done < max_resweeps:
        return "RESWEEP"
    if extra_mode:
        return "EXIT_SUCCESS"
    if not had_candidates and pitch_layers_left > 0:
        return "NEXT_LAYER"
    return "HUMAN"


def decide_post_success(recheck_pos, fired_pos, extra_targets: int,
                        max_extra: int, min_dist_px: float) -> str:
    """採集成功後「畫面還有另一個追蹤框」的續採決策（純函式，incident 072 對策）。

    回傳 "CONTINUE" / "EXIT"。寧漏勿誤（漏了＝維持今日行為，誤續採＝多繞一輪 sweep）：
    - recheck_pos None（成功後畫面沒框）→ EXIT
    - extra_targets >= max_extra（續採上限）→ EXIT
    - fired_pos None（晚到確認路徑，上一發座標已被 RESWEEP 清掉，無法距離閘）→ EXIT
    - 距離 < min_dist_px → EXIT（剛採掉的框擊中後 2~10s 才淡出，原地殘影非新礦）
    - 其餘 → CONTINUE

    距離用歐氏距離。072 實錄：真第二顆距上一發開火座標 551px、剛採掉淡出框漂移 ≤8px，
    距離閘 100px 兩側各有 ~5.5x / ~12x 餘裕。
    """
    if recheck_pos is None:
        return "EXIT"
    if extra_targets >= max_extra:
        return "EXIT"
    if fired_pos is None:
        return "EXIT"
    dx = recheck_pos[0] - fired_pos[0]
    dy = recheck_pos[1] - fired_pos[1]
    if (dx * dx + dy * dy) ** 0.5 < min_dist_px:
        return "EXIT"
    return "CONTINUE"


def decide_verify_poll(gone: bool, confirmed: bool, elapsed_s: float, window_s: float) -> str:
    """D3 開火後「輪詢驗證」的單步決策（純函式，H015 對策）。

    回傳 "SUCCESS" / "POLL" / "RESWEEP" / "RETRY"。

    舊流程 click 後固定等 0.5s 抓一幀就判生死——太早：H015 第二槍實際命中，但追蹤框
    是擊中後 2~10s 才消失、聊天成功行更晚才到（且聊天無新訊息 ~15s 會整個淡出，唯有
    新訊息會讓它重新顯示）→ 單幀抓在空窗上 = gone=False + no-new → RETRY → 超時誤交人工。

    - confirmed → SUCCESS（隨時早退；晚到的聊天行就是靠輪詢接住的）
    - 窗口未到 → POLL（框在不在都續等：框慢消失/成功行未到都不是結論）
    - 窗口到   → 交 decide_harvest_result 收尾（gone→RESWEEP、框還在→RETRY）
    """
    if confirmed:
        return "SUCCESS"
    if elapsed_s < window_s:
        return "POLL"
    return decide_harvest_result(gone, confirmed)


def normalize_rotations(net: int, dirs: int = 8) -> int:
    """淨轉動化約成 360° 環上的最短等價路徑（純函式）。

    8 方位 45° 一格：淨右轉 7 ≡ 左轉 1（回 -1）、淨 ±8 ≡ 不動（回 0）。
    每次旋轉要 key_press + 0.35s settle，繞遠路一趟最多白花 ~2.4s。
    正好對面（|net|=dirs/2）左右等距，取正（步數相同，方向無差）。
    """
    r = net % dirs
    return r if r <= dirs // 2 else r - dirs


def plan_return_rotations(from_dir: int, to_dir: int, dirs: int = 8) -> int:
    """sweep 完成後從 from_dir 轉到 to_dir 的最短帶號步數（純函式；正=右轉、負=左轉）。

    sweep 結束站在 dir 7；舊版一律往左轉 (7-best_dir) 次——best_dir=0 要左轉 7 次
    （~2.4s），其實右轉 1 次 wrap 360° 就到（0.35s）。
    """
    return normalize_rotations(to_dir - from_dir, dirs)


def restore_actions(net_rotations: int) -> list:
    """挖完後要轉回原角度的動作序列（純函式）。

    先 normalize_rotations 取最短等價路徑（淨右轉 7 → 右轉 1 補滿 360°，不左轉 7 次），
    再反向：淨右轉 N（net>0）→ N 個 ROTATE_LEFT；淨左轉則相反。
    """
    net_rotations = normalize_rotations(net_rotations)
    if net_rotations > 0:
        return ["ROTATE_LEFT"] * net_rotations
    if net_rotations < 0:
        return ["ROTATE_RIGHT"] * (-net_rotations)
    return []


def rotation_looks_eaten(mean_diff, changed_frac, mean_thresh: float, frac_thresh: float) -> bool:
    """旋轉鍵前後幀「幾乎沒變」＝按鍵被吃掉（純函式，2026-07-05 視角回歸 45° 偏移對策）。

    視角回歸靠 net_rotations 計數反轉，前提是每個 ,/. 都真的生效——被吃一次就差 45°
    （pickup 動畫/焦點被搶都會吃鍵；挖礦視角是 90° 倍數對齊，差 45° 直接影響效率）。
    旋轉 45° 讓中央場景劇變、被吃則幾乎逐位元相同（覆蓋 UI 不轉、角色 idle 只微幅變化）。
    誤判方向的取捨：實際轉了卻誤判被吃而重送＝直接製造 45° 偏移，比漏判（退回舊行為）
    更糟 → 兩訊號（平均差＋有感變化像素佔比）都近零才判被吃；近全黑礦坑旋轉的平均差
    可能低於門檻，但變化像素佔比仍高，AND 條件擋住這種誤重送。無從比較（None）一律
    當已生效（寧信不重送）。
    """
    if mean_diff is None or changed_frac is None:
        return False
    return mean_diff <= mean_thresh and changed_frac <= frac_thresh


def format_rotation_hint(net_rotations: int) -> str:
    """把淨轉動轉成給人工看的 Discord 提示文字（純函式）。

    `.,` 各 45°；正=右轉（.）、負=左轉（,）。restore_view 後視角回到原點，
    使用者若想面對剛剛採集放棄時的追蹤框角度，需要按對應鍵 |net| 次。
    回傳空字串代表 net=0（不需提示；視角已在原點）。
    """
    abs_rot = abs(net_rotations)
    if abs_rot == 0:
        return ""
    key = "." if net_rotations > 0 else ","
    return f"（面對追蹤框：按 {key} {abs_rot} 次 ≈ {abs_rot*45}°）"

@dataclass(frozen=True)
class GiveupCrop:
    """放棄時要裁的一張左側對比圖（純資料）。

    source: "before"（本輪 _pre_scan_ref，採集開始基準）| "after"（放棄當下 frame）
    region: "chat"（左上 has-found 訊息）| "backpack"（左下 NORMAL 面板）
    label : 快照 label（_hsnap_crop 會再前綴本輪 harvest_id）
    """
    source: str
    region: str
    label: str


@dataclass(frozen=True)
class GiveupPlan:
    """採集放棄時的視角處置 + 截圖方案（純資料）。

    restore_view : 轉回原視角？（無框才轉回、便於判斷礦是否已被玩家挖走）
    tracker_view : 主圖用「面對追蹤框」裁圖？（有框採不到時 True，人工可據此手動採）
    review_crops : 4 張左側前後對比裁圖（聊天×前後、背包×前後）。**兩條路徑都附**
                   （H015：D3 超時只送框裁圖、而框已消失＝圖上空無一物，使用者無從判斷）
    """
    restore_view: bool
    tracker_view: bool
    review_crops: tuple


# 無框放棄路徑固定的 4 張裁圖（Discord 2x2：上排聊天前後、下排背包前後）
_REVIEW_CROPS = (
    GiveupCrop("before", "chat", "giveup_before_chat"),
    GiveupCrop("after", "chat", "giveup_after_chat"),
    GiveupCrop("before", "backpack", "giveup_before_backpack"),
    GiveupCrop("after", "backpack", "giveup_after_backpack"),
)


def plan_giveup(face_tracker: bool) -> GiveupPlan:
    """採集放棄時依「有無追蹤框」決定視角處置 + 截圖方案（純函式，需求 A+C）。

    face_tracker=True（找到追蹤框但採不到，D3 階段失敗）：**不轉回**視角、保持面對追蹤框，
      主圖給「面對追蹤框」裁圖，人工一眼看到框可手動採。
    face_tracker=False（沒找到框 / 掃描超時 / 採到但重新聚焦失敗）：**轉回**原視角（快速恢復、
      便於判斷礦是否已被玩家挖走）。

    兩條路徑都附 4 張左側前後對比裁圖（聊天×前後、背包×前後）——H015：D3 超時其實已採到
    （驗證抓太早誤判），只送的框裁圖上框已消失＝空無一物，人工無從判斷；聊天/背包前後對比
    才是「礦是否已採到」的可判證據，與視角無關（左側 UI 是螢幕覆蓋層）。
    """
    if face_tracker:
        return GiveupPlan(restore_view=False, tracker_view=True, review_crops=_REVIEW_CROPS)
    return GiveupPlan(restore_view=True, tracker_view=False, review_crops=_REVIEW_CROPS)


def giveup_send_groups(review_crops):
    """把放棄裁圖依 region 分組，供 Discord「分開發送」（純函式）。

    回傳 [(region, [GiveupCrop, ...]), ...]，順序＝region 首次出現順序。`_REVIEW_CROPS`
    為聊天在前、背包在後 → **先發聊天框、再發背包**。每群保留前/後兩張，維持既有「前後
    對比」模式，只是從「一則 4 圖（Discord 2×2）」改成「兩則各 2 圖」（見 2026-07-02 需求）。
    有框放棄路徑（review_crops 為空）→ 回空 list（沿用單張追蹤框圖，不分組）。
    """
    groups = []
    index = {}
    for c in review_crops:
        if c.region not in index:
            index[c.region] = len(groups)
            groups.append((c.region, []))
        groups[index[c.region]][1].append(c)
    return groups

def prepare_scan():
    """停止移動、置中鏡頭——在這之後應立刻截圖當 reference，再呼叫 execute_scan。"""
    ic.key_up("w"); ic.mouse_up()
    ic.center_crosshair()                  # 置中後角色裝備位置才穩定
    time.sleep(0.15)                       # 等畫面更新再截 reference

def execute_scan():
    """置中後裝備 D2 + 點擊觸發掃描（與 prepare_scan 分開是為了讓呼叫端在中間截 reference）。

    ★ D2(slot 2) 是 toggle（rule 3、fixtures/slot/README 警告）：掃描器已裝備時再按 "2"
    會**卸裝**而非重掃。連續兩次掃描、中間沒換 slot（俯仰層轉換 mid 全空→up，沒開 D3）
    時，第二次的 "2" 把掃描器卸下、左鍵點空氣 → 整層沒掃描（H065：harvest 121 up 層全空）。
    守門：先讀 slot 2 是否已選中，已裝備就只 click 重掃、不按 "2"（比照 D1 的 slot_selected）。
    """
    if not vision.slot_selected(capture.grab(), cfg.d2_slot_region,
                                cfg.d2_selected_greenness_min):
        ic.key_press("2")                      # 掃描器未裝備 → 裝上（已裝備時不按：toggle 陷阱）
        time.sleep(0.3)                        # 等裝備動畫
    ic.click_at(cfg.screen_w // 2, cfg.screen_h // 2)  # 左鍵觸發掃描（已裝備時 click 即重掃）
    time.sleep(1.5)                        # 等追蹤框出現

def restore_view(net_rotations: int, rotate=None):
    """實際送鍵把視角轉回原角度（挖完成功後呼叫）。

    rotate：可注入的單步旋轉 callable(direction)->bool（+1 右轉 .、-1 左轉 ,）；
    main 傳 Bot._rotate_verified 讓每步都以前後幀驗證「真的轉了」、被吃就重送
    （視角回歸差 45° 的根治點）。預設 None 直接送鍵（無驗證，測試/降級用）。
    """
    for action in restore_actions(net_rotations):
        d = -1 if action == "ROTATE_LEFT" else 1
        if rotate is not None:
            rotate(d)
        elif d < 0:
            ic.rotate_left()
        else:
            ic.rotate_right()


def scan_succeeded(texts) -> bool:
    """D2 掃描成功確認：OCR 文字裡有 Local-ish token 即成功。

    標籤在**右下角效果列**的雷達徽章上（2026-07-25 實機校準；早期註解寫「左下」是錯的）。
    呼叫端逐格 OCR 後把各格文字丟進來，故收 list。
    彈窗吃掉 click 時掃描沒觸發 → 白掃 8 方位 ~19s（CLAUDE.md D2 段）。
    容忍 OCR 噪音（i/l 同形），0.75 門檻夾在 'global'(0.73) 與 'locaI'(0.8+) 之間；
    D2 的 Z（`Cave Skim`）同樣是雷達徽章，實測 ratio 遠低於門檻不會誤判。
    """
    for text in texts or []:
        for tok in (text or "").lower().split():
            t = tok.strip(":.,!1234567890 ")
            if not t:
                continue
            if t == "local" or SequenceMatcher(None, t, "local").ratio() >= 0.75:
                return True
    return False


def scan_cooldown_ready(badge_present: bool, since_last_auto_s: float,
                        cooldown_s: float, ocr_ok: bool) -> bool:
    """採集掃描前的 D2 左鍵就緒判定（純函式）。

    OCR 可用 → 看效果列徽章：`Local` 還在＝Cyberscan 仍在冷卻，按下去不會生效。
    OCR 不可用 → 退回定時（距上次自動使用超過冷卻長度即視為好了）。
    兩條路都保守：寧可多等一輪，也不要在冷卻中送出無效掃描而白掃 8 方位。
    """
    if ocr_ok:
        return not badge_present
    return since_last_auto_s > cooldown_s


def format_radar_status(scan_on: bool, cave_on: bool, ocr_ok: bool = True) -> str:
    """D2 雷達連續使用的啟用情形（啟動訊息／`status` 共用一行文字）。

    掛機者要一眼看出「現在會不會自動重按」，所以直接寫開/關，不寫 config 欄位名。
    OCR 不可用時就緒判定退回定時後備，會影響準確度 → 明講，不靜默降級。
    """
    def mark(on):
        return "✅ 開" if on else "⬜ 關"
    line = f"掃描(D2 左鍵)：{mark(scan_on)}｜削洞(D2 Z)：{mark(cave_on)}"
    if (scan_on or cave_on) and not ocr_ok:
        line += "（OCR 不可用 → 改用定時後備）"
    if scan_on:
        line += "\nℹ 掃描開啟中：與採集共用 D2 冷卻，採集會先等冷卻結束再掃（最多多等 ~30s）"
    return line


def cave_skim_present(texts) -> bool:
    """效果列文字裡有沒有「Cave Skim」徽章＝D2 的 Z 還在冷卻中。

    與 scan_succeeded 對稱：呼叫端逐格 OCR 後把各格文字丟進來。徽章文字分兩行，
    OCR 實測讀成 'cave\\nskim'。任一 token 像 cave 或 skim 都算——兩個字都夠獨特，
    對 'Local'/'Used' 的相似度遠低於門檻，不會互相誤判。
    """
    for text in texts or []:
        for tok in (text or "").lower().split():
            t = tok.strip(":.,!1234567890 ")
            if not t:
                continue
            for want in ("cave", "skim"):
                if t == want or SequenceMatcher(None, t, want).ratio() >= 0.75:
                    return True
    return False


def plan_boost_pair_due(screen_count, last_pair_count, every_n: int) -> bool:
    """FOV 前後幀對取樣節流（2026-07-19）：螢幕計數每前進 every_n 存一組。

    boost FOV 縮小隨使用次數累積（有極限、位置未知）——曲線量測靠「到期(縮)→
    補瓶(展開)」前後幀同場景自比，每次都存太肥（1080p 對 ~200 組/場），依螢幕
    計數節流。計數讀不出（None）不存（沒 x 軸標籤的量測點無用）；every_n<=0
    ＝功能關閉；session 首次（last None）＝基準點必存。
    """
    if every_n <= 0 or screen_count is None:
        return False
    return last_pair_count is None or screen_count - last_pair_count >= every_n


# ── chill 前證據快取 ＋ NORMAL 面板名字欄（spec 2026-07-30）────────────────────

def pick_prechill_ref(entries, before_ts: float, min_age_s: float, max_age_s: float):
    """環形緩衝取用（純函式）：回「落在 [before_ts-max_age_s, before_ts-min_age_s] 的最新一筆」。

    entries 依時間遞增（deque append 天生保序）。沒有合格的回 None。

    **下界** `min_age_s`：太新的參考可能已經含了那次挖掘（chill 偵測本身有延遲），
    差分就會是 0＝救不到。

    **上界** `max_age_s`：快取進 HARVESTING 時不清空（spec 要求），所以「上一場採集
    剛結束、回到 MINING 沒幾秒又 chill」時，緩衝裡還留著**上一場之前**的幀。拿它當基準
    會把上一場採到的礦算成這一場的新增＝假救援＝靜默放生一顆真稀有礦且沒有任何 log
    會發現。過期就回 None（＝救援整個跳過＝回到今日行為），寧漏勿誤。
    """
    newest = before_ts - min_age_s
    oldest = before_ts - max_age_s
    for entry in reversed(list(entries)):
        if entry[0] <= newest:
            return entry if entry[0] >= oldest else None
    return None


# 名字與數量黏成同一框時的切點：第一個數字或逗號之前
# （"Cloverstone 1,6" → "Cloverstone"、"Imbollyx. 8" → "Imbollyx."）。
_PANEL_COUNT_START = re.compile(r"[\d,]")


def parse_panel_ore_names(boxes, max_x: int, min_y: int, min_letters: int = 3) -> list:
    """左下 NORMAL 面板的 `ocr.read_text_boxes` 結果 → 畫面上有哪些礦名（保序去重、小寫）。

    boxes 的 center 必須是 **crop 座標**（`read_text_boxes` 不加 region_offset 時就是）。
    兩道幾何閘與字母下限見 `Config.panel_name_col_max_x` / `panel_row_min_y` /
    `panel_name_min_letters`：靜態 UI（NORMAL／www）在前後兩張裁圖本來就會互相抵銷，
    閘擋的是**會變動**的右側 craft 面板數字被讀歪成假礦名。

    ⚠ 本函式**只讀名字不讀數字**，所以不需要 craft 面板守門——2026-07-30 實測 125 那張是
    Shamrock「Materials to Craft」面板開著拍的，名字仍 0.999+ 全數讀出。未來任何要讀**數字**
    的實作**必須**先守門：該面板從 x≈185 起疊在數字欄上，OCR 會讀到配方需求
    （`310/190 Siogyne`）而不是存量——那是**錯的值不是缺值**。
    """
    out, seen = [], set()
    for box in boxes or []:
        cx, cy = box.get("center", (0, 0))
        if cx > max_x or cy < min_y:
            continue
        text = box.get("text") or ""
        cut = _PANEL_COUNT_START.search(text)
        name = (text[:cut.start()] if cut else text).strip(" .,:;-_|")
        if sum(ch.isalpha() for ch in name) < min_letters:
            continue
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def new_rare_panel_ores(pre_names, cur_names) -> list:
    """面板名字集合差分 → cur 新增、且**在高階白名單上**的礦名（保序）。

    pre 為空 → 一律回 []：快取剛建立／OCR 全滅時每個名字看起來都是新的，會把整個面板
    當成「這次挖到的」。寧漏勿誤（誤判的代價是靜默放生一顆真稀有礦）。

    ⚠ H069：這裡**不可以**用「非 common」當稀有判準。`common_ore_names()` 是**聊天
    排除清單**，只收 Surreal/Mythic（＋會出變體的 Master 底名）——因為只有那兩階會被動
    進聊天。但 NORMAL 面板列的是**整個背包**，絕大多數列（Sugarmuck／Cloverstone／
    Imbollyx／Bonnite…）階級遠低於 Surreal、兩張表都沒有 → 落 unknown。舊版把 unknown
    當非-common，於是「鎬子挖了兩分鐘」必然生出新名字＝救援對任何 giveup 都命中
    （2026-07-31 harvest 145：sugarmuck／egguinox／cloverstone 假命中，真稀有礦被放生）。

    白名單（`rare_ores`）收的是 Exotic 以上，正是 chill 會響、D3 要採的那批 →
    改成**要有正面證據**才算進帳。分類走 `game_data.classify_found_ore`（不是
    `fuzzy_match_ore`——那個只比對**事件**礦名，本面板的 Faedrine 全數對不上），
    它含變體前綴剝除、尾端雜訊容忍與模糊兜底，`rare_fuzzy` 一併採計。
    """
    from . import game_data              # 延後 import：game_data 載入資料檔，模組層會拖慢 import
    pre = {n.lower() for n in pre_names or ()}
    if not pre:
        return []
    return [n for n in cur_names or ()
            if n.lower() not in pre
            and game_data.classify_found_ore(n)[0] in ("rare", "rare_fuzzy")]


def chill_reconcile_unbalanced(edge_count: int, gained_count: int) -> bool:
    """雙 chill 對帳（純函式）：上升緣數 ≥2 且進帳非-common 礦名數 < 上升緣數 → 帳不平。

    上升緣數 <2 一律帳平——單聲 chill 不進對帳。
    ⚠ 已知漏判：兩顆**同礦種**只會算成一顆（名字早就在面板上、只有數量 +1，而數量欄
    在 craft 面板開著時讀到的是配方需求不是存量）。這是漏判不是錯判，寧漏勿誤。
    """
    return edge_count >= 2 and gained_count < edge_count
