"""偵測階級門檻：實機快照回歸測試（H160, 2026-08-02）。

fixture：H160 的 panel_zero_failed 面板裁圖，含 leprechaun(Exquisite) + clovara(Exotic)。
這是「混合階級面板」——同時有門檻以上和以下的 礦，是 tier threshold 的兩側夾證據。

驗證三條路同步：
- 名字閘：門檻 Exquisite 時 clovara(Exotic) 從 rare_panel_ores 消失
- 救援色相閘：門檻 Exquisite 時 46°(Exotic) 從 whitelist_hue_hits 消失
- 零點色相閘：門檻 Exquisite 時 46°(Exotic) 不再擋零點（加入低階帶）
"""
import os

import cv2
import pytest

from miningbot import ocr, harvester, game_data, vision
from miningbot.config import DEFAULT as cfg

FIXTURE = os.path.join("tests", "fixtures", "panel",
                       "h160_leprechaun_exquisite_clovara_exotic.png")


@pytest.fixture(autouse=True)
def _reset_tier():
    game_data.set_detection_disabled_tiers(set())
    yield
    game_data.set_detection_disabled_tiers(set())


def _read_panel():
    """讀 fixture → (names, row_ys, hues)。"""
    img = cv2.imread(FIXTURE)
    assert img is not None, f"fixture 讀不到: {FIXTURE}"
    boxes = ocr.read_text_boxes(img)
    rows = harvester.parse_panel_rows(
        boxes, cfg.panel_name_col_max_x, cfg.panel_row_min_y,
        cfg.panel_name_min_letters)
    names = [n for n, _ in rows]
    row_ys = [cy for _, cy in rows]
    hues = vision.panel_row_hues(img, row_ys, *cfg.panel_hue_sample_x)
    return names, hues


def test_exotic_threshold_detects_both_exquisite_and_exotic():
    """門檻 Exotic（預設）→ leprechaun(Exq) + clovara(Exo) 都判 rare。"""
    game_data.set_detection_disabled_tiers(set())
    names, _ = _read_panel()
    rare = harvester.rare_panel_ores(names)
    assert "leprechaun" in rare, "leprechaun(Exquisite) 必須判 rare"
    assert "clovara" in rare, "clovara(Exotic) 必須判 rare（門檻 Exotic 不過濾）"


def test_exquisite_threshold_excludes_exotic_ore():
    """門檻 Exquisite → clovara(Exotic) 不在 rare_panel_ores，leprechaun(Exq) 仍在。"""
    game_data.set_detection_disabled_tiers({"Exotic"})
    names, _ = _read_panel()
    rare = harvester.rare_panel_ores(names)
    assert "leprechaun" in rare, "leprechaun(Exquisite) 必須仍判 rare"
    assert "clovara" not in rare, "clovara(Exotic) 必須被排除"


def test_exquisite_threshold_excludes_exotic_hue_from_whitelist():
    """門檻 Exquisite → 46°(Exotic) 不在 whitelist_hue_hits，128°(Exquisite) 仍在。"""
    game_data.set_detection_disabled_tiers({"Exotic"})
    _, hues = _read_panel()
    eff_wl = game_data.effective_whitelist_hues({"Exotic"}, cfg.panel_whitelist_hues)
    hits = harvester.whitelist_hue_hits(hues, eff_wl, cfg.panel_hue_tol_deg)
    hit_set = {round(h) for h in hits}
    assert 128 in hit_set, "128°(Exquisite) 必須命中白名單色相"
    assert 46 not in hit_set, "46°(Exotic) 不得命中白名單色相"


def test_exotic_threshold_exotic_hue_still_in_whitelist():
    """門檻 Exotic（預設）→ 46°(Exotic) 仍在 whitelist_hue_hits。"""
    game_data.set_detection_disabled_tiers(set())
    _, hues = _read_panel()
    eff_wl = game_data.effective_whitelist_hues(set(), cfg.panel_whitelist_hues)
    hits = harvester.whitelist_hue_hits(hues, eff_wl, cfg.panel_hue_tol_deg)
    hit_set = {round(h) for h in hits}
    assert 46 in hit_set, "46°(Exotic) 必須命中（門檻 Exotic 不過濾）"


def test_exquisite_threshold_exotic_hue_does_not_block_zero_point():
    """門檻 Exquisite → 46°(Exotic) 在低階帶裡，不擋零點；128°(Exq) 仍擋。"""
    game_data.set_detection_disabled_tiers({"Exotic"})
    _, hues = _read_panel()
    eff_low = game_data.effective_low_tier_hues({"Exotic"}, cfg.panel_low_tier_hues)
    blocked = harvester.non_low_tier_hues(hues, eff_low, cfg.panel_hue_tol_deg)
    block_set = {round(h) for h in blocked}
    # 128°(Exquisite) 不在低階帶 → 仍擋零點（面板有 Exquisite 礦）
    assert 128 in block_set, "128°(Exquisite) 應擋零點（面板有 Exquisite 礦）"
    # 46°(Exotic) 在低階帶（門檻以下） → 不擋零點
    assert 46 not in block_set, "46°(Exotic) 不該擋零點（已降級為低階）"
