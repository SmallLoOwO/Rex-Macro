"""roblox_menu 純決策模組單元測試（TDD）。

設計：docs/superpowers/specs/2026-07-08-menu-preflight-boost-design.md 第 1 節。
所有函式只吃/回資料（OCR 文字框列表、字串），不碰螢幕/鍵鼠——比照 reentry.py 的
「決策純函式＋I/O 在 Bot」慣例。「嚴格贏過其他選項」的模糊比對精神抄
reentry.pick_layer_button（寧漏勿誤：分不清就不判定為命中）。
"""
import os
import pytest
from miningbot import roblox_menu

MOVEMENT_MODES = ("Default (Keyboard)", "Keyboard + Mouse", "Click to Move")


def _rec(text, center):
    return {"text": text, "score": 0.9, "center": center}


TAB_ROW = [
    _rec("People", (576, 156)),
    _rec("Settings", (774, 156)),
    _rec("Gallery", (976, 156)),
    _rec("Report", (1179, 156)),
    _rec("Help", (1378, 156)),
]

MOVEMENT_ROW_RECS = [
    _rec("Camera Sensitivity", (579, 441)),
    _rec("Movement Mode", (571, 503)),
    _rec("Default (Keyboard)", (1153, 503)),
    _rec("Shift Lock Switch", (571, 565)),
    _rec("On", (1155, 566)),
]


class TestMenuOpen:
    def test_true_when_tab_labels_visible(self):
        assert roblox_menu.menu_open(TAB_ROW, 0.7) is True

    def test_false_when_no_tab_labels(self):
        recs = [_rec("Cloverstone 204", (80, 470))]
        assert roblox_menu.menu_open(recs, 0.7) is False

    def test_false_on_empty_records(self):
        assert roblox_menu.menu_open([], 0.7) is False


class TestFindTabCenter:
    def test_exact_hit(self):
        assert roblox_menu.find_tab_center(TAB_ROW, "Settings", 0.7) == (774, 156)

    def test_ocr_noise_still_hits(self):
        # 遊戲字型 i/l 同形（比照 H033）：Settlngs 仍應命中
        recs = [_rec("Settlngs", (774, 156))]
        assert roblox_menu.find_tab_center(recs, "Settings", 0.7) == (774, 156)

    def test_no_match_returns_none(self):
        recs = [_rec("People", (576, 156))]
        assert roblox_menu.find_tab_center(recs, "Settings", 0.7) is None


class TestFindLabelRowY:
    def test_hits_movement_mode(self):
        assert roblox_menu.find_label_row_y(MOVEMENT_ROW_RECS, "Movement Mode", 0.7) == 503

    def test_none_when_absent(self):
        recs = [_rec("Shift Lock Switch", (571, 565))]
        assert roblox_menu.find_label_row_y(recs, "Movement Mode", 0.7) is None


class TestReadRowValue:
    def test_hits_same_row_value_column(self):
        v = roblox_menu.read_row_value(MOVEMENT_ROW_RECS, 503, (1000, 1350), 18)
        assert v == "Default (Keyboard)"

    def test_ignores_other_rows(self):
        v = roblox_menu.read_row_value(MOVEMENT_ROW_RECS, 503, (1000, 1350), 18)
        assert v != "On"          # "On" 屬於 Shift Lock Switch 那列(y=566)，不該被讀到

    def test_none_when_row_has_no_value_in_range(self):
        recs = [_rec("Movement Mode", (571, 503))]
        assert roblox_menu.read_row_value(recs, 503, (1000, 1350), 18) is None

    def test_y_tolerance_respected(self):
        recs = [_rec("Movement Mode", (571, 503)), _rec("Default (Keyboard)", (1153, 530))]
        # 差 27px，超過容差 18 → 不該算同列
        assert roblox_menu.read_row_value(recs, 503, (1000, 1350), 18) is None


