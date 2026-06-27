"""REX 礦坑事件資料庫。

D4 右鍵刷新事件時，用來判斷目前的事件是否值得保留（左鍵確認）還是刷新（右鍵）。
每筆事件記錄：OCR 比對用片段（match）、礦物名（ore）、稀有度、持續時間、
每秒生成率（chance/s）、特殊效果（effect）。

資料來源：使用者提供（REX wiki + 實機，2026-06-28）。
未來方向：透過 Discord 訊息動態指定 keep 清單，控制哪些事件要保留。

純資料 + 純函式，可單元測試（不碰 OCR / I/O）。
"""
from __future__ import annotations


# ── 事件清單（按稀有度升序）─────────────────────────────────────────────
# match = OCR 比對用片段（遊戲內事件訊息的子字串，不分大小寫比對）
# tier  = 粗分等級（S/A/B/C），僅供預設排序參考；使用者可自訂 keep 清單覆蓋
EVENTS: list[dict] = [
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

# 快速查詢索引：match 片段 → event dict（O(1)）
_BY_MATCH: dict[str, dict] = {ev["match"]: ev for ev in EVENTS}


def match_event(text: str) -> dict | None:
    """把 OCR 讀到的事件文字比對 EVENTS，回傳命中的事件（或 None）。

    不分大小寫；只要 text「包含」任一 match 片段就算命中。
    若多個片段同時命中，回傳稀有度最高的（優先保留高價值事件）。
    """
    text_lower = text.lower()
    hits = [ev for ev in EVENTS if ev["match"].lower() in text_lower]
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
    # 1. 完全相符
    for ev in EVENTS:
        if _norm(ev["ore"]) == q:
            return ev["ore"]
    # 2. query 是 礦物名的子字串（例如 "hall" → "Hallownest"）
    hits = [ev for ev in EVENTS if q in _norm(ev["ore"])]
    if hits:
        return max(hits, key=lambda e: e["rarity"])["ore"]
    # 3. 礦物名是 query 的子字串（例如 "the all seeing" → "The All-Seeing"）
    hits = [ev for ev in EVENTS if _norm(ev["ore"]) in q]
    if hits:
        return max(hits, key=lambda e: e["rarity"])["ore"]
    return None


def format_event_list_embed(keep_ores: set[str] | None = None) -> dict:
    """產生 Discord embed JSON，列出所有事件 + keep 狀態（✅/❌）。"""
    keep_ores = keep_ores or set()
    fields = []
    for ev in EVENTS:
        status = "✅" if ev["ore"] in keep_ores else "❌"
        fields.append({
            "name": f"{status} {ev['ore']}",
            "value": f"{ev['rarity']:,}｜{ev['effect'][:50]}",
            "inline": True,
        })
    return {
        "title": "REX 事件清單",
        "description": "`!keep <礦物名>` 保留｜`!unkeep <礦物名>` 取消｜`!clear` 全清",
        "color": 0x00ff88,
        "fields": fields,
    }
