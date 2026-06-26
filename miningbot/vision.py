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


# 稀有礦追蹤框的綠色 HSV 範圍（外框恆為亮綠，與紅色礦坑背景對比明顯）
_TRACKER_GREEN_LO = (38, 70, 70)
_TRACKER_GREEN_HI = (90, 255, 255)

def find_tracker(frame_bgr, margin_frac: float = 0.10, log=None):
    """偵測 D2 掃描後的稀有礦「追蹤框」，回傳框中心 (x, y)；找不到回 None。

    為何不用邊緣模板：wiki 模板只有外框、且追蹤框**中心顏色隨礦物變**，記不完所有顏色。
    追蹤框的恆定特徵是「**亮綠外框 + 內部黑色方環 + 彩色中心**」——用顏色+結構抓，對中心色不敏感、
    又能排除場景其他綠色物件（無黑環）與綠色數字/面板。
    `log`：傳一個 callable（如 logger.debug），會印出每個綠色候選的判定指標，方便調參。
    """
    h, w = frame_bgr.shape[:2]
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, _TRACKER_GREEN_LO, _TRACKER_GREEN_HI)
    cnts, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mx0, my0 = w * margin_frac, h * margin_frac
    mx1, my1 = w * (1 - margin_frac), h * (1 - margin_frac)
    best = None
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 100 or area > 5000:                 # 太小=雜訊、太大=面板/大片綠
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        if not (12 <= bw <= 80 and 12 <= bh <= 80):
            continue
        if abs(bw - bh) > max(bw, bh) * 0.5:          # 大致方形
            continue
        cx, cy = x + bw // 2, y + bh // 2
        in_area = (mx0 < cx < mx1 and my0 < cy < my1)  # 排除邊緣面板/HUD
        roi = frame_bgr[max(0, cy - bh // 3):cy + bh // 3,
                        max(0, cx - bw // 3):cx + bw // 3]
        if roi.size == 0:
            continue
        dark = float(np.mean(np.all(roi < 60, axis=2)))   # 中心黑色方環比例
        # 中心要有「亮且飽和的非綠色」= 礦物色填心。排除綠色數字（如 $金額的 0/9，
        # 也是綠框+黑洞，但中心只有黑、無彩色填心）。
        roi_hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        H, S, V = roi_hsv[:, :, 0], roi_hsv[:, :, 1], roi_hsv[:, :, 2]
        colored = (S > 90) & (V > 90) & ((H < 35) | (H > 95))
        colored_frac = float(colored.mean())
        accept = in_area and dark > 0.10 and colored_frac > 0.04
        if log is not None:
            log("tracker候選 (%d,%d) area=%d dark=%.2f colored=%.2f in_area=%s -> %s"
                % (cx, cy, int(area), dark, colored_frac, in_area, "OK" if accept else "rej"))
        if accept and (best is None or area > best[0]):
            best = (area, (cx, cy))
    return best[1] if best else None
