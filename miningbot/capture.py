"""
capture.py — 截圖與視窗定位
擷取螢幕並裁切 Region，回傳 BGR ndarray 供 cv2 使用。
"""

import mss
import numpy as np


def grab(region=None) -> np.ndarray:
    """擷取整個主螢幕或指定區域 dict(top,left,width,height)，回傳 BGR uint8 ndarray。

    mss 的 np.array(shot) 回傳 BGRA 四通道。
    cv2 期待 BGR 三通道，因此只需丟棄 alpha，不需反轉通道順序。
    """
    with mss.mss() as sct:
        mon = region or sct.monitors[1]
        shot = sct.grab(mon)
        arr = np.array(shot)          # shape (H, W, 4), dtype uint8, channels BGRA
        bgr = np.ascontiguousarray(arr[:, :, :3])  # drop alpha → BGR, ensure C-contiguous
        return bgr


def crop(image_bgr: np.ndarray, region) -> np.ndarray:
    """從 BGR 圖像裁切 Region 區域。

    Args:
        image_bgr: grab() 回傳的 BGR ndarray。
        region:    miningbot.config.Region（含 .x .y .w .h）。

    Returns:
        裁切後的 BGR ndarray（view，非 copy）。
    """
    return image_bgr[region.y:region.y + region.h, region.x:region.x + region.w]
