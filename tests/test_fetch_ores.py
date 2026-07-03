"""fetch_ores 純解析邏輯測試（不打網路）。

wiki 世界頁的礦表是 tabber 分段的 MediaWiki 表格；解析器要處理：
- 一般列：|[[Diamantine]] \\n |{{Colour|Surreal}} \\n |100,000
- 帶連結別名：|[[Lucky Cave|Lucky]]
- rarity 帶註記：|877,699 (Cave Floors)
- 特殊礦名：Miles/egg、V1B3_C0R3、Heart.bit、Kardiá、Cracked Egg
"""
from miningbot.fetch_ores import parse_ore_rows, split_tiers, LOW_TIERS, HIGH_TIERS

SAMPLE = """
|-|
Amourite Layer =
{| class="recipe"
!Ore
!Tier
!Rarity
|-
|[[Amourite]]
|{{Colour|Layer}}
|0
|-
|[[Honestite]]
|{{Colour|Common}}
|700
|-
|[[Diamantine]]
|{{Colour|Surreal}}
|100,000
|-
|[[Dulcinette]]
|{{Colour|Mythic}}
|500,000
|-
|[[Saerylium]]
|{{Colour|Exotic}}
|3,000,000
|-
|[[Diamorite]]
|{{Colour|Exquisite}}
|12,000,000
|-
|[[Kardiá]]
|{{Colour|Transcendent}}
|45,000,000
|}
|-|
Cave Exclusives =
{| class="recipe"
!Ore
!Tier
!Rarity
!Cave
|-
|[[Beehive]]
|{{Colour|Mythic}}
|36,520 (Cave Ceilings)
|[[Floral Cave|Floral]]
|-
|[[Cl0ver]]
|{{Colour|Transcendent}}
|1,329,787
|[[Lucky Cave|Lucky]]
|}
"""


def test_parse_extracts_ore_tier_rarity_layer():
    rows = parse_ore_rows(SAMPLE)
    d = {r["ore"]: r for r in rows}
    assert d["Diamantine"] == {"ore": "Diamantine", "tier": "Surreal",
                               "rarity": 100_000, "layer": "Amourite"}
    assert d["Diamorite"]["tier"] == "Exquisite"
    assert d["Diamorite"]["rarity"] == 12_000_000


def test_parse_handles_cave_section_and_rarity_notes():
    rows = parse_ore_rows(SAMPLE)
    d = {r["ore"]: r for r in rows}
    # rarity 帶「(Cave Ceilings)」註記仍取得到數字；區段名當 layer
    assert d["Beehive"]["rarity"] == 36_520
    assert d["Beehive"]["layer"] == "Cave Exclusives"


def test_parse_handles_special_ore_names():
    rows = parse_ore_rows(SAMPLE)
    names = {r["ore"] for r in rows}
    assert {"Kardiá", "Cl0ver"} <= names


def test_parse_skips_layer_tier_rows():
    # Layer 階（圖層方塊本身）不是礦，不進清單
    assert all(r["tier"] != "Layer" for r in parse_ore_rows(SAMPLE))


def test_split_tiers_low_high():
    low, high = split_tiers(parse_ore_rows(SAMPLE))
    assert {r["ore"] for r in low} == {"Diamantine", "Dulcinette", "Beehive"}
    assert {r["ore"] for r in high} == {"Saerylium", "Diamorite", "Kardiá", "Cl0ver"}
    # Common 等更低階：兩邊都不收（不進聊天、與採集確認無關）
    all_names = {r["ore"] for r in low} | {r["ore"] for r in high}
    assert "Honestite" not in all_names


def test_tier_constants_cover_expected():
    assert LOW_TIERS == ("Surreal", "Mythic")
    assert "Exquisite" in HIGH_TIERS and "Otherworldly" in HIGH_TIERS


