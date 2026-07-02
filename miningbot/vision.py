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
                 shape_roi_px: int = 160, with_score: bool = False):
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
            # 差分過濾：掃描前就已存在的彩色物件（礦石本體/角色裝備）→ 排除
            if ref_mask is not None:
                ref_fill = float(np.mean(ref_mask[y:y+bh, x:x+bw] > 0))
                if ref_fill > 0.15:
                    if log is not None:
                        log("tracker候選 (%d,%d) area=%d fill=%.2f ref_fill=%.2f -> rej(preexist)"
                            % (cx, cy, int(area), frame_fill, ref_fill))
                    continue
            # 專注外框：量「整個 bbox」的彩色佔比（色相無關 S>90&V>90），不再只看中心。
            # 為何不看中心：追蹤框中心顏色每次會變（不同礦色/粉紅/甚至純黑空心 BGR[0,0,0]），
            # 中心非不變特徵；舊版要求中心 2/3 有彩色像素，遇黑心框 colored=0 → 被當暗色 UI
            # 面板拒掉而漏抓（2026-06-29 黑心綠框 black_center_scene.png 踩坑根因）。
            # 真追蹤框有「厚實彩色外框」→ 整框彩色佔比高（實測黑心 0.51-0.62、彩心 0.7-1.0）；
            # 細框暗色 UI 面板佔比低（合成 0.33、實機 ≈0.16）→ 用佔比門檻區隔，形狀確認再精篩。
            bb_hsv = hsv[y:y+bh, x:x+bw]
            colored = (bb_hsv[:, :, 1] > 90) & (bb_hsv[:, :, 2] > 90)
            colored_frac = float(colored.mean())
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
