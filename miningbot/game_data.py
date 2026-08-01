"""REX active-world 事件與礦物資料庫。

每個有效世界都有獨立事件與礦物表；`WORLDS` 是目前支援世界的唯一 registry。
新增世界時必須同時補事件、低階排除資料、表情映射與對應測試。

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
    # Master 底名：normal 不進聊天，但 ionized/spectral 變體會被動進（H039 2026-07-04
    # 實錄 an ionized Heartstone；剝變體前綴後查的是底名 → 列底名）。fetch_ores 只收
    # Surreal+ 不會印它的 diff，wiki Lucernia 頁有列（Master 1/50,000、ionized 1/4M）。
    {"ore": "Heartstone",       "rarity": 50_000,  "layer": "Amourite",     "tier": "Master"},
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


# ── World 0: Digita：低稀有度礦（common_ores）────────────────────────────
# 資料源：rex-reincarnated wiki World 0 頁，經 fetch_ores 解析（2026-07-05 匯入）。
# AI/數位世界（Statistone/Wireframe/Matricite 圖層）。layer="?" = wiki 該列未帶圖層資訊（layer 僅資訊備查，排除邏輯只用 礦名+tier）。
_WORLD0_COMMON_ORES: list[dict] = [
    {"ore": 'Hyposhock', "rarity": 15051, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Dualisplite', "rarity": 18300, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Constellatrix', "rarity": 24142, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Prismator', "rarity": 39790, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Gizmonium', "rarity": 105000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Apparatus', "rarity": 115000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Annalyte', "rarity": 130500, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Planetarium', "rarity": 144144, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Abstractum', "rarity": 150001, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Nebulaize', "rarity": 165400, "layer": '?', "tier": 'Surreal'},
    {"ore": 'TeeVox B', "rarity": 188888, "layer": '?', "tier": 'Surreal'},
    {"ore": 'TeeVox G', "rarity": 188888, "layer": '?', "tier": 'Surreal'},
    {"ore": 'TeeVox R', "rarity": 188888, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Dischargium', "rarity": 215000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Fantaisine', "rarity": 221340, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Crimsonhack', "rarity": 225255, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Revolvus', "rarity": 233334, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Oscillyx', "rarity": 243700, "layer": '?', "tier": 'Surreal'},
    {"ore": 'subject.greenglitch', "rarity": 249999, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Technetium', "rarity": 250000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'RGB', "rarity": 255255, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Dreamveil', "rarity": 255700, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Prismata', "rarity": 286100, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Wishmore', "rarity": 293070, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Decimate', "rarity": 311000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Tensegrum', "rarity": 341056, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Mesmegram', "rarity": 353353, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Knorus', "rarity": 360063, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Spinvolt', "rarity": 360630, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Projectron', "rarity": 379220, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Cogchain', "rarity": 392400, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Whipstorm', "rarity": 420840, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Electroball', "rarity": 450054, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Gauzian', "rarity": 490000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Astral Processor', "rarity": 495000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Hedron', "rarity": 512125, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Conduit', "rarity": 525200, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Ammolite', "rarity": 537000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Darkstar', "rarity": 545545, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Electris', "rarity": 575550, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Magneticore', "rarity": 593070, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Pocket Galaxy', "rarity": 597000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Stilomite', "rarity": 620309, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Hyperchrome', "rarity": 624999, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Mystirune', "rarity": 633633, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Shockbox', "rarity": 674220, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Bronzeprint', "rarity": 682322, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Cobaltax', "rarity": 688587, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Cosmalens', "rarity": 727340, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Schematan', "rarity": 740005, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Retronium', "rarity": 744744, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Datakill', "rarity": 765321, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Candesium', "rarity": 765400, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Zalgrain', "rarity": 849992, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Mooncharm', "rarity": 875578, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Axisium', "rarity": 909090, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Turnfire', "rarity": 939935, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Kadabstrum', "rarity": 974758, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Rendispike', "rarity": 979595, "layer": '?', "tier": 'Mythic'},
]

# ── World 1: Natura：低稀有度礦（common_ores）────────────────────────────
# 資料源：rex-reincarnated wiki World 1 頁，經 fetch_ores 解析（2026-07-05 匯入）。
# 自然/古老王國（Stone/Basalt/Granite 圖層）。layer="?" = wiki 該列未帶圖層資訊（layer 僅資訊備查，排除邏輯只用 礦名+tier）。
_WORLD1_COMMON_ORES: list[dict] = [
    {"ore": 'Opal', "rarity": 16000, "layer": 'Cave Exclusives', "tier": 'Surreal'},
    {"ore": 'Divinessence', "rarity": 16000, "layer": 'Cave Exclusives', "tier": 'Surreal'},
    {"ore": 'Tanzanite', "rarity": 95550, "layer": 'Basalt', "tier": 'Surreal'},
    {"ore": 'Theiograph', "rarity": 100000, "layer": 'Marble', "tier": 'Surreal'},
    {"ore": 'Spatializine', "rarity": 122500, "layer": 'Diorite', "tier": 'Surreal'},
    {"ore": 'Purpurite', "rarity": 130000, "layer": 'Obsidian', "tier": 'Surreal'},
    {"ore": 'Eluryan', "rarity": 140120, "layer": 'Diorite', "tier": 'Surreal'},
    {"ore": 'Rainbonite', "rarity": 150000, "layer": 'Marble', "tier": 'Surreal'},
    {"ore": 'Elusium', "rarity": 155000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Elysian', "rarity": 155000, "layer": 'Basalt', "tier": 'Surreal'},
    {"ore": 'Promethium', "rarity": 198500, "layer": 'Granite', "tier": 'Surreal'},
    {"ore": 'Cryotic', "rarity": 206000, "layer": 'Cave Exclusives', "tier": 'Mythic'},
    {"ore": 'Rusticog', "rarity": 210000, "layer": 'Mantle', "tier": 'Surreal'},
    {"ore": 'Heliostra', "rarity": 240000, "layer": 'Outer Core', "tier": 'Surreal'},
    {"ore": 'Heliostra', "rarity": 240000, "layer": 'Inner Core', "tier": 'Surreal'},
    {"ore": 'Prismatica', "rarity": 250000, "layer": 'Marble', "tier": 'Surreal'},
    {"ore": 'Jet', "rarity": 255000, "layer": 'Obsidian', "tier": 'Surreal'},
    {"ore": 'Vanadinite', "rarity": 300000, "layer": 'Mantle', "tier": 'Surreal'},
    {"ore": 'Erythrite', "rarity": 310000, "layer": 'Obsidian', "tier": 'Surreal'},
    {"ore": 'Eluxant', "rarity": 317350, "layer": 'Granite', "tier": 'Surreal'},
    {"ore": 'Antiquite', "rarity": 355555, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Solarite', "rarity": 500000, "layer": 'Outer Core', "tier": 'Mythic'},
    {"ore": 'Solarite', "rarity": 500000, "layer": 'Inner Core', "tier": 'Mythic'},
    {"ore": 'Zefendium', "rarity": 507000, "layer": 'Obsidian', "tier": 'Mythic'},
    {"ore": 'Alternium', "rarity": 525000, "layer": 'Mantle', "tier": 'Mythic'},
    {"ore": 'Viverra', "rarity": 540000, "layer": 'Mantle', "tier": 'Mythic'},
    {"ore": 'Seraphrite', "rarity": 560200, "layer": 'Marble', "tier": 'Mythic'},
    {"ore": 'Lanthanite', "rarity": 584000, "layer": 'Diorite', "tier": 'Mythic'},
    {"ore": 'Unobtainium', "rarity": 631000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Nocturnite', "rarity": 670000, "layer": 'Basalt', "tier": 'Mythic'},
    {"ore": 'Animyl', "rarity": 689101, "layer": 'Diorite', "tier": 'Mythic'},
    {"ore": 'Aesthetium', "rarity": 714925, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Newtonium', "rarity": 755050, "layer": 'Granite', "tier": 'Mythic'},
    {"ore": 'Nuummite', "rarity": 875000, "layer": 'Basalt', "tier": 'Mythic'},
    {"ore": 'Chromatite', "rarity": 875000, "layer": 'Marble', "tier": 'Mythic'},
    {"ore": 'Prasiloudis', "rarity": 883185, "layer": 'Granite', "tier": 'Mythic'},
    {"ore": 'Viscriol', "rarity": 900100, "layer": 'Obsidian', "tier": 'Mythic'},
]

# ── World 2：低稀有度礦（common_ores）─────────────────────────────────
# 資料源：rex-reincarnated wiki World 2 頁，經 fetch_ores 解析（2026-07-05 匯入）。
# 板岩/永久凍土＋銀河/魔法洞穴。layer="?" = wiki 該列未帶圖層資訊（layer 僅資訊備查，排除邏輯只用 礦名+tier）。
_WORLD2_COMMON_ORES: list[dict] = [
    {"ore": 'Condensium', "rarity": 106000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Culindrene', "rarity": 131262, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Exoflame', "rarity": 138000, "layer": 'Riftrock', "tier": 'Surreal'},
    {"ore": 'Lotivium', "rarity": 175000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Ridalite', "rarity": 181707, "layer": 'Void', "tier": 'Surreal'},
    {"ore": 'Tealine', "rarity": 208000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Protonium', "rarity": 228000, "layer": 'Darkmatter', "tier": 'Surreal'},
    {"ore": 'Zenflow', "rarity": 231000, "layer": 'Riftrock', "tier": 'Surreal'},
    {"ore": 'Fluorite', "rarity": 284000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Cestilade', "rarity": 286000, "layer": 'Void', "tier": 'Surreal'},
    {"ore": 'Calite', "rarity": 335000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Violixium', "rarity": 374000, "layer": 'Riftrock', "tier": 'Surreal'},
    {"ore": 'Auroralium', "rarity": 382000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Versulium', "rarity": 416000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Ignacaelum', "rarity": 419000, "layer": 'Darkmatter', "tier": 'Surreal'},
    {"ore": 'Aquatic Vortex', "rarity": 515000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Ignisaxum', "rarity": 517780, "layer": 'Darkmatter', "tier": 'Mythic'},
    {"ore": 'Divinushield', "rarity": 532000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Plasmal', "rarity": 575000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Mycerian', "rarity": 588000, "layer": 'Riftrock', "tier": 'Mythic'},
    {"ore": 'Vexerite', "rarity": 616000, "layer": 'Void', "tier": 'Mythic'},
    {"ore": "Void's Iris", "rarity": 686686, "layer": 'Void', "tier": 'Mythic'},
    {"ore": 'Coldstorm', "rarity": 737000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Chromavitrite', "rarity": 745000, "layer": 'Riftrock', "tier": 'Mythic'},
    {"ore": 'Nemolite', "rarity": 765432, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Cometryx', "rarity": 775000, "layer": 'Darkmatter', "tier": 'Mythic'},
    {"ore": 'The Dream', "rarity": 780800, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Nitoril', "rarity": 794782, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Fracidial', "rarity": 817000, "layer": 'Void', "tier": 'Mythic'},
    {"ore": 'Quadratus', "rarity": 888888, "layer": '?', "tier": 'Mythic'},
    {"ore": 'The Nightmare', "rarity": 964250, "layer": 'Riftrock', "tier": 'Mythic'},
]

# ── Subworld 1: Luna Refuge：低稀有度礦（common_ores）──────────────────
# 資料源：rex-reincarnated wiki Subworld 1 頁，經 fetch_ores 解析（2026-07-05 匯入）。
# 月球/太空聚落（Moon Stone/Moon Mantle 圖層）。layer="?" = wiki 該列未帶圖層資訊（layer 僅資訊備查，排除邏輯只用 礦名+tier）。
_SUBWORLD1_COMMON_ORES: list[dict] = [
    {"ore": 'Actinium', "rarity": 120000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'EDMium', "rarity": 145000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Electrolium', "rarity": 145000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Deathinium', "rarity": 145000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Lunar Newtonium', "rarity": 286000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Frostical', "rarity": 290000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Lunar Promethium', "rarity": 310000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Uldarite', "rarity": 325000, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Vortennial', "rarity": 600000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Unobtainium', "rarity": 631000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'SFoRE', "rarity": 650000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'WOOD GRAIN', "rarity": 710000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Lunar Dyronsinite', "rarity": 730000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Hyperstone', "rarity": 870000, "layer": '?', "tier": 'Mythic'},
]

# ── Subworld 2: Farlight：低稀有度礦（common_ores）──────────────────────
# 資料源：rex-reincarnated wiki Subworld 2 頁，經 fetch_ores 解析（2026-07-05 匯入）。
# 太空/反物質（Outer Space/Antimatter/Vacuum 圖層）。layer="?" = wiki 該列未帶圖層資訊（layer 僅資訊備查，排除邏輯只用 礦名+tier）。
_SUBWORLD2_COMMON_ORES: list[dict] = [
    {"ore": 'Shadow Neutronite', "rarity": 10229, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Protonite', "rarity": 12131, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Fire Neutronite', "rarity": 14287, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Agspernite', "rarity": 18288, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Taaffeite', "rarity": 20002, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Adamantium', "rarity": 30229, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Ethereal Gem', "rarity": 34000, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Luminous Gem', "rarity": 44004, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Magma Gem', "rarity": 98998, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Illuminite', "rarity": 99999, "layer": 'Outer Space', "tier": 'Surreal'},
    {"ore": 'Fire Gem', "rarity": 121212, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Ulexite', "rarity": 122245, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Corrupt Adamantium', "rarity": 191440, "layer": 'Vacuum', "tier": 'Surreal'},
    {"ore": 'Neo Cretium', "rarity": 222281, "layer": 'Antimatter', "tier": 'Surreal'},
    {"ore": 'Void Neutronite', "rarity": 222555, "layer": 'Vacuum', "tier": 'Surreal'},
    {"ore": 'Ultra Neutronite', "rarity": 255505, "layer": 'Outer Space', "tier": 'Surreal'},
    {"ore": 'Pulsarite', "rarity": 300004, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Enigmasteri', "rarity": 332305, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Corrupt Beryl', "rarity": 411060, "layer": 'Vacuum', "tier": 'Surreal'},
    {"ore": 'Accerite', "rarity": 441133, "layer": '?', "tier": 'Surreal'},
    {"ore": 'Neutronite', "rarity": 444411, "layer": 'Antimatter', "tier": 'Surreal'},
    {"ore": 'Void Heliotrope', "rarity": 454545, "layer": 'Vacuum', "tier": 'Surreal'},
    {"ore": 'Corrupt Soul Matter', "rarity": 455554, "layer": 'Vacuum', "tier": 'Surreal'},
    {"ore": 'Frost Gem', "rarity": 567890, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Spectral Gem', "rarity": 577343, "layer": 'Antimatter', "tier": 'Mythic'},
    {"ore": 'Joey Crystal', "rarity": 600004, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Galactic Gem', "rarity": 656339, "layer": 'Outer Space', "tier": 'Mythic'},
    {"ore": 'Celestial Gem', "rarity": 756345, "layer": 'Outer Space', "tier": 'Mythic'},
    {"ore": 'Splendidium Crystal', "rarity": 900004, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Water Gem', "rarity": 987654, "layer": '?', "tier": 'Mythic'},
    {"ore": 'Abyssal Gem', "rarity": 999999, "layer": 'Vacuum', "tier": 'Mythic'},
]


# ── World 0: Digita：事件清單（按稀有度升序）───────────────────────────────────
# 資料源：rex-reincarnated wiki World 0 頁 Events 表（2026-07-05 fetch_ores 風格解析）。
# AI/數位世界。tier=預設 "B"（wiki 無此欄位，僅排序參考、不影響任何判斷邏輯，待人工評級）。
_WORLD0_EVENTS: list[dict] = [
    {
        "match": 'flurry of stars strengthens',
        "ore": 'Nebula Tempest',
        "rarity": 1000000,
        "duration_s": 900,
        "chance_per_s": 150,
        "effect": "Boosts the player's walkspeed by +5 Speed.Summons a star shower around the player.",
        "tier": "B",
    },
    {
        "match": 'stardust from across space',
        "ore": 'Aetherion',
        "rarity": 1564444,
        "duration_s": 2100,
        "chance_per_s": 1000,
        "effect": "Makes Stardust spawn naturally.Boosts The Inktorb's luck to 1.7 Luck.Adds an event roll for Starry Caves at a boosted rate of 1/8.",
        "tier": "B",
    },
    {
        "match": 'soothing frequencies emit from',
        "ore": 'Antlerion',
        "rarity": 11086357,
        "duration_s": 1140,
        "chance_per_s": 1500,
        "effect": 'Cave Exclusive ores receive a 1.15 luck boost.Automatically tracks supernatural ores spawned by you or naturally by the mine.Lucidium Locator recharges twice as fast.',
        "tier": "B",
    },
    {
        "match": 'emissions of redacted signals',
        "ore": 'CORRUPTELA',
        "rarity": 19910012,
        "duration_s": 960,
        "chance_per_s": 200,
        "effect": 'Every 30 second Lifespan, all stats are multiplied by random numbers between 0.7 and 1.4.Applies a VHS-filter to the screen.',
        "tier": "B",
    },
    {
        "match": 'starlit vistas shine upon',
        "ore": 'Cosmonolithius',
        "rarity": 25000000,
        "duration_s": 1500,
        "chance_per_s": 290,
        "effect": "Boosts The Inktorb's luck to 1.6 Luck.",
        "tier": "B",
    },
    {
        "match": 'sudden electric fluxes charge',
        "ore": 'Photon Fluxulite',
        "rarity": 30000000,
        "duration_s": 900,
        "chance_per_s": 360,
        "effect": "Boosts the player's walkspeed by +15% Speed.Boosts the player's jump height by +10% Jump.Boosts the player's max health by +20% Health.Cybernetium Radar recharges twice as fast.",
        "tier": "B",
    },
    {
        "match": 'strifes in fabric plateau',
        "ore": 'Darkmatter Stabilizer',
        "rarity": 34971563,
        "duration_s": 600,
        "chance_per_s": 650,
        "effect": "Boosts The Inktorb's luck to 2 Luck.",
        "tier": "B",
    },
    {
        "match": 'magical shimmers cleave into',
        "ore": 'Nebulova',
        "rarity": 43129183,
        "duration_s": 2700,
        "chance_per_s": 750,
        "effect": "All cave types roll ores from Starry Caves at a 3x rarity increase.Boosts The Inktorb's luck to 1.55 Luck.",
        "tier": "B",
    },
    {
        "match": 'luscious holograms fluoresce with',
        "ore": 'Virtuosity',
        "rarity": 59130299,
        "duration_s": 1800,
        "chance_per_s": 555,
        "effect": 'All ores in the Matricite Layer receive a +20% luck boost.All ores in any other layer receive a +10% luck boost.Applies a green tint to the screen.',
        "tier": "B",
    },
    {
        "match": 'virtual barricade assembles at',
        "ore": 'The Firewall',
        "rarity": 60300120,
        "duration_s": 2100,
        "chance_per_s": 800,
        "effect": '- ores in the Virus Layer receive a +15% luck boost. Disables the gimmick of the Virus Layer.Event ends if TR0J4N or SCARLET spawns.',
        "tier": "B",
    },
    {
        "match": 'lights from the steel',
        "ore": 'Mekanos',
        "rarity": 320830300,
        "duration_s": 2100,
        "chance_per_s": 1900,
        "effect": 'Increases lighting saturation.Extremely vibrant ores (HSL brightness = 1, lightness >= 0.5) gain a +20% luck boost.The affected ores are:Magenta, Cyan, Yellow, Capella, Antistone, Crosswire, Partition, Nullum, Circadia, Endolite, Matrix Remnant, Viralburst, Entropite, Hackware Decimate, Virophage, Dualisplite, Zalgrain, Adasparta, RGB, Cobaltax, Poor Connection, Electricore, Matrisse, MK2 Sonar, Fulmara, Limelight, Δ, Amaranthine, CORRUPTELA, Chaotica, Roundabout, Luminosaic, Terascental, Voltiflux, Speedulant, Virtulily, Pixelated Mass, Matrixalga, Sustained Axiom, Novurbite, CHECKPOINT.0901, Equalizosity, Thermazine, Unstable Megacore and SCARLET.',
        "tier": "B",
    },
    {
        "match": 'celestial message reverberates from',
        "ore": 'Theon',
        "rarity": 590300300,
        "duration_s": 1800,
        "chance_per_s": 2100,
        "effect": "Makes Array spawn naturally.Boosts The Inktorb's luck to 1.8 Luck.Adds an event roll for Matrix Caves at a boosted rate of 1/5.",
        "tier": "B",
    },
    {
        "match": 'rifts in space time',
        "ore": 'C◊SMIC_SPLIT',
        "rarity": 840500500,
        "duration_s": None,
        "chance_per_s": 3000,
        "effect": 'Boosts tool proc rate inversely proportional to the mine capacity, starting at x1.35 and decreasing to x1.15.Increases lighting contrast.',
        "tier": "B",
    },
    {
        "match": 'again and again and',
        "ore": '∞',
        "rarity": 20000000000,
        "duration_s": None,
        "chance_per_s": None,
        "effect": '}',
        "tier": "B",
    },
]

# ── World 1: Natura：事件清單（按稀有度升序）───────────────────────────────────
# 資料源：rex-reincarnated wiki World 1 頁 Events 表（2026-07-05 fetch_ores 風格解析）。
# 自然/古老王國。tier=預設 "B"（wiki 無此欄位，僅排序參考、不影響任何判斷邏輯，待人工評級）。
_WORLD1_EVENTS: list[dict] = [
    {
        "match": 'mystical clock s ticking',
        "ore": 'Temporum',
        "rarity": 2600000,
        "duration_s": 600,
        "chance_per_s": 300,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'searing blue mineral forms',
        "ore": 'Blazuine',
        "rarity": 3800000,
        "duration_s": 300,
        "chance_per_s": 400,
        "effect": "Boosts The Inktorb's luck to 1.6 Luck.",
        "tier": "B",
    },
    {
        "match": 'volatile substance bursts out',
        "ore": 'Combustal',
        "rarity": 3850000,
        "duration_s": 300,
        "chance_per_s": 340,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'lustrous crystal shard illuminates',
        "ore": 'Vitrilyx',
        "rarity": 4444444,
        "duration_s": 900,
        "chance_per_s": 244,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'almighty crystal glitters green',
        "ore": 'Spristium',
        "rarity": 8600000,
        "duration_s": 2700,
        "chance_per_s": 180,
        "effect": 'All ores locked to the Granite Layer are 20% more common.',
        "tier": "B",
    },
    {
        "match": 'abstract shape changing metal',
        "ore": 'Euclideum',
        "rarity": 9898845,
        "duration_s": 600,
        "chance_per_s": 544,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'peculiar crystal reveals its',
        "ore": 'Quandrium',
        "rarity": 14500000,
        "duration_s": 1500,
        "chance_per_s": 200,
        "effect": 'Makes Chroma Contaris and Musgravite 4x (400%) more common. Does not stack with luck boosts.',
        "tier": "B",
    },
    {
        "match": 'ground sizzles below your',
        "ore": 'Cleopatrite',
        "rarity": 14500000,
        "duration_s": 1500,
        "chance_per_s": 200,
        "effect": 'Makes Sunstone, Incinderium, Core Fragment, and Solarite 3x (300%) more common. Does not stack with luck boosts.',
        "tier": "B",
    },
    {
        "match": 'you feel nauseated as',
        "ore": 'Sentient Viscera',
        "rarity": 22000000,
        "duration_s": 600,
        "chance_per_s": 250,
        "effect": "Pinned ores recieve a +10% luck boost.Boosts The Inktorb's luck to 1.8 Luck.",
        "tier": "B",
    },
    {
        "match": 'pale shimmering fragment bursts',
        "ore": 'Pastelorium',
        "rarity": 26580000,
        "duration_s": 180,
        "chance_per_s": 2000,
        "effect": 'Makes Elusium and Elysian 5x (500%) more common. Does not stack with luck boosts.',
        "tier": "B",
    },
    {
        "match": 'ethereal glow illuminates the',
        "ore": 'Lucidium',
        "rarity": 28277282,
        "duration_s": 600,
        "chance_per_s": 200,
        "effect": 'Light-based gears"Light-based gears" refer to the Candilium Candle, Accretium Fireball, Flashlight, Suncindium Flashbang and Luminatite Lantern. give a +5% luck boost.Cave exclusive ores have a +5% luck boost.',
        "tier": "B",
    },
    {
        "match": 'black inky substance accumulates',
        "ore": 'Inkonium',
        "rarity": 46700000,
        "duration_s": 1200,
        "chance_per_s": 666,
        "effect": "Adds an event roll for Void Caves at a boosted rate of 1/9.Makes Voidstone able to spawn anywhere.Boosts The Inktorb's luck to 2 Luck.",
        "tier": "B",
    },
    {
        "match": 'you feel a strong',
        "ore": 'Magnetyx',
        "rarity": 48000000,
        "duration_s": 300,
        "chance_per_s": 300,
        "effect": 'Gears receive a 25% proc rate boost. Adds an event roll for Metallic Caves at a boosted rate of 1/5.',
        "tier": "B",
    },
    {
        "match": 'strange feeling clouds up',
        "ore": 'Vaporwave Crystal',
        "rarity": 50000000,
        "duration_s": 1200,
        "chance_per_s": 300,
        "effect": "Makes Intoxium able to spawn anywhere with a rarity of '''1 in 255,000'''.All layers have a +5% luck boost.",
        "tier": "B",
    },
    {
        "match": 'presence of an astronomical',
        "ore": 'Ω',
        "rarity": 50000000,
        "duration_s": None,
        "chance_per_s": 1000,
        "effect": 'Adds an event roll for Divine Caves at a boosted rate of 1/10.Makes Etherstone be able to spawn anywhere.Cave types rarer than 1/20 receive a +30% spawn chance boost.',
        "tier": "B",
    },
    {
        "match": 'radiant spiral of magic',
        "ore": 'Candilium',
        "rarity": 55000000,
        "duration_s": 1500,
        "chance_per_s": 300,
        "effect": 'Removes Bedrock from the Inner Core Layer.',
        "tier": "B",
    },
    {
        "match": 'vibrant glint flashes in',
        "ore": 'Idolium',
        "rarity": 140000000,
        "duration_s": 1500,
        "chance_per_s": 400,
        "effect": 'Adds an event roll for Prismatic Caves at a boosted rate of 1/10.Makes Prismatistone able to spawn anywhere.Prismatic Cave spawns have a +15% luck boost.',
        "tier": "B",
    },
    {
        "match": 'you shiver as the',
        "ore": 'Inclemetite',
        "rarity": 225000000,
        "duration_s": 1500,
        "chance_per_s": 400,
        "effect": 'Adds an event roll for Frozen Caves at a boosted rate of 1/3.Makes Ice spawn naturally in Basalt.All ores in Basalt receive a +7.5% luck boost.',
        "tier": "B",
    },
    {
        "match": 'pallid radiance tenuously lights',
        "ore": 'Illusory Bubblegram',
        "rarity": 342000040,
        "duration_s": None,
        "chance_per_s": 1111,
        "effect": 'Adds an event roll for Elemental Caves at a boosted rate of 1/9.Makes Celestone able to spawn anywhere.Cave-rolled ores receive a +20% luck boost.',
        "tier": "B",
    },
]

# ── World 2：事件清單（按稀有度升序）───────────────────────────────────
# 資料源：rex-reincarnated wiki World 2 頁 Events 表（2026-07-05 fetch_ores 風格解析）。
# 板岩/永久凍土＋銀河魔法洞穴。tier=預設 "B"（wiki 無此欄位，僅排序參考、不影響任何判斷邏輯，待人工評級）。
_WORLD2_EVENTS: list[dict] = [
    {
        "match": 'core of a star',
        "ore": 'Arcaleus',
        "rarity": 4418000,
        "duration_s": 600,
        "chance_per_s": 355,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'microscopic quarks orbit around',
        "ore": 'Atomium',
        "rarity": 6110020,
        "duration_s": 600,
        "chance_per_s": 305,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'clusters of rocks begin',
        "ore": 'Circeterra',
        "rarity": 8100000,
        "duration_s": 600,
        "chance_per_s": 400,
        "effect": "Boosts The Inktorb's luck to 1.6x.",
        "tier": "B",
    },
    {
        "match": 'shooting star streaks across',
        "ore": 'Estrela',
        "rarity": 10520000,
        "duration_s": 1200,
        "chance_per_s": 360,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'once frozen heart begins',
        "ore": 'Heart of the Frosted',
        "rarity": 11750000,
        "duration_s": 1500,
        "chance_per_s": 275,
        "effect": "Applies a slippery effect to Permafrost.All ores are +10% more common while mining in the Permafrost Layer.Boosts The Inktorb's luck to 1.6 Luck.",
        "tier": "B",
    },
    {
        "match": 'galactic hues emerge far',
        "ore": 'Galactic Rupture',
        "rarity": 16250000,
        "duration_s": 1200,
        "chance_per_s": 225,
        "effect": 'Special caves receive a +20% spawn chance boost.',
        "tier": "B",
    },
    {
        "match": 'high voltage plasma releases',
        "ore": 'Plasmonium',
        "rarity": 17725000,
        "duration_s": 300,
        "chance_per_s": 550,
        "effect": 'Increases recharge chance of Lucidium Locator by 20%.Reduces Cybernetium Radar ability cooldowns by 12 seconds.',
        "tier": "B",
    },
    {
        "match": 'generations of lost spirits',
        "ore": 'Spiritian',
        "rarity": 19828000,
        "duration_s": 900,
        "chance_per_s": 450,
        "effect": "Increases luck boost from Soul Scythe's blue blocks by '''+0.0004x'''.",
        "tier": "B",
    },
    {
        "match": 'electrifying forces convulse beneath',
        "ore": 'Catastormite',
        "rarity": 22530000,
        "duration_s": 2100,
        "chance_per_s": 475,
        "effect": 'Automatically tracks + ores spawned by you or naturally by the mine.',
        "tier": "B",
    },
    {
        "match": 'unknown signal emerges from',
        "ore": 'NOO S-Sing. T1',
        "rarity": 28310000,
        "duration_s": 2100,
        "chance_per_s": 405,
        "effect": "Mythic tier and below ores in the Darkmatter and Void layers are +10% more common.Boosts The Inktorb's luck to 1.8x.",
        "tier": "B",
    },
    {
        "match": 'scorching heat emerges from',
        "ore": 'Coronal Flare',
        "rarity": 50505050,
        "duration_s": 2100,
        "chance_per_s": 325,
        "effect": 'Pickaxes and Gears receive a +10% proc rate boost.',
        "tier": "B",
    },
    {
        "match": 'frigid gases cool the',
        "ore": 'Frostrainium',
        "rarity": 66288400,
        "duration_s": 300,
        "chance_per_s": 650,
        "effect": 'All Cave Exclusive ores are 15% more common.',
        "tier": "B",
    },
    {
        "match": 'gyrating iridescent star shines',
        "ore": 'Vitriol',
        "rarity": 71749500,
        "duration_s": 2700,
        "chance_per_s": 450,
        "effect": 'Ores are 10% more common in all layers except the Void Layer.Disables fake spawns in the Void Layer unless Candilium Candle is equipped.',
        "tier": "B",
    },
    {
        "match": 'energy deep within the',
        "ore": 'Obliveracy Endmost',
        "rarity": 75000750,
        "duration_s": 300,
        "chance_per_s": 675,
        "effect": "Gears with manually-activated abilities receive a +10% proc rate boost.Boosts The Inktorb's luck to 2x.",
        "tier": "B",
    },
    {
        "match": 'chromatic shards crystallize throughout',
        "ore": 'Acrimony',
        "rarity": 191847000,
        "duration_s": 3300,
        "chance_per_s": 725,
        "effect": 'and ores are 10% more common.',
        "tier": "B",
    },
    {
        "match": 'fragments of a distant',
        "ore": 'NOO P α',
        "rarity": 565656000,
        "duration_s": 1800,
        "chance_per_s": 1900,
        "effect": "Green Riftrock makes fake ores in the Void Layer and all layers receive a +10% luck boost.Purple Riftrock boosts the luck of cave type ores by 5% and all cave types receive a 10% spawn chance boost.Boosts The Inktorb's luck to 2.1x.",
        "tier": "B",
    },
]

# ── Subworld 1: Luna Refuge：事件清單（按稀有度升序）───────────────────────────────────
# 資料源：rex-reincarnated wiki Subworld 1 頁 Events 表（2026-07-05 fetch_ores 風格解析）。
# 月球/太空聚落。tier=預設 "B"（wiki 無此欄位，僅排序參考、不影響任何判斷邏輯，待人工評級）。
_SUBWORLD1_EVENTS: list[dict] = [
    {
        "match": 'confidential information from the',
        "ore": 'Lunar Codex',
        "rarity": 213337,
        "duration_s": 2700,
        "chance_per_s": 1337,
        "effect": "Boosts The Inktorb's luck to x1.55.",
        "tier": "B",
    },
    {
        "match": 'sweat beads accumulate on',
        "ore": 'Lunar Flaeon',
        "rarity": 1333333,
        "duration_s": 1200,
        "chance_per_s": 200,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'air gets colder around',
        "ore": 'Lunar Freon',
        "rarity": 1333333,
        "duration_s": 1200,
        "chance_per_s": 200,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'skin prickles and stings',
        "ore": 'Lunar Poiseon',
        "rarity": 1333333,
        "duration_s": 1200,
        "chance_per_s": 200,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'quarry decays below your',
        "ore": 'Lunar Astatine',
        "rarity": 2000000,
        "duration_s": 900,
        "chance_per_s": 350,
        "effect": "Boosts The Inktorb's luck to x2.",
        "tier": "B",
    },
    {
        "match": 'powerful force emits from',
        "ore": 'Sagittarius Quasar',
        "rarity": 2500000,
        "duration_s": 1500,
        "chance_per_s": 300,
        "effect": "Boosts The Inktorb's luck to x1.7.",
        "tier": "B",
    },
    {
        "match": 'birth of an almighty',
        "ore": 'Protoflare',
        "rarity": 6000000,
        "duration_s": 360,
        "chance_per_s": 350,
        "effect": "Gives a +10% luck boost to any cave-type ores.Boosts The Inktorb's luck to x1.85.",
        "tier": "B",
    },
    {
        "match": 'e s t h e t',
        "ore": 'Vaporwave Pulsar',
        "rarity": 9500000,
        "duration_s": 900,
        "chance_per_s": 450,
        "effect": 'Quintuples the chance of finding Garnet in Moonrock.',
        "tier": "B",
    },
    {
        "match": 'high mass compact rotating',
        "ore": 'RGB Pulsar',
        "rarity": 45555555,
        "duration_s": None,
        "chance_per_s": 550,
        "effect": 'Increases chances of Interstellar, Magmatic, and Radioactive caves to spawn by 20%.',
        "tier": "B",
    },
]

# ── Subworld 2: Farlight：事件清單（按稀有度升序）───────────────────────────────────
# 資料源：rex-reincarnated wiki Subworld 2 頁 Events 表（2026-07-05 fetch_ores 風格解析）。
# 太空/反物質世界。tier=預設 "B"（wiki 無此欄位，僅排序參考、不影響任何判斷邏輯，待人工評級）。
_SUBWORLD2_EVENTS: list[dict] = [
    {
        "match": 'light from the antimatter',
        "ore": 'Anti-Shadow Crystal',
        "rarity": 5750000,
        "duration_s": 300,
        "chance_per_s": 300,
        "effect": 'None',
        "tier": "B",
    },
    {
        "match": 'gravitational force drags you',
        "ore": 'SGR_A',
        "rarity": 19499240,
        "duration_s": 2100,
        "chance_per_s": 500,
        "effect": 'Decreases world gravity by 10%.',
        "tier": "B",
    },
    {
        "match": 'glimmer of hope flickers',
        "ore": "Thai's Star",
        "rarity": 22222222,
        "duration_s": 900,
        "chance_per_s": 400,
        "effect": 'All ores in the Vacuum Layer are +20% more common.',
        "tier": "B",
    },
    {
        "match": 'endless machinations signal money',
        "ore": 'Tycoon Crystal',
        "rarity": 22500004,
        "duration_s": 1800,
        "chance_per_s": 600,
        "effect": 'All the ores with the word "Crystal" in their name become *1.1x more common.',
        "tier": "B",
    },
    {
        "match": 'magmatic flares scorch the',
        "ore": 'X-Flare',
        "rarity": 31250000,
        "duration_s": 1800,
        "chance_per_s": 2000,
        "effect": 'All abilities are +20% more likely to trigger.',
        "tier": "B",
    },
    {
        "match": 'golden relic buried long',
        "ore": "Agsperum's Charm",
        "rarity": 34250000,
        "duration_s": 2700,
        "chance_per_s": 750,
        "effect": 'This ore can only be spawned when this event is active.Ores in the Space Rock Layer are +10% more common.',
        "tier": "B",
    },
    {
        "match": 'swirling vortex begins to',
        "ore": 'Void Eye',
        "rarity": 44444444,
        "duration_s": 3000,
        "chance_per_s": 800,
        "effect": "Sets The Inktorb's luck to 1.8x.Abilities in the Vacuum Layer are +20% more likely to activate.",
        "tier": "B",
    },
    {
        "match": 'bolting flashes of light',
        "ore": 'Hyperstar',
        "rarity": 65400100,
        "duration_s": 900,
        "chance_per_s": 1000,
        "effect": "Default Pickaxe's luck is set to 1.29 ^ P, where P is the tier of your highest owned pickaxe.This luck boost overrides any other luck bonuses, such as layer luck from events or the multiplicative boost from Candilium Candle.",
        "tier": "B",
    },
    {
        "match": 'vibrant patterns give color',
        "ore": 'X2 Crystal',
        "rarity": 75554224,
        "duration_s": 2400,
        "chance_per_s": 700,
        "effect": 'Variant ores are +15% more common.',
        "tier": "B",
    },
    {
        "match": 'this will be a',
        "ore": 'Shadow-X',
        "rarity": 136932133,
        "duration_s": 1800,
        "chance_per_s": 5000,
        "effect": "Sets The Inktorb's luck to 3x.The Inktorb now has a 20% chance of making any ores it generates fake.All cave types receive a +25% spawn chance boost.X2-Bomb's abilities are *1.2x more likely to trigger.",
        "tier": "B",
    },
    {
        "match": 'off in the distance',
        "ore": 'Polaris Australis',
        "rarity": 140000000,
        "duration_s": None,
        "chance_per_s": 1500,
        "effect": 'This ore can only spawn while this event is active.All radial explosions have their volume increased by +10%.',
        "tier": "B",
    },
    {
        "match": 'benedictio antiqua dignitatem tuam',
        "ore": 'Troylezian',
        "rarity": 222333444,
        "duration_s": 900,
        "chance_per_s": 2500,
        "effect": "Before luck is applied, adds '''10,000,000,000''' to Fiction's rarity.After luck is applied, subtracts '''10,000,000,000''' from Fiction's rarity.This event's effect cannot reduce Fiction's rarity to below '''1 in 7,500,000,000'''.",
        "tier": "B",
    },
    {
        "match": 'hypnotic happiness floods the',
        "ore": 'Serotonin',
        "rarity": 432198765,
        "duration_s": 900,
        "chance_per_s": 3000,
        "effect": "Sets The Inktorb's luck to 2.1x.Dark ores (HSL lightness Affected ores: Chroma, Equinox, Spoogalite, Andromedite, Vyrixial, Astarium, Corrupt Electronite, Nebulum, Adamantium, Corrupt Adamantium, Void Neutronite, Galactic Gem, Celestial Gem, Abyssal Gem, Nemesis Crystal, Vortex Crystal, RGB Crystal, Cryptical, SGR_A, Tycoon Crystal, Copy Crystal, Shadow Cherkasyl, Chromablank, Serotonin, Shadow-X, and Fiction. gain a *1.15x luck boost.",
        "tier": "B",
    },
    {
        "match": 'this morning sky has',
        "ore": 'Prisma',
        "rarity": 1222222222,
        "duration_s": None,
        "chance_per_s": 4000,
        "effect": 'Ores in the Antimatter, Vacuum and ??? layers are +30% more common.Ores in the Space Rock and Outer Space layers are',
        "tier": "B",
    },
]


# ── 世界登記 + 目前世界偵測 ─────────────────────────────────────────────
# 所有登記世界皆具事件與低階礦物資料，支援 D4、世界偵測與採集排除。
AESTERIA = World("Aesteria", _AESTERIA_EVENTS, _AESTERIA_COMMON_ORES)
LUCERNIA = World("Lucernia", _LUCERNIA_EVENTS, _LUCERNIA_COMMON_ORES)
# 下列五世界事件（wiki Events 表）＋ common_ores 皆齊 → D4 keep/reroll、世界自動偵測、
# 採集排除全部生效。tier 欄位為預設（wiki 無此評級，僅排序參考）。
# 世界名用 wiki 標準鍵（「World 0」等，與 fetch_ores / assets/rare_ores.json 一致）。
WORLD0 = World("World 0", _WORLD0_EVENTS, _WORLD0_COMMON_ORES)          # Digita（AI/數位）
WORLD1 = World("World 1", _WORLD1_EVENTS, _WORLD1_COMMON_ORES)          # Natura（自然/王國）
WORLD2 = World("World 2", _WORLD2_EVENTS, _WORLD2_COMMON_ORES)          # 板岩/永久凍土＋魔法洞穴
SUBWORLD1 = World("Subworld 1", _SUBWORLD1_EVENTS, _SUBWORLD1_COMMON_ORES) # Luna Refuge（月球聚落）
SUBWORLD2 = World("Subworld 2", _SUBWORLD2_EVENTS, _SUBWORLD2_COMMON_ORES) # Farlight（太空/反物質）
WORLDS: dict[str, World] = {
    "Aesteria": AESTERIA, "Lucernia": LUCERNIA,
    "World 0": WORLD0, "World 1": WORLD1, "World 2": WORLD2,
    "Subworld 1": SUBWORLD1, "Subworld 2": SUBWORLD2,
}

# Discord 表情分頁按鈕：世界 → emoji。新增世界時這裡也要加對應表情（表情要互異，
# 且測試 test_world_emoji_covers_all_registered_worlds 鎖 WORLDS/WORLD_EMOJI 鍵一致）。
# 使用者在 Discord 點表情 → 切換到該世界的事件分頁（編輯同一則 list 訊息）。
# emoji 依各世界 wiki 主題描述挑選：🌍 Aesteria 夏日島／🌙 Lucernia 季節薄暮／
# 🤖 World 0: Digita AI 數位／🌳 World 1: Natura 自然王國／🔮 World 2 銀河魔法／
# 🌕 Subworld 1: Luna Refuge 月球聚落／🌌 Subworld 2: Farlight 太空反物質。
WORLD_EMOJI: dict[str, str] = {
    "Aesteria": "🌍", "Lucernia": "🌙",
    "World 0": "🤖", "World 1": "🌳", "World 2": "🔮",
    "Subworld 1": "🌕", "Subworld 2": "🌌",
}


def emoji_to_world(emoji: str) -> str | None:
    """表情 → 世界名（找不到回 None）。Discord 表情分頁切換用。"""
    for w, em in WORLD_EMOJI.items():
        if em == emoji:
            return w
    return None


# ── 層別深度區間（wiki 同步：`python -m miningbot.fetch_layers` 印 diff）──────
# 為什麼要這張表：**遊戲畫面不會顯示「你在第幾層」**。唯一可機讀的位置訊號是頂部
# 那行 Depth 數值，而層→深度是 wiki 記載的固定區間，故 (世界, 深度) 可逆推層別。
# 用途：回礦落地時把「實際到達的層」記進 ledger 當 ground truth，取代原本只記
# 使用者宣告字串 `sticky_layer` 的作法（該字串 bot 從不驗證，實測 20 筆點擊有 5 筆
# 標成 Mantle Layer 但畫面實為 Shamrock）。
#
# ⚠ 三個踩過的坑，改這張表前先讀：
#   1. **深度區間跨世界完全重疊**——每個世界都從 0-999 起、每 1000m 一層。
#      0-999m 同時是 Spookstone/Lucitreum/Statistone/Stone/Slate/Moon Stone/
#      Space Rock。所以查表的鍵**必須含世界**，只有深度定不出層。
#   2. **層名非全域唯一，同名層在不同世界深度不同**——Jollystone 在 Aesteria 是
#      5000-5999，在（已併入 Aesteria 的）Wintera Isle 是 1000-1999。wiki infobox
#      的 depth 欄會並列多段，抓取時必須挑本世界那段。
#   3. **深度會超出表**——實測 25790m（tests/fixtures/reentry/h046_depth_25790m.png）
#      是 H043 虛空墜落的讀數，不是合法層深。區間外一律回 None，**不可夾到最近的層**。
#
# 每層未必是 1000m：World 1 的 Core 拆成 Outer 7000-7499 / Inner 7500-7999 兩個
# 500m 層（wiki `[[Core Layer|Outer Core]]`／`[[Core Layer|Inner Core]]` 共用同頁）；
# Subworld 2 的 ??? 是 4000-5999 兩千米寬。所以查表用實際區間、不可用 depth//1000。
LAYER_DEPTHS: dict[str, tuple[tuple[str, int, int], ...]] = {
    "Aesteria": (
        ("Spookstone", 0, 999), ("Affement", 1000, 1999),
        ("Withered Sand", 2000, 2999), ("Hexafite", 3000, 3999),
        ("Deepfrost", 4000, 4999), ("Jollystone", 5000, 5999),
        ("Maculite", 6000, 6999), ("Surmilum", 7000, 7999),
        ("Sugarstone", 8000, 8999), ("Delucemite", 9000, 9999),
    ),
    "Lucernia": (
        ("Lucitreum", 0, 999), ("Cicallite", 1000, 1999),
        ("Confectent", 2000, 2999), ("Foligrass", 3000, 3999),
        ("Sepulcrum", 4000, 4999), ("Wickrock", 5000, 5999),
        ("Amourite", 6000, 6999), ("Shamrock", 7000, 7999),
        ("Brittlestone", 8000, 8999), ("Harmonine", 9000, 9999),
    ),
    "World 0": (
        ("Statistone", 0, 999), ("Wireframe", 1000, 1999),
        ("Matricite", 2000, 2999), ("Mechaloid", 3000, 3999),
        ("Steel", 4000, 4999), ("Penumbrum", 5000, 5999),
        ("Twilement", 6000, 6999), ("Cosmorock", 7000, 7999),
        ("Glitch", 8000, 8999), ("Virus", 9000, 9999),
    ),
    "World 1": (
        ("Stone", 0, 999), ("Basalt", 1000, 1999),
        ("Granite", 2000, 2999), ("Diorite", 3000, 3999),
        ("Obsidian", 4000, 4999), ("Marble", 5000, 5999),
        ("Mantle", 6000, 6999), ("Outer Core", 7000, 7499),
        ("Inner Core", 7500, 7999),
    ),
    "World 2": (
        ("Slate", 0, 999), ("Permafrost", 1000, 1999),
        ("Shatterstone", 2000, 2999), ("Riftrock", 3000, 3999),
        ("Darkmatter", 4000, 4999), ("Void", 5000, 5999),
    ),
    "Subworld 1": (
        ("Moon Stone", 0, 999), ("Moon Mantle", 1000, 1999),
        ("Moon Core", 2000, 2999), ("Rocc", 3000, 3999),
    ),
    "Subworld 2": (
        ("Space Rock", 0, 999), ("Outer Space", 1000, 1999),
        ("Antimatter", 2000, 2999), ("Vacuum", 3000, 3999),
        ("???", 4000, 5999),
    ),
}

# 深度可變、**故意不列入 LAYER_DEPTHS** 的層。Frost 是活動特殊層，每次礦場重置會
# 隨機取代掉一層（wiki infobox 寫 `depth = Variable`），沒有固定區間；活動期間某個
# 深度帶未必是表上那層 → 查表結果在 Frost 活動中不可信。列在這裡是為了讓
# fetch_layers 的 diff 不會每次都報「wiki 有但 game_data 缺」。
VARIABLE_DEPTH_LAYERS: frozenset[str] = frozenset({"Frost"})


def layer_for_depth(world: str | None, depth_m: float | None) -> str | None:
    """(世界, 深度 m) → 層名；任一項缺失或深度落在區間外都回 None。

    回 None 的情形都是「無法斷定」而非「錯誤」，呼叫端應照舊走原本的
    sticky_layer 宣告值，不要因為查不到就中斷流程：
      - world/depth 為 None（世界尚未偵測到、Depth OCR 讀不到或讀到 Surface）
      - world 不在 LAYER_DEPTHS（新世界還沒同步）
      - depth 落在所有區間外（H043 虛空墜落實測 25790m；負值）
    """
    if world is None or depth_m is None:
        return None
    for name, lo, hi in LAYER_DEPTHS.get(world, ()):
        if lo <= depth_m <= hi:
            return name
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


def detect_world_from_ore(ore_name: str) -> str | None:
    """從被動聊天「has found X」的礦名 X 反推世界：哪個世界的 common_ores 命中此名。

    結構同 `detect_world`（事件版），差別是掃 common_ores 而非 events，且來源是
    D3 verify 已在讀的聊天行（零額外 OCR 成本，可補足事件訊號尚未出現的情況）。剝變體
    前綴/冠詞後（沿用 classify_found_ore 同一套 `_strip_variant` 前處理）用
    startswith 找命中世界；唯一命中一個世界 → 回該世界名；零個或跨世界撞名 → None
    （保守，同 detect_world 的規則——不確定就不鎖，寧可繼續用聯集排除清單）。
    """
    from .ocr import _strip_variant
    if not ore_name:
        return None
    base = _strip_variant(ore_name.strip().lower())
    if not base:
        return None
    hit = {name for name, w in WORLDS.items()
           if any(base.startswith(o["ore"].lower()) for o in w.common_ores)}
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


# ── 偵測階級門檻（2026-08-02）：可調高「什麼算稀有」的最低階級 ──────────────
# 階級順序＝fetch_ores.HIGH_TIERS（唯一來源；順序即高低）。
# classify_found_ore 在命中 rare 礦後檢查 tier ≥ 門檻；低於 → 回 "common"。
# 效果蔓延到面板色檢、救援路 A/B、採集驗證、通知標注——無需逐處改動。
from .fetch_ores import HIGH_TIERS as _HIGH_TIERS
_TIER_ORDER: dict[str, int] = {t: i for i, t in enumerate(_HIGH_TIERS)}
HIGH_TIER_NAMES: tuple[str, ...] = _HIGH_TIERS   # 供 web/DC 驗證用（唯一來源）

# 量測到的 tier→面板底色色相（2026-07-31 D11 + 2026-08-02 實機全面板截圖驗證）。
# 六階色相在實機面板上量到，3/6 與 wiki 官方 HSV 比對誤差 ≤1°：
#   Exotic wiki 45° vs 實機 46°｜Enigmatic wiki 70° vs 實機 70°｜Otherworldly wiki 333° vs 實機 334°
#   Exquisite/Transcendent/Unfathomable 的 wiki 頁面無 HEX 欄位，靠實機量測。
# Imaginary / Zenith 未量測——靠 non_low_tier_hues 反向閘兜住。
# ⚠ Transcendent 210° 與 Unfathomable 218° 僅差 8°，tol=6 時帶邊重疊（212-216）；
#   兩階都屬高階，對偵測無影響；門檻設在兩階之間時色相交叉驗有模糊空間。
TIER_HUES: dict[str, float] = {
    "Exotic": 46.0,       # 黃     wiki F6C940 HSV 45°
    "Exquisite": 128.0,   # 綠
    "Transcendent": 210.0,  # 藍
    "Enigmatic": 70.0,    # 亮綠/金 wiki CDF600 HSV 70°
    "Unfathomable": 218.0,  # 深藍偏黑
    "Otherworldly": 334.0,  # 深紅   wiki 5E0E32 HSV 333°
}

_detection_min_tier: str | None = None   # None = 不過濾（預設）；測試不設 = 現行行為


def set_detection_min_tier(tier: str | None) -> None:
    """設定偵測系統的最低稀有階級。None 或 "Exotic" = 不過濾（現行行為）。

    模組級變數，GIL 下原子讀寫——Discord 輪詢執行緒寫、主迴圈讀，同 current_world 模式。
    """
    global _detection_min_tier
    _detection_min_tier = tier


def get_detection_min_tier() -> str | None:
    return _detection_min_tier


def _is_below_threshold(info: dict) -> bool:
    """info 的 tier 是否低於偵測門檻。

    無門檻（None）→ False。門檻＝Exotic（最低有效值）→ False（不過濾＝現行行為，
    含未知 tier）。門檻高於 Exotic → tier 未知（不在 _TIER_ORDER）也判 below
    （安全方向：未知的當低階）。
    """
    if _detection_min_tier is None:
        return False
    min_rank = _TIER_ORDER.get(_detection_min_tier, 0)
    if min_rank == 0:           # Exotic＝最低 → 不過濾（等同 None）
        return False
    tier_rank = _TIER_ORDER.get(info.get("tier", ""), -1)
    return tier_rank < min_rank


def effective_whitelist_hues(min_tier: str | None,
                             base_whitelist: tuple) -> tuple:
    """≥ min_tier 的量測色相（救援 whitelist_hue_hits 用）。

    min_tier=None / Exotic → 回 base 不動（現行行為）。
    門檻以上未量測的 tier 不在結果裡——那些靠名字閘分類，色相交叉驗無法確認（保守）。
    base_whitelist 與 TIER_HUES 取交集後再過濾，確保 config 自訂值不被靜默丟棄。
    """
    if min_tier is None or _TIER_ORDER.get(min_tier, 0) == 0:
        return base_whitelist
    min_rank = _TIER_ORDER.get(min_tier, 0)
    # 只保留 base_whitelist 裡也出現在 TIER_HUES 且 ≥ min_rank 的色相
    measured_above = {h for t, h in TIER_HUES.items()
                      if _TIER_ORDER.get(t, 999) >= min_rank}
    return tuple(h for h in base_whitelist if h in measured_above)


def effective_low_tier_hues(min_tier: str | None,
                            base_low_tier: tuple) -> tuple:
    """base_low_tier ＋ < min_tier 的量測色相（零點 non_low_tier_hues 用）。

    門檻以下的 tier 色相加入低階帶 → 零點閘不再為它們擋零點成立。
    去重保序（dict.fromkeys）。
    """
    if min_tier is None:
        return base_low_tier
    min_rank = _TIER_ORDER.get(min_tier, 0)
    below = tuple(h for t, h in TIER_HUES.items()
                  if _TIER_ORDER.get(t, 999) < min_rank)
    return tuple(dict.fromkeys(tuple(base_low_tier) + below))


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


_rare_ores_cache: dict | None = None    # world 名 → {正規化礦名 → info}；"__union__" = 聯集


def _load_rare_ores() -> dict:
    global _rare_ores_cache
    if _rare_ores_cache is None:
        import json
        by_world: dict = {}
        union: dict = {}
        try:
            with open(_rare_ores_path(), encoding="utf-8") as f:
                data = json.load(f)
            for world, rows in data.get("worlds", {}).items():
                table = {r["ore"].lower(): {**r, "world": world} for r in rows}
                by_world[world] = table
                union.update(table)
        except Exception:
            pass                      # 檔案缺/壞 → 空表（分類降級為 unknown，不炸主迴圈）
        by_world["__union__"] = union
        _rare_ores_cache = by_world
    return _rare_ores_cache


def rare_ores(world_name: str | None = None) -> dict:
    """正規化礦名 → {ore, tier, rarity, layer, world}（lazy 載入＋快取）。

    與 `common_ore_names` 同款收斂模式：給定世界（事件已鎖定）→ 只回該世界的表
    （不可能採到別世界的礦、同名礦跨世界階級可能不同）；None/未知世界 → 全世界聯集（保守）。
    """
    tables = _load_rare_ores()
    return tables.get(world_name) or tables["__union__"]


def rare_ore_names() -> tuple[str, ...]:
    """高階白名單的礦名（原大小寫、去重保序）——OCR 模糊匹配的詞彙表（H020 對策）。

    與 `common_ore_names` 同款收斂：世界已鎖定 → 該世界白名單；未定 → 全世界聯集。
    檔案缺/壞 → 空 tuple（fuzzy 兜底自動停用，行為安全降級回精確匹配）。
    """
    table = rare_ores(current_world_name())
    return tuple(dict.fromkeys(info["ore"] for info in table.values()))


# 三態分類的模糊兜底門檻（2026-07-04 H033 對策）：RapidOCR 對遊戲字型 i/l 同形的誤讀
# （Essentium→Essentlum=0.889、Diamantine→Dianantine=0.90）信心很高、精確 startswith
# 對不上 → 高階被標「⚠ 未知礦名」、低階誤讀洗版未知警告。0.80 遠高於 ocr 垃圾救援層的
# FUZZY_ORE_RATIO=0.62：這裡只修「近失拼字」，真正的清單漂移（新礦名）仍須落 unknown
# 浮出來（H020 垃圾 velyiiuinm→Valytium=0.667 必須不被吃掉）。
CLASSIFY_FUZZY_RATIO = 0.80


def _prefix_hit(base: str, name: str) -> bool:
    """`base` 以礦名 `name` 開頭，**且結束在名字邊界上**（H069）。

    裸 `startswith` 對短礦名是毒藥：Lucernia 白名單真的有一顆叫 `Eg`（Brittlestone、
    Transcendent），所以 `egguinox`.startswith(`eg`) → 一顆低階礦被判成 Transcendent。
    2026-07-31 harvest 145 實錄：交人工前救援因此假命中、靜默放生一顆真稀有礦。
    同型地雷還有 `It.` / `Luna` / `Sol` / `Y` / `Bug` / `Vys` / `Lynx`。

    尾端只放行**非英數**（OCR 雜訊 `bandeau!`、洞穴註記 ` (floral cave)`）——多一個
    字母屬於拼字近失，交給下面的模糊兜底判，不走精確路徑。
    """
    if not base.startswith(name):
        return False
    rest = base[len(name):]
    return not rest or not rest[0].isalnum()


def classify_found_ore(ore_text: str) -> tuple[str, dict | None]:
    """OCR 抽出的礦名（已小寫）→ ("common"|"rare"|"rare_fuzzy"|"unknown", 白名單 info 或 None)。

    與排除比對同一套容忍：剝 Ionized/Spectral 變體前綴、`_prefix_hit` 容忍尾端雜訊
    （OCR 噪音、洞穴註記「(floral cave)」）。common 優先於 rare（守門員先判）；
    兩張表都隨 current_world 收斂（排除清單走 common_ore_names、白名單走 rare_ores）。
    精確都對不上 → 模糊最近鄰兜底（CLASSIFY_FUZZY_RATIO；rare 須嚴格贏過 common、
    平手判 common——與 ocr 模糊路徑同的「寧漏勿假」規則）。"rare_fuzzy" 的 info
    是白名單 info 的複本、多帶 fuzzy_ratio（供通知標注 ≈ 讓人工核對是否誤配）。
    """
    from .ocr import _strip_variant, _best_match   # 單一事實來源；ocr 不 import 本模組、無循環
    if not ore_text:
        return "unknown", None
    base = _strip_variant(ore_text.strip().lower())
    if any(_prefix_hit(base, c.lower()) for c in common_ore_names()):
        return "common", None
    rare_table = rare_ores(current_world_name())
    for name, info in rare_table.items():
        if _prefix_hit(base, name):
            if _is_below_threshold(info):
                return "common", None
            return "rare", info
    # 模糊兜底：候選比照 ocr._fuzzy_rare_line 取「全部 / 前 1 / 前 2 個 token」
    # （容忍礦名後黏雜訊/洞穴註記，也涵蓋多字礦名），各表取最高分。
    tokens = base.split()
    if not tokens:
        return "unknown", None
    cands = {base, tokens[0], " ".join(tokens[:2])}
    common_pairs = [(c.lower(), c) for c in common_ore_names()]
    rare_pairs = [(name, name) for name in rare_table]
    best_common = max(_best_match(c, common_pairs)[0] for c in cands)
    best_rare, best_rare_name = max(
        (_best_match(c, rare_pairs) for c in cands), key=lambda t: t[0])
    if best_rare >= CLASSIFY_FUZZY_RATIO and best_rare > best_common:
        best_info = rare_table[best_rare_name]
        if _is_below_threshold(best_info):
            return "common", None
        return "rare_fuzzy", {**best_info, "fuzzy_ratio": best_rare}
    if best_common >= CLASSIFY_FUZZY_RATIO:
        return "common", None
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
        "description": "`keep <礦物名>` 保留｜`unkeep <礦物名>` 取消｜`clear` 全清｜`list [世界]` 切換（點下方表情直接跳世界）",
        "color": 0x00ff88,
        "fields": fields,
        "footer": {"text": "符號對照：" + "｜".join(f"{em} {w}" for w, em in WORLD_EMOJI.items())},
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
