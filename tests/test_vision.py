import os
import cv2
import numpy as np
from miningbot.vision import (find_template, template_present, find_template_edges,
                              find_tracker, find_marker, best_outline_score,
                              template_outline_edges)

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


# --- exclude 區域測試 (Problem A) ---

def test_find_tracker_exclude_rejects_tracker_inside_chat_region():
    # 模擬 HANDOFF §3 問題 A：(434,385) 落在聊天框內，加 exclude 後應回 None
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 434, 385)  # 在聊天框邊緣位置
    chat_rect = (0, 110, 460, 390)  # cfg.chat_region (x,y,w,h)=(0,110,460,280) → (x0,y0,x1,y1)
    loc = find_tracker(scene, exclude=[chat_rect])
    assert loc is None, f"聊天框內的假陽性應被 exclude 排除，但回傳了 {loc}"


def test_find_tracker_exclude_still_detects_tracker_outside_zone():
    # exclude 排掉聊天框，但真礦在 (955, 300) 應仍偵測到
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    chat_rect = (0, 110, 460, 390)
    loc = find_tracker(scene, exclude=[chat_rect])
    assert loc is not None, "exclude 不應排掉聊天框外的真 tracker"
    assert abs(loc[0] - 955) < 10 and abs(loc[1] - 300) < 10


def test_find_tracker_empty_exclude_behaves_same_as_default():
    # exclude=() 或不傳 exclude，行為相同
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    loc_default = find_tracker(scene)
    loc_empty = find_tracker(scene, exclude=())
    assert loc_default == loc_empty


# --- reference_bgr 差分過濾測試 (pre-scan vs post-scan) ---

def test_find_tracker_rejects_solid_purple_blob_cave_wall():
    """紫色實心 blob（fill≈0.75，中心也是紫色）模擬 cave wall 誤判 → 應排除。
    ring_score = frame_fill - inner_fill：實心圓 inner_fill≈1.0 → ring_score<0 → 拒。
    """
    scene = np.zeros((1080, 1920, 3), np.uint8)
    cx, cy = 955, 300
    # BGR=(180,50,130) → HSV≈(139,184,180)，落在 Exclusive tracker HSV range(H118-165)
    purple_bgr = (180, 50, 130)
    cv2.circle(scene, (cx, cy), 21, purple_bgr, -1)   # 實心圓 fill≈0.75，中心也是紫
    assert find_tracker(scene) is None, "cave wall 紫色實心 blob 應被環形結構過濾排除"


def test_find_tracker_reference_rejects_preexisting_colored_object():
    """D2 掃描前就存在的彩色礦石（同顏色 range），掃描後仍在同位置 → 應被過濾。"""
    scene = np.zeros((1080, 1920, 3), np.uint8)
    ref   = np.zeros((1080, 1920, 3), np.uint8)
    # 在 reference（掃描前）同樣位置畫一個實心綠色塊（模擬礦石本體）
    cv2.rectangle(ref, (940, 285), (970, 315), (0, 255, 0), -1)  # 綠色實心（tracker 顏色範圍）
    # scene（掃描後）同位置有追蹤框
    _draw_tracker(scene, 955, 300)
    loc = find_tracker(scene, reference_bgr=ref)
    assert loc is None, f"掃描前已存在的彩色物件應被 reference 過濾，但回傳 {loc}"


def test_find_tracker_reference_accepts_new_tracker_not_in_ref():
    """reference（掃描前）為空，掃描後才新出現的追蹤框應正常偵測。"""
    scene = np.zeros((1080, 1920, 3), np.uint8)
    ref   = np.zeros((1080, 1920, 3), np.uint8)   # 掃描前畫面全黑（無任何彩色物件）
    _draw_tracker(scene, 955, 300)
    loc = find_tracker(scene, reference_bgr=ref)
    assert loc is not None, "掃描前不存在、掃描後才出現的追蹤框應被偵測到"
    assert abs(loc[0] - 955) < 10 and abs(loc[1] - 300) < 10


# --- 色相無關確認（回歸：黃綠中心礦不該漏抓）---

def test_find_tracker_detects_yellowgreen_center_marker():
    """回歸 very_rare.png 根因：藍框 + 黃綠中心（H≈60，落在舊版 colored 排除的 H35-95 帶）。

    舊版 `colored=(S>90)&(V>90)&((H<35)|(H>95))` 會把黃綠中心算成 colored=0 → 漏抓。
    修成色相無關後應偵測到（Ionized 那類黃綠中心礦）。
    """
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300, color=(255, 127, 0))            # 藍框 H≈105（range1）
    cv2.rectangle(scene, (951, 296), (959, 304), (0, 255, 0), -1)  # 黃綠中心 H≈60
    assert find_tracker(scene) is not None, "黃綠中心追蹤框不應被漏抓"


# --- 混合偵測：HSV 定位 + 外框形狀確認 ---

def test_find_tracker_no_shape_templates_is_pure_hsv():
    """不傳 shape_templates → 行為同純 HSV（向後相容）。"""
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    assert find_tracker(scene) is not None
    assert find_tracker(scene, shape_templates=None) is not None
    assert find_tracker(scene, shape_templates={}) is not None


