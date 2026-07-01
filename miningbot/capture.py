"""
capture.py — 截圖與視窗定位
擷取螢幕並裁切 Region，回傳 BGR ndarray 供 cv2 使用。
"""

import threading
import numpy as np

# 每執行緒快取一個 mss 實例：原本每次 grab() 都 `with mss.mss()` 重建整個截圖 context
# （Windows 上每次重建 GDI device context + bitmap，是 mss 官方明文警告的反模式）。
# 主迴圈每 ~50ms grab 一次、sweep 一輪 grab ~17 次，重用實例省下大量重建成本。
# 用 threading.local（非單一全域）是因 mss 實例**非執行緒安全**，而 grab() 會從主迴圈
# 與熱鍵執行緒（_resume→init_mining_sequence→_ensure_pickaxe）兩處呼叫——共享單一
# 實例會壞。各執行緒各自持有、各自重用。
_local = threading.local()


def _cached(local, attr, factory):
    """每執行緒快取：首次存取時用 factory 建好存進 local，之後重用（純函式，可測）。"""
    obj = getattr(local, attr, None)
    if obj is None:
        obj = factory()
        setattr(local, attr, obj)
    return obj


def _new_sct():
    """建一個 mss 實例。mss 採惰性 import：讓 `import capture` 不拉進 mss（無螢幕 CI /
    純邏輯測試不受影響）；DPI-aware 已由 main._set_dpi_aware 在任何 grab 前先設好。"""
    import mss
    return mss.mss()


def grab(region=None) -> np.ndarray:
    """擷取整個主螢幕或指定區域 dict(top,left,width,height)，回傳 BGR uint8 ndarray。

    mss 的 np.array(shot) 回傳 BGRA 四通道。
    cv2 期待 BGR 三通道，因此只需丟棄 alpha，不需反轉通道順序。
    每執行緒重用同一個 mss 實例（見 _local / _cached），不再每幀重建。
    """
    sct = _cached(_local, "sct", _new_sct)
    mon = region or sct.monitors[1]
    shot = sct.grab(mon)
    # np.frombuffer(raw) 是零拷貝 view，比 np.array(shot)（會把 ScreenShot 當序列逐列
    # Python 迭代）直接。shot.raw 為 BGRA bytes，reshape 後丟 alpha → BGR，
    # ascontiguousarray 確保 C-contiguous 給 cv2。輸出與舊 np.array 路徑 byte-identical。
    arr = np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)
    # cv2.cvtColor(BGRA2BGR) 丟 alpha 得 C-contiguous BGR，與舊 ascontiguousarray(arr[:,:,:3])
    # **byte-identical**，但快 ~8x（實測 154ms→19ms/幀）：後者對 stride-4 的 view 逐元素複製慢，
    # 前者走 SIMD。grab 每幀都跑（主迴圈 ~20/s + sweep 一輪 17 次），這 ~135ms/幀省很大。
    import cv2
    bgr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
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
