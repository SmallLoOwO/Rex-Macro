import os
import cv2
import numpy as np
import pytest
from miningbot.vision import (find_template, template_present, find_template_edges,
                              find_tracker, find_tracker_near, find_marker, best_outline_score,
                              template_outline_edges, frames_differ, detect_tracker_core,
                              banner_text_hue)

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


def test_find_tracker_with_score_returns_triple():
    """with_score=True 回傳 (x, y, score)，供 sweep 早停判斷高吻合度。

    純 HSV（無模板）時 score=colored_frac；有模板且 confirmed 時 score=edge。
    乾淨的合成 tracker 純 HSV 應有高 colored_frac。
    """
    scene = np.zeros((1080, 1920, 3), np.uint8)
    _draw_tracker(scene, 955, 300)
    r = find_tracker(scene, with_score=True)
    assert r is not None and len(r) == 3
    x, y, score = r
    assert abs(x - 955) < 40 and abs(y - 300) < 40
    assert 0.0 <= score <= 1.0 and score > 0.25         # 回傳有意義的分數（此合成圖 colored_frac≈0.3）
    # 找不到時 with_score 仍回 None（非 tuple）
    assert find_tracker(np.zeros((1080, 1920, 3), np.uint8), with_score=True) is None


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
    # UI 面板誤判候選：「細彩色外框 + 暗色內部」→ 整框彩色佔比低（實測 0.33）→ 排除。
    # 模擬 logs/rot_3.png 中 (257,933) 的左側 UI 面板誤判（實機面板更低、≈0.16）。
    # 注意：判斷專注「外框彩色佔比」，不再要求中心有顏色——真追蹤框中心會變色甚至純黑空心
    # （見 test_find_tracker_detects_black_center_marker），但其厚實外框佔比遠高於細框面板。
    scene = np.zeros((1080, 1920, 3), np.uint8)
    cx, cy = 257, 933
    cv2.rectangle(scene, (cx-25, cy-25), (cx+25, cy+25), (0, 255, 0), 3)  # 綠色細外框
    cv2.rectangle(scene, (cx-22, cy-22), (cx+22, cy+22), (25, 25, 25), -1)  # 暗色內部、無彩色中心
    assert find_tracker(scene) is None


def test_find_tracker_detects_black_center_marker():
    """回歸 2026-06-29：厚實綠外框 + 純黑空心中心（無彩色中心）仍要偵測到。

    追蹤框中心顏色每次會變（礦色/粉紅/純黑空心 BGR[0,0,0]），只有外框不變。
    舊版 accept 要求中心 2/3 ROI 有彩色像素（colored_frac>0.04），遇黑心框
    colored=0.00 → 被當暗色 UI 面板拒掉 → 漏抓、稀有沒採到。改成「專注外框彩色佔比」後
    黑心厚框（佔比≈0.62）應通過，細框暗面板（≈0.33）仍排除。"""
    scene = np.zeros((1080, 1920, 3), np.uint8)
    cx, cy = 955, 300
    cv2.rectangle(scene, (cx-15, cy-15), (cx+15, cy+15), (0, 255, 0), -1)   # 厚實綠外框
    cv2.rectangle(scene, (cx-10, cy-10), (cx+10, cy+10), (0, 0, 0), -1)     # 純黑中心填滿中央 2/3（無彩色）
    loc = find_tracker(scene)
    assert loc is not None, "黑心（純黑中心）追蹤框不應被漏抓——判斷應專注外框"
    assert abs(loc[0] - cx) < 10 and abs(loc[1] - cy) < 10


def test_find_tracker_hybrid_detects_black_center_real_scene():
    """真實資料：assets/black_center_scene.png（綠框 + 純黑中心的 exquisite 階追蹤框）。

    回歸 2026-06-29 RobloxScreenShot20260629_225228619：中心純黑（BGR 0,0,0）。
    舊版於 HSV accept 因 colored_frac(中心)=0.00 被拒（當成暗色 UI 面板）→ 整圖回 None
    → 機器人沒進 D3、稀有沒採到。混合偵測（HSV 專注外框佔比 0.56 + 形狀 edge 0.64）應命中
    框中心 (~1108,442)，且不被角色紅光/左側面板等假陽性蓋過。"""
    img_path = "assets/black_center_scene.png"
    tmpl_path = "assets/markers/exquisite_tracker_real.png"
    if not (os.path.exists(img_path) and os.path.exists(tmpl_path)):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    tmpl = cv2.imread(tmpl_path, cv2.IMREAD_UNCHANGED)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, shape_templates={"exq": tmpl},
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px,
                       shape_hard_floor=cfg.tracker_shape_hard_floor)
    assert loc is not None and abs(loc[0] - 1108) < 40 and abs(loc[1] - 442) < 40


def test_find_tracker_hybrid_detects_green_solid_center_scene():
    """真實資料：assets/green_center_scene.png（H13, RobloxScreenShot20260702_153209768）。

    綠框 + 黑環 + **亮綠實心中心**的追蹤框（右上 ~1365,277）。綠 HSV mask 同時吃到外框與
    中心 → 整框 fill≈1.00、ring≈0.00 → 舊版 HSV 前置關卡 rej(not_ring)（且 fill≥0.85 一併擋），
    在形狀確認前就被否決 → 整圖回 None、機器人沒進 D3、稀有沒採到（H13 漏抓根因）。
    但外框形狀 edge≈0.64（≫0.45 門檻）→ 混合模式應由形狀確認命中；ring/fill 結構關卡不得硬拒真框。"""
    img_path = "assets/green_center_scene.png"
    tmpls = {}
    for n in ("exotic_tracker_real", "exquisite_tracker_real", "transcendent_tracker_real"):
        t = cv2.imread(f"assets/markers/{n}.png", cv2.IMREAD_UNCHANGED)
        if t is not None and t.ndim == 3 and t.shape[2] == 3:
            tmpls[n] = t
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, shape_templates=tmpls,
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px,
                       shape_hard_floor=cfg.tracker_shape_hard_floor)
    assert loc is not None, "綠實心中心追蹤框不應被 ring/fill 關卡漏抓（形狀 edge≈0.64 應命中）"
    assert abs(loc[0] - 1365) < 40 and abs(loc[1] - 277) < 40


