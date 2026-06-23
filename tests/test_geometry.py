from miningbot.geometry import aim_decision

# 畫面中心 (960, 540)，容差 25，垂直極端比例 0.35（=> |dy|>540*0.35=189 視為極端）
CENTER = (960, 540)

def test_marker_centered_means_fire():
    d = aim_decision((965, 545), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "FIRE"

def test_marker_left_means_rotate_left():
    d = aim_decision((300, 540), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "ROTATE_LEFT"

def test_marker_right_means_rotate_right():
    d = aim_decision((1600, 540), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "ROTATE_RIGHT"

def test_marker_near_horizontal_uses_mouse_fine_aim():
    # 水平偏差小（在一次轉視角的視野內），垂直在範圍內 → 用滑鼠微調
    d = aim_decision((1000, 560), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "MOUSE_AIM"
    assert d.dx == 40 and d.dy == 20

def test_vertical_extreme_means_human():
    d = aim_decision((960, 760), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "HUMAN"  # dy=220 > 189
