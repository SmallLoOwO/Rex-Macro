import cv2
import numpy as np

def find_template(scene_bgr, template_bgr, threshold: float):
    """回傳模板在 scene 的中心座標 (x, y)，找不到回 None。

    使用 TM_SQDIFF_NORMED：值越小越相似（0=完全吻合，1=完全不同）。
    TM_CCOEFF_NORMED 在均勻模板（zero variance）時會產生全 1.0 的退化結果，
    因此改用 SQDIFF_NORMED 以確保正確性。
    threshold 語義同 TM_CCOEFF_NORMED：0.9 代表「至少 90% 相似」，
    對應 SQDIFF_NORMED 的 min_val <= (1 - threshold)。
    """
    res = cv2.matchTemplate(scene_bgr, template_bgr, cv2.TM_SQDIFF_NORMED)
    min_val, _, min_loc, _ = cv2.minMaxLoc(res)
    # Guard against NaN/degenerate results
    if not np.isfinite(min_val) or min_val > (1.0 - threshold):
        return None
    th, tw = template_bgr.shape[:2]
    return (min_loc[0] + tw // 2, min_loc[1] + th // 2)

def template_present(scene_bgr, template_bgr, threshold: float) -> bool:
    return find_template(scene_bgr, template_bgr, threshold) is not None

def frames_differ(baseline_bgr, current_bgr, mean_diff_threshold: float = 2.0) -> bool:
    """兩張同尺寸裁圖是否有肉眼可見變化（平均絕對差 > 門檻）——聊天輪詢的省 OCR 閘。

    D3 後輪詢驗證（H015 對策）每 ~1s 檢查聊天，但聊天全區 3-pass OCR 實測 ~10s
    （滿版文字），不能每輪都跑。聊天是螢幕覆蓋層、輪詢期間角色靜止 → 沒新訊息時
    裁圖近乎逐位元相同（實測連 PNG 位元組數都一樣）；新訊息出現或聊天淡出都會
    大幅改變像素 → 只在變化時才 OCR。基準缺失或尺寸不合＝無從比較 → 當作有變化。
    """
    d = frames_mean_diff(baseline_bgr, current_bgr)
    return True if d is None else d > mean_diff_threshold


def frames_mean_diff(baseline_bgr, current_bgr) -> float | None:
    """兩張裁圖的平均絕對差；基準缺/尺寸不合回 None（無從比較＝frames_differ 視為有變）。

    拆出數值版是給詳細 log 用（H020 事後排錯）：光看 frames_differ 的 bool 無法回答
    「為什麼那輪沒觸發 OCR」——差值多少、離門檻多遠，要留在 harvest.log 裡。
    """
    if baseline_bgr is None or current_bgr is None:
        return None
    if baseline_bgr.shape != current_bgr.shape:
        return None
    return float(np.mean(cv2.absdiff(baseline_bgr, current_bgr)))


def frames_changed_frac(baseline_bgr, current_bgr, pixel_thresh: int = 12) -> float | None:
    """有感變化像素的佔比（任一 channel 絕對差 > pixel_thresh 才算變化）；無從比較回 None。

    驗證式旋轉的第二訊號（2026-07-05）：近全黑礦坑旋轉 45° 的「平均差」可能低於門檻
    （像素值本來就低），但有感變化像素的佔比仍高；被吃的按鍵只剩角色 idle 微幅變化、
    佔比近零。與 frames_mean_diff 搭配讓 rotation_looks_eaten 的「被吃」判定保守
    （兩訊號都近零才重送——實際轉了卻重送＝直接製造 45° 偏移）。
    """
    if baseline_bgr is None or current_bgr is None:
        return None
    if baseline_bgr.shape != current_bgr.shape:
        return None
    d = cv2.absdiff(baseline_bgr, current_bgr)
    per_pixel = d.max(axis=2) if d.ndim == 3 else d
    return float(np.mean(per_pixel > pixel_thresh))


def _canny(img_bgr):
    return cv2.Canny(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY), 50, 150)

