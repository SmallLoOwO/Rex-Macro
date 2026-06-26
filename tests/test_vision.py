import cv2
import numpy as np
from miningbot.vision import (find_template, template_present, find_template_edges,
                              find_tracker)

def _scene_with_patch(patch, at):
    scene = np.zeros((300, 400, 3), np.uint8)
    y, x = at
    ph, pw = patch.shape[:2]
    scene[y:y+ph, x:x+pw] = patch
    return scene


def _draw_tracker(scene, cx, cy, size=30):
    """畫一個稀有礦追蹤框：綠外框 + 黑色方環 + 彩色中心。"""
    h = size // 2
    cv2.rectangle(scene, (cx-h, cy-h), (cx+h, cy+h), (0, 255, 0), -1)         # 綠外框
    cv2.rectangle(scene, (cx-h+6, cy-h+6), (cx+h-6, cy+h-6), (0, 0, 0), -1)   # 黑方環
    cv2.rectangle(scene, (cx-4, cy-4), (cx+4, cy+4), (255, 0, 255), -1)       # 彩色中心（隨礦物變）


def test_find_tracker_detects_green_black_marker():
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    loc = find_tracker(scene)
    assert loc is not None
    assert abs(loc[0] - 955) < 10 and abs(loc[1] - 300) < 10


def test_find_tracker_ignores_plain_green_blob():
    # 場景中其他綠色物件（沒有黑色方環）不該被當成追蹤框
    scene = np.zeros((1080, 1920, 3), np.uint8)
    cv2.rectangle(scene, (900, 280), (930, 310), (0, 255, 0), -1)
    assert find_tracker(scene) is None


def test_find_tracker_inner_color_independent():
    # 中心顏色不同（不同礦物）仍要偵測到 —— 認綠框+黑環，不認中心色
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    cv2.rectangle(scene, (951, 296), (959, 304), (0, 200, 255), -1)  # 換成橘色中心
    assert find_tracker(scene) is not None


def test_find_tracker_none_when_empty():
    assert find_tracker(np.zeros((1080, 1920, 3), np.uint8)) is None

def test_find_template_returns_center():
    patch = np.full((20, 20, 3), 200, np.uint8)
    scene = _scene_with_patch(patch, at=(100, 150))
    loc = find_template(scene, patch, threshold=0.9)
    assert loc == (160, 110)  # center x=150+10, y=100+10

def test_find_template_missing_returns_none():
    patch = np.full((20, 20, 3), 200, np.uint8)
    scene = np.zeros((300, 400, 3), np.uint8)
    assert find_template(scene, patch, threshold=0.9) is None

def test_template_present_bool():
    patch = np.full((20, 20, 3), 123, np.uint8)
    scene = _scene_with_patch(patch, at=(50, 50))
    assert template_present(scene, patch, threshold=0.9) is True

def test_pixel_matches_within_tolerance():
    from miningbot.vision import pixel_matches
    scene = np.zeros((100, 100, 3), np.uint8)
    scene[50, 40] = (43, 43, 43)  # BGR
    assert pixel_matches(scene, (40, 50), 0x2B2B2B, tol=5) is True
    assert pixel_matches(scene, (40, 50), 0x000000, tol=5) is False

def test_frame_mean_diff_zero_for_identical():
    from miningbot.vision import frame_mean_diff
    a = np.full((10, 10, 3), 100, np.uint8)
    assert frame_mean_diff(a, a.copy()) == 0.0
    b = np.full((10, 10, 3), 110, np.uint8)
    assert frame_mean_diff(a, b) == 10.0

def _framed_box(fill_color):
    """灰底上畫一個 24x24 的方框（外框形狀固定，填色可變）。"""
    img = np.full((40, 40, 3), 30, np.uint8)
    cv2.rectangle(img, (8, 8), (31, 31), fill_color, 2)
    return img

def test_find_template_edges_is_color_invariant():
    # 模板是灰框；場景裡放一個「同形狀但不同顏色」的紅框 → 邊緣比對仍要找到
    template = _framed_box((200, 200, 200))
    scene = np.full((200, 200, 3), 30, np.uint8)
    scene[60:100, 90:130] = _framed_box((0, 0, 255))  # 紅框，形狀相同
    loc = find_template_edges(scene, template, threshold=0.4)
    assert loc is not None
    assert abs(loc[0] - 110) <= 4 and abs(loc[1] - 80) <= 4  # 中心約 (90+20, 60+20)

def test_find_template_edges_missing_returns_none():
    template = _framed_box((200, 200, 200))
    scene = np.full((200, 200, 3), 30, np.uint8)  # 一片均勻、沒有任何形狀
    assert find_template_edges(scene, template, threshold=0.4) is None

def test_find_template_edges_matches_when_scaled():
    # 模板 40x40，場景裡是放大 1.5 倍的同形狀（顏色也不同）→ 提供對應 scale 要找得到
    template = _framed_box((200, 200, 200))
    big = cv2.resize(_framed_box((0, 0, 255)), None, fx=1.5, fy=1.5,
                     interpolation=cv2.INTER_AREA)
    scene = np.full((220, 220, 3), 30, np.uint8)
    h, w = big.shape[:2]
    scene[40:40 + h, 50:50 + w] = big
    loc = find_template_edges(scene, template, threshold=0.4, scales=(1.5,))
    assert loc is not None
    assert abs(loc[0] - (50 + w // 2)) <= 5 and abs(loc[1] - (40 + h // 2)) <= 5

def _ring(color):
    img = np.full((40, 40, 3), 30, np.uint8)
    cv2.circle(img, (20, 20), 12, color, 2)
    return img

def test_find_best_marker_picks_matching_shape_and_reports_name():
    from miningbot.vision import find_best_marker
    # 兩個不同形狀模板：方框 vs 圓環。場景裡放的是圓環（顏色不同）→ 要選到 "circle"
    templates = {"box": _framed_box((200, 200, 200)), "circle": _ring((200, 200, 200))}
    scene = np.full((200, 200, 3), 30, np.uint8)
    scene[60:100, 90:130] = _ring((0, 0, 255))
    result = find_best_marker(scene, templates, threshold=0.3)
    assert result is not None
    name, loc = result
    assert name == "circle"
    assert abs(loc[0] - 110) <= 5 and abs(loc[1] - 80) <= 5

def test_find_best_marker_none_when_no_shape():
    from miningbot.vision import find_best_marker
    templates = {"box": _framed_box((200, 200, 200)), "circle": _ring((200, 200, 200))}
    scene = np.full((200, 200, 3), 30, np.uint8)  # 沒有任何形狀
    assert find_best_marker(scene, templates, threshold=0.3) is None
