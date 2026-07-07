"""抓 REX wiki 各世界的礦物清單：dump 高階白名單 + diff 低階排除清單。

用法：
    python -m miningbot.fetch_ores                # 抓 WORLDS 內所有世界，寫 assets/rare_ores.json
    python -m miningbot.fetch_ores --dry-run      # 只印 diff、不寫檔

輸出兩件事：
1. `assets/rare_ores.json`：**高階（Exotic 以上）白名單**——D3 採集目標的完整礦名表，
   給三態分類用（在排除清單→忽略；在白名單→SUCCESS+顯示階級；都不在→未知礦名告警）。
2. **低階（Surreal/Mythic）diff**：與 `game_data.WORLDS[world].common_ores` 比對，印出
   wiki 有但 game_data 缺的礦——遊戲更新加新礦時跑一次就知道排除清單要補什麼。
   排除清單本身仍手動維護在 game_data（安全關鍵：誤列 D3 目標＝H014 假陰性重演，
   要人工過目；有測試鎖「Exotic 以上絕不可列」）。

網路注意：fandom 網頁端擋非瀏覽器 UA（403/402），但 MediaWiki API（api.php?action=parse）
帶 Mozilla UA 可通（2026-07-03 實測）。
"""
import argparse
import json
import os
import re
import urllib.parse
import urllib.request

from . import game_data

API = "https://rex-reincarnated.fandom.com/api.php"

# 會被動進聊天的低階（排除清單對象）／D3 採集目標的高階（白名單對象）。
# Rare/Master 只有 Spectral 變體會進聊天，靠 ocr.VARIANT_PREFIXES 前綴剝除處理，不列表。
LOW_TIERS = ("Surreal", "Mythic")
HIGH_TIERS = ("Exotic", "Exquisite", "Transcendent", "Enigmatic",
              "Unfathomable", "Otherworldly", "Imaginary", "Zenith")

# Rare/Master：H039 教訓——這兩階的 ionized/spectral 變體也會被動進聊天，
# 底名缺列 common_ores → 假 special/假 rare count。仍非 D3 目標（chill 只對 Exotic+），
# 列底名不會重演 H014；advisory 只印、不自動寫入 game_data（清單仍人工維護）。
ADVISORY_TIERS = ("Rare", "Master")

# 已不存在／已合併的世界（wiki 頁還在但遊戲內沒有）——不蒐集，否則引入假的跨世界同名。
# Wintera Isle 已併入 Aesteria（其冬季礦現於 Aesteria）；Tutorial World 已移除
# （使用者確認 2026-07-03）。此二者正是先前 34 個跨世界同名的來源。
DEPRECATED_WORLDS = frozenset({"Wintera Isle", "Tutorial World"})

# 一列礦：|[[礦名]] 或 |[[礦名|別名]] ＋ |{{Colour|階級}} ＋ |數字rarity（可帶註記）
_ROW_RE = re.compile(
    r"\|\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*\n"
    r"\|\{\{Colour\|(\w+)\}\}\s*\n"
    r"\|([\d,]+)")
# tabber 分段標題：「Xxx Layer =」或「Cave Exclusives =」
_SECTION_RE = re.compile(r"^\s*([\w \-]+?)(?: Layer)? =", re.M)


def parse_ore_rows(wikitext: str) -> list:
    """世界頁 wikitext → [{ore, tier, rarity, layer}]（Layer 階的圖層方塊本身不算礦、跳過）。"""
    rows = []
    for sec in re.split(r"\|-\|\s*", wikitext):
        m = _SECTION_RE.match(sec)
        layer = m.group(1).strip() if m else "?"
        for om in _ROW_RE.finditer(sec):
            tier = om.group(2)
            if tier == "Layer":
                continue
            # wiki 連結目標可能帶消歧義後綴（[[Candy Bucket (Ore)]]），遊戲內聊天名沒有
            ore = re.sub(r"\s*\(Ore\)$", "", om.group(1))
            rows.append({"ore": ore, "tier": tier,
                         "rarity": int(om.group(3).replace(",", "")), "layer": layer})
    return rows


