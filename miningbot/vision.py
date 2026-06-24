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

def find_template_edges(scene_bgr, template_bgr, threshold: float, scales=(1.0,)):
    """顏色無關 + 多尺度的模板定位：先用 Canny 取邊緣（只看形狀）再比對。

    適用於目標填色每次都不同、但外框/形狀固定的情況（例如掃描後的礦物標記）。
    `scales` 會把模板縮放成多種大小各試一次，取最佳——這樣即使模板（例如 wiki 圖）
    的尺寸跟畫面上不一致也能找到（模板比對本身不具縮放不變性）。
    回中心座標 (x, y)，找不到回 None。threshold 為邊緣相關度（0..1，越高越嚴）。
    """
    scene_gray = cv2.cvtColor(scene_bgr, cv2.COLOR_BGR2GRAY)
    scene_e = cv2.Canny(scene_gray, 50, 150)
    sh, sw = scene_e.shape[:2]
    best_loc = None
    best_val = -1.0
    for s in scales:
        if s == 1.0:
            t = template_bgr
        else:
            t = cv2.resize(template_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th > sh or tw > sw or th < 4 or tw < 4:
            continue                              # 模板比畫面大、或縮到太小 → 跳過
        tmpl_e = cv2.Canny(cv2.cvtColor(t, cv2.COLOR_BGR2GRAY), 50, 150)
        res = cv2.matchTemplate(scene_e, tmpl_e, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if np.isfinite(max_val) and max_val > best_val:
            best_val = max_val
            best_loc = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
    if best_loc is None or best_val < threshold:
        return None
    return best_loc

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
