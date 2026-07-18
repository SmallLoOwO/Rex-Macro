"""D5 boost 偵測三態回歸測試（2026-07-08 遊戲更新新增永久計數圖示）。

背景：右下角原本只有「boost 生效中的瓶子圖示」，遊戲更新後新增一顆常駐的
「使用次數計數」圖示，長得跟 boost 瓶子一樣，只是位置固定在 boost 瓶子右側、
不會消失。舊 boost_indicator_region 涵蓋到它 → 判定邏輯（瓶子消失=該補 D5）
永遠看到一顆「瓶子」→ 永遠判生效中、永遠不補 D5。

對策：boost_indicator_region 右緣縮到永久計數圖示左緣（Task 1 已改）；模板取自
已追蹤的 active_47 fixture 內倒數圖示，原始全幀 bbox 經像素差分鎖定為
(1676,1010)-(1734,1068)，換算到 fixture 是 (526,75)-(584,133)，58x58。

fixtures 是三個真實遊戲畫面狀態，直接裁 cfg.boost_indicator_region 那塊區域
（即 find_template_edges 在正式程式碼裡實際會收到的輸入）：
- before_only_count：只有永久計數圖示（該圖示已被新 region 排除在外）→ 預期偵測不到瓶子 → 該補 D5
- active_47 / active_61：計數圖示之外還有倒數圖示（47s/61s，兩種數字驗證邊緣比對不受數字影響）
  → 預期偵測到瓶子 → 生效中，不該補

「無圖示」（新伺服器、從未用過 D5）today 沒截到樣本，見 docs 最後校準清單。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import vision  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "boost")
BOOST_TEMPLATE_RECT = (526, 75, 58, 58)


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def _template():
    scene = _load("active_47.png")
    x, y, w, h = BOOST_TEMPLATE_RECT
    return scene[y:y + h, x:x + w].copy()


def test_only_permanent_counter_icon_is_not_detected_as_boost():
    # 只有永久計數圖示（無倒數）→ 該補 D5：偵測必須是 None
    scene = _load("before_only_count.png")
    result = vision.find_template_edges(scene, _template(), cfg.boost_edge_threshold,
                                        cfg.boost_buff_scales)
    assert result is None


def test_active_47_countdown_detected():
    scene = _load("active_47.png")
    result = vision.find_template_edges(scene, _template(), cfg.boost_edge_threshold,
                                        cfg.boost_buff_scales)
    assert result is not None


def test_active_61_countdown_detected():
    # 另一個數字變體（61 而非 47）：邊緣比對忽略數字，必須同樣偵測到
    scene = _load("active_61.png")
    result = vision.find_template_edges(scene, _template(), cfg.boost_edge_threshold,
                                        cfg.boost_buff_scales)
    assert result is not None
