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