def test_find_tracker_hybrid_detects_occluded_green_tracker_near_threshold():
    """真實資料：assets/occluded_green_tracker_scene.png（173709，綠框被角色帽子擋到角）。

    真綠框（角色頭上 ~982,434、colored≈0.93）但外框被帽子冠飾切到 → 形狀 edge≈0.43，
    差舊門檻 0.45 一點點、又是實心中心（非 survivor）→ 舊版漏抓、你手動截圖回報。
    實測「裝備假陽性 edge≤0.30、真框 edge≥0.43」中間有 gap → 門檻降到 0.42（DEFAULT）後應命中。
    用 DEFAULT.tracker_shape_threshold 鎖意圖：門檻若被調回 ≥0.44 這測試會紅、提醒別回退。"""
    img_path = "assets/occluded_green_tracker_scene.png"
    tmpls = {}
    for n in ("exotic_tracker_real", "exquisite_tracker_real", "transcendent_tracker_real"):
        t = cv2.imread(f"assets/markers/{n}.png", cv2.IMREAD_UNCHANGED)
        if t is not None and t.ndim == 3 and t.shape[2] == 3:
            tmpls[n] = t
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, shape_templates=tmpls,
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px,
                       shape_hard_floor=cfg.tracker_shape_hard_floor)
    assert loc is not None, "被帽子擋到角的綠框（edge≈0.43）應在門檻 0.42 下命中"
    assert 900 < loc[0] < 1060 and 400 < loc[1] < 500, f"應命中角色頭上綠框區，實得 {loc}"


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


def test_find_tracker_hybrid_detects_exquisite_green_marker():
    """真實資料：exquisite（綠）追蹤框 = 方框 + 四角綠芒（非純方框）。

    2026-06-29 補 exquisite_tracker_real.png 後，綠階真框應被命中 (918,305)。
    補模板前此框 best_outline_score≈0.42-0.53（部分卡 survivor）；補後綠階群均 ≥0.45 confirmed。
    """
    img_path = "assets/exquisite_scene.png"
    tmpl_path = "assets/markers/exquisite_tracker_real.png"
    if not (os.path.exists(img_path) and os.path.exists(tmpl_path)):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    tmpl = cv2.imread(tmpl_path, cv2.IMREAD_UNCHANGED)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, shape_templates={"exq": tmpl},
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px,
                       shape_hard_floor=cfg.tracker_shape_hard_floor)
    assert loc is not None and abs(loc[0] - 918) < 40 and abs(loc[1] - 305) < 40


def test_hard_floor_separates_equipment_band_from_real_trackers():
    """回歸 2026-06-28 夜間兩次裝備誤射（borderline edge 翻盤）。

    實機證據（harvest.log）：
      - 真追蹤框 edge≥0.44（19:38=0.44 colored=1.00、20:21=0.57-0.63）
      - 裝備誤射 edge≤0.26（20:50=0.25、22:42=0.26，均射在角色自身橘紅裝備上）
    兩次誤射都落在舊 hard_floor 0.25 的正上方 → 判 survivor → soft filter 救回 → 開火。
    hard_floor 必須 > 0.26（擋下裝備帶）且 ≤ 0.358（保留未見階級外框代理
    square_outline_30=0.358，見上面 soft_filter 測試），落在 0.26 與 0.44 的大空隙中。
    """
    from miningbot.config import DEFAULT as cfg
    assert cfg.tracker_shape_hard_floor > 0.26, "須擋下 22:42 裝備誤射的 edge=0.26"
    assert cfg.tracker_shape_hard_floor <= 0.358, "不可誤殺未見階級外框代理(edge≈0.358)"


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


# --- frames_differ：聊天輪詢的省 OCR 閘（H015 對策）---
# D3 後輪詢驗證每 ~1s 抓幀；聊天全區 3-pass OCR 實測 ~10s（滿版文字），不能每輪都跑。
# 聊天是螢幕覆蓋層、角色靜止時裁圖近乎逐位元相同 → 只有像素變了（新訊息/淡出）才值得 OCR。
def test_frames_differ_false_for_identical_crops():
    a = np.full((80, 200, 3), 120, np.uint8)
    assert frames_differ(a, a.copy()) is False