def _best_edge_match(scene_e, sh, sw, template_bgr, scales):
    """在多尺度下找模板邊緣的最佳匹配，回 (best_val, best_center) 或 (-1, None)。"""
    best_val, best_loc = -1.0, None
    for s in scales:
        t = template_bgr if s == 1.0 else cv2.resize(
            template_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th > sh or tw > sw or th < 4 or tw < 4:
            continue                              # 模板比畫面大、或縮到太小 → 跳過
        res = cv2.matchTemplate(scene_e, _canny(t), cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if np.isfinite(max_val) and max_val > best_val:
            best_val = max_val
            best_loc = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
    return best_val, best_loc

def find_template_edges(scene_bgr, template_bgr, threshold: float, scales=(1.0,)):
    """顏色無關 + 多尺度的模板定位：先用 Canny 取邊緣（只看形狀）再比對。

    適用於目標填色每次都不同、但外框/形狀固定的情況（例如掃描後的礦物標記）。
    `scales` 會把模板縮放成多種大小各試一次，取最佳——這樣即使模板（例如 wiki 圖）
    的尺寸跟畫面上不一致也能找到（模板比對本身不具縮放不變性）。
    回中心座標 (x, y)，找不到回 None。threshold 為邊緣相關度（0..1，越高越嚴）。
    """
    scene_e = _canny(scene_bgr)
    sh, sw = scene_e.shape[:2]
    val, loc = _best_edge_match(scene_e, sh, sw, template_bgr, scales)
    return loc if (loc is not None and val >= threshold) else None

def find_best_marker(scene_bgr, templates: dict, threshold: float, scales=(1.0,)):
    """在多個標記模板（不同階級）中找最佳匹配（顏色無關 + 多尺度）。

    templates: {名稱: BGR 模板}。回 (名稱, (x, y)) 或 None。
    名稱通常是階級（exotic/mythic…），可順便知道掃到哪一級。
    """
    scene_e = _canny(scene_bgr)
    sh, sw = scene_e.shape[:2]
    best_name, best_val, best_loc = None, -1.0, None
    for name, tmpl in templates.items():
        val, loc = _best_edge_match(scene_e, sh, sw, tmpl, scales)
        if loc is not None and val > best_val:
            best_name, best_val, best_loc = name, val, loc
    if best_loc is None or best_val < threshold:
        return None
    return (best_name, best_loc)

def best_template_match_scored(scene_bgr, templates: list, scales=(1.0,)):
    """多模板取最佳 (score, center)；找不到回 (-1.0, None)。

    與 find_template_edges 的差別：回分數不設門檻——reentry sweep 要跨 8 方位
    比大小、由呼叫端用 config 門檻決定「夠不夠信心」（寧漏勿誤在決策層做）。
    """
    scene_e = _canny(scene_bgr)
    sh, sw = scene_e.shape[:2]
    best_val, best_loc = -1.0, None
    for t in templates:
        v, loc = _best_edge_match(scene_e, sh, sw, t, scales)
        if loc is not None and v > best_val:
            best_val, best_loc = v, loc
    return best_val, best_loc

def load_template(path: str):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return img

def load_template_any(path: str):
    """保留 alpha 載入（wiki 追蹤框是透明 PNG、只有外框；IMREAD_COLOR 會丟掉透明通道）。"""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    return img

def pixel_matches(scene_bgr, xy, rgb_hex: int, tol: int) -> bool:
    """指定點顏色是否接近 rgb_hex（容差 tol，逐通道）。scene 為 BGR。"""
    x, y = xy
    b, g, r = (int(c) for c in scene_bgr[y, x])
    R = (rgb_hex >> 16) & 0xFF
    G = (rgb_hex >> 8) & 0xFF
    B = rgb_hex & 0xFF
    return abs(r - R) <= tol and abs(g - G) <= tol and abs(b - B) <= tol

def frame_mean_diff(a_bgr, b_bgr) -> float:
    """兩幀平均絕對像素差，用於卡住偵測。"""
    return float(np.mean(np.abs(a_bgr.astype(np.int16) - b_bgr.astype(np.int16))))


def region_greenness(scene_bgr, region) -> float:
    """區域『綠色主導』程度＝平均 G − 平均 (R+B)/2（BGR 影像；region 為 config.Region）。

    hotbar 選中（裝備中）的槽位底色會轉綠 → 綠色主導值明顯為正；未選中為灰、值近 0。
    用來取代易受版面位移影響的單點 `pixel_matches`（工作列調回顯示後底部 UI 上移約 50px，
    寫死單點會落到場景上）。取整區平均而非單點 → 對輕微位移/雜訊穩健。
    """
    roi = scene_bgr[region.y:region.y + region.h, region.x:region.x + region.w]
    b = float(roi[..., 0].mean())
    g = float(roi[..., 1].mean())
    r = float(roi[..., 2].mean())
    return g - (r + b) / 2.0


def slot_selected(scene_bgr, region, threshold: float) -> bool:
    """槽位是否為『選中/裝備中』狀態（底色轉綠）：greenness ≥ threshold 即選中。"""
    return region_greenness(scene_bgr, region) >= threshold


def chat_icon_probe_mean(icon_bgr, probe) -> float:
    """聊天圖示補丁（泡泡內部，見 chat_icon_state）灰階平均值（H047）。

    拆出數值版供呼叫端 log 用（事後 grep probe 實測值），也讓 chat_icon_state 內部共用
    同一份切片邏輯——比照 region_greenness/slot_selected、frames_mean_diff/frames_differ
    的拆法。probe=(x0,y0,x1,y1) 為 icon_bgr 內的相對座標。
    """
    x0, y0, x1, y1 = probe
    patch = icon_bgr[y0:y1, x0:x1]
    return float(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).mean())


def chat_icon_state(icon_bgr, probe, open_min_gray: float, closed_max_gray: float) -> str:
    """聊天圖示開關判定（H047）。回 'open' | 'closed' | 'unknown'。

    icon_bgr：chat_icon_state_region 裁圖（BGR）。probe=(x0,y0,x1,y1) 為 crop 內相對座標，
    取泡泡內部補丁（左下內部，避開中央文字筆劃與右上未讀徽章）灰階平均：
    >=open_min_gray 判開（實心白泡泡）、<=closed_max_gray 判關（空心、內部暗）、
    其間 unknown（呼叫端絕不能點擊——誤判開頂多維持現狀，誤判關點下去會把開著的
    聊天框關掉，才是破壞性動作，方向必須保守）。
    兩側夾：開 238..255 / 關 81..87（docs/incidents.md H047）。
    """
    mean = chat_icon_probe_mean(icon_bgr, probe)
    if mean >= open_min_gray:
        return "open"
    if mean <= closed_max_gray:
        return "closed"
    return "unknown"


# 各階級追蹤框外框 HSV 顏色範圍（wiki 量測 ± 余量）
# 橘/黃/綠：Exotic(H22), Enigmatic(H34), Exquisite(H64) → H18-78
# 藍系：Transcendent(H105), Unfathomable(H109) → H88-130
# 紫系：Exclusive(H142) → H118-165
# 暗紅：Otherworldly(H167) → H153-179
_TRACKER_COLORS = [
    (np.array([ 18,  80,  50], np.uint8), np.array([ 78, 255, 255], np.uint8)),
    (np.array([ 88, 130,  40], np.uint8), np.array([130, 255, 255], np.uint8)),
    (np.array([118,  60,  15], np.uint8), np.array([165, 255, 255], np.uint8)),
    (np.array([153, 100,  50], np.uint8), np.array([179, 255, 255], np.uint8)),
]

def template_outline_edges(template):
    """取模板的「外框輪廓」邊緣圖（給形狀比對用）。

    wiki 追蹤框圖是**透明 PNG、只有外框**（中心會填不同礦色，故只能比外框）：
    有 alpha 通道 → 用 alpha（不透明=外框）算 Canny，得到純外框輪廓。
    實機裁圖無 alpha → 退回灰階 Canny。

    注意：`cv2.imread(IMREAD_COLOR)` 會丟掉 alpha，務必用 `IMREAD_UNCHANGED` 載入 wiki 圖。
    """
    if template.ndim == 3 and template.shape[2] == 4:
        return cv2.Canny(template[:, :, 3], 50, 150)
    return _canny(template)


def _best_edge_match_sized(scene_e, sh, sw, tmpl_edges, scales, min_px=12):
    """多尺度比對「模板輪廓邊緣圖」，連命中尺寸一起回傳：(best_val, best_center, tw, th)。

    縮放的是邊緣圖本身（INTER_NEAREST 保形）。min_px 擋掉縮太小的尺度——
    10px 以下的輪廓會在雜亂場景產生假高分（實測 scale 0.2 噪點誤判）。
    """
    best_val, best_loc, best_tw, best_th = -1.0, None, 0, 0
    for s in scales:
        e = tmpl_edges if s == 1.0 else cv2.resize(
            tmpl_edges, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST)
        th, tw = e.shape[:2]
        if th > sh or tw > sw or th < min_px or tw < min_px:
            continue
        res = cv2.matchTemplate(scene_e, e, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if np.isfinite(max_val) and max_val > best_val:
            best_val = max_val
            best_loc = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
            best_tw, best_th = tw, th
    return best_val, best_loc, best_tw, best_th


def _colored_ring_score(frame_bgr, cx, cy, bw, bh, s_min=90, v_min=90):
    """色相無關地量一個 bbox 的「彩色佔比」與「環形結構」。

    回傳 (colored_frac, ring_score)：
    - colored_frac：bbox 內高飽和(S>s_min)且夠亮(V>v_min)的像素比例——
      不分色相，所以任何階級顏色的追蹤框（橘/藍/紫/綠…）都算。灰色岩壁飽和度低 → 接近 0。
    - ring_score = colored_frac - inner_frac（中心 30%-70% 區）：真追蹤框邊框/箭頭有色、
      中心是黑環/礦色 → 邊緣彩色多、正值；實心彩色 blob 中心也有色 → 接近 0。
    """
    x0 = max(0, cx - bw // 2); y0 = max(0, cy - bh // 2)
    roi = frame_bgr[y0:y0 + bh, x0:x0 + bw]
    if roi.size == 0:
        return 0.0, 0.0
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    colored = (hsv[:, :, 1] > s_min) & (hsv[:, :, 2] > v_min)
    frac = float(colored.mean())
    mh, mw = colored.shape
    inner = colored[int(mh * 0.30):int(mh * 0.70), int(mw * 0.30):int(mw * 0.70)]
    inner_frac = float(inner.mean()) if inner.size > 0 else frac
    return frac, frac - inner_frac


def find_marker(frame_bgr, templates, edge_threshold: float = 0.50, scales=(1.0,),
                exclude=(), margin_frac: float = 0.10,
                min_colored: float = 0.20, log=None):
    """以「實機追蹤框裁圖」做形狀（邊緣）比對為主的偵測器——顏色無關，可跨階通用。

    為什麼用形狀而非 HSV：追蹤框的「黑邊方框＋四方向箭頭」輪廓跨階級固定，只有
    邊框/中心顏色隨階級與礦物變。Canny 邊緣比對忽略顏色 → 同一張實機裁圖即可命中
    不同顏色的階級（實測色相位移後仍命中），不必為每個新色系手刻 HSV 範圍。

    為什麼用「實機裁圖」而非 wiki 圖：wiki 是乾淨向量 icon，邊緣結構與遊戲內實際渲染
    （抗鋸齒＋彩色中心＋雜亂背景）對不上，實測 wiki 模板完全配不到；實機裁圖 edge≈0.91。

    流程：每個模板多尺度邊緣比對取最佳位置 → 在該位置做色相無關的彩色/環形確認
    （排除剛好同形狀的灰色岩壁邊緣）→ 取邊緣分數最高者。

    templates: {名稱: BGR 實機裁圖}。空 dict → 退回 HSV find_tracker（尚未建模板的階級的安全網）。
    """
    if not templates:
        return find_tracker(frame_bgr, margin_frac=margin_frac, exclude=exclude,
                            log=log, reference_bgr=None)
    h, w = frame_bgr.shape[:2]
    scene_e = _canny(frame_bgr)
    sh, sw = scene_e.shape[:2]
    mx0, my0 = w * margin_frac, h * margin_frac
    mx1, my1 = w * (1 - margin_frac), h * (1 - margin_frac)
    best = None  # (edge_val, (cx, cy))
    for name, tmpl in templates.items():
        tmpl_edges = template_outline_edges(tmpl)
        val, loc, tw, th = _best_edge_match_sized(scene_e, sh, sw, tmpl_edges, scales)
        if loc is None or val < edge_threshold:
            continue
        cx, cy = loc
        in_area = (mx0 < cx < mx1 and my0 < cy < my1)
        in_exclude = any(x0 <= cx <= x1 and y0 <= cy <= y1 for (x0, y0, x1, y1) in exclude)
        colored_frac, ring = _colored_ring_score(frame_bgr, cx, cy, tw, th)
        # 形狀（edge）已把實心 blob/灰岩濾掉大半；色相無關的 colored_frac 再擋「同形狀但灰色」
        # 的岩壁邊緣。ring 只記錄供調參參考，不當門檻（追蹤框中心常是亮礦色，ring 可能 ≤0）。
        accept = (in_area and not in_exclude and colored_frac >= min_colored)
        if log is not None:
            log("marker候選 %s (%d,%d) edge=%.2f colored=%.2f ring=%.2f in_area=%s -> %s"
                % (name, cx, cy, val, colored_frac, ring, in_area, "OK" if accept else "rej"))
        if accept and (best is None or val > best[0]):
            best = (val, (cx, cy))
    return best[1] if best else None


def best_outline_score(scene_bgr, templates, scales=(1.0,), min_px=12) -> float:
    """回傳 templates 中任一模板外框在 scene 的最佳邊緣相關度（0..1）。

    給「混合偵測」的形狀確認用：在 HSV 候選周圍的小 ROI 上跑，分數高 = 該處有追蹤框外框。
    templates 可混用 wiki 透明圖（用 alpha 外框）與實機裁圖（用灰階邊緣）。
    """
    if scene_bgr is None or scene_bgr.size == 0 or not templates:
        return -1.0
    scene_e = _canny(scene_bgr)
    sh, sw = scene_e.shape[:2]
    best = -1.0
    for tmpl in templates.values():
        val, loc, _, _ = _best_edge_match_sized(
            scene_e, sh, sw, template_outline_edges(tmpl), scales, min_px)
        if loc is not None and val > best:
            best = val
    return best


def find_tracker(frame_bgr, margin_frac: float = 0.10, exclude=(), log=None,
                 reference_bgr=None, shape_templates=None,
                 shape_threshold: float = 0.45,
                 shape_hard_floor: float = 0.25,
                 shape_scales=(0.6, 0.8, 1.0, 1.2, 1.5, 2.0),
                 shape_roi_px: int = 160, with_score: bool = False,
                 collect_rejects=None):
    """偵測 D2 掃描後的稀有礦「追蹤框」，回傳框中心 (x, y)；找不到回 None。

    各階級外框顏色不同（Exquisite 綠、Exotic 橘、Enigmatic 萊姆、Exclusive 暗紫、
    Otherworldly 暗紅、Transcendent 亮藍、Unfathomable 暗藍）——每個顏色範圍獨立偵測：
    空心率用「當前這個顏色的 mask」計算，避免其他顏色（如紅色礦坑背景 H≈168）干擾。

    reference_bgr：D2 掃描前截圖。提供後會過濾「掃描前就存在的彩色物件」，
    只接受掃描後才新出現的追蹤框，有效排除礦石本體/角色裝備等假陽性。
    `log`：傳 callable 可印出每個候選的判定指標，方便調參。

    shape_templates：傳入實機裁圖 dict 後啟用「混合偵測」——HSV 負責快速找候選，
    再在每個候選周圍的小 ROI 跑外框形狀比對確認，拒掉「有顏色但不是追蹤框形狀」的
    假陽性（如角色裝備）。空/None → 純 HSV（向後相容）。形狀比對只在小 ROI 上跑，
    比全幀模板比對快上百倍。

    shape_hard_floor：edge 低於此值的候選直接拒（連 soft filter 也不救）——擋「HSV
    很強但形狀完全錯」的裝備誤判（實測 edge≈0.16）。只有 survivor（floor≤edge<
    threshold）才退回 HSV，保留「未見階級外框配不到模板」的安全網。
    """
    h, w = frame_bgr.shape[:2]
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    ref_hsv = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2HSV) if reference_bgr is not None else None
    mx0, my0 = w * margin_frac, h * margin_frac
    mx1, my1 = w * (1 - margin_frac), h * (1 - margin_frac)
    candidates = []   # [(colored_frac, cx, cy, ring_ok)] 通過 HSV 收集的候選
    for lo, hi in _TRACKER_COLORS:
        color_mask = cv2.inRange(hsv, lo, hi)
        ref_mask = cv2.inRange(ref_hsv, lo, hi) if ref_hsv is not None else None
        cnts, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < 400 or area > 5000:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            if not (18 <= bw <= 80 and 18 <= bh <= 80):
                continue
            if abs(bw - bh) > max(bw, bh) * 0.5:
                continue
            cx, cy = x + bw // 2, y + bh // 2
            in_area = (mx0 < cx < mx1 and my0 < cy < my1)
            in_exclude = any(x0 <= cx <= x1 and y0 <= cy <= y1 for (x0, y0, x1, y1) in exclude)
            # 空心率：只算「當前這個顏色的 mask」——避免礦坑背景同色系的 H 范圍干擾
            frame_fill = float(np.mean(color_mask[y:y+bh, x:x+bw] > 0))
            # 環形結構：tracker 外框的顏色多分佈在邊緣；cave wall/實心 blob 中心也有顏色
            # ring_score = frame_fill - inner_fill（縮 30% 取中心區）；空心框 ≈ 0.5，實心 blob ≈ 0
            _mx = max(1, int(bw * 0.30)); _my = max(1, int(bh * 0.30))
            _inner = color_mask[y+_my:y+bh-_my, x+_mx:x+bw-_mx]
            _inner_fill = float(np.mean(_inner > 0)) if _inner.size > 0 else frame_fill
            ring_score = frame_fill - _inner_fill
            # 專注外框：量「整個 bbox」的彩色佔比（色相無關 S>90&V>90），不再只看中心。
            # 為何不看中心：追蹤框中心顏色每次會變（不同礦色/粉紅/甚至純黑空心 BGR[0,0,0]），
            # 中心非不變特徵；舊版要求中心 2/3 有彩色像素，遇黑心框 colored=0 → 被當暗色 UI
            # 面板拒掉而漏抓（2026-06-29 黑心綠框 black_center_scene.png 踩坑根因）。
            # 真追蹤框有「厚實彩色外框」→ 整框彩色佔比高（實測黑心 0.51-0.62、彩心 0.7-1.0）；
            # 細框暗色 UI 面板佔比低（合成 0.33、實機 ≈0.16）→ 用佔比門檻區隔，形狀確認再精篩。
            # （colored_frac 算在差分過濾之前——它只讀 hsv，搬動安全；remote-aim 近失候選外露要用）
            bb_hsv = hsv[y:y+bh, x:x+bw]
            colored = (bb_hsv[:, :, 1] > 90) & (bb_hsv[:, :, 2] > 90)
            colored_frac = float(colored.mean())
            # 差分過濾：掃描前就已存在的彩色物件（礦石本體/角色裝備）→ 排除
            if ref_mask is not None:
                ref_fill = float(np.mean(ref_mask[y:y+bh, x:x+bw] > 0))
                if ref_fill > 0.15:
                    if collect_rejects is not None and colored_frac > 0.40:
                        collect_rejects.append({"pos": (cx, cy), "colored": colored_frac,
                                                "edge": None, "reason": "preexist"})
                    if log is not None:
                        log("tracker候選 (%d,%d) area=%d fill=%.2f ref_fill=%.2f -> rej(preexist)"
                            % (cx, cy, int(area), frame_fill, ref_fill))
                    continue
            # ring_ok：環形/空心「結構」訊號。**在混合模式下不再當硬門檻**——真追蹤框的中心
            # 可能是亮礦色實心（H13 綠實心中心 fill≈1.00、ring≈0.00）或彩色圖示，會讓 ring≈0/負、
            # fill≥0.85，被舊版 rej(not_ring)/fill 關卡在「形狀確認前」誤殺（H13 漏抓根因；
            # 同 2026-06-29 黑心框那類「中心非不變特徵」的坑）。改由形狀（edge）當精準仲裁：
            # ring/fill 只保留為 (a) 純 HSV 後備（無形狀模板時的唯一結構過濾）、(b) survivor 防線
            # （borderline edge 才需 ring_ok，擋非環形假陽性被拉上來），confirmed 一律不看 ring_ok。
            ring_ok = (ring_score >= 0.15 and frame_fill < 0.85)
            accept = (in_area and not in_exclude and colored_frac > 0.40)
            if log is not None:
                log("tracker候選 (%d,%d) area=%d fill=%.2f ring=%.2f colored=%.2f ring_ok=%s in_area=%s -> %s"
                    % (cx, cy, int(area), frame_fill, ring_score, colored_frac, ring_ok, in_area,
                       "OK" if accept else "rej"))
            if accept:
                candidates.append((colored_frac, cx, cy, ring_ok))
            elif collect_rejects is not None and colored_frac > 0.40:
                # remote-aim 近失候選外露：colored 夠強但被 margin/exclude 擋下（值得人工看）
                reason = "margin" if not in_area else "exclude"
                collect_rejects.append({"pos": (cx, cy), "colored": colored_frac,
                                        "edge": None, "reason": reason})

    # ---- 形狀確認（混合方案）：HSV 候選 → 小 ROI 外框比對，拒假陽性 ----
    # 三區判定：edge ≥ threshold → confirmed（不看 ring_ok，救回實心/彩心真框）；
    # hard_floor ≤ edge < threshold **且 ring_ok** → survivor（退回 HSV，容忍未見階級、
    # 但要求環形以免非環形假陽性翻盤）；其餘 → 拒。
    if shape_templates:
        confirmed = []
        survivors = []      # borderline：保留給 HSV fallback（未見階級安全網）
        for cf, cx, cy, ring_ok in candidates:
            r = shape_roi_px // 2
            roi = frame_bgr[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
            score = best_outline_score(roi, shape_templates, shape_scales)
            verdict = ("OK" if score >= shape_threshold
                       else "soft" if (score >= shape_hard_floor and ring_ok)
                       else "hard_rej")
            if log is not None:
                log("shape確認 (%d,%d) colored=%.2f edge=%.2f ring_ok=%s floor=%.2f thr=%.2f -> %s"
                    % (cx, cy, cf, score, ring_ok, shape_hard_floor, shape_threshold, verdict))
            if collect_rejects is not None and verdict in ("hard_rej", "soft"):
                collect_rejects.append({"pos": (cx, cy), "colored": cf,
                                        "edge": score, "reason": verdict})
            if score >= shape_threshold:
                confirmed.append((score, cx, cy))       # 形狀夠像＝真框，中心實心與否都收
            elif score >= shape_hard_floor and ring_ok:
                survivors.append((score, cx, cy))       # 存 edge 分數（供 with_score / 早停）
            # else：hard_rej（形狀太錯）或「borderline 但非環形」→ 完全移除
        if confirmed:
            confirmed.sort(reverse=True)        # 形狀分數最高者勝
            s, cx, cy = confirmed[0]
            return (cx, cy, s) if with_score else (cx, cy)
        if survivors:
            # Soft filter：borderline 環形候選（可能是未見階級外框）→ 退回純 HSV
            if log is not None:
                log("shape未確認但 edge≥%.2f 且環形，退回純 HSV（survivors=%d）"
                    % (shape_hard_floor, len(survivors)))
            candidates = survivors               # (edge, cx, cy) 3-tuple
        else:
            # 無 confirmed、無環形 survivor → 判定無追蹤框（拒裝備/非環形誤判）
            if log is not None:
                log("shape無 confirmed 亦無環形 survivor，判定無追蹤框（候選=%d）" % len(candidates))
            return None
    else:
        # 純 HSV（無形狀模板，未見階級安全網）：形狀無法仲裁 → 環形結構是唯一過濾，只留 ring_ok
        candidates = [(cf, cx, cy) for cf, cx, cy, ring_ok in candidates if ring_ok]

    # 排名：survivor 用 edge、純 HSV 用 colored_frac（真 tracker≈1.00 > 裝備誤判≈0.75-0.88），
    # 兩者皆「分數高者勝」語意一致；元素統一為 (score, cx, cy) 3-tuple。
    if not candidates:
        return None
    candidates.sort(reverse=True)
    s, cx, cy = candidates[0]
    return (cx, cy, s) if with_score else (cx, cy)


def find_tracker_near(frame_bgr, center_xy, radius_px, *, frame_margin_frac=0.0,
                      exclude=(), reference_bgr=None, log=None, **kwargs):
    """在 center_xy 周圍 radius_px 的方形 ROI 內跑 find_tracker，座標映射回全幀。

    verify 輪詢的 gone 檢查用：開火座標已知，全幀掃描（~2s）是浪費——ROI 版 ~0.3s。
    frame_margin_frac＝「全幀」邊緣排除帶：ROI 邊不是螢幕邊，故子圖內 margin 一律 0、
    改在映射回全幀後套同一條帶（語意與全幀版一致，H019/H026 的 margin 教訓不重演）。
    找不到回 None——呼叫端自行決定是否全幀後備（H026 FOV 位移可能超出任何小 ROI）。
    """
    h, w = frame_bgr.shape[:2]
    cx, cy = int(center_xy[0]), int(center_xy[1])
    x0, y0 = max(0, cx - radius_px), max(0, cy - radius_px)
    x1, y1 = min(w, cx + radius_px), min(h, cy + radius_px)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None
    sub = frame_bgr[y0:y1, x0:x1]
    sub_ref = reference_bgr[y0:y1, x0:x1] if reference_bgr is not None else None
    shifted = []
    for ex0, ey0, ex1, ey1 in exclude:
        sx0, sy0 = max(ex0 - x0, 0), max(ey0 - y0, 0)
        sx1, sy1 = min(ex1 - x0, x1 - x0), min(ey1 - y0, y1 - y0)
        if sx1 > sx0 and sy1 > sy0:
            shifted.append((sx0, sy0, sx1, sy1))
    res = find_tracker(sub, margin_frac=0.0, exclude=tuple(shifted),
                       reference_bgr=sub_ref, log=log, **kwargs)
    if res is None:
        return None
    mapped = (res[0] + x0, res[1] + y0) + tuple(res[2:])
    mx, my = int(w * frame_margin_frac), int(h * frame_margin_frac)
    if not (mx <= mapped[0] <= w - mx and my <= mapped[1] <= h - my):
        return None
    return mapped


def detect_tracker_core(region_bgr, profiles, *, min_area: int = 80,
                        ar_lo: float = 0.6, ar_hi: float = 1.7,
                        extent_min: float = 0.6, border_margin: int = 6,
                        border_dark_max: int = 70,
                        border_dark_frac_min: float = 0.15, log=None):
    """限縮區域內找追蹤框「實心亮色中心」的真正中心（harvest 101 spec §6）。

    與 find_tracker 的差別：find_tracker 對「尖刺太陽星框＋實心亮綠中心＋綠地形背景」這類
    框有結構盲點（整幀假陽性、放大全 MISS，spec v1/v2 已證）。本函式只掃玩家選定的單格
    區域（cell_crop）——限縮範圍避開全幀干擾，直接回框**真正中心**（非格心量化值）。

    對每個 profile 的 HSV 範圍取 mask→morphology open→輪廓→篩「方形＋實心＋周圍黑邊」→
    多命中取面積最大。回 (cx, cy, profile_name, border_frac)|None；座標**相對 region**。

    黑邊判定：框 bbox 外側 border_margin 寬的環帶裡，gray≤border_dark_max 的像素佔比
    ≥border_dark_frac_min 才收——擋「亮色中心但周圍無黑邊」的非框亮塊（空格背景）。
    profiles=[]（未覆蓋色系）→ None（永不誤射；靠退路放大手選兜底）。
    """
    if region_bgr is None or region_bgr.size == 0 or not profiles:
        return None
    H, W = region_bgr.shape[:2]
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    kernel = np.ones((3, 3), np.uint8)
    best = None   # (area, cx, cy, name, border_frac)
    for prof in profiles:
        name, lo, hi = prof[0], prof[1], prof[2]
        mask = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            if bw <= 0 or bh <= 0:
                continue
            ar = bw / bh
            if not (ar_lo <= ar <= ar_hi):
                continue
            extent = area / (bw * bh)
            if extent < extent_min:
                continue
            # 黑邊環帶：bbox 外側 border_margin 寬的環（擴張框 − 原框），clamp 在 region 內。
            rx0 = max(0, x - border_margin)
            ry0 = max(0, y - border_margin)
            rx1 = min(W, x + bw + border_margin)
            ry1 = min(H, y + bh + border_margin)
            ring = np.ones((ry1 - ry0, rx1 - rx0), dtype=bool)
            ring[max(0, border_margin):max(0, border_margin) + bh,
                 max(0, border_margin):max(0, border_margin) + bw] = False
            ring_pixels = gray[ry0:ry1, rx0:rx1][ring]
            border_frac = (float(np.mean(ring_pixels <= border_dark_max))
                           if ring_pixels.size > 0 else 0.0)
            if border_frac < border_dark_frac_min:
                if log is not None:
                    log("core候選 (%d,%d) name=%s area=%d ar=%.2f ext=%.2f border=%.2f -> rej(border)"
                        % (x + bw // 2, y + bh // 2, name, int(area), ar, extent, border_frac))
                continue
            cx, cy = x + bw // 2, y + bh // 2
            if log is not None:
                log("core候選 (%d,%d) name=%s area=%d ar=%.2f ext=%.2f border=%.2f -> OK"
                    % (cx, cy, name, int(area), ar, extent, border_frac))
            if best is None or area > best[0]:
                best = (area, cx, cy, name, border_frac)
    if best is None:
        return None
    _, cx, cy, name, border_frac = best
    return (cx, cy, name, border_frac)


# ===== boost 使用次數計數器（2026-07-19）=====
# 右下角 boost 藥水圖示上的紅色藝術字＝session 內使用次數（重進伺服器歸零）。
# boost FOV 縮小隨此次數累積（作用中變大/到期變小），這個數字是 FOV 漂移的
# 狀態變數。Tesseract 對此字體只有 8/10（166 讀空、211 掉尾數），但紅 mask
# 乾淨且字體固定尺寸（逐像素跨樣本差 ≤2.6%）→ 數字模板比對。
# 模板來源：07-17~07-19 歷史快照裁圖（41/39/32/43/80/42/83/124/166/211/17/15/50），
# 由裁圖 mask 自動轉字串，未手動修飾。類間最近鄰 6~8 mismatch 0.177。
_BOOST_COUNT_DIGITS = {
    "0": (
        "...####....",
        "..#######..",
        ".#########.",
        "####..####.",
        "####...####",
        "###....####",
        "###....####",
        "###....####",
        "###....####",
        "####...###.",
        "##########.",
        ".########..",
        "..######...",
    ),
    "1": (
        "######",
        "######",
        "######",
        "..####",
        "..####",
        "..####",
        "..####",
        "..####",
        "#.####",
        "#.####",
        "..####",
        "..####",
        "..####",
    ),
    "2": (
        "...#####..",
        ".########.",
        "##########",
        ".##...####",
        "......####",
        "......####",
        ".....####.",
        "....####..",
        "...####...",
        "..####....",
        ".#########",
        ".#########",
        ".#########",
    ),
    "3": (
        ".########.",
        ".#########",
        ".#########",
        ".....####.",
        "....####..",
        "...#####..",
        "...######.",
        "...#######",
        ".......###",
        ".......###",
        ".#########",
        "#########.",
        ".#######..",
    ),
    "4": (
        "......###...#",
        ".....####...#",
        ".....###....#",
        "....####.....",
        "...####......",
        "..####.......",
        "..####.####..",
        ".####..####..",
        "#############",
        "#############",
        ".###########.",
        ".......####..",
        ".......####..",
    ),
    "5": (
        "..########.",
        "..########.",
        ".#########.",
        ".####......",
        ".####......",
        ".#######...",
        ".#########.",
        ".#########.",
        ".......####",
        ".......####",
        ".#########.",
        "##########.",
        ".#######...",
    ),
    "6": (
        "....#####.",
        "..########",
        ".########.",
        "#####.....",
        "####......",
        "########..",
        "##########",
        "##########",
        "####...###",
        "####...###",
        "####..####",
        ".#########",
        "..######..",
    ),
    "7": (
        ".##########",
        "###########",
        "###########",
        "####..#####",
        "###...####.",
        "......####.",
        ".....####..",
        ".....####..",
        "....####...",
        "....####...",
        "....####...",
        "...####....",
        "...####....",
    ),
    "8": (
        "...#####...",
        ".########..",
        "##########.",
        "####..####.",
        "####..####.",
        ".#########.",
        ".########..",
        "##########.",
        "###....###.",
        "###....####",
        "####..####.",
        "##########.",
        "..######...",
    ),
    "9": (
        "...#####...",
        ".########..",
        ".#########.",
        "####...####",
        "####...####",
        "####...####",
        ".##########",
        "..#########",
        ".......####",
        ".......####",
        "..########.",
        ".########..",
        ".#######...",
    ),
}


def _boost_count_templates():
    return {d: np.array([[c == "#" for c in row] for row in rows], dtype=np.uint8)
            for d, rows in _BOOST_COUNT_DIGITS.items()}


_BOOST_COUNT_TEMPLATES = None          # lazy：import 時不建 numpy 陣列


def boost_count_red_mask(crop_bgr):
    """計數器紅字遮罩（飽和紅、hue 環繞兩端）；元件切割與模板比對共用。"""
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (0, 120, 120), (10, 255, 255)) | \
        cv2.inRange(hsv, (170, 120, 120), (180, 255, 255))


def read_boost_use_count(crop_bgr, max_mismatch: float = 0.08):
    """右下角計數器裁圖 → 使用次數 int；讀不出（含任一未知字元）回 None。

    紅 mask → 連通元件（數字尺寸閘：w 4..16 / h 10..16 / area 30..160，擋掉
    場景紅色滲入——07-19 ep3 快照左緣曾出現 area 916 的紅色場景塊）→ 由左至右
    逐字模板比對（mismatch＝像素不一致比例；兩側夾：類內 ≤0.026 vs 類間最近
    0.177）。任一字元 mismatch 全模板 > max_mismatch＝未知字元 → 整筆回 None
    （寧可不讀不誤讀；呼叫端可落原圖供模板增補）。
    """
    global _BOOST_COUNT_TEMPLATES
    if _BOOST_COUNT_TEMPLATES is None:
        _BOOST_COUNT_TEMPLATES = _boost_count_templates()
    mask = boost_count_red_mask(crop_bgr)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if 4 <= w <= 16 and 10 <= h <= 16 and 30 <= a <= 160:
            comps.append((int(x), int(y), int(w), int(h)))
    if not 1 <= len(comps) <= 4:
        return None
    comps.sort()
    digits = ""
    for x, y, w, h in comps:
        patch = (mask[y:y + h, x:x + w] > 127).astype(np.uint8)
        best = None
        for d, t in _BOOST_COUNT_TEMPLATES.items():
            p = patch
            if p.shape != t.shape:
                p = cv2.resize(p, (t.shape[1], t.shape[0]),
                               interpolation=cv2.INTER_NEAREST)
            frac = float(np.mean(p != t))
            if best is None or frac < best[1]:
                best = (d, frac)
        if best is None or best[1] > max_mismatch:
            return None
        digits += best[0]
    return int(digits)
