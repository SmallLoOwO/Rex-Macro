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

def find_tracker(frame_bgr, margin_frac: float = 0.10, log=None):
    """偵測 D2 掃描後的稀有礦「追蹤框」，回傳框中心 (x, y)；找不到回 None。

    各階級外框顏色不同（Exquisite 綠、Exotic 橘、Enigmatic 萊姆、Exclusive 暗紫、
    Otherworldly 暗紅、Transcendent 亮藍、Unfathomable 暗藍）——每個顏色範圍獨立偵測：
    空心率用「當前這個顏色的 mask」計算，避免其他顏色（如紅色礦坑背景 H≈168）干擾。
    `log`：傳 callable 可印出每個候選的判定指標，方便調參。
    """
    h, w = frame_bgr.shape[:2]
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mx0, my0 = w * margin_frac, h * margin_frac
    mx1, my1 = w * (1 - margin_frac), h * (1 - margin_frac)
    best = None
    for lo, hi in _TRACKER_COLORS:
        color_mask = cv2.inRange(hsv, lo, hi)
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
            # 空心率：只算「當前這個顏色的 mask」——避免礦坑背景同色系的 H 范圍干擾
            frame_fill = float(np.mean(color_mask[y:y+bh, x:x+bw] > 0))
            roi = frame_bgr[max(0, cy - bh // 3):cy + bh // 3,
                            max(0, cx - bw // 3):cx + bw // 3]
            if roi.size == 0:
                continue
            dark = float(np.mean(np.all(roi < 60, axis=2)))
            roi_hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            H, S, V = roi_hsv[:, :, 0], roi_hsv[:, :, 1], roi_hsv[:, :, 2]
            colored = (S > 90) & (V > 90) & ((H < 35) | (H > 95))
            colored_frac = float(colored.mean())
            # accept 條件：彩色中心要夠明顯（colored_frac>0.50，真實 tracker≈1.00），
            # 或同時有黑環+部分彩色（合成 tracker dark≈0.65 colored≈0.16）。
            # 排除「暗色 UI 面板」：dark 高但 colored≈0（左側面板誤判）。
            accept = (in_area and frame_fill < 0.85
                      and ((dark > 0.10 and colored_frac > 0.04) or colored_frac > 0.50))
            if log is not None:
                log("tracker候選 (%d,%d) area=%d fill=%.2f dark=%.2f colored=%.2f in_area=%s -> %s"
                    % (cx, cy, int(area), frame_fill, dark, colored_frac, in_area, "OK" if accept else "rej"))
            # 排名用 colored_frac（最高優先）：真 tracker≈1.00 > 角色裝備誤判≈0.75-0.88
            if accept and (best is None or colored_frac > best[0]):
                best = (colored_frac, (cx, cy))
    return best[1] if best else None