def test_frames_differ_true_when_text_like_change_appears():
    a = np.full((80, 200, 3), 120, np.uint8)
    b = a.copy()
    cv2.putText(b, "has found X", (5, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    assert frames_differ(a, b) is True


def test_frames_differ_true_when_baseline_missing_or_shape_mismatch():
    a = np.full((80, 200, 3), 120, np.uint8)
    assert frames_differ(None, a) is True          # 尚無基準 → 必須 OCR
    assert frames_differ(a[:40], a) is True        # 尺寸不同（區域改了）→ 必須 OCR


def test_find_tracker_edge_clipped_scene_documents_margin_rejection():
    """真實資料：assets/edge_clipped_tracker_scene.png（H019, RobloxScreenShot20260703_172635259）。

    追蹤框被 D5 到期的 FOV 收縮推到畫面右緣 (~1862,418)、部分裁切。預設 margin_frac=0.1
    的邊緣排除帶會拒收（in_area=False）→ 整圖回 None——這正是 H019 verify 失敗、誤判
    「未找到」交人工的機制。margin=0 時同一顆框 edge≈0.57（≫0.42 門檻）可正常命中。
    此測試釘住兩個事實：邊緣框對預設偵測不可見（上游靠 pick_sweep_candidate 選居中候選
    ＋verify 失敗重掃一次補救），以及框本身形狀完好可辨（margin 是唯一擋它的關卡）。"""
    img_path = "assets/edge_clipped_tracker_scene.png"
    tmpls = {}
    for n in ("exotic_tracker_real", "exquisite_tracker_real", "transcendent_tracker_real"):
        t = cv2.imread(f"assets/markers/{n}.png", cv2.IMREAD_UNCHANGED)
        if t is not None and t.ndim == 3 and t.shape[2] == 3:
            tmpls[n] = t
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    kw = dict(exclude=excl, shape_templates=tmpls,
              shape_threshold=cfg.tracker_shape_threshold,
              shape_scales=cfg.tracker_shape_scales,
              shape_roi_px=cfg.tracker_shape_roi_px,
              shape_hard_floor=cfg.tracker_shape_hard_floor)
    assert find_tracker(img, margin_frac=0.1, **kw) is None       # H019 失敗機制
    loc = find_tracker(img, margin_frac=0.0, **kw)                # 框本身完好可辨
    assert loc is not None and abs(loc[0] - 1862) < 40 and abs(loc[1] - 418) < 40
    # H026 後 margin 收窄進 config：實戰預設值也必須收得回這顆右緣框
    loc2 = find_tracker(img, margin_frac=cfg.tracker_margin_frac, **kw)
    assert loc2 is not None and abs(loc2[0] - 1862) < 40 and abs(loc2[1] - 418) < 40


def test_find_tracker_bottom_edge_scene_h026_recovered_by_config_margin():
    """真實資料：assets/bottom_edge_tracker_scene.png（H026, RobloxScreenShot20260704_005233867）。

    D5 到期的 FOV 收縮是以畫面中心為錨的 ~2.6x 縮放：sweep 早停確認過的框 (1084,744)
    被推到底緣 (1288,1020)。舊 margin_frac=0.1 的底部排除帶（y>972 全拒）在全部 8 個
    方位都擋掉它——yaw 旋轉只改 x 不改 y，框永遠在帶內 → 重掃全空、誤交人工（H026）。
    實戰預設 cfg.tracker_margin_frac=0.02（y≤1058）收得回；邊緣雜訊仍有
    preexist 差分／colored_frac／形狀確認三道閘擋著（0.02 對全 fixture 集無新假陽性）。"""
    img_path = "assets/bottom_edge_tracker_scene.png"
    tmpls = {}
    for n in ("exotic_tracker_real", "exquisite_tracker_real", "transcendent_tracker_real"):
        t = cv2.imread(f"assets/markers/{n}.png", cv2.IMREAD_UNCHANGED)
        if t is not None and t.ndim == 3 and t.shape[2] == 3:
            tmpls[n] = t
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    kw = dict(exclude=excl, shape_templates=tmpls,
              shape_threshold=cfg.tracker_shape_threshold,
              shape_scales=cfg.tracker_shape_scales,
              shape_roi_px=cfg.tracker_shape_roi_px,
              shape_hard_floor=cfg.tracker_shape_hard_floor)
    assert find_tracker(img, margin_frac=0.1, **kw) is None       # H026 失敗機制（舊帶擋真框）
    loc = find_tracker(img, margin_frac=cfg.tracker_margin_frac, **kw)
    assert loc is not None and abs(loc[0] - 1288) < 40 and abs(loc[1] - 1020) < 40
    assert cfg.tracker_margin_frac <= 0.02   # H026 框 y=1020 需 margin ≤ (1-1020/1080)=0.055；留餘裕釘 0.02


def test_frames_mean_diff_value_and_none_cases():
    # 詳細 log 用：回傳實際平均差值；基準缺/尺寸不合 → None（無從比較）
    from miningbot.vision import frames_mean_diff
    a = np.zeros((20, 30, 3), dtype=np.uint8)
    b = a.copy(); b[:, :, :] = 6
    assert frames_mean_diff(a, a.copy()) == 0.0
    assert abs(frames_mean_diff(a, b) - 6.0) < 1e-6
    assert frames_mean_diff(None, a) is None
    assert frames_mean_diff(a, np.zeros((10, 30, 3), dtype=np.uint8)) is None


# --- frames_changed_frac：驗證式旋轉的第二訊號（2026-07-05）---
# 旋轉 45° 在近全黑礦坑「平均差」可能很低（像素值本來就低），但「有感變化像素的
# 佔比」仍高；被吃的按鍵只剩角色 idle 微幅變化、佔比近零。與 frames_mean_diff 搭配
# 讓「被吃」判定保守（兩訊號都近零才重送——實際轉了卻重送＝直接製造 45° 偏移）。

def test_frames_changed_frac_zero_for_identical():
    from miningbot.vision import frames_changed_frac
    a = np.full((40, 60, 3), 80, dtype=np.uint8)
    assert frames_changed_frac(a, a.copy(), pixel_thresh=12) == 0.0

def test_frames_changed_frac_ignores_subthreshold_noise():
    from miningbot.vision import frames_changed_frac
    a = np.full((10, 10, 3), 80, dtype=np.uint8)
    b = a + 5                                        # 全圖微幅雜訊（低於 pixel_thresh）
    assert frames_changed_frac(a, b, pixel_thresh=12) == 0.0

def test_frames_changed_frac_counts_perceptible_region():
    from miningbot.vision import frames_changed_frac
    a = np.full((10, 10, 3), 80, dtype=np.uint8)
    c = a.copy(); c[:5, :, 0] = 200                  # 上半僅單一 channel 大變（仍算有感）
    assert abs(frames_changed_frac(a, c, pixel_thresh=12) - 0.5) < 1e-6

def test_frames_changed_frac_none_when_uncomparable():
    from miningbot.vision import frames_changed_frac
    a = np.zeros((10, 10, 3), dtype=np.uint8)
    assert frames_changed_frac(None, a, pixel_thresh=12) is None
    assert frames_changed_frac(a, np.zeros((5, 5, 3), dtype=np.uint8), pixel_thresh=12) is None


def test_find_tracker_near_maps_roi_hit_back_to_full_frame_coords():
    scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _draw_tracker(scene, 900, 500, size=44, color=(60, 220, 240))
    full = find_tracker(scene, margin_frac=0.02)
    near = find_tracker_near(scene, (905, 495), 180, frame_margin_frac=0.02)
    assert full is not None and near is not None
    assert abs(near[0] - full[0]) <= 2 and abs(near[1] - full[1]) <= 2


def test_find_tracker_near_returns_none_when_center_far_from_tracker():
    scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _draw_tracker(scene, 1500, 800, size=44, color=(60, 220, 240))
    assert find_tracker_near(scene, (300, 300), 180, frame_margin_frac=0.02) is None


def test_find_tracker_near_shifts_exclude_rects_into_roi():
    scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _draw_tracker(scene, 900, 500, size=44, color=(60, 220, 240))
    excl = [(860, 460, 940, 540)]   # 全幀座標蓋住框 → ROI 內也必須被排除
    assert find_tracker_near(scene, (905, 495), 180,
                             frame_margin_frac=0.02, exclude=excl) is None


def test_find_tracker_near_keeps_h026_bottom_edge_tracker_visible():
    # 對應 H026：ROI 路徑不可重新引入邊緣排除帶殺真框的機制。
    # 全幀 margin 0.02 收得回 (1288,1020) → ROI 版在同 margin 下也必須收得回；
    # margin 0.10 下必須同樣拒收（語意與全幀版一致）。
    img_path = "assets/bottom_edge_tracker_scene.png"
    tmpls = {}
    for n in ("exotic_tracker_real", "exquisite_tracker_real", "transcendent_tracker_real"):
        t = cv2.imread(f"assets/markers/{n}.png", cv2.IMREAD_UNCHANGED)
        if t is not None and t.ndim == 3 and t.shape[2] == 3:
            tmpls[n] = t
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    kw = dict(shape_templates=tmpls, shape_threshold=cfg.tracker_shape_threshold,
              shape_scales=cfg.tracker_shape_scales, shape_roi_px=cfg.tracker_shape_roi_px,
              shape_hard_floor=cfg.tracker_shape_hard_floor)
    loc = find_tracker_near(img, (1288, 1020), 180,
                            frame_margin_frac=cfg.tracker_margin_frac, **kw)
    assert loc is not None and abs(loc[0] - 1288) < 40 and abs(loc[1] - 1020) < 40
    assert find_tracker_near(img, (1288, 1020), 180,
                             frame_margin_frac=0.10, **kw) is None


# --- best_template_match_scored：reentry sweep 跨 8 方位比分數用 ---
from miningbot import vision


def test_best_template_match_scored_finds_rect():
    scene = np.zeros((300, 400, 3), dtype=np.uint8)
    cv2.rectangle(scene, (160, 125), (240, 175), (200, 80, 200), 3)
    tmpl = scene[115:185, 150:250].copy()
    score, center = vision.best_template_match_scored(scene, [tmpl], scales=(1.0,))
    assert score > 0.8
    assert abs(center[0] - 200) < 10 and abs(center[1] - 150) < 10


def test_best_template_match_scored_empty_templates():
    scene = np.zeros((100, 100, 3), dtype=np.uint8)
    assert vision.best_template_match_scored(scene, [], scales=(1.0,)) == (-1.0, None)


# --- H040（2026-07-11）：shape ROI 撐大（207px 粗紅方框裝不進 160px ROI）---
# harvest 070 實錄：畫面正中央 207×208px 粗紅色方形追蹤框（bbox x836-1043、y492-700），
# HSV 找到候選（colored 0.79-0.99），但 tracker_shape_roi_px=160 的 ROI 只有 160×160
# 裝不下 207px 的框 → 模板×尺度超 ROI 被 _best_edge_match_sized 的 th>sh 跳過
# → 8 方位全空 → 誤交人工。ROI 尺寸把可偵測框大小硬上限在 ~160px 是結構性缺口。
# 對策：roi 160→320（207px 真框＋模板 213px×尺度 1.4≈298 都要裝得下）。

def _load_real_markers_h040():
    """載入 assets/markers 內無 alpha 的 3 通道實機裁圖（含 H040 新增的紅方框模板）。"""
    names = ("red_square_tracker_real", "exotic_tracker_real",
             "exquisite_tracker_real", "transcendent_tracker_real")
    tmpls = {}
    for n in names:
        t = cv2.imread(f"assets/markers/{n}.png", cv2.IMREAD_UNCHANGED)
        if t is not None and t.ndim == 3 and t.shape[2] == 3:
            tmpls[n] = t
    return tmpls


def test_h040_red_square_tracker_detected_in_scene():
    """TP 場景：assets/red_square_tracker_scene.png（070_dir0 全幀，207px 粗紅方框）。

    roi=160（舊值）裝不下 207px 框 → 抓不到（這就是事故）；roi=320（新值）應命中
    中心 ~(991,553)、edge≈1.00，落在 bbox x∈[836,1043] y∈[492,700] 內。
    用 cfg.tracker_shape_roi_px：改 config 前此測試必紅（鎖住 roi 是唯一瓶頸）。
    """
    img_path = "assets/red_square_tracker_scene.png"
    tmpls = _load_real_markers_h040()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, reference_bgr=None,
                       margin_frac=cfg.tracker_margin_frac,
                       shape_templates=tmpls,
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_hard_floor=cfg.tracker_shape_hard_floor,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px)
    assert loc is not None, "207px 粗紅方框在 roi=320 下應被偵測到（H040 事故根因）"
    assert 836 <= loc[0] <= 1043 and 492 <= loc[1] <= 700, \
        f"中心應落在紅方框 bbox 內，實得 {loc}"


def test_h040_red_ribbon_equipment_not_detected():
    """負樣本：assets/red_ribbon_equipment_scene.png（069_dir5，角色紅緞帶裝飾）。

    紅緞帶裝備 edge 峰值 0.21-0.38（不越 0.42 門檻）→ 即使 roi 撐大也不可誤判為追蹤框。
    """
    img_path = "assets/red_ribbon_equipment_scene.png"
    tmpls = _load_real_markers_h040()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, reference_bgr=None,
                       margin_frac=cfg.tracker_margin_frac,
                       shape_templates=tmpls,
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_hard_floor=cfg.tracker_shape_hard_floor,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px)
    assert loc is None, f"紅緞帶裝備（edge≤0.38）不應被誤判為追蹤框，實得 {loc}"