def test_parse_strips_wiki_disambiguation_suffix():
    # wiki 連結目標帶消歧義後綴「Candy Bucket (Ore)」；遊戲內聊天名是「Candy Bucket」
    sample = """
|-|
Sugarstone Layer =
{| class="recipe"
|-
|[[Candy Bucket (Ore)]]
|{{Colour|Mythic}}
|744,200
|}
"""
    rows = parse_ore_rows(sample)
    assert rows[0]["ore"] == "Candy Bucket"


# ---- 全礦蒐集＋跨世界撞名檢查 ----
# 分類/排除都靠礦名比對，跨世界同名（尤其階級不同時）會互相污染；
# 蒐集全部礦（所有 tier、依世界分）讓這個假設可驗證、可回歸。
from miningbot.fetch_ores import find_name_collisions


def test_find_name_collisions_reports_cross_world_same_name():
    worlds = {
        "A": [{"ore": "Foo", "tier": "Surreal", "rarity": 1, "layer": "x"},
              {"ore": "Bar", "tier": "Common",  "rarity": 2, "layer": "x"}],
        "B": [{"ore": "Foo", "tier": "Exotic",  "rarity": 3, "layer": "y"}],
    }
    col = find_name_collisions(worlds)
    assert set(col) == {"Foo"}
    assert {(w, t) for w, t, _ in col["Foo"]} == {("A", "Surreal"), ("B", "Exotic")}


def test_find_name_collisions_ignores_same_world_multi_layer():
    # 同世界同名多圖層（如 Ambitium 同時在 Amourite/Shamrock 層）＝合法，不算撞名
    worlds = {"A": [{"ore": "Ambitium", "tier": "Common", "rarity": 400, "layer": "Amourite"},
                    {"ore": "Ambitium", "tier": "Common", "rarity": 400, "layer": "Shamrock"}]}
    assert find_name_collisions(worlds) == {}


def test_find_name_collisions_empty_when_no_overlap():
    worlds = {"A": [{"ore": "Foo", "tier": "Rare", "rarity": 1, "layer": "x"}],
              "B": [{"ore": "Bar", "tier": "Rare", "rarity": 1, "layer": "y"}]}
    assert find_name_collisions(worlds) == {}


def test_committed_ores_all_has_no_cross_class_conflicts():
    # 分類正確性真正依賴的不變量：沒有礦名「在 A 世界是低階（排除對象）、在 B 世界是
    # 高階（採集目標）」——否則世界未鎖定時的聯集判定會歧義。同階同名合法且存在
    # （2026-07-03 驗證：34 個，全是 Aesteria↔Wintera Isle / Tutorial↔World 1 共用礦）。
    import json, os
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "ores_all.json")
    with open(path, encoding="utf-8") as f:
        worlds = json.load(f)["worlds"]
    assert find_class_conflicts(worlds) == {}


# ---- 低/高衝突檢查（find_class_conflicts）----
from miningbot.fetch_ores import find_class_conflicts


def test_find_class_conflicts_flags_low_in_one_high_in_another():
    worlds = {
        "A": [{"ore": "Foo", "tier": "Surreal", "rarity": 1, "layer": "x"}],
        "B": [{"ore": "Foo", "tier": "Exotic",  "rarity": 2, "layer": "y"}],
    }
    assert set(find_class_conflicts(worlds)) == {"Foo"}


def test_find_class_conflicts_allows_same_tier_cross_world():
    # 季節島/教學關共用礦：同名同階（甚至同名不同「階但同類」）→ 不算衝突
    worlds = {
        "A": [{"ore": "Sub-Zero", "tier": "Surreal", "rarity": 1, "layer": "Frost"}],
        "B": [{"ore": "Sub-Zero", "tier": "Surreal", "rarity": 1, "layer": "Isle"}],
        "C": [{"ore": "Freon", "tier": "Exotic", "rarity": 3, "layer": "x"}],
        "D": [{"ore": "Freon", "tier": "Exotic", "rarity": 3, "layer": "y"}],
    }
    assert find_class_conflicts(worlds) == {}