def split_tiers(rows: list) -> tuple:
    """rows → (低階 Surreal/Mythic, 高階 Exotic 以上)；更低階（Common~Master）兩邊都不收。"""
    low = [r for r in rows if r["tier"] in LOW_TIERS]
    high = [r for r in rows if r["tier"] in HIGH_TIERS]
    return low, high


def fetch_page_wikitext(page: str) -> str:
    """MediaWiki API 抓頁面 wikitext（fandom 需帶瀏覽器 UA）。"""
    url = f"{API}?action=parse&page={urllib.parse.quote(page)}&format=json&prop=wikitext"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return data["parse"]["wikitext"]["*"]


def fetch_world_names() -> list:
    """從 wiki Category:Worlds 動態列出所有世界頁名（遊戲不只 game_data.WORLDS 那兩個）。

    過濾 DEPRECATED_WORLDS（wiki 頁還在、但遊戲內已移除/合併的世界）。
    失敗時退回 game_data.WORLDS（至少涵蓋正在玩的世界，不讓整個同步掛掉）。
    """
    url = (f"{API}?action=query&list=categorymembers"
           f"&cmtitle=Category:Worlds&cmlimit=100&format=json")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        names = [m["title"] for m in data["query"]["categorymembers"]
                 if m["title"] not in DEPRECATED_WORLDS]
        return names or list(game_data.WORLDS)
    except Exception as e:
        print(f"Category:Worlds 抓取失敗: {e}（退回 game_data.WORLDS）")
        return list(game_data.WORLDS)


def find_name_collisions(worlds_rows: dict) -> dict:
    """跨世界撞名檢查：{world: rows} → {礦名: [(world, tier, layer), ...]}（只含跨≥2世界的）。

    分類/排除都靠礦名比對，跨世界同名（尤其階級不同）會互相污染——世界收斂
    （rare_ores(world)/common_ore_names）就是為此；這裡讓假設「目前無撞名」可驗證。
    同世界同名多圖層（如 Ambitium 同在 Amourite/Shamrock 層）合法、不算撞名。
    """
    seen: dict = {}
    for world, rows in worlds_rows.items():
        for r in rows:
            seen.setdefault(r["ore"], {}).setdefault(world, []).append((r["tier"], r["layer"]))
    out = {}
    for ore, by_world in seen.items():
        if len(by_world) >= 2:
            out[ore] = [(w, t, layer) for w, pairs in by_world.items() for t, layer in pairs]
    return out


def find_class_conflicts(worlds_rows: dict) -> dict:
    """低/高衝突：礦名在某世界屬低階（排除對象）、另一世界屬高階（採集目標）→ 歧義。

    這才是分類正確性依賴的不變量（同階同名跨世界合法且存在：季節島/教學關共用礦）。
    回傳 {礦名: [(world, tier), ...]}，空 dict = 無衝突。
    """
    out = {}
    for ore, places in find_name_collisions(worlds_rows).items():
        classes = {("low" if t in LOW_TIERS else "high") for _, t, _ in places}
        if len(classes) > 1:
            out[ore] = [(w, t) for w, t, _ in places]
    return out


def diff_common_ores(world_name: str, low_rows: list) -> list:
    """wiki 低階 vs game_data 排除清單：回傳 game_data 缺的 rows（要人工補列的候選）。"""
    have = {o["ore"] for o in game_data.WORLDS[world_name].common_ores}
    return [r for r in low_rows if r["ore"] not in have]


def low_tier_advisory(all_ores: list) -> list:
    """Rare/Master 底名 advisory（H039 類缺口事前補）——只印，不自動寫入 game_data。

    過濾 tier ∈ ADVISORY_TIERS，依 world 再依 ore 名排序。Exotic 以上是 D3 目標，
    絕不可出現在這裡（誤列＝重演 H014 假陰性）；Surreal/Mythic 已由主清單（低階排除清單）
    涵蓋，不重複列出。
    """
    rows = [r for r in all_ores if r.get("tier") in ADVISORY_TIERS]
    return sorted(rows, key=lambda r: (r.get("world", ""), r["ore"]))


