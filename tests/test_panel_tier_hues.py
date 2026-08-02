"""面板列底色的階級色相回歸（2026-08-02 實機素材，D13）。

`TIER_HUES` 的值先前有兩階（Unfathomable／Otherworldly）只有 wiki 色碼、沒有
實機佐證，但註釋表把它們與真正量到的並排、都標「實機 Δ≤1°」——看起來像八階全
驗過。這批 fixture 補上實機證據，並把「固定取樣協議」釘死：

固定窗 cfg.panel_hue_sample_x + 逐列中位（不用平均）。首次量測用環形平均得
Unfathomable 227.4°（差 8.4°，看起來像表值錯了），實際是被紅色礦名的抗鋸齒像素
污染；逐列中位是 220.0°。量測方式本身就是結論的一部分，故一併測。

素材與 ground truth：tests/fixtures/panel_tiers/。
"""
import json
import os

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import game_data, harvester, vision  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "panel_tiers")
HUE_TOL_DEG = 1.5          # 實機 vs 表值容差（量到的最大偏差是 1.0°）


def _ground_truth():
    with open(os.path.join(FIXTURES, "ground_truth.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _panel_crop(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    r = cfg.ore_panel_region
    return img[r.y:r.y + r.h, r.x:r.x + r.w]


def _band_hue(crop, y0, y1):
    """固定取樣協議：固定窗 + 逐列中位 → 跨列中位（見 fixtures README）。

    灰階列（Common／Layer，S=0）沒有任何飽和像素——不能當成「取不到底色」而
    跳過，那會讓整條帶從量測結果裡消失（盲區）。灰階的 H 本來就無意義，
    production 的 `panel_row_hues` 對它們也是回 0.0，這裡照做。
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    x0, x1 = cfg.panel_hue_sample_x
    rows = []
    for y in range(y0, y1 + 1):
        strip = hsv[y, x0:x1]
        m = strip[:, 1] > 60                    # 濾文字邊緣（灰階列會整列落空）
        if m.sum() >= 20:
            rows.append(float(np.median(strip[m, 0])) * 2)
    if rows:
        return float(np.median(rows))
    # 整條帶都沒有飽和像素 → 灰階列。確認確實是灰（而不是裁錯位置）再回 0.0。
    sat = float(np.median(hsv[y0:y1 + 1, x0:x1, 1]))
    assert sat <= 30, f"y {y0}-{y1} 取不到底色像素，但也不是灰階（S={sat:.0f}）"
    return 0.0


def _all_bands():
    for frame in _ground_truth()["frames"]:
        for band in frame["bands"]:
            yield frame["file"], band


@pytest.mark.parametrize("fname,band", list(_all_bands()),
                         ids=lambda v: v["tier"] if isinstance(v, dict) else None)
def test_measured_hue_matches_ground_truth(fname, band):
    """每條帶量到的色相＝ground truth 記的值。"""
    crop = _panel_crop(fname)
    y0, y1 = band["y"]
    got = _band_hue(crop, y0, y1)
    want = band["hue"]
    d = min(abs(got - want), 360 - abs(got - want))
    assert d <= HUE_TOL_DEG, (
        f'{band["tier"]} 於 {fname} y{y0}-{y1}：量到 {got:.1f}°、'
        f'ground truth {want}°，差 {d:.1f}°')


@pytest.mark.parametrize("fname,band", list(_all_bands()),
                         ids=lambda v: v["tier"] if isinstance(v, dict) else None)
def test_high_tier_hues_match_tier_hues_table(fname, band):
    """HIGH_TIERS 的實機色相＝TIER_HUES 表值；LOW_TIERS 不得出現在表裡。

    LOW 那半是有意義的：Mythic 304／Surreal 166／Master 280 若混進 TIER_HUES，
    零點閘會把它們當高階，面板永遠不成立零點。
    """
    tier = band["tier"]
    if band.get("low_tier"):
        assert tier not in game_data.TIER_HUES, (
            f"{tier} 是低階（排除清單），不該出現在 TIER_HUES")
        return
    assert tier in game_data.TIER_HUES, f"{tier} 缺在 TIER_HUES"
    crop = _panel_crop(fname)
    got = _band_hue(crop, *band["y"])
    want = game_data.TIER_HUES[tier]
    d = min(abs(got - want), 360 - abs(got - want))
    assert d <= HUE_TOL_DEG, (
        f"{tier}：實機 {got:.1f}° vs TIER_HUES {want}°，差 {d:.1f}°")


def test_whitelist_gate_accepts_every_high_tier_band():
    """白名單色相閘對每條高階帶都必須命中——這是面板色檢的實際判定路徑。"""
    missed = []
    for fname, band in _all_bands():
        if band.get("low_tier"):
            continue
        got = _band_hue(_panel_crop(fname), *band["y"])
        if not harvester.whitelist_hue_hits([got], cfg.panel_whitelist_hues,
                                            cfg.panel_hue_tol_deg):
            missed.append(f'{band["tier"]}({got:.0f}°)')
    assert not missed, f"白名單色相閘漏掉高階帶: {'、'.join(missed)}"


def test_low_tier_bands_are_not_counted_as_high():
    """低階帶不得被反向閘當成高階——會讓面板零點永遠不成立。"""
    wrong = []
    for fname, band in _all_bands():
        if not band.get("low_tier"):
            continue
        got = _band_hue(_panel_crop(fname), *band["y"])
        if harvester.non_low_tier_hues([got], cfg.panel_low_tier_hues,
                                       cfg.panel_hue_tol_deg):
            wrong.append(f'{band["tier"]}({got:.0f}°)')
    assert not wrong, f"低階帶被當成高階: {'、'.join(wrong)}"


def test_grey_rows_are_not_mistaken_for_high_tier():
    """灰階列（Common／Layer，S=0）不得擋零點，也不得算稀有。

    H 對灰階無意義（panel_row_hues 回 0.0）。現行判定正確是因為 0.0 也在
    panel_low_tier_hues 裡——這條測試釘住那個結果，低階帶若被改動就紅燈。
    """
    crop = _panel_crop("tiers_grey_lowtier_20260802.png")
    row_ys = [308, 344, 380, 416, 452]          # Glass/Orglass/Bass/Foligrass/Frosted Grass
    hues = vision.panel_row_hues(crop, row_ys, *cfg.panel_hue_sample_x)
    assert harvester.non_low_tier_hues(hues, cfg.panel_low_tier_hues,
                                       cfg.panel_hue_tol_deg) == [], \
        "灰階列被當成高階 → 面板零點永遠不成立"
    assert harvester.whitelist_hue_hits(hues, cfg.panel_whitelist_hues,
                                        cfg.panel_hue_tol_deg) == [], \
        "灰階列被算成稀有礦"


def test_two_grey_tiers_are_separable_by_value():
    """Common 與 Layer 只差亮度——若將來要分辨它們，V 是唯一的軸。

    在色帶起點 x=18 量：Common V=192（wiki C1C1C1=193）、Layer V=132。
    現行程式不分辨這兩者（都是低階，無需分辨），這條測試守的是「素材裡確實
    有兩種可分的灰」，避免將來有人以為灰階只有一種。
    """
    crop = _panel_crop("tiers_grey_lowtier_20260802.png")
    common = float(np.median(crop[295:322, 18:20]))     # Glass
    layer = float(np.median(crop[403:430, 18:20]))      # Foligrass
    assert abs(common - 193) <= 3, f"Common 該是 wiki C1C1C1≈193，量到 {common}"
    assert common - layer > 40, f"兩種灰該分得開：Common {common} vs Layer {layer}"


@pytest.mark.parametrize("fname,band", list(_all_bands()),
                         ids=lambda v: v["tier"] if isinstance(v, dict) else None)
def test_band_origin_x18_equals_wiki_colour(fname, band):
    """色帶起點 x=18 ＝ wiki 官方色（漸層由此往右衰減）。

    這是將來要加 S/V 判據時的錨點：現行取樣窗 (120,165) 的 V 已衰減到原色
    ~55%，量到的絕對值沒有跨階級可比性，x=18 有。
    """
    wiki = _ground_truth()["band_origin"]["verified_tiers"].get(band["tier"])
    if wiki is None:
        pytest.skip(f'{band["tier"]} 無 wiki 色碼')
    crop = _panel_crop(fname)
    y0, y1 = band["y"]
    got = np.median(crop[y0 + 4:y1 - 4, 18:20].reshape(-1, 3), axis=0)
    r, g, b = (int(wiki[i:i + 2], 16) for i in (0, 2, 4))
    want = np.array([b, g, r], dtype=float)
    delta = np.abs(got - want).max()
    assert delta <= 3, (
        f'{band["tier"]}：x=18 量到 BGR {got.astype(int)}、'
        f'wiki {wiki} = {want.astype(int)}，最大差 {delta:.0f}')


def test_measure_tool_identifies_every_ground_truth_band():
    """`miningbot.measure_tier_hues` 對三張 fixture 的每條帶都要認出正確階級。

    工具是使用者持續補階級時的入口（`uv run python -m miningbot.measure_tier_hues`），
    它報錯階級比沒有工具更糟——會把「量到的」寫進 TIER_HUES。這條把它自己也納入
    迴歸：自動切帶 + 命名，兩者任一退步就紅燈。
    """
    from miningbot import measure_tier_hues as mt

    for frame in _ground_truth()["frames"]:
        crop = _panel_crop(frame["file"])
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        x0, x1 = cfg.panel_hue_sample_x
        found = {}
        for y0, y1 in mt.detect_bands(hsv, x0, x1):
            if y1 < cfg.panel_row_min_y:
                continue                        # 標頭／篩選框，不是礦列
            r = mt.band_hue(hsv, y0, y1, x0, x1)
            if r is None:
                continue
            h, s, _v, _n = r
            bgr = mt.origin_bgr(crop, y0, y1)
            if s <= mt.GREY_SAT_MAX:            # 灰階：只能用 x=18 的未衰減亮度
                for t, gv in mt.GREY_TIER_VALUES.items():
                    if abs(int(bgr[0]) - gv) <= mt.GREY_TIER_TOL:
                        found[t] = h
            else:
                tier, d, _low = mt.nearest_tier(h)
                if d <= 1.5:
                    found[tier] = h
        want = {b["tier"] for b in frame["bands"]}
        assert want <= set(found), (
            f'{frame["file"]}：工具沒認出 {want - set(found)}（認出的是 {sorted(found)}）')


def test_hue_is_stable_across_the_horizontal_gradient():
    """漸層只在 V 上，H 沿列恆定（使用者 2026-08-02 疑慮的實測答案）。

    這條測試守的是「取樣位置不影響階級判定」這個前提——一旦遊戲改成連 H 也漸層，
    固定窗就不夠了，必須在這裡紅燈而不是等實機誤判。
    """
    crop = _panel_crop("tiers_high4_20260802.png")
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    y0, y1 = 402, 678                        # Transcendent 帶（最厚）
    hues, vals = [], []
    for x in range(20, 212, 8):
        col = hsv[y0:y1, x:x + 4].reshape(-1, 3)
        m = col[:, 1] > 60
        if m.sum() < 50:
            continue
        hues.append(float(np.median(col[m, 0])) * 2)
        vals.append(float(np.median(col[m, 2])))
    assert max(hues) - min(hues) <= 1.0, (
        f"H 沿水平方向不該漂：{min(hues):.1f}-{max(hues):.1f}")
    assert max(vals) - min(vals) > 100, (
        "V 的漸層應該很明顯（沒有就是素材或裁切換了，這條測試的前提要重驗）")