class TestValueMatchesTarget:
    OTHERS_FOR_DEFAULT = ("Keyboard + Mouse", "Click to Move")

    def test_exact_match(self):
        assert roblox_menu.value_matches_target(
            "Default (Keyboard)", "Default (Keyboard)", self.OTHERS_FOR_DEFAULT, 0.6) is True

    def test_ocr_noise_still_hits(self):
        assert roblox_menu.value_matches_target(
            "Defauit (Keyboard)", "Default (Keyboard)", self.OTHERS_FOR_DEFAULT, 0.6) is True

    def test_wrong_value_is_false(self):
        assert roblox_menu.value_matches_target(
            "Keyboard + Mouse", "Click to Move",
            ("Default (Keyboard)", "Click to Move"), 0.6) is False

    def test_ambiguous_returns_false(self):
        # 對 target 與 other 分數打平/都低 → 分不清，不判命中（寧漏勿誤）
        assert roblox_menu.value_matches_target(
            "Mode", "Keyboard + Mouse", self.OTHERS_FOR_DEFAULT, 0.6) is False


# ---------- 實機截圖回歸（Settings 選單截圖，鎖住整條「OCR框→找列→讀值」） ----------
# fixtures 2026-07-28 於**全螢幕版面**重拍（原 2026-07-08 拍於視窗化最大化）：裁圖＝
# cfg.menu_panel_region 那塊，偏移一律用 cfg 取，不再寫死 (460,130)——版面一改就對不上。

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402
from miningbot import ocr  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "menu")


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


rapid_skip = pytest.mark.skipif(not ocr.rapidocr_available(), reason="rapidocr 未安裝")


def _panel_offset():
    from miningbot.config import DEFAULT as cfg
    return (cfg.menu_panel_region.x, cfg.menu_panel_region.y)


@rapid_skip
@pytest.mark.fixture
@pytest.mark.ocr
def test_real_screenshot_default_keyboard_detected():
    img = _load("mm_cycle0.png")
    recs = ocr.read_text_boxes(img, region_offset=_panel_offset())
    row_y = roblox_menu.find_label_row_y(recs, "Movement Mode", 0.7)
    assert row_y is not None
    value = roblox_menu.read_row_value(recs, row_y, (1000, 1350), 18)
    assert roblox_menu.value_matches_target(
        value, "Default (Keyboard)", ("Keyboard + Mouse", "Click to Move"), 0.6) is True


@rapid_skip
@pytest.mark.fixture
@pytest.mark.ocr
def test_real_screenshot_keyboard_mouse_detected_and_not_confused_with_default():
    img = _load("mm_cycle1.png")
    recs = ocr.read_text_boxes(img, region_offset=_panel_offset())
    row_y = roblox_menu.find_label_row_y(recs, "Movement Mode", 0.7)
    assert row_y is not None
    value = roblox_menu.read_row_value(recs, row_y, (1000, 1350), 18)
    assert roblox_menu.value_matches_target(
        value, "Keyboard + Mouse", ("Default (Keyboard)", "Click to Move"), 0.6) is True
    assert roblox_menu.value_matches_target(
        value, "Default (Keyboard)", ("Keyboard + Mouse", "Click to Move"), 0.6) is False


@rapid_skip
@pytest.mark.fixture
@pytest.mark.ocr
def test_fixed_roi_recognition_only_reads_movement_mode_row():
    from miningbot.config import DEFAULT as cfg

    for name, expected in (
        ("mm_cycle0.png", "Default (Keyboard)"),
        ("mm_cycle1.png", "Keyboard + Mouse"),
    ):
        img = _load(name)
        panel = cfg.menu_panel_region

        def panel_crop(region):
            x0, y0 = region.x - panel.x, region.y - panel.y
            return img[y0:y0 + region.h, x0:x0 + region.w]

        label = ocr.read_text_line(panel_crop(cfg.menu_movement_label_region), engine="rapidocr")
        value = ocr.read_text_line(panel_crop(cfg.menu_movement_value_region), engine="rapidocr")

        assert roblox_menu.text_matches_label(label, "Movement Mode", 0.6)
        assert roblox_menu.find_matching_option(value, cfg.movement_mode_options, 0.6) == expected
