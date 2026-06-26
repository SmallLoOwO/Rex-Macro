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


def _draw_tracker(scene, cx, cy, size=30, color=(0, 255, 0)):
    """畫一個稀有礦追蹤框：指定顏色外框 + 黑色方環 + 彩色中心。"""
    h = size // 2
    cv2.rectangle(scene, (cx-h, cy-h), (cx+h, cy+h), color, -1)               # 指定顏色外框
    cv2.rectangle(scene, (cx-h+6, cy-h+6), (cx+h-6, cy+h-6), (0, 0, 0), -1)   # 黑方環
    cv2.rectangle(scene, (cx-4, cy-4), (cx+4, cy+4), (255, 0, 255), -1)       # 彩色中心（隨礦物變）


def test_find_tracker_detects_green_black_marker():
    # Exquisite 階級（亮綠外框）
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    loc = find_tracker(scene)
    assert loc is not None
    assert abs(loc[0] - 955) < 10 and abs(loc[1] - 300) < 10


def test_find_tracker_exotic_orange():
    # Exotic 階級（橘色外框 H22）也要偵測到
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300, color=(0, 187, 255))  # BGR for HSV(22,255,255)
    loc = find_tracker(scene)
    assert loc is not None, "Exotic 橘色追蹤框未偵測到"
    assert abs(loc[0] - 955) < 10


def test_find_tracker_transcendent_blue():
    # Transcendent 階級（亮藍外框 H105）也要偵測到
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300, color=(255, 127, 0))  # BGR for HSV(105,255,255)
    loc = find_tracker(scene)
    assert loc is not None, "Transcendent 藍色追蹤框未偵測到"
    assert abs(loc[0] - 955) < 10


def test_find_tracker_ignores_plain_green_blob():
    # 純綠色實心 blob（非空心框）不應被偵測
    scene = np.zeros((1080, 1920, 3), np.uint8)
    cv2.rectangle(scene, (900, 280), (930, 310), (0, 255, 0), -1)
    assert find_tracker(scene) is None


def test_find_tracker_ignores_plain_orange_blob():
    # 純橘色實心 blob 也不應被偵測（空心率過高）
    scene = np.zeros((1080, 1920, 3), np.uint8)
    cv2.rectangle(scene, (900, 280), (930, 310), (0, 187, 255), -1)
    assert find_tracker(scene) is None


def test_find_tracker_inner_color_independent():
    # 中心顏色不同（不同礦物）仍要偵測到 —— 認外框+黑環，不認中心色
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    cv2.rectangle(scene, (951, 296), (959, 304), (0, 200, 255), -1)  # 換成橘色中心
    assert find_tracker(scene) is not None


def test_find_tracker_ignores_dark_panel_without_colored_center():
    # UI 面板誤判候選：彩色外框 + 暗色內部（高 dark）但「沒有彩色中心」(colored≈0)
    # → accept 必須排除。模擬 logs/rot_3.png 中 (257,933) 的左側 UI 面板誤判。
    scene = np.zeros((1080, 1920, 3), np.uint8)
    cx, cy = 257, 933
    cv2.rectangle(scene, (cx-25, cy-25), (cx+25, cy+25), (0, 255, 0), 3)  # 綠色細外框
    cv2.rectangle(scene, (cx-22, cy-22), (cx+22, cy+22), (25, 25, 25), -1)  # 暗色內部、無彩色中心
    assert find_tracker(scene) is None


def test_find_tracker_prefers_higher_colored_over_larger_area():
    # 兩個都通過 accept 的候選：colored_frac 較高者勝，即使 area 較小。
    # 對應 HANDOFF「修 2」：真 tracker colored≈1.00 要贏過裝備誤判 colored≈0.75-0.88。
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300, size=30)    # colored_frac 較高、area 較小
    _draw_tracker(scene, 1200, 300, size=40)   # colored_frac 較低、area 較大
    loc = find_tracker(scene)
    assert loc is not None
    # 新排名（colored_frac 高者勝）應選 955；舊排名（area 大者勝）會選 1200
    assert abs(loc[0] - 955) < 15


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
