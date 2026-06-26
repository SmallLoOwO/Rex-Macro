from miningbot.window import WindowState, displacement_reason, window_displaced

# 啟動時量到的「已知正確」全螢幕基準。實機可能因 DPI 縮放回報非 1920x1080，
# 故用基準相對比較（偵測「從正確狀態跑掉」），不寫死絕對解析度。
BASELINE = WindowState(found=True, foreground=True, x=0, y=0, w=1536, h=864)
POS_TOL = 2
SIZE_TOL = 4


def cur(**kw):
    base = dict(found=True, foreground=True, x=0, y=0, w=1536, h=864)
    base.update(kw)
    return WindowState(**base)


def reason(state):
    return displacement_reason(state, BASELINE, POS_TOL, SIZE_TOL)


def test_matches_baseline_is_ok():
    assert reason(cur()) is None


def test_missing_window_is_displaced():
    assert reason(cur(found=False)) == "window_missing"


def test_lost_focus_is_displaced():
    assert reason(cur(foreground=False)) == "not_foreground"


def test_moved_window_is_displaced():
    assert reason(cur(x=50)) == "moved"
    assert reason(cur(y=-30)) == "moved"


def test_resized_window_is_displaced():
    assert reason(cur(w=1280, h=720)) == "resized"


def test_small_offset_within_tolerance_is_ok():
    # 視窗邊框/捨入造成的 1px 偏差不該誤判
    assert reason(cur(x=1, y=-1, w=BASELINE.w - 3, h=BASELINE.h + 2)) is None


def test_missing_beats_foreground_check():
    # 視窗不存在時，前景旗標無意義 —— 應先回 window_missing
    assert reason(cur(found=False, foreground=False)) == "window_missing"


def test_baseline_on_secondary_monitor():
    # 基準原點非 (0,0)（如副螢幕）也要正確：相對基準沒動就 OK
    base = WindowState(found=True, foreground=True, x=1920, y=0, w=1536, h=864)
    same = WindowState(found=True, foreground=True, x=1920, y=0, w=1536, h=864)
    moved = WindowState(found=True, foreground=True, x=1980, y=0, w=1536, h=864)
    assert displacement_reason(same, base, POS_TOL, SIZE_TOL) is None
    assert displacement_reason(moved, base, POS_TOL, SIZE_TOL) == "moved"


def test_window_displaced_bool_wrapper():
    assert window_displaced(cur(foreground=False), BASELINE, POS_TOL, SIZE_TOL) is True
    assert window_displaced(cur(), BASELINE, POS_TOL, SIZE_TOL) is False
