"""fetch_layers 的純解析器（不連網；wikitext 片段取自 2026-07-22 實際頁面）。

這些片段各自代表一個踩過的坑，改解析時不要簡化掉：同頁多層（Outer/Inner Core）、
同層多世界（Jollystone）、無固定深度（Frost）、顯示名大小寫筆誤（rocc）。
"""
from miningbot import fetch_layers


# ── parse_layer_links ───────────────────────────────────────────────────
def test_display_name_wins_when_one_page_serves_two_layers():
    """World 1 的 Core 是兩個不同的層共用同一頁——只看頁名會少一層並取錯深度。"""
    wt = ("|layers = [[Mantle Layer|Mantle]]<br>[[Core Layer|Outer Core]]"
          "<br>[[Core Layer|Inner Core]]")
    assert fetch_layers.parse_layer_links(wt) == [
        ("Mantle Layer", "Mantle"),
        ("Core Layer", "Outer Core"),
        ("Core Layer", "Inner Core"),
    ]


def test_case_only_mismatch_falls_back_to_page_name():
    """Subworld 1 的 `[[Rocc Layer|rocc]]` 是 wiki 筆誤（該頁本文皆為 Rocc）。"""
    assert fetch_layers.parse_layer_links("|layers = [[Rocc Layer|rocc]]") == [
        ("Rocc Layer", "Rocc")]


def test_link_without_pipe_strips_layer_suffix():
    assert fetch_layers.parse_layer_links("|layers = [[Shamrock Layer]]") == [
        ("Shamrock Layer", "Shamrock")]


def test_missing_layers_field_yields_empty():
    assert fetch_layers.parse_layer_links("|ores = 375") == []


# ── parse_depth_for ─────────────────────────────────────────────────────
SHAMROCK = ("{{LayerInfobox|depth = 7000m-7999m}}\n==Introduction==\n"
            "The '''Shamrock Layer''' is the eighth layer in [[Lucernia]], "
            "spanning from 7000m – 7999m in the mine. The Shamrock Layer has 32 ores.")


def test_intro_sentence_gives_range_and_evidence():
    lo, hi, why = fetch_layers.parse_depth_for(SHAMROCK, "Shamrock", "Lucernia")
    assert (lo, hi) == (7000, 7999)
    assert "eighth layer in Lucernia" in why      # 依據原文留著供人工覆核


def test_intro_sentence_disambiguates_two_layers_on_one_page():
    """同頁兩層時，只有點名該層＋該世界的句子能區分；infobox 兩段無從對應。"""
    core = ("{{LayerInfobox|depth = 7000m-7499m}}{{LayerInfobox|depth = 7500m-7999m}}\n"
            "The Outer Core Layer is the second-last layer in World 1, and found "
            "through 7000m – 7499m. "
            "The Inner Core Layer is the last layer in World 1, spanning from "
            "7500m – 7999m.")
    assert fetch_layers.parse_depth_for(core, "Outer Core", "World 1")[:2] == (7000, 7499)
    assert fetch_layers.parse_depth_for(core, "Inner Core", "World 1")[:2] == (7500, 7999)


def test_multi_world_infobox_picks_the_requested_world():
    """Jollystone 並列兩個世界的深度；抓錯段會把 Aesteria 記成 1000-1999。"""
    wt = ("{{LayerInfobox\n|depth = 1000m – 1999m ([[Wintera Isle]])<br>"
          "5000m – 5999m ([[Aesteria]])\n}}\nNo qualifying sentence here.")
    assert fetch_layers.parse_depth_for(wt, "Jollystone", "Aesteria")[:2] == (5000, 5999)


def test_variable_depth_layer_reports_no_range():
    wt = "{{LayerInfobox\n|depth = Variable\n}}\nThe Frost Layer is a special layer."
    lo, hi, why = fetch_layers.parse_depth_for(wt, "Frost", "Aesteria")
    assert (lo, hi) == (None, None)
    assert "Variable" in why


def test_sentence_for_another_world_is_not_borrowed():
    """句子點名的是別的世界時不得採用——這是同名層跨世界污染的入口。"""
    lo, hi, _ = fetch_layers.parse_depth_for(
        "The Jollystone Layer is the second layer in Wintera Isle, spanning from "
        "1000m – 1999m.", "Jollystone", "Aesteria")
    assert (lo, hi) == (None, None)


# ── diff_world ──────────────────────────────────────────────────────────
def test_diff_clean_when_matching_game_data():
    from miningbot import game_data
    rows = list(game_data.LAYER_DEPTHS["Lucernia"])
    assert fetch_layers.diff_world("Lucernia", rows) == []


def test_diff_reports_changed_and_missing_layers():
    from miningbot import game_data
    rows = [(n, lo, hi) for n, lo, hi in game_data.LAYER_DEPTHS["Lucernia"]
            if n != "Harmonine"]
    rows = [("Shamrock", 7000, 7500) if n == "Shamrock" else (n, lo, hi)
            for n, lo, hi in rows]
    out = fetch_layers.diff_world("Lucernia", rows)
    assert any("Shamrock" in line and "不一致" in line for line in out)
    assert any("Harmonine" in line for line in out)


def test_diff_does_not_nag_about_variable_depth_layers():
    """Frost 本來就不在表裡也不會被 wiki 抓到，不該每次都報缺。"""
    from miningbot import game_data
    rows = list(game_data.LAYER_DEPTHS["Aesteria"])
    assert fetch_layers.diff_world("Aesteria", rows) == []
