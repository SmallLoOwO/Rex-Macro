"""NORMAL 面板名字欄剖析：對實機裁圖跑完整 RapidOCR 管線（spec 2026-07-30 救援設計）。

`tests/test_harvester.py` 用合成 box 測剖析規則；本檔測的是**真的 OCR 出得來嗎**——
黏框位置、craft 面板遮擋、幾何閘的取值，只有實機幀能反駁。

素材：harvest 125（2026-07-29 15:29:34）交人工前後的 `backpack_review_region` 裁圖。
那一輪聊天最底行是 `small_lo has found Faedrine`、面板上也有 Faedrine，三層八方位
全空仍交了人工——救援要救的正是這一型。兩張相隔 7 秒、內容相同（採集期間 bot 已停止
挖礦），所以它同時是「完全沒變 → 不得判定進帳」的迴歸。

需要 rapidocr（`read_text_boxes` 唯一路徑，不做 tesseract 後備）；不可用時整檔 skip。
"""
import os

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import harvester, ocr  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "panel")

pytestmark = pytest.mark.skipif(not ocr.rapidocr_available(),
                                reason="rapidocr 引擎不可用")


def _load(name):
    # CJK 路徑下 cv2.imread 靜默失敗 → 一律走 np.fromfile + imdecode
    path = os.path.join(FIXTURES, name)
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def _names(name):
    return harvester.parse_panel_ore_names(
        ocr.read_text_boxes(_load(name)),
        cfg.panel_name_col_max_x, cfg.panel_row_min_y)


@pytest.fixture(scope="module")
def before_names():
    return _names("125_giveup_before_backpack.png")


def test_fixture_crop_matches_configured_region():
    """裁圖尺寸必須等於 backpack_review_region——幾何閘的取值以此為座標系。"""
    img = _load("125_giveup_before_backpack.png")
    assert img.shape[:2] == (cfg.backpack_review_region.h, cfg.backpack_review_region.w)


def test_reads_all_six_visible_ore_names(before_names):
    """六列礦名全數讀出（含兩列與數字黏成同一框的）。"""
    assert before_names == ["leprechaun", "faedrine", "cleavelite", "siogyne",
                            "weevil", "cloverstone", "plentium", "imbollyx"]


def test_ui_chrome_and_craft_panel_never_become_ore_names(before_names):
    """NORMAL 標頭、www 篩選框、右側 Shamrock craft 面板都不得混進名字集合。

    www 是**篩選文字框**不是 placeholder（打非匹配字串＝清空面板）；bot 不碰它，
    但它絕不能被當成一個礦名。
    """
    assert not {"normal", "www", "sh", "mat"} & set(before_names)
    assert all(not any(ch.isdigit() for ch in n) for n in before_names)


def test_faedrine_is_the_rescue_signal(before_names):
    """125 的關鍵證據：Faedrine 在面板上、且落在高階白名單（Exquisite）。"""
    from miningbot import game_data
    assert "faedrine" in before_names
    assert game_data.classify_found_ore("faedrine")[0] == "rare"
    assert harvester.rare_panel_ores(before_names) == ["leprechaun", "faedrine"]


def test_after_panel_has_same_whitelist_ores(before_names):
    """前後兩張內容相同 → 白名單存在性檢查照樣讀到 Faedrine。"""
    after = _names("125_giveup_after_backpack.png")
    assert harvester.rare_panel_ores(after) == ["leprechaun", "faedrine"]


def test_h069_live_panel_has_no_whitelist_ores():
    """H069 實錄（2026-07-31 harvest 145）：整排全是鎬子挖到的低階礦 → 白名單回空。

    舊版判準「非 common」讓 unknown（sugarmuck/cloverstone）＋被 `Eg` 前綴誤配的
    egguinox 算成進帳，bot 不交人工，真稀有礦被放生。跑完整 OCR 管線：剖析或分類
    任一邊回歸都會讓它變紅。
    """
    from miningbot import game_data
    game_data.set_world("Lucernia")
    try:
        names = _names("145_rescue_cur_panel.png")
        assert "sugarmuck" in names                        # 素材沒讀歪才有資格斷言
        assert harvester.rare_panel_ores(names) == []
    finally:
        game_data.clear_world()
