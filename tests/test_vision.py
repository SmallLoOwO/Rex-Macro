import cv2
import numpy as np
from miningbot.vision import find_template, template_present, find_template_edges

def _scene_with_patch(patch, at):
    scene = np.zeros((300, 400, 3), np.uint8)
    y, x = at
    ph, pw = patch.shape[:2]
    scene[y:y+ph, x:x+pw] = patch
    return scene

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
