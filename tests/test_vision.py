import os
import cv2
import numpy as np
from miningbot.vision import (find_template, template_present, find_template_edges,
                              find_tracker, find_tracker_near, find_marker, best_outline_score,
                              template_outline_edges, frames_differ)

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
