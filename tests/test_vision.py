import numpy as np
from miningbot.vision import find_template, template_present

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