def test_find_tracker_hybrid_shape_soft_filter_falls_back_to_hsv():
    """HSV 接受 + 形狀落在 [hard_floor, threshold) → survivor → soft filter 退回純 HSV。

    對應三區判定：edge≥threshold 確認、hard_floor≤edge<threshold 保留為 survivor
    （容忍未見階級外框配不到模板）、edge<hard_floor 硬拒。square_outline_30 對
    _draw_tracker 實測 ≈0.36，落在 survivor 區（舊版 circle≈0.18 現會被硬拒）。
    """
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)                                  # HSV 會接受
    square_tmpl = np.full((40, 40, 3), 30, np.uint8)
    cv2.rectangle(square_tmpl, (5, 5), (35, 35), (220, 220, 220), 2)  # 方框（實測 edge≈0.36）
    loc = find_tracker(scene, shape_templates={"sq": square_tmpl}, shape_threshold=0.7)
    assert loc is not None, "borderline edge（survivor）應退回純 HSV，不應 return None"


def test_find_tracker_hybrid_hard_floor_rejects_wrong_shape():
    """HSV 接受 + 形狀全錯（edge < hard_floor）→ 硬拒，不 soft-filter。

    回歸 015044 裝備誤射根因：裝備 colored=0.84（HSV 強）但 edge≈0.16（形狀全錯），
    舊版 soft filter 救回來 → 誤判。加 hard_floor 後直接 return None。
    circle 對 _draw_tracker 實測 ≈0.18，低於預設 hard_floor 0.25。
    """
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)                                  # HSV 會接受
    circle = np.full((40, 40, 3), 30, np.uint8)
    cv2.circle(circle, (20, 20), 14, (220, 220, 220), 2)           # 圓環（實測 edge≈0.18 < 0.25）
    loc = find_tracker(scene, shape_templates={"circle": circle}, shape_threshold=0.7)
    assert loc is None, "edge < hard_floor 的候選應被硬拒，不應 soft-filter 救回"


def test_find_tracker_hybrid_detects_real_marker():
    """真實資料：very_rare.png（紅礦坑、黃綠中心的 Transcendent 框）→ 混合偵測應命中 (~1230,643)。"""
    img_path = "assets/very_rare.png"
    tmpl_path = "assets/markers/transcendent_tracker_real.png"
    if not (os.path.exists(img_path) and os.path.exists(tmpl_path)):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    real = cv2.imread(tmpl_path, cv2.IMREAD_UNCHANGED)
    # 純 HSV（色相無關修正）也要能找到
    assert find_tracker(img) is not None, "色相無關修正後純 HSV 應能找到黃綠中心框"
    loc = find_tracker(img, shape_templates={"t": real},
                       shape_scales=(0.7, 1.0, 1.4), shape_threshold=0.45)
    assert loc is not None
    assert abs(loc[0] - 1230) < 40 and abs(loc[1] - 643) < 40


def test_find_tracker_hybrid_rejects_equipment_false_positive():
    """真實資料：015044 sweep_confirmed（裝備誤射 @(990,665)）→ hard_floor 應擋下。

    回歸 2026-06-28 根因：shape-confirm 正確判 edge=0.16→rej，但舊版 soft filter
    翻盤退回 HSV → 誤判裝備為追蹤框。加 hard_floor=0.25 後應 return None。
    """
    img_path = "assets/false_positive_equipment.png"
    tmpl_path = "assets/markers/exotic_tracker_real.png"
    if not (os.path.exists(img_path) and os.path.exists(tmpl_path)):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    tmpl = cv2.imread(tmpl_path, cv2.IMREAD_UNCHANGED)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, shape_templates={"exotic": tmpl},
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_hard_floor=cfg.tracker_shape_hard_floor)
    assert loc is None, "裝備誤射（edge≈0.16 < hard_floor 0.25）應被硬拒，不 soft-filter"


# --- find_marker（全幀形狀偵測，顏色無關）與輔助 ---

def test_template_outline_edges_uses_alpha_channel():
    """透明模板（BGRA）→ 用 alpha 外框算邊緣，而非被填黑的彩色版。"""
    t = np.zeros((40, 40, 4), np.uint8)
    cv2.rectangle(t, (8, 8), (31, 31), (255, 255, 255, 255), 2)    # 不透明方框外框，其餘透明
    e = template_outline_edges(t)
    assert e.shape == (40, 40)
    assert int(e.max()) > 0


def test_find_marker_color_independent_via_outline():
    """形狀相同、顏色不同 → 外框比對仍命中（顏色無關，可跨階通用）。"""
    tmpl = np.full((40, 40, 3), 30, np.uint8)
    cv2.rectangle(tmpl, (6, 6), (33, 33), (200, 200, 200), 3)
    scene = np.zeros((1080, 1920, 3), np.uint8)
    cv2.rectangle(scene, (938, 283), (977, 322), (255, 255, 0), 3)  # 青色方框（同形狀、異色）
    loc = find_marker(scene, {"t": tmpl}, edge_threshold=0.3,
                      scales=(0.8, 1.0, 1.2), min_colored=0.05)
    assert loc is not None
    assert abs(loc[0] - 957) < 25 and abs(loc[1] - 302) < 25


def test_find_marker_empty_templates_falls_back_to_hsv():
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    assert find_marker(scene, {}) is not None


def test_best_outline_score_high_for_matching_shape_low_for_blank():
    tmpl = np.full((40, 40, 3), 30, np.uint8)
    cv2.rectangle(tmpl, (6, 6), (33, 33), (200, 200, 200), 3)
    scene = np.full((200, 200, 3), 30, np.uint8)
    cv2.rectangle(scene, (80, 80), (119, 119), (0, 0, 255), 3)      # 同形狀紅框
    assert best_outline_score(scene, {"t": tmpl}, scales=(0.8, 1.0, 1.2)) >= 0.4
    blank = np.full((200, 200, 3), 30, np.uint8)
    assert best_outline_score(blank, {"t": tmpl}, scales=(0.8, 1.0, 1.2)) < 0.4
