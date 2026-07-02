"""REX 礦坑遊戲資料庫（**分世界 / world**）。

REX 分世界（world），每個世界有各自的事件清單與礦物表。目前實作 **Aesteria** 與
**Lucernia**（兩者事件 + 低稀有度礦皆齊備）。之後新增世界只要再建一個 `World` 並加進
`WORLDS` 即可（事件、礦物都各自獨立）。

每個世界含：
- `events`：D4 事件清單。D4 右鍵刷新時判斷目前事件是否值得保留（左鍵確認）還是刷新。
  每筆記：OCR 比對片段（match）、礦名（ore）、稀有度、持續時間、每秒生成率、特殊效果。
- `common_ores`：**低稀有度礦**（普通鎬子會挖到的）。D3 採集確認時用來「**篩掉**」——
  聊天「<小名> has found X」若 X 屬於 common_ores 就是普通挖礦、不算 D3 採集；
  反之（不在排除清單）視為稀有礦 → 採集成功。用「排除低稀有度」而非「列舉高稀有度」，
  因高稀有度礦太多列不完，低稀有度反而有限（使用者決策 2026-06-29）。

資料來源：使用者提供（REX wiki + 實機）。純資料 + 純函式，可單元測試（不碰 OCR / I/O）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class World:
    name: str
    events: list[dict]          # D4 事件清單（按稀有度升序）
    common_ores: list[dict]     # 低稀有度礦（D3 採集確認的「排除清單」）


# ── Aesteria：事件清單（按稀有度升序）───────────────────────────────────
# match = OCR 比對用片段（遊戲內事件訊息的子字串，不分大小寫比對）
# tier  = 粗分等級（S/A/B/C），僅供預設排序參考；使用者可自訂 keep 清單覆蓋
_AESTERIA_EVENTS: list[dict] = [
    {
        "match": "fluttering",
        "ore": "Mythical Hive",
        "rarity": 6_666_666,
        "duration_s": 26.6 * 60,
        "chance_per_s": 400,
        "effect": "追加 Heartstring Caves 事件 roll（1/10 加成）",
        "tier": "B",
    },
    {
        "match": "dust devil",
        "ore": "Dunestride",
        "rarity": 8_404_000,
        "duration_s": 20 * 60,
        "chance_per_s": 375,
        "effect": "無",
        "tier": "C",
    },
    {
        "match": "memorable beacon",
        "ore": "Aurora Polaris",
        "rarity": 10_000_000,
        "duration_s": 15 * 60,
        "chance_per_s": 1275,
        "effect": "所有洞穴 礦物 luck +5%",
        "tier": "B",
    },
    {
        "match": "verdant luster",
        "ore": "Panselinos",
        "rarity": 17_100_200,
        "duration_s": 30 * 60,
        "chance_per_s": 700,
        "effect": "The Inktorb luck ×1.7",
        "tier": "A",
    },
    {
        "match": "hordes of eyes",
        "ore": "The All-Seeing",
        "rarity": 18_222_222,
        "duration_s": 20 * 60,
        "chance_per_s": 650,
        "effect": "The Inktorb luck ×1.9（本表最高倍率）",
        "tier": "A",
    },
    {
        "match": "muffled laughter",
        "ore": "Corerupted",
        "rarity": 21_300_000,
        "duration_s": 15 * 60,
        "chance_per_s": 500,
        "effect": "走路速度 +2",
        "tier": "C",
    },
    {
        "match": "constellations of ice",
        "ore": "Cryonstelar",
        "rarity": 37_275_000,
        "duration_s": 40 * 60,
        "chance_per_s": 525,
        "effect": "The Inktorb luck ×1.6",
        "tier": "A",
    },
    {
        "match": "soft petals",
        "ore": "Sunflower",
        "rarity": 42_400_000,
        "duration_s": 33.3 * 60,
        "chance_per_s": 840,
        "effect": "非手動能力 proc +8%",
        "tier": "B",
    },
    {
        "match": "royal ice",
        "ore": "Divinis",
        "rarity": 49_641_680,
        "duration_s": 20 * 60,
        "chance_per_s": 700,
        "effect": "追加 Snowveil Caves 事件 roll（1/12 加成）",
        "tier": "A",
    },
    {
        "match": "whirlwind of souls",
        "ore": "Ectoplasmado",
        "rarity": 71_130_000,
        "duration_s": 40 * 60,
        "chance_per_s": 1000,
        "effect": "The Inktorb luck ×1.6",
        "tier": "A",
    },
    {
        "match": "twisted sarcophagus",
        "ore": "Umbrasnare",
        "rarity": 72_000_000,
        "duration_s": 25 * 60,
        "chance_per_s": 790,
        "effect": "The Inktorb luck ×1.8",
        "tier": "A",
    },
    {
        "match": "jovial carols",
        "ore": "Yuletide Star",
        "rarity": 74_724_000,
        "duration_s": 30 * 60,
        "chance_per_s": 800,
        "effect": "圖層 luck +1%/好友（最高 +5%）；釘選 礦物 luck +5%",
        "tier": "A",
    },
    {
        "match": "summer freedom",
        "ore": "Frutiflux",
        "rarity": 76_543_210,
        "duration_s": 25 * 60,
        "chance_per_s": 1300,
        "effect": "Surmilum 圖層所有 礦物 luck +20%",
        "tier": "A",
    },
    {
        "match": "ice crystals flicker",
        "ore": "Ephemryst",
        "rarity": 190_520_000,
        "duration_s": 30 * 60,
        "chance_per_s": 1333,
        "effect": "Frost/Deepfrost 圖層 luck +15%；其他圖層 +7.5%",
        "tier": "S",
    },
    {
        "match": "twilight magic",
        "ore": "Vocarus",
        "rarity": 200_500_500,
        "duration_s": 33 * 60,
        "chance_per_s": 1560,
        "effect": "追加 Fractured Caves roll（1/25）；Sugarstone 橙→圖層+10%，紫→洞穴+10%",
        "tier": "S",
    },
    {
        "match": "sanctum of tears",
        "ore": "Hallownest",
        "rarity": 210_167_002,
        "duration_s": 60 * 60,
        "duration": "60min（本表最長）",
        "chance_per_s": 1490,
        "effect": "追加 Soulseek Caves roll（1/7）；Withered Sand/Hexafite luck +15%",
        "tier": "S",
    },
]

# ── Aesteria：低稀有度礦（D3 採集確認的「排除清單」）─────────────────────
# ore = 礦名（比對用）；rarity = 稀有度數字；layer = 出處圖層；tier = 階級（資訊備查）。
#
# 遊戲機制（使用者確認 2026-06-29）：**只有 Surreal + Mythic 這兩階會出現在聊天框**；
# Exotic 以上不會被動進聊天，改用 **chill 聲音**觸發採集。但**用 D3 親手採到高階礦時，那一筆
# 會進聊天**（與被動挖礦不同）。所以這份清單＝「全部會被動進聊天的低階礦」的完整集合。
#
# 用途：採集後比對聊天「has found X」——X 在此清單（低階）→ 忽略；X 不在（＝D3 採到的高階）→ 稀有礦 → 成功。
#   亦即清單是**排除器**：擋掉低階誤觸發，讓「剩下不在清單的 has found」＝真正採到的高階。
# **稀有度與 layer 無關**。階級由低到高累積排除：Surreal < Mythic < …（< Exotic 以上＝採集目標，不列）。
# ⚠️ 反轉策略的取捨：高稀有度礦太多列不完，故改列舉「低稀有度」來排除。安全性「取決於清單完整」——
#    漏列一個會進聊天的低階礦 → 它出現時被誤當高階 → 假成功；故兩階都要列全（使用者已確認只有這兩階進聊天）。
#    另：OCR 把礦名讀錯成不在清單的字也會偶發假成功；用 startswith 容忍尾端雜訊降低誤判。
_AESTERIA_COMMON_ORES: list[dict] = [
    # --- Surreal 階（99k–490k）---
    {"ore": "Peppermint Core", "rarity": 99_000,  "layer": "Frost",         "tier": "Surreal"},
    {"ore": "Snowfall",        "rarity": 101_500, "layer": "Deepfrost",     "tier": "Surreal"},
    {"ore": "Deltium",         "rarity": 130_000, "layer": "Withered Sand", "tier": "Surreal"},
    {"ore": "Lovelocket",      "rarity": 155_000, "layer": "Affement",      "tier": "Surreal"},
    {"ore": "Pyrinal",         "rarity": 182_330, "layer": "Sugarstone",    "tier": "Surreal"},
    {"ore": "Bandeau",         "rarity": 190_400, "layer": "Affement",      "tier": "Surreal"},
    {"ore": "Peppermist",      "rarity": 190_600, "layer": "Jollystone",    "tier": "Surreal"},
    {"ore": "Frostarian",      "rarity": 205_000, "layer": "Frost",         "tier": "Surreal"},
    {"ore": "Incandescine",    "rarity": 211_500, "layer": "Maculite",      "tier": "Surreal"},
    {"ore": "Vermillion",      "rarity": 230_000, "layer": "Spookstone",    "tier": "Surreal"},
    {"ore": "Vapudric",        "rarity": 230_190, "layer": "Delucemite",    "tier": "Surreal"},
    {"ore": "Sub-Zero",        "rarity": 281_000, "layer": "Deepfrost",     "tier": "Surreal"},
    {"ore": "Mistletide",      "rarity": 312_000, "layer": "Jollystone",    "tier": "Surreal"},
    {"ore": "Darkseed",        "rarity": 312_940, "layer": "Delucemite",    "tier": "Surreal"},
    {"ore": "Spiritcage",      "rarity": 333_334, "layer": "Hexafite",      "tier": "Surreal"},
    {"ore": "Frostenice",      "rarity": 340_000, "layer": "Frost",         "tier": "Surreal"},
    {"ore": "Breezeflow",      "rarity": 341_000, "layer": "Surmilum",      "tier": "Surreal"},
    {"ore": "Spelsine",        "rarity": 343_333, "layer": "Spookstone",    "tier": "Surreal"},
    {"ore": "Compact Snow",    "rarity": 359_210, "layer": "Deepfrost",     "tier": "Surreal"},
    {"ore": "Dusksekkar",      "rarity": 372_050, "layer": "Sugarstone",    "tier": "Surreal"},
    {"ore": "Eyeballium",      "rarity": 390_200, "layer": "Spookstone",    "tier": "Surreal"},
    {"ore": "Peppernite",      "rarity": 400_300, "layer": "Jollystone",    "tier": "Surreal"},
    {"ore": "Doomsekkar",      "rarity": 411_845, "layer": "Sugarstone",    "tier": "Surreal"},
    {"ore": "Pobble",          "rarity": 420_000, "layer": "Surmilum",      "tier": "Surreal"},
    {"ore": "Viripendage",     "rarity": 432_000, "layer": "Withered Sand", "tier": "Surreal"},
    {"ore": "Ghostdeerium",    "rarity": 443_210, "layer": "Delucemite",    "tier": "Surreal"},
    {"ore": "Candensium",      "rarity": 450_000, "layer": "Frost",         "tier": "Surreal"},  # 原誤植 "Cublexrtiye"（fetch_ores diff 抓到，2026-07-03；名字錯＝該礦從未被排除）
    {"ore": "Illumite",        "rarity": 490_120, "layer": "Maculite",      "tier": "Surreal"},
    # --- Mythic 階（500k–991k）---
    {"ore": "Crystallized Solarite", "rarity": 500_000, "layer": "Frost",         "tier": "Mythic"},
    {"ore": "Frigishard",      "rarity": 554_000, "layer": "Jollystone",    "tier": "Mythic"},
    {"ore": "Heldis",          "rarity": 570_900, "layer": "Spookstone",    "tier": "Mythic"},
    {"ore": "Blizzardine",     "rarity": 603_500, "layer": "Deepfrost",     "tier": "Mythic"},
    {"ore": "Pool Noodle",     "rarity": 620_100, "layer": "Maculite",      "tier": "Mythic"},
    {"ore": "Vialite",         "rarity": 640_200, "layer": "Withered Sand", "tier": "Mythic"},
    {"ore": "Infrapolus",      "rarity": 640_460, "layer": "Hexafite",      "tier": "Mythic"},
    {"ore": "Candied Nocturnite", "rarity": 670_000, "layer": "Frost",      "tier": "Mythic"},
    {"ore": "Candy Vortex",    "rarity": 720_000, "layer": "Frost",         "tier": "Mythic"},
    {"ore": "Vermedictum",     "rarity": 720_000, "layer": "Spookstone",    "tier": "Mythic"},
    {"ore": "Candy Bucket",    "rarity": 744_200, "layer": "Sugarstone",    "tier": "Mythic"},
    {"ore": "Cordis Gemma",    "rarity": 750_000, "layer": "Affement",      "tier": "Mythic"},
    {"ore": "Jollinyte",       "rarity": 750_000, "layer": "Jollystone",    "tier": "Mythic"},
    {"ore": "Solar Haze",      "rarity": 777_776, "layer": "Maculite",      "tier": "Mythic"},
    {"ore": "Fragfall",        "rarity": 777_777, "layer": "Surmilum",      "tier": "Mythic"},
    {"ore": "Cucurbite",       "rarity": 778_000, "layer": "Withered Sand", "tier": "Mythic"},
    {"ore": "Fettersine",      "rarity": 780_300, "layer": "Hexafite",      "tier": "Mythic"},
    {"ore": "Passionblaze",    "rarity": 810_000, "layer": "Affement",      "tier": "Mythic"},
    {"ore": "Nightwatcher",    "rarity": 832_770, "layer": "Delucemite",    "tier": "Mythic"},
    {"ore": "Astralisium",     "rarity": 841_100, "layer": "Deepfrost",     "tier": "Mythic"},
    {"ore": "Mystifall",       "rarity": 991_999, "layer": "Surmilum",      "tier": "Mythic"},
]


# ── Lucernia：事件清單（按稀有度升序）───────────────────────────────────
# match = OCR 比對片段（事件訊息子字串，小寫）；effect 保留英文（使用者原資料為英文），
# 已清除 wiki 圖示 artifact（LuckIconNew/RateIconNew/SpeedIconNew → 純倍率/百分比）。
# tier 為粗分（對照 Aesteria 稀有度區間賦值），僅供排序參考。
# ⚠️ 使用者 2026-06-30 另附一列 "Yellow pointlight shines bright above your head."
#    無 礦名/稀有度/時長/生成率/效果 欄位 → 視為不完整，暫不列入；補齊後再加。
_LUCERNIA_EVENTS: list[dict] = [
    {
        "match": "serene ballad",
        "ore": "Essentium",
        "rarity": 3_000_000,
        "duration_s": 10 * 60,
        "chance_per_s": 300,
        "effect": "None",
        "tier": "C",
    },
    {
        "match": "reindeer gallops",
        "ore": "Antlerice",
        "rarity": 14_100_200,
        "duration_s": 8 * 60,
        "chance_per_s": 555,
        "effect": "The Inktorb luck ×1.8",
        "tier": "C",
    },
    {
        "match": "encapsulated wonderland",
        "ore": "Snowglobe III",
        "rarity": 18_000_073,
        "duration_s": 10 * 60,
        "chance_per_s": 650,
        "effect": "Layer luck +2.5% per friended player in server",
        "tier": "C",
    },
    {
        "match": "specter cyclone",
        "ore": "Soulswirl",
        "rarity": 19_314_790,
        "duration_s": 32 * 60,
        "chance_per_s": 400,
        "effect": "None",
        "tier": "C",
    },
    {
        "match": "bouncing baubles",
        "ore": "Ornaswirl",
        "rarity": 20_888_888,
        "duration_s": 12 * 60,
        "chance_per_s": 700,
        "effect": "None",
        "tier": "C",
    },
    {
        "match": "brave eggs",
        "ore": "Miles/egg",
        "rarity": 21_174_717,
        "duration_s": 20 * 60,
        "chance_per_s": 500,
        "effect": "Walkspeed per Uncommon+ found (higher tier → more speed)",
        "tier": "C",
    },
    {
        "match": "reflective crystal",
        "ore": "Crystalia",
        "rarity": 38_201_298,
        "duration_s": 15 * 60,
        "chance_per_s": 777,
        "effect": "Special caves +15% spawn chance",
        "tier": "B",
    },
    {
        "match": "solemn star",
        "ore": "Polaris",
        "rarity": 40_020_011,
        "duration_s": 17 * 60,
        "chance_per_s": 800,
        "effect": "Cicallite layer ores +25% more common",
        "tier": "B",
    },
    {
        "match": "viridescent ice crystals",
        "ore": "Verdafrost",
        "rarity": 50_200_630,
        "duration_s": 20 * 60,
        "chance_per_s": 930,
        "effect": "All abilities ×1.1 proc rate; Confectent layer +15%",
        "tier": "A",
    },
    {
        "match": "rushing water",
        "ore": "Evergreen",
        "rarity": 53_000_654,
        "duration_s": 40 * 60,
        "chance_per_s": 710,
        "effect": "Ores below Exotic +15%; walkspeed +7",
        "tier": "A",
    },
    {
        "match": "heartbeat comes in sync",
        "ore": "Heart.bit",
        "rarity": 62_000_178,
        "duration_s": 30 * 60,
        "chance_per_s": 820,
        "effect": "Ores with loud audios +15% more common",
        "tier": "A",
    },
    {
        "match": "resonant caws",
        "ore": "Cobbore",
        "rarity": 62_400_150,
        "duration_s": 35 * 60,
        "chance_per_s": 720,
        "effect": "Manual-ability gears: +10% proc to non-manual abilities",
        "tier": "A",
    },
    {
        "match": "premonitions of terror",
        "ore": "Keres",
        "rarity": 72_380_000,
        "duration_s": 48.13 * 60,
        "chance_per_s": 850,
        "effect": "The Inktorb luck ×1.9; manual-ability gears +10% proc to non-manual",
        "tier": "A",
    },
    {
        "match": "choir of fairies",
        "ore": "Celinity",
        "rarity": 135_000_000,
        "duration_s": 60 * 60,
        "chance_per_s": 1000,
        "effect": "All ores (layer + cave) +20% more common",
        "tier": "A",
    },
    {
        "match": "memories of idyllic fall",
        "ore": "Reminiscence",
        "rarity": 234_030_360,
        "duration_s": 55 * 60,
        "chance_per_s": 980,
        "effect": "Foligrass layer +15%; Mythic-and-below outside Foligrass +8%",
        "tier": "S",
    },
    {
        "match": "eternal clock",
        "ore": "DOOMSDAY",
        "rarity": 266_666_666,
        "duration_s": 90 * 60,
        "chance_per_s": 1159,
        "effect": "Only spawns when this event is active",
        "tier": "S",
    },
    {
        "match": "elegant lotus",
        "ore": "Yuki Onna",
        "rarity": 350_150_200,
        "duration_s": 34 * 60,
        "chance_per_s": 1111,
        "effect": "Variants +11%; Lucitreum layer +10%",
        "tier": "S",
    },
    {
        "match": "decorations all around",
        "ore": "Wintburg",
        "rarity": 590_200_035,
        "duration_s": 45 * 60,
        "chance_per_s": 1300,
        "effect": "1/15 chance for Firework Caves; pinned ores +20%",
        "tier": "S",
    },
]

# ── Lucernia：低稀有度礦（D3 採集確認的「排除清單」）─────────────────────
# 同 Aesteria 慣例：只有 Surreal + Mythic 這兩階會被動進聊天框；Exotic 以上改用
# chill 聲音觸發。圖層為 Lucernia 特有：Confectent / Lucitreum / Sepulcrum /
# Cicallite / Foligrass / Wickrock。
_LUCERNIA_COMMON_ORES: list[dict] = [
    # --- Surreal 階（100k–490k）---
    {"ore": "Presentine",       "rarity": 100_293, "layer": "Confectent", "tier": "Surreal"},
    {"ore": "Tinsel",           "rarity": 177_825, "layer": "Lucitreum",  "tier": "Surreal"},
    {"ore": "Vitiscus",         "rarity": 194_067, "layer": "Sepulcrum",  "tier": "Surreal"},
    {"ore": "Fannolair",        "rarity": 196_499, "layer": "Cicallite",  "tier": "Surreal"},
    {"ore": "Gup",              "rarity": 202_204, "layer": "Foligrass",  "tier": "Surreal"},
    {"ore": "Asternigh",        "rarity": 229_322, "layer": "Lucitreum",  "tier": "Surreal"},
    {"ore": "Frostfeeb",        "rarity": 242_730, "layer": "Cicallite",  "tier": "Surreal"},
    {"ore": "Darkfeeb",         "rarity": 266_666, "layer": "Wickrock",   "tier": "Surreal"},
    {"ore": "Kelvine",          "rarity": 273_150, "layer": "Cicallite",  "tier": "Surreal"},
    {"ore": "Polanorth",        "rarity": 277_777, "layer": "Confectent", "tier": "Surreal"},
    {"ore": "Starseeker",       "rarity": 326_643, "layer": "Lucitreum",  "tier": "Surreal"},
    {"ore": "Beanie",           "rarity": 330_010, "layer": "Confectent", "tier": "Surreal"},
    {"ore": "Hexaburst",        "rarity": 360_420, "layer": "Sepulcrum",  "tier": "Surreal"},
    {"ore": "Luminescence",     "rarity": 400_400, "layer": "Lucitreum",  "tier": "Surreal"},
    {"ore": "Syrooze",          "rarity": 430_000, "layer": "Foligrass",  "tier": "Surreal"},
    {"ore": "Lucifite",         "rarity": 466_666, "layer": "Wickrock",   "tier": "Surreal"},
    {"ore": "Yuleflare",        "rarity": 490_100, "layer": "Confectent", "tier": "Surreal"},
    # --- Mythic 階（510k–981k）---
    {"ore": "Nivaorum",         "rarity": 510_202, "layer": "Cicallite",  "tier": "Mythic"},
    {"ore": "Memoramber",       "rarity": 533_126, "layer": "Foligrass",  "tier": "Mythic"},
    {"ore": "Magician",         "rarity": 616_603, "layer": "Sepulcrum",  "tier": "Mythic"},
    {"ore": "Shattered Amulet", "rarity": 640_100, "layer": "Lucitreum",  "tier": "Mythic"},
    {"ore": "Crescendo",        "rarity": 666_666, "layer": "Wickrock",   "tier": "Mythic"},
    {"ore": "Warmthion",        "rarity": 679_010, "layer": "Confectent", "tier": "Mythic"},
    {"ore": "Glacialyst",       "rarity": 680_102, "layer": "Cicallite",  "tier": "Mythic"},
    {"ore": "Stockingstone",    "rarity": 710_200, "layer": "Confectent", "tier": "Mythic"},
    {"ore": "Moonstruck",       "rarity": 724_564, "layer": "Sepulcrum",  "tier": "Mythic"},
    {"ore": "Vampirite",        "rarity": 766_666, "layer": "Wickrock",   "tier": "Mythic"},
    {"ore": "Bonium",           "rarity": 803_259, "layer": "Sepulcrum",  "tier": "Mythic"},
    {"ore": "Plaidore",         "rarity": 850_400, "layer": "Foligrass",  "tier": "Mythic"},
    {"ore": "Contemptus Gemma", "rarity": 866_666, "layer": "Wickrock",   "tier": "Mythic"},
    {"ore": "Jollycane",        "rarity": 960_000, "layer": "Confectent", "tier": "Mythic"},
    {"ore": "Zerocite",         "rarity": 980_999, "layer": "Lucitreum",  "tier": "Mythic"},
    # --- 2026 春季更新四圖層（Amourite / Shamrock / Brittlestone / Harmonine）---
    # H014（2026-07-03）誤判環境：情人節主題 Amourite 圖層。這批 Surreal/Mythic 會被動
    # 進聊天，漏列會讓「聊天淡出喚醒後的舊行」被當新稀有 → 假成功。
    # 資料源：rex-reincarnated wiki Lucernia 頁。Exotic 以上（Saerylium/Diamorite 等）
    # 是 D3 採集目標，**絕不可列進來**（H014 的 Diamorite 若被排除＝重演假陰性）。
    {"ore": "Diamantine",       "rarity": 100_000, "layer": "Amourite",     "tier": "Surreal"},
    {"ore": "Ladyfeeb",         "rarity": 300_000, "layer": "Amourite",     "tier": "Surreal"},
    {"ore": "Dulcinette",       "rarity": 500_000, "layer": "Amourite",     "tier": "Mythic"},
    {"ore": "Loveletter",       "rarity": 600_000, "layer": "Amourite",     "tier": "Mythic"},
    {"ore": "Heartbeet",        "rarity": 900_000, "layer": "Amourite",     "tier": "Mythic"},
    {"ore": "Siogyne",          "rarity": 232_109, "layer": "Shamrock",     "tier": "Surreal"},
    {"ore": "Weevil",           "rarity": 323_456, "layer": "Shamrock",     "tier": "Surreal"},
    {"ore": "Riches",           "rarity": 543_456, "layer": "Shamrock",     "tier": "Mythic"},
    {"ore": "Cleavelite",       "rarity": 767_676, "layer": "Shamrock",     "tier": "Mythic"},
    {"ore": "Toppatrick",       "rarity": 901_210, "layer": "Shamrock",     "tier": "Mythic"},
    {"ore": "Polkegg",          "rarity": 129_129, "layer": "Brittlestone", "tier": "Surreal"},
    {"ore": "Cracked Egg",      "rarity": 231_231, "layer": "Brittlestone", "tier": "Surreal"},
    {"ore": "Yolkfeeb",         "rarity": 439_439, "layer": "Brittlestone", "tier": "Surreal"},
    {"ore": "Ovacuum",          "rarity": 617_617, "layer": "Brittlestone", "tier": "Mythic"},
    {"ore": "Baggsket",         "rarity": 888_888, "layer": "Brittlestone", "tier": "Mythic"},
    {"ore": "Synthesite",       "rarity": 222_222, "layer": "Harmonine",    "tier": "Surreal"},
    {"ore": "Melodium",         "rarity": 444_444, "layer": "Harmonine",    "tier": "Surreal"},
    {"ore": "Echonox",          "rarity": 555_555, "layer": "Harmonine",    "tier": "Mythic"},
    {"ore": "Cirfith",          "rarity": 777_777, "layer": "Harmonine",    "tier": "Mythic"},
    # --- 洞穴限定（Cave Exclusives）的 Surreal/Mythic：聊天行帶「(Xxx Cave)」尾註，
    #     _is_rare_ore 的 startswith 容忍會正確吃掉尾註仍判為 common（H014 的
    #     Jollycane (Candied Cave) 即此格式）。rarity 是洞穴內機率、與圖層礦不同尺度。---
    {"ore": "Bungy",            "rarity": 7_478,  "layer": "Eggshell Cave",   "tier": "Surreal"},
    {"ore": "Yolkbang",         "rarity": 7_478,  "layer": "Eggshell Cave",   "tier": "Surreal"},
    {"ore": "Halcylite",        "rarity": 21_234, "layer": "Lucky Cave",      "tier": "Surreal"},
    {"ore": "Weesp",            "rarity": 41_250, "layer": "Umbragloom Cave", "tier": "Surreal"},
    {"ore": "Beehive",          "rarity": 36_520, "layer": "Floral Cave",     "tier": "Mythic"},
    {"ore": "Rotatrim",         "rarity": 46_455, "layer": "Lucky Cave",      "tier": "Mythic"},
    {"ore": "Duskgravite",      "rarity": 63_836, "layer": "Umbragloom Cave", "tier": "Mythic"},
]


# ── 世界登記 + 目前世界偵測 ─────────────────────────────────────────────
AESTERIA = World("Aesteria", _AESTERIA_EVENTS, _AESTERIA_COMMON_ORES)
LUCERNIA = World("Lucernia", _LUCERNIA_EVENTS, _LUCERNIA_COMMON_ORES)
WORLDS: dict[str, World] = {"Aesteria": AESTERIA, "Lucernia": LUCERNIA}

# Discord 表情分頁按鈕：世界 → emoji。新增世界時這裡也要加對應表情（表情要互異）。
# 使用者在 Discord 點表情 → 切換到該世界的事件分頁（編輯同一則 !list 訊息）。
WORLD_EMOJI: dict[str, str] = {"Aesteria": "🌍", "Lucernia": "🌙"}


def emoji_to_world(emoji: str) -> str | None:
    """表情 → 世界名（找不到回 None）。Discord 表情分頁切換用。"""
    for w, em in WORLD_EMOJI.items():
        if em == emoji:
            return w
    return None

# 目前世界：**預設未確定（None）**。遊戲沒有直接顯示在哪個世界，要靠「看到的事件屬於哪個世界」
# 來推斷（事件是分世界的）。未確定前，採集確認的排除清單用「所有世界的聯集」當保守後備；
# 一旦事件唯一鎖定某世界，就收斂成該世界的清單——更準、也省去把各世界清單都比一次。
_current_world_name: str | None = None


def set_world(name: str) -> None:
    """鎖定目前世界；未知名稱拋 KeyError。"""
    global _current_world_name
    if name not in WORLDS:
        raise KeyError(f"unknown world: {name!r} (have {list(WORLDS)})")
    _current_world_name = name


def clear_world() -> None:
    """清掉目前世界判定（回到未確定）。礦坑重置/換場後若想重新偵測可呼叫。"""
    global _current_world_name
    _current_world_name = None


def current_world_name() -> str | None:
    return _current_world_name


def current_world() -> World | None:
    """目前世界（未確定回 None）。"""
    return WORLDS.get(_current_world_name) if _current_world_name else None


def all_events() -> list[dict]:
    """所有世界的事件聯集（事件比對/世界偵測用——讀到事件時還不知在哪個世界）。"""
    return [ev for w in WORLDS.values() for ev in w.events]


def all_common_ores() -> list[dict]:
    """所有世界的低稀有度礦聯集（世界未確定時的保守排除清單）。"""
    return [o for w in WORLDS.values() for o in w.common_ores]


def detect_world(event_text: str) -> str | None:
    """從事件文字推斷世界：哪個世界的事件清單命中此文字。

    唯一一個世界命中 → 回該世界名；零個或多個世界都命中（事件跨世界共用、無法區分）→ None。
    """
    text_lower = event_text.lower()
    hit = {w.name for w in WORLDS.values()
           if any(ev["match"].lower() in text_lower for ev in w.events)}
    return next(iter(hit)) if len(hit) == 1 else None


def update_world_from_event(event_text: str) -> str | None:
    """偵測並（若唯一命中且與現況不同）鎖定世界；回傳目前世界名（或 None）。

    呼叫端在每次 OCR 到事件列時呼叫即可（搭既有事件 OCR 的便車）。
    """
    w = detect_world(event_text)
    if w and w != _current_world_name:
        set_world(w)
    return _current_world_name


def common_ore_names() -> tuple[str, ...]:
    """D3 採集確認的低稀有度排除清單名稱（去重保序）。

    世界已確定 → 該世界的清單；未確定 → 所有世界聯集（保守，避免漏排除而假成功）。
    """
    w = current_world()
    ores = w.common_ores if w is not None else all_common_ores()
    return tuple(dict.fromkeys(o["ore"] for o in ores))


# ── 高階白名單（assets/rare_ores.json，fetch_ores 從 wiki 抓）＋三態分類 ─────────
# 排除清單仍是守門員（common→忽略）；白名單的角色是「分類器＋告警器」：
# 在白名單 → SUCCESS 且通知標注階級；兩邊都不在（unknown）→ 仍算成功（安全方向：
# 礦多半真的採到了），但通知標注「未知礦名」——OCR 誤讀或遊戲更新的清單漂移自己浮出來，
# 不會靜默失效。檔案缺/壞 → 空白名單（一切非 common 都變 unknown，行為安全降級）。
_RARE_ORES_PATH = None   # 測試可覆寫；None = 預設 assets/rare_ores.json


def _rare_ores_path() -> str:
    import os
    if _RARE_ORES_PATH:
        return _RARE_ORES_PATH
    return os.path.join(os.path.dirname(__file__), "..", "assets", "rare_ores.json")


_rare_ores_cache: dict | None = None


def rare_ores() -> dict:
    """正規化礦名 → {ore, tier, rarity, layer, world}（所有世界聯集；lazy 載入＋快取）。"""
    global _rare_ores_cache
    if _rare_ores_cache is None:
        import json
        table: dict = {}
        try:
            with open(_rare_ores_path(), encoding="utf-8") as f:
                data = json.load(f)
            for world, rows in data.get("worlds", {}).items():
                for r in rows:
                    table[r["ore"].lower()] = {**r, "world": world}
        except Exception:
            pass                      # 檔案缺/壞 → 空表（分類降級為 unknown，不炸主迴圈）
        _rare_ores_cache = table
    return _rare_ores_cache


def classify_found_ore(ore_text: str) -> tuple[str, dict | None]:
    """OCR 抽出的礦名（已小寫）→ ("common"|"rare"|"unknown", 白名單 info 或 None)。

    與排除比對同一套容忍：剝 Ionized/Spectral 變體前綴、startswith 容忍尾端雜訊
    （OCR 噪音、洞穴註記「(floral cave)」）。common 優先於 rare（守門員先判）。
    """
    from .ocr import _strip_variant   # 單一事實來源（VARIANT_PREFIXES）；ocr 不 import 本模組、無循環
    if not ore_text:
        return "unknown", None
    base = _strip_variant(ore_text.strip().lower())
    if any(base.startswith(c.lower()) for c in common_ore_names()):
        return "common", None
    for name, info in rare_ores().items():
        if base.startswith(name):
            return "rare", info
    return "unknown", None


# 向後相容：模組層 EVENTS 指向 Aesteria 事件（測試與既有呼叫端引用）。
EVENTS: list[dict] = _AESTERIA_EVENTS


def match_event(text: str) -> dict | None:
    """把 OCR 讀到的事件文字比對「所有世界」的事件，回傳命中的事件（或 None）。

    不分大小寫；只要 text「包含」任一 match 片段就算命中。搜全世界（非目前世界）——
    讀到事件時世界可能還沒鎖定，且這也是 detect_world 推斷世界的依據。
    若多個片段同時命中，回傳稀有度最高的（優先保留高價值事件）。
    """
    text_lower = text.lower()
    hits = [ev for ev in all_events() if ev["match"].lower() in text_lower]
    if not hits:
        return None
    return max(hits, key=lambda e: e["rarity"])


def is_kept(text: str, keep_ores: set[str] | None = None) -> bool:
    """判斷目前事件是否該保留（True=左鍵確認 / False=右鍵刷新）。

    keep_ores = 要保留的 礦物名 集合（例如 {"The All-Seeing", "Hallownest"}）。
    None = 目前無預設清單（所有已知事件都刷新）—— 等使用者透過 Discord 指定後才有保留行為。
    """
    ev = match_event(text)
    if ev is None:
        return False                        # 認不得的事件 → 刷新
    if keep_ores is not None:
        return ev["ore"] in keep_ores       # 使用者自訂清單
    return False                            # 無清單 → 一律刷新（保守）


def duration_str(ev: dict) -> str:
    """把 duration_s（秒）轉成人類可讀的字串（例如 '40min' / '33.3min'）。"""
    secs = ev["duration_s"]
    mins = secs / 60
    if mins == int(mins):
        return f"{int(mins)}min"
    return f"{mins:.1f}min"


def fuzzy_match_ore(query: str) -> str | None:
    """用查詢字串模糊比對 礦物名（不分大小寫，連字號/空格互通）。

    比對順序：完全相符 > query 是 礦物名的子字串 > 礦物名是 query 的子字串。
    多個命中時回傳稀有度最高的。找不到回 None。
    """
    def _norm(s: str) -> str:
        return s.lower().strip().replace("-", " ")
    q = _norm(query)
    if not q:
        return None
    events = all_events()
    # 1. 完全相符
    for ev in events:
        if _norm(ev["ore"]) == q:
            return ev["ore"]
    # 2. query 是 礦物名的子字串（例如 "hall" → "Hallownest"）
    hits = [ev for ev in events if q in _norm(ev["ore"])]
    if hits:
        return max(hits, key=lambda e: e["rarity"])["ore"]
    # 3. 礦物名是 query 的子字串（例如 "the all seeing" → "The All-Seeing"）
    hits = [ev for ev in events if _norm(ev["ore"]) in q]
    if hits:
        return max(hits, key=lambda e: e["rarity"])["ore"]
    return None


def format_event_list_embed(keep_ores: set[str] | None = None, world: str | None = None) -> dict:
    """產生 Discord embed JSON，列出事件 + keep 狀態（✅/❌）。

    world = 指定世界名（如 "Aesteria"/"Lucernia"）→ 只列該世界事件（分頁用）；
    None → 所有世界聯集（行為同舊版）。embed title 標註目前分頁的世界。
    keep_ores 仍是跨世界比對（使用者 keep 清單不分世界）。
    """
    keep_ores = keep_ores or set()
    if world is not None and world in WORLDS:
        events = WORLDS[world].events
        title_world = world
    else:
        events = all_events()
        title_world = "所有世界"
    fields = []
    for ev in events:
        status = "✅" if ev["ore"] in keep_ores else "❌"
        fields.append({
            "name": f"{status} {ev['ore']}",
            "value": f"{ev['rarity']:,}｜{ev['effect'][:50]}",
            "inline": True,
        })
    return {
        "title": f"REX 事件清單（{title_world}）",
        "description": "`!keep <礦物名>` 保留｜`!unkeep <礦物名>` 取消｜`!clear` 全清｜`!list [世界]` 切換",
        "color": 0x00ff88,
        "fields": fields,
    }


def ore_world(ore: str) -> str | None:
    """ 礦名 → 所屬世界（依各世界 events 的 ore 欄位比對）；找不到回 None。

    保留清單依世界分組顯示用（!keep/!unkeep 回覆）。保留的幾乎都是事件 礦，
    故只比對 events；common_ores 不檢查（那不是 D4 會刷新的對象）。
    """
    for name, world in WORLDS.items():
        if any(ev["ore"] == ore for ev in world.events):
            return name
    return None


def format_keep_by_world(keep_ores: set[str]) -> str:
    """把保留清單依世界分組，回 Discord 顯示字串。

    每個世界一行：``【<世界>】< 礦1>, < 礦2>, …``（ 礦名 sorted）；沒對應到任何
    世界事件的 礦歸到 ``【其他】``。空集合回 ``（空）``。世界順序依 ``WORLDS``，
    「其他」最後；沒 礦的世界不輸出該行（避免空行）。

    例： ``【Aesteria】Ephemryst, Sunflower\\n【Lucernia】Celinity, Wintburg``
    """
    if not keep_ores:
        return "（空）"
    by_world: dict[str | None, list[str]] = {}
    for ore in keep_ores:
        by_world.setdefault(ore_world(ore), []).append(ore)
    lines = []
    for w in WORLDS:                          # 固定順序（Aesteria → Lucernia → …）
        ores = sorted(by_world.get(w, []))
        if ores:
            lines.append(f"【{w}】{', '.join(ores)}")
    other = sorted(by_world.get(None, []))
    if other:
        lines.append(f"【其他】{', '.join(other)}")
    return "\n".join(lines)