def print_low_tier_advisory(advisory: list) -> None:
    """印 Rare/Master 底名 advisory 表（依世界分組）——人工核對後補進 game_data common_ores。"""
    if not advisory:
        print("\n（無 Rare/Master 底名資料）")
        return
    print(f"\n== Rare/Master 底名 advisory（{len(advisory)} 筆，H039 類缺口事前補）==")
    print("僅供人工核對，不會自動寫入 game_data；Exotic 以上絕不會出現在此表。")
    cur_world = None
    for r in advisory:
        if r.get("world") != cur_world:
            cur_world = r.get("world")
            print(f"  -- {cur_world} --")
        print(f"    {{\"ore\": \"{r['ore']}\", \"tier\": \"{r['tier']}\"}}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印 diff/撞名報告、不寫檔")
    ap.add_argument("--dest", default="assets/rare_ores.json", help="高階白名單輸出路徑")
    ap.add_argument("--dest-all", default="assets/ores_all.json",
                    help="全礦（所有 tier、依世界分）輸出路徑——撞名驗證/未來擴充用")
    ap.add_argument("--audit-low-tiers", action="store_true",
                    help="印 Rare/Master 底名 advisory（H039 類缺口事前補；只印不寫檔）")
    args = ap.parse_args()

    out = {"source": API, "worlds": {}}
    all_rows: dict = {}
    advisory_rows: list = []
    for world in fetch_world_names():          # 所有 wiki 世界（不只 game_data.WORLDS 那兩個）
        print(f"== {world} ==")
        try:
            wikitext = fetch_page_wikitext(world)
        except Exception as e:
            print(f"  FAIL 抓取失敗: {e}（沿用舊檔）")
            continue
        rows = parse_ore_rows(wikitext)
        low, high = split_tiers(rows)
        # 只留「會進聊天框」的階級（Surreal+）：Common~Master 不進聊天、與採集確認無關
        all_rows[world] = low + high
        out["worlds"][world] = high
        for r in rows:
            if r["tier"] in ADVISORY_TIERS:
                advisory_rows.append({**r, "world": world})
        print(f"  解析 {len(rows)} 礦：低階 {len(low)}、高階 {len(high)}（聊天相關 {len(low) + len(high)}）")
        if world in game_data.WORLDS:          # 排除清單只維護正在玩的世界
            missing = diff_common_ores(world, low)
            if missing:
                print(f"  ★ 排除清單缺 {len(missing)} 個（請人工過目後補進 game_data）：")
                for r in missing:
                    print(f"    {{\"ore\": \"{r['ore']}\", \"rarity\": {r['rarity']}, "
                          f"\"layer\": \"{r['layer']}\", \"tier\": \"{r['tier']}\"}},")
            else:
                print("  排除清單與 wiki 一致")

    # 低/高衝突＝分類正確性依賴的不變量；同階同名（季節島/教學關共用礦）合法、只列數字
    conflicts = find_class_conflicts(all_rows)
    same = find_name_collisions(all_rows)
    print(f"\n跨世界同名 {len(same)} 個（同階合法）；低/高衝突 {len(conflicts)} 個")
    for ore, places in sorted(conflicts.items()):
        print(f"  ★ {ore}: " + "; ".join(f"{w}:{t}" for w, t in places))

    if args.audit_low_tiers:
        print_low_tier_advisory(low_tier_advisory(advisory_rows))

    if args.dry_run:
        print("--dry-run：不寫檔")
        return
    for dest, data, desc in ((args.dest, out, "高階白名單"),
                             (args.dest_all, {"source": API, "worlds": all_rows},
                              "聊天相關階級（Surreal+）")):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        total = sum(len(v) for v in data["worlds"].values())
        print(f"寫入 {dest}：{total} 筆（{desc}）")


if __name__ == "__main__":
    main()
