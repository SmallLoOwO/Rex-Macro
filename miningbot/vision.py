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