def test_072_dual_tracker_scene_detects_first_fired_target():
    """真實資料：assets/dual_tracker_scene.png（incident 072，開火前雙框幀）。

    同畫面兩顆不同階礦的追蹤框；採第一顆前 find_tracker 應定位到 (607,223)（edge≈0.78）。
    釘住「成功收場幀上第二顆仍清晰存在」的對照幀——這是 072 漏採根因（成功後無條件回 MINING）。"""
    img_path = "assets/dual_tracker_scene.png"
    tmpls = _load_real_markers_h040()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, reference_bgr=None,
                       margin_frac=cfg.tracker_margin_frac,
                       shape_templates=tmpls,
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_hard_floor=cfg.tracker_shape_hard_floor,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px)
    assert loc is not None, "072 雙框幀應偵測到 (607,223) 追蹤框（edge≈0.78 ≫ 0.42 門檻）"
    assert abs(loc[0] - 607) <= 20 and abs(loc[1] - 223) <= 20, f"應命中首發目標 (607,223)，實得 {loc}"


def test_072_post_success_second_tracker_scene_detected():
    """真實資料：assets/post_success_second_tracker_scene.png（incident 072，成功收場幀）。

    採到第一顆後畫面仍有第二顆追蹤框（edge≈0.61 ≫ 0.42）。釘住「成功後畫面仍
    有另一個可採目標」——decide_post_success 距離閘（548px vs 100px）正是據此判定續採。

    H057 期望值修正：舊版釘 (1097,475)——那是 HSV 候選中心（藉 320px ROI 內偏移 96px
    的真框拿到 0.61），實際畫面上唯一的框（黃色尖刺太陽框）在 **(1043,555)**（人工目視
    裁圖確認）。重錨修正後 find_tracker 回傳形狀命中中心＝真框位置。"""
    img_path = "assets/post_success_second_tracker_scene.png"
    tmpls = _load_real_markers_h040()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    excl = [(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)]
    loc = find_tracker(img, exclude=excl, reference_bgr=None,
                       margin_frac=cfg.tracker_margin_frac,
                       shape_templates=tmpls,
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_hard_floor=cfg.tracker_shape_hard_floor,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px)
    assert loc is not None, "072 成功收場幀應偵測到第二顆 (1043,555) 追蹤框（edge≈0.61 ≫ 0.42 門檻）"
    assert abs(loc[0] - 1043) <= 20 and abs(loc[1] - 555) <= 20, f"應命中第二顆真框 (1043,555)，實得 {loc}"


# --- collect_rejects：近失候選外露（2026-07-11 remote-aim spec Phase A1）---
# find_tracker 傳入 collect_rejects list 時，把「值得人工看的被拒候選」外露；
# 不傳＝行為 byte-identical（純外掛，既有判定零改動）。

