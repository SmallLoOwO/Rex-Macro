"""傳送板偵測器 v0：吃一張回礦方位全幀，回 ``(x, y, score)`` 或 `None`。

回礦介入時玩家要在八方位圖裡找 Teleportation Board 點下去。這支的工作是**猜**
它在哪——只做建議，永遠不自動點（H043 虛空墜落是全自動那條路的代價）。

## 配方怎麼量出來的（2026-07-28，語料 corpus/reentry 18 張）

板子的視覺特徵：**紫羅蘭色外框**（頂橫樑 + 兩側柱）圍著一塊深藍黑面板，面板上是
一格格青色小按鈕與亮字。夜間場景裡其餘物件是去飽和的綠灰地形與雪地，所以「中亮度
中飽和的紫」本身就相當獨特——但**不是唯一**：夜空、左側礦物面板、右側圖示欄、
底部工具列在同一個色相帶裡，只是**更暗或更飽和**。實測（`cv2` 取百分位）：

| 區域 | H 中位 | S 中位 | V 中位 |
|---|---|---|---|
| 板子外框 | 133 | 108-113 | 115-127 |
| 夜空 | 129 | 157 | 48 |
| 左側礦物面板 | 129 | 121 | 44 |
| 右側圖示欄 | 128 | 125 | 47 |

分得開的是 **V**（板子亮、背景暗）與 **S 上界**（夜空/UI 更飽和）。

色遮罩之後再過四道幾何閘（板子 vs 通過色閘的雜訊，同樣是實測值）：
長寬比 ~2.05-2.21、bbox 內遮罩占比 ~0.31-0.33、內部暗像素占比 ~0.56-0.62、
內部極亮像素占比 ~0.05（發光 UI 元件會到 0.36-0.50）。

## v0 的限制（不要在別處宣稱它更強）

語料是**單一世界（Lucernia）、單一層（Shamrock）、全夜晚**，只有 4 個實際板子
實例。v0 只求在這個分布上可用，不求泛化；換世界／白天場景必須重新量。
`build_reentry_dataset --eval` 是唯一的量尺，兩側夾（命中率與誤報數一起看）。

⚠ 資料集的 `negative` 是「玩家沒選這個方位」，**不等於「這張圖裡沒有板子」**：
板子夠寬，相鄰方位（±45°）常常也照得到。實測 ep20/dir7 與 ep23/dir1 都被標成
negative，肉眼確認**都是真的板子**。所以 `--eval` 的 false-positive 數字是上界，
不是實際誤報。
"""

from __future__ import annotations

from .config import DEFAULT as cfg


def _clamp_roi(roi, width: int, height: int):
    x, y, w, h = roi
    x = max(0, min(int(x), width))
    y = max(0, min(int(y), height))
    return x, y, max(0, min(int(w), width - x)), max(0, min(int(h), height - y))


def candidate_score(aspect: float, fill: float, dark_frac: float) -> float:
    """三個實測特徵 → [0, 1] 分數（純函式）。

    每一項是「離實測中心多遠」的線性衰減，取幾何平均——任何一項明顯偏離就整體
    塌下來，不會被另外兩項救回（算術平均會）。中心值來自語料裡 4 個板子實例，
    寬度取到足以容納最弱的那個（被左側面板遮住一角的 ep23/dir1，aspect 1.68）。
    """
    ar_score = max(0.0, 1.0 - abs(aspect - cfg.teleport_board_aspect_center)
                   / cfg.teleport_board_aspect_tolerance)
    fill_score = max(0.0, 1.0 - abs(fill - cfg.teleport_board_fill_center)
                     / cfg.teleport_board_fill_tolerance)
    dark_score = min(1.0, dark_frac / max(1e-6, cfg.teleport_board_dark_ref))
    return float((ar_score * fill_score * dark_score) ** (1.0 / 3.0))


def detect(frame):
    """回 ``(x, y, score)``＝畫面上最像傳送板的位置與分數；找不到回 `None`。

    座標是**板子外框的中心**（native 全幀座標）。玩家實際點的位置多半在中心偏下
    的按鈕區，實測偏差 36-37px，遠在 `reentry_dataset_hit_radius_px`(80) 之內。

    ROI 只用來排掉**螢幕空間 UI** 的邊緣（左側礦物面板、右側圖示欄、頂端橫幅、
    底部工具列），不是對板子位置的假設——玩家可以用 `上|下` 調俯仰，寫死 y 帶會
    在調完之後整個瞎掉。
    """
    import cv2
    import numpy as np

    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    height, width = frame.shape[:2]
    rx, ry, rw, rh = _clamp_roi(cfg.teleport_board_roi, width, height)
    if rw <= 0 or rh <= 0:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    h_lo, h_hi = cfg.teleport_board_hue_range
    s_lo, s_hi = cfg.teleport_board_sat_range
    v_lo, v_hi = cfg.teleport_board_val_range
    mask = ((h >= h_lo) & (h <= h_hi) & (s >= s_lo) & (s <= s_hi)
            & (v >= v_lo) & (v <= v_hi)).astype(np.uint8)
    roi_only = np.zeros_like(mask)
    roi_only[ry:ry + rh, rx:rx + rw] = 1
    k = int(cfg.teleport_board_close_px)
    mask = cv2.morphologyEx((mask * roi_only) * 255, cv2.MORPH_CLOSE,
                            np.ones((k, k), np.uint8))

    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    ar_lo, ar_hi = cfg.teleport_board_aspect_range
    fill_lo, fill_hi = cfg.teleport_board_fill_range
    best = None
    for i in range(1, count):
        x, y, w, hh, area = stats[i]
        if area < cfg.teleport_board_min_area or w < 40 or hh < 20:
            continue
        aspect = w / float(hh)
        if not (ar_lo <= aspect <= ar_hi):
            continue
        fill = area / float(w * hh)
        if not (fill_lo <= fill <= fill_hi):
            continue
        inner_v = hsv[y:y + hh, x:x + w, 2]
        dark = float((inner_v < cfg.teleport_board_dark_v).mean())
        bright = float((inner_v > cfg.teleport_board_bright_v).mean())
        if dark < cfg.teleport_board_min_dark_frac:
            continue
        if bright > cfg.teleport_board_max_bright_frac:
            continue
        score = candidate_score(aspect, fill, dark)
        if best is None or score > best[2]:
            best = (int(round(centroids[i][0])), int(round(centroids[i][1])), score)
    return best