def _hollow_ring(img, cx, cy, size=40, color=(60, 220, 60), thick=6):
    """畫一個彩色空心方框（模擬追蹤框外框），回傳中心座標。"""
    h = size // 2
    cv2.rectangle(img, (cx - h, cy - h), (cx + h, cy + h), color, thick)
    return cx, cy


def test_collect_rejects_margin_band():
    """邊緣帶內的彩色環：現狀被拒（in_area=False）、collect_rejects 應收到 reason=margin。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _hollow_ring(img, 60, 540)          # x=60 落在 margin_frac=0.10 的左緣帶（<192）
    rejects = []
    loc = find_tracker(img, margin_frac=0.10, collect_rejects=rejects)
    assert loc is None
    assert any(r["reason"] == "margin" and abs(r["pos"][0] - 60) <= 5 for r in rejects), rejects


def test_collect_rejects_none_keeps_behavior():
    """不傳 collect_rejects：回傳值與傳了之後的回傳值完全一致（外掛零影響）。"""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    _hollow_ring(img, 960, 540)
    a = find_tracker(img, margin_frac=0.10)
    b = find_tracker(img, margin_frac=0.10, collect_rejects=[])
    assert a == b


def test_collect_rejects_hard_rej_real_equipment():
    """真實資料：H040 紅緞帶裝備場景——現狀 hard_rej 拒收，collect_rejects 應把它外露。"""
    img_path = "assets/red_ribbon_equipment_scene.png"
    tmpls = _load_real_markers_h040()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    from miningbot.config import DEFAULT as cfg
    rejects = []
    loc = find_tracker(img, margin_frac=cfg.tracker_margin_frac,
                       shape_templates=tmpls,
                       shape_threshold=cfg.tracker_shape_threshold,
                       shape_hard_floor=cfg.tracker_shape_hard_floor,
                       shape_scales=cfg.tracker_shape_scales,
                       shape_roi_px=cfg.tracker_shape_roi_px,
                       collect_rejects=rejects)
    assert loc is None                       # H040 回歸：裝備仍不誤收
    assert any(r["reason"] == "hard_rej" for r in rejects), rejects


# ===== boost 使用次數計數器（2026-07-19）=====
from miningbot.vision import read_boost_use_count

_BC_FIX = "tests/fixtures/boost_count"


def test_boost_use_count_known_values():
    """13 個實機裁圖（07-14~07-19 快照，值 15~211）逐一比對。

    Tesseract 對此字體只有 8/10（166 讀空、211 掉尾數）；模板比對必須全中。
    """
    import glob
    files = sorted(glob.glob(os.path.join(_BC_FIX, "count_*.png")))
    assert len(files) >= 13
    for f in files:
        truth = int(os.path.basename(f).split("_")[1].split(".")[0])
        img = cv2.imread(f)
        assert read_boost_use_count(img) == truth, f


def test_boost_use_count_negative_regions():
    """無計數器區域（天空/紅色場景滲入）一律 None——寧可不讀不誤讀。"""
    for name in ("none_sky.png", "none_red_scene.png"):
        img = cv2.imread(os.path.join(_BC_FIX, name))
        assert img is not None, name
        assert read_boost_use_count(img) is None, name


def test_boost_use_count_unknown_glyph_rejects_whole_read():
    """數字尺寸的紅色實心塊（未知字元）→ 整筆 None，不吐部分讀值。"""
    img = cv2.imread(os.path.join(_BC_FIX, "count_41.png"))
    img[40:53, 20:31] = (0, 0, 255)          # 塞一個 11×13 純紅塊（過尺寸閘、配不上模板）
    assert read_boost_use_count(img) is None


# ===== detect_tracker_core（harvest 101 手動瞄準精定位）=====
# 限縮單格區域找追蹤框實心亮色中心。合成圖驗演算法邊界，實機裁格 fixture 驗真值。
# fixture＝**粗格原生裁圖**（正是 detect_tracker_core 在實機吃到的東西），存 tests/fixtures/
# 而非 assets/——assets/**/*.png 被 .gitignore 排除，是機器本地 runtime 輸入（tests/AGENTS.md）。
# 兩側夾（面積）：真框心 256×6／663（含本機 edge_clipped_tracker_scene 33×32）
#              vs 亮綠地形 4918/15043/17268/25631 → tracker_core_max_area=1800。
_AIM_FIX = "tests/fixtures/aim"
_GREEN_PROFILE = [("green", (40, 150, 150), (85, 255, 255))]


def _draw_core(region, cx, cy, half=8, with_border=False, border=6, bg=200):
    """合成追蹤框中心：飽和綠實心方塊（BGR(0,255,0)＝HSV(60,255,255)），可選黑邊環帶。

    bg=200（亮灰）模擬「無黑邊」的空格背景；with_border=True 在綠心外圍 border px
    填黑，模擬真框周圍黑邊。core 16×16（area 256，同 spec §6 綠框實測面積）。
    """
    region[:] = (bg, bg, bg)
    if with_border:
        cv2.rectangle(region, (cx - half - border, cy - half - border),
                      (cx + half + border, cy + half + border), (0, 0, 0), -1)
    cv2.rectangle(region, (cx - half, cy - half), (cx + half, cy + half),
                  (0, 255, 0), -1)


def test_detect_tracker_core_green_hit_with_border():
    # 綠心（211,189）＋黑邊環帶 → 命中中心、profile=green、border_frac≥0.15（合成兩側夾正例）
    region = np.zeros((270, 320, 3), np.uint8)
    _draw_core(region, 211, 189, with_border=True, bg=200)
    r = detect_tracker_core(region, _GREEN_PROFILE)
    assert r is not None
    cx, cy, name, border_frac = r
    assert abs(cx - 211) <= 15 and abs(cy - 189) <= 15
    assert name == "green"
    assert border_frac >= 0.15


def test_detect_tracker_core_green_no_border_rejected():
    # 綠心但無黑邊（亮灰背景）→ border_frac≈0 < 0.15 → None（非框亮塊，兩側夾負例）
    region = np.zeros((270, 320, 3), np.uint8)
    _draw_core(region, 211, 189, with_border=False, bg=200)
    assert detect_tracker_core(region, _GREEN_PROFILE) is None


def test_detect_tracker_core_empty_region():
    # 無綠心（純背景）→ 無 contour 過 min_area → None（空格兩側夾負例）
    region = np.zeros((270, 320, 3), np.uint8)
    region[:] = (200, 200, 200)
    assert detect_tracker_core(region, _GREEN_PROFILE) is None


def test_detect_tracker_core_empty_profiles_returns_none():
    # profiles=[]（未覆蓋色系）→ None（永不誤射；靠退路放大手選兜底）
    region = np.zeros((270, 320, 3), np.uint8)
    _draw_core(region, 211, 189, with_border=True, bg=200)
    assert detect_tracker_core(region, []) is None


def test_detect_tracker_core_coords_relative_to_region():
    # 座標相對 region（非全幀）：同一綠心在 region (50,40) → 回 (50,40) 附近
    region = np.zeros((270, 320, 3), np.uint8)
    _draw_core(region, 50, 40, with_border=True, bg=200)
    r = detect_tracker_core(region, _GREEN_PROFILE)
    assert r is not None and abs(r[0] - 50) <= 15 and abs(r[1] - 40) <= 15


def test_detect_tracker_core_green_scene_fixture():
    # 實機真值（101 第二發 aim_fire 幀）：裁 C1→相對 (211,189)＝絕對 (851,189)、0px、
    # border_frac 0.35、框心面積 256（17×17）；空鄰格 B1→None。
    # 相對路徑：cv2.imread 讀不到本 repo 的非 ASCII 絕對路徑（同檔 _BC_FIX 慣例）
    crop = cv2.imread(f"{_AIM_FIX}/101_core_green_c1.png")     # C1 region (640,0,320,270)
    assert crop is not None
    r = detect_tracker_core(crop, _GREEN_PROFILE)
    assert r is not None
    cx, cy, name, border_frac = r
    assert abs(cx - 211) <= 15 and abs(cy - 189) <= 15
    assert name == "green" and border_frac >= 0.15
    # 空鄰格 B1 (320,0,320,270) → None
    b1 = cv2.imread(f"{_AIM_FIX}/101_core_green_b1.png")
    assert b1 is not None
    assert detect_tracker_core(b1, _GREEN_PROFILE) is None


def test_detect_tracker_core_bright_terrain_is_not_a_tracker():
    """實機負例：整片亮綠地形不得被當框自動開火（101 dir2 survey 幀 D1 格）。

    地形色與框心同屬綠 HSV 範圍，且大塊地形實心（extent 0.70）、被格邊裁成近方形
    （198×185、ar 1.07）、bbox 外環帶落在暗地形上（border_frac 0.89）——ar/extent/border
    三道關卡全過。唯一結構差異是**面積**：框心 256（17×17），地形 25631（≈100 倍）。
    無面積上限時 best 取面積最大 → 即使該格真有框也會被地形蓋掉、朝地形中心開一發。
    """
    d1 = cv2.imread(f"{_AIM_FIX}/101_terrain_fp_d1.png")       # D1 region (960,0,320,270)
    assert d1 is not None
    assert detect_tracker_core(d1, _GREEN_PROFILE) is None
    # 紅綠自證：拿掉面積上限，同一張圖就會回報 (207,177)——確認本測試真的夾在 max_area 上，
    # 不是被別的關卡順手擋掉（門檻回退時此測試必紅）。
    unguarded = detect_tracker_core(d1, _GREEN_PROFILE, max_area=10 ** 9)
    assert unguarded is not None and unguarded[3] > 0.8


def test_detect_tracker_core_oversized_blob_rejected():
    # 面積上限兩側夾：真框心 ≤663 收、地形級大塊（>1800）拒——即使黑邊環帶齊全
    region = np.zeros((270, 320, 3), np.uint8)
    _draw_core(region, 160, 135, half=40, with_border=True, bg=200)   # 81×81=6561
    assert detect_tracker_core(region, _GREEN_PROFILE) is None
    region2 = np.zeros((270, 320, 3), np.uint8)
    _draw_core(region2, 160, 135, half=16, with_border=True, bg=200)  # 33×33=1089 ≤1800
    assert detect_tracker_core(region2, _GREEN_PROFILE) is not None
# --- H057（2026-07-20 harvest 097）：同色黏連救援＋confirmed 重錨 ---
# 097 dir4：亮綠追蹤框 (983,435) 貼上受光綠牆 → RETR_EXTERNAL 把框和牆接成一條
# 爆 area/bbox 閘的大輪廓（bbox 493x85、area 14620），真框在形狀確認前就出局；
# 同幀角色的臉 (959,547) 藉 320px shape ROI「借」到隔壁真框的 0.61 分而成為
# 全畫面最佳命中（H040 撐大 ROI 引入的交叉污染）。
# 兩條對策：(1) confirmed 重錨到形狀命中中心；(2) 超大輪廓 V-submask 二次分割救援。


def _load_real_markers_h057():
    """production 同款形狀確認集：assets/markers 內全部無 alpha 的實機裁圖。"""
    names = ("red_square_tracker_real", "exotic_tracker_real", "enigmatic_tracker_real",
             "exquisite_tracker_real", "transcendent_tracker_real")
    tmpls = {}
    for n in names:
        t = cv2.imread(f"assets/markers/{n}.png", cv2.IMREAD_UNCHANGED)
        if t is not None and t.ndim == 3 and t.shape[2] == 3:
            tmpls[n] = t
    return tmpls


def _h057_kwargs(tmpls, rescue=True):
    from miningbot.config import DEFAULT as cfg
    _c = cfg.chat_region
    kw = dict(exclude=[(_c.x, _c.y, _c.x + _c.w, _c.y + _c.h)],
              margin_frac=cfg.tracker_margin_frac,
              shape_templates=tmpls,
              shape_threshold=cfg.tracker_shape_threshold,
              shape_hard_floor=cfg.tracker_shape_hard_floor,
              shape_scales=cfg.tracker_shape_scales,
              shape_roi_px=cfg.tracker_shape_roi_px)
    if rescue:
        kw.update(rescue_v_min=cfg.tracker_rescue_v_min,
                  rescue_area_min=cfg.tracker_rescue_area_min,
                  rescue_max=cfg.tracker_rescue_max_candidates,
                  rescue_dedup_px=cfg.tracker_rescue_dedup_px)
    return kw


def test_h057_green_on_green_manual_frame_hits_true_frame_not_face():
    """真實資料：tests/fixtures/tracker/h057_green_on_green_manual.png（097 dir4 手動掃圖）。

    修復前 find_tracker 回 (959,547)＝角色的臉（借分 0.61）；真框 (983,435)
    連候選都進不了。修復後（重錨＋救援）必須命中真框、且不得再回臉的位置。"""
    img_path = "tests/fixtures/tracker/h057_green_on_green_manual.png"
    tmpls = _load_real_markers_h057()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    loc = find_tracker(img, **_h057_kwargs(tmpls))
    assert loc is not None, "097 dir4 真框 (983,435) 應被偵測到（H057 事故根因）"
    assert abs(loc[0] - 983) <= 20 and abs(loc[1] - 435) <= 20, f"應命中真框 (983,435)，實得 {loc}"
    assert not (abs(loc[0] - 959) <= 10 and abs(loc[1] - 547) <= 10), "不得再命中角色的臉 (959,547)"


def test_h057_reanchor_alone_redeems_borrowed_score():
    """重錨隔離測試：關閉救援（rescue_v_min=None）後，臉候選 (959,547) 的 0.61

    分來自 ROI 內偏移 114px 的真框——重錨必須把 confirmed 座標搬回形狀命中處
    (983,435)，而不是留在借分的候選中心。"""
    img_path = "tests/fixtures/tracker/h057_green_on_green_manual.png"
    tmpls = _load_real_markers_h057()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    loc = find_tracker(img, **_h057_kwargs(tmpls, rescue=False))
    assert loc is not None
    assert abs(loc[0] - 983) <= 20 and abs(loc[1] - 435) <= 20, f"重錨應回真框 (983,435)，實得 {loc}"


def test_h057_incident_sweep_frame_now_detects():
    """真實資料：tests/fixtures/tracker/h057_green_on_green_sweep.png（097 sweep dir4 幀，16:20:43）。

    這張就是當時 giveup 交人工的其中一幀——真框 (983,436) 在畫面上，但被同色
    黏連吃掉、八方位全空。修復後同一幀必須直接命中（本次 giveup 本可完全避免）。
    注意：實機 sweep 還有 reference_bgr 差分；本測試無 reference，守的是
    「黏連本身不再讓真框出局」這一層。"""
    img_path = "tests/fixtures/tracker/h057_green_on_green_sweep.png"
    tmpls = _load_real_markers_h057()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    loc = find_tracker(img, **_h057_kwargs(tmpls))
    assert loc is not None, "097 sweep dir4 幀的真框 (983,436) 應被偵測到"
    assert abs(loc[0] - 983) <= 20 and abs(loc[1] - 436) <= 20, f"應命中真框 (983,436)，實得 {loc}"


def _h057_wall_scene(with_frame: bool):
    """合成黏連：HSV(63,220,75) 受光綠牆（V 低於救援門檻 150、高於色域 V 下限 50），

    可選直接「畫」一個同色相、V=255 的空心方環在牆上——環與牆在同一條 inRange
    mask 內相連 → RETR_EXTERNAL 必黏成一條爆 area/bbox 閘的大輪廓（097 dir4 根因
    的最小重現）。回傳 (scene, 環中心, 環模板（黑底裁圖，給形狀確認）)。"""
    scene = np.zeros((1080, 1920, 3), np.uint8)
    wall_hsv = np.full((300, 500, 3), (63, 220, 75), np.uint8)
    scene[400:700, 700:1200] = cv2.cvtColor(wall_hsv, cv2.COLOR_HSV2BGR)
    ring_bgr = tuple(int(v) for v in cv2.cvtColor(
        np.full((1, 1, 3), (63, 230, 255), np.uint8), cv2.COLOR_HSV2BGR)[0, 0])
    cx, cy, half, thick = 950, 550, 15, 5
    tmpl = np.zeros((44, 44, 3), np.uint8)
    cv2.rectangle(tmpl, (22 - half, 22 - half), (22 + half, 22 + half), ring_bgr, thick)
    if not with_frame:
        return scene, None, tmpl
    cv2.rectangle(scene, (cx - half, cy - half), (cx + half, cy + half), ring_bgr, thick)
    return scene, (cx, cy), tmpl


def test_h057_rescue_second_segmentation_recovers_frame_glued_to_wall():
    """救援隔離測試（合成）：環貼同色牆 → 無救援必 None（黏連爆閘），

    開救援後 V-submask 二次分割必須救回環中心。"""
    scene, center, tmpl = _h057_wall_scene(with_frame=True)
    kw = dict(shape_templates={"ring": tmpl}, shape_threshold=0.42, shape_hard_floor=0.30,
              shape_scales=(0.7, 1.0, 1.4), shape_roi_px=320, margin_frac=0.02)
    assert find_tracker(scene, **kw) is None, "黏連未救援時本應漏掉（爆 area/bbox 閘）"
    loc = find_tracker(scene, rescue_v_min=150, rescue_area_min=120, **kw)
    assert loc is not None, "救援應在爆閘輪廓 bbox 內二次分割救回真框"
    assert abs(loc[0] - center[0]) <= 20 and abs(loc[1] - center[1]) <= 20, f"應命中 {center}，實得 {loc}"


def test_h057_rescue_wall_without_frame_stays_none():
    """救援負樣本（合成）：純受光綠牆（V=75 < 救援門檻 150）→ 開救援也不得生出候選。"""
    scene, _, tmpl = _h057_wall_scene(with_frame=False)
    loc = find_tracker(scene, shape_templates={"ring": tmpl}, shape_threshold=0.42,
                       shape_hard_floor=0.30, shape_scales=(0.7, 1.0, 1.4),
                       shape_roi_px=320, margin_frac=0.02,
                       rescue_v_min=150, rescue_area_min=120)
    assert loc is None


def test_h057_rescue_no_false_positive_on_equipment_scene():
    """救援負樣本（實機）：069_dir5 紅緞帶裝備場景。救援會從爆閘輪廓分出裝備碎片

    （實測 edge 0.26~0.34），但全數必須被形狀門檻 0.42 hard_rej——結果仍 None。"""
    img_path = "assets/red_ribbon_equipment_scene.png"
    tmpls = _load_real_markers_h057()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    loc = find_tracker(img, **_h057_kwargs(tmpls))
    assert loc is None, f"裝備碎片（edge≤0.34）不得因救援翻盤為追蹤框，實得 {loc}"


# ---- H068（2026-07-31，harvest 129/133/141 玩家標註）：框被角色/裝備擋角 ----
# edge 掉到 0.33~0.41 卡在 shape_threshold 0.42 下方 → 八方位全空誤交人工。
# 玩家在網頁標註工具把這些幀標成 false_negative，離線重放量出兩側：
#   真框（被拒）edge/colored = 0.33/0.86、0.36/0.86 ×3、0.40/0.86、0.41/0.86、0.36/1.00
#   誤收側 colored≥0.80 群 edge 最高 0.33（H026 粉紅岩層 colored=1.00），其餘 ≤0.31
# → 二維軟收 edge≥0.35 且 colored≥0.80（岩層之上留 0.02）。0.33 那顆真框救不回，記 D09。
# 礦石面板文字 0.86/0.33 也在附近，靠 ore_panel_region 結構性排除而不是靠門檻。


def _h068_kwargs(tmpls):
    """production 同款參數（含 H068 軟收與 ore_panel_region 排除）。"""
    from miningbot.config import DEFAULT as cfg
    return dict(
        exclude=[(r.x, r.y, r.x + r.w, r.y + r.h)
                 for r in (cfg.chat_region, cfg.ore_panel_region)],
        margin_frac=cfg.tracker_margin_frac,
        shape_templates=tmpls,
        shape_threshold=cfg.tracker_shape_threshold,
        shape_hard_floor=cfg.tracker_shape_hard_floor,
        shape_soft_edge=cfg.tracker_shape_soft_edge,
        shape_soft_colored=cfg.tracker_shape_soft_colored,
        shape_scales=cfg.tracker_shape_scales,
        shape_roi_px=cfg.tracker_shape_roi_px,
        rescue_v_min=cfg.tracker_rescue_v_min,
        rescue_area_min=cfg.tracker_rescue_area_min,
        rescue_max=cfg.tracker_rescue_max_candidates,
        rescue_dedup_px=cfg.tracker_rescue_dedup_px)


def test_h068_avatar_occluded_tracker_is_found():
    """真實資料：h068_avatar_occluded_tracker.png（harvest 129 sweep dir4，20:07:45）。

    真框 (937,458) edge=0.36 colored=0.86（框壓在角色頭頂、外框被擋掉一角）；
    同幀最強誤收候選 (1054,655) edge=0.30 colored=0.87 必須留在門檻外。
    關掉軟收（shape_soft_edge=1.0）這張就回 None——事故當下正是如此。"""
    img_path = "tests/fixtures/tracker/h068_avatar_occluded_tracker.png"
    tmpls = _load_real_markers_h057()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    loc = find_tracker(img, **_h068_kwargs(tmpls))
    assert loc is not None, "129 dir4 真框 (937,458) 應被偵測到（H068 事故根因）"
    assert abs(loc[0] - 937) <= 20 and abs(loc[1] - 458) <= 20, f"應命中真框 (937,458)，實得 {loc}"


def test_h068_panel_text_never_beats_tracker():
    """真實資料：h068_panel_vs_tracker.png（harvest 141 sweep up dir6，02:31:39）。

    同幀三個 0.33~0.36 的候選：真框 (1396,815) colored=1.00、裝備 (1375,719)
    colored=0.56、NORMAL 面板文字 (70,869) colored=0.86。面板那顆兩軸都過軟收門檻，
    只能靠 ore_panel_region 排除——所以這張同時守「軟收收得回真框」與「面板不得翻盤」。"""
    img_path = "tests/fixtures/tracker/h068_panel_vs_tracker.png"
    tmpls = _load_real_markers_h057()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    loc = find_tracker(img, **_h068_kwargs(tmpls))
    assert loc is not None, "141 up dir6 真框 (1396,815) 應被偵測到"
    assert abs(loc[0] - 1396) <= 20 and abs(loc[1] - 815) <= 20, f"應命中真框，實得 {loc}"
    assert loc[0] > 240, f"不得命中左側 NORMAL 面板文字，實得 {loc}"


def test_h068_soft_path_does_not_admit_equipment_scene():
    """軟收負樣本（實機）：069_dir5 紅緞帶裝備場景。裝備碎片最高 edge=0.29

    （colored 0.88），低於軟收 edge 門檻 0.35 → 開了軟收仍必須是 None。
    誤收側的另一半在 test_find_tracker_bottom_edge_scene_h026_...：H026 場景的粉紅
    岩層 colored=1.00 edge=0.33，是目前量到最高的誤收值，0.35 就是壓著它訂的。"""
    img_path = "assets/red_ribbon_equipment_scene.png"
    tmpls = _load_real_markers_h057()
    if not (os.path.exists(img_path) and tmpls):
        import pytest; pytest.skip("缺實機圖/模板")
    img = cv2.imread(img_path)
    loc = find_tracker(img, **_h068_kwargs(tmpls))
    assert loc is None, f"裝備碎片（edge≤0.29）不得被軟收路徑翻盤，實得 {loc}"


def test_h068_ore_panel_region_covers_panel_text_but_not_world():
    """ore_panel_region 兩側夾：必須蓋住量到的面板候選 (70,869)、(80,509)、(121,619)，

    且不得吃到同幀真框 (1396,815)、(979,550)。"""
    from miningbot.config import DEFAULT as cfg
    r = cfg.ore_panel_region
    inside = lambda p: r.x <= p[0] <= r.x + r.w and r.y <= p[1] <= r.y + r.h
    for p in [(70, 869), (80, 509), (121, 619)]:
        assert inside(p), f"面板文字候選 {p} 應被排除區蓋住"
    for p in [(1396, 815), (937, 458), (1433, 491)]:
        assert not inside(p), f"真框 {p} 不得落進排除區"


# ── banner_text_hue：chill banner 色相取樣（double-chill 偵測，2026-08-02）─────

def _banner_with_text(text_bgr, bg_bgr=(18, 18, 18), h=22, w=200):
    """合成 banner 圖：暗底＋指定顏色的文字像素條。"""
    img = np.full((h, w, 3), bg_bgr, np.uint8)
    # 在中間畫一條「文字」色帶（模擬有色文字）
    img[6:16, 40:160] = text_bgr
    return img


def test_banner_text_hue_returns_none_for_dark_background():
    """純暗底（無高飽和文字）→ None。"""
    img = np.full((22, 200, 3), (18, 18, 18), np.uint8)
    assert banner_text_hue(img) is None


def test_banner_text_hue_extracts_green_text_hue():
    """綠色文字 (BGR 0,255,0 → OpenCV HSV H≈60) → 回傳 ≈60。"""
    img = _banner_with_text((0, 255, 0))
    hue = banner_text_hue(img)
    assert hue is not None
    assert 55 <= hue <= 65  # OpenCV H=60 ±容差


def test_banner_text_hue_distinguishes_red_and_blue():
    """紅色 (H≈0) vs 藍色 (H≈120) 文字色相不同——double chill 偵測的基礎。"""
    red_hue = banner_text_hue(_banner_with_text((0, 0, 255)))    # BGR red
    blue_hue = banner_text_hue(_banner_with_text((255, 0, 0)))   # BGR blue
    assert red_hue is not None and blue_hue is not None
    diff = abs(red_hue - blue_hue)
    diff = min(diff, 180 - diff)
    assert diff > 30, f"紅藍色相差應 >30°（OpenCV 制），實得 Δ{diff}"


def test_banner_text_hue_few_pixels_returns_none():
    """文字像素少於 pixel_min → None（避免雜訊偽陽性）。"""
    img = np.full((22, 200, 3), (18, 18, 18), np.uint8)
    img[10, 100] = (0, 255, 0)  # 只有一個像素
    assert banner_text_hue(img, pixel_min=20) is None
