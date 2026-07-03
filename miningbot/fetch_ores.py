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


def diff_common_ores(world_name: str, low_rows: list) -> list:
    """wiki 低階 vs game_data 排除清單：回傳 game_data 缺的 rows（要人工補列的候選）。"""
    have = {o["ore"] for o in game_data.WORLDS[world_name].common_ores}
    return [r for r in low_rows if r["ore"] not in have]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印 diff/撞名報告、不寫檔")
    ap.add_argument("--dest", default="assets/rare_ores.json", help="高階白名單輸出路徑")
    ap.add_argument("--dest-all", default="assets/ores_all.json",
                    help="全礦（所有 tier、依世界分）輸出路徑——撞名驗證/未來擴充用")
    args = ap.parse_args()

    out = {"source": API, "worlds": {}}
    all_rows: dict = {}
    for world in game_data.WORLDS:
        print(f"== {world} ==")
        try:
            wikitext = fetch_page_wikitext(world)
        except Exception as e:
            print(f"  FAIL 抓取失敗: {e}（沿用舊檔）")
            continue
        rows = parse_ore_rows(wikitext)
        all_rows[world] = rows
        low, high = split_tiers(rows)
        out["worlds"][world] = high
        print(f"  解析 {len(rows)} 礦：低階 {len(low)}、高階 {len(high)}")
        missing = diff_common_ores(world, low)
        if missing:
            print(f"  ★ 排除清單缺 {len(missing)} 個（請人工過目後補進 game_data）：")
            for r in missing:
                print(f"    {{\"ore\": \"{r['ore']}\", \"rarity\": {r['rarity']}, "
                      f"\"layer\": \"{r['layer']}\", \"tier\": \"{r['tier']}\"}},")
        else:
            print("  排除清單與 wiki 一致")

    # 跨世界撞名報告：分類/排除靠礦名比對，同名跨世界會互相污染（世界收斂的存在理由）
    collisions = find_name_collisions(all_rows)
    if collisions:
        print(f"\n★ 跨世界同名礦 {len(collisions)} 個：")
        for ore, places in sorted(collisions.items()):
            tiers = {t for _, t, _ in places}
            mark = "（階級不同！）" if len(tiers) > 1 else ""
            print(f"  {ore}{mark}: " + "; ".join(f"{w}/{layer}/{t}" for w, t, layer in places))
    else:
        print("\n跨世界撞名：無（世界收斂目前只是保險）")

    if args.dry_run:
        print("--dry-run：不寫檔")
        return
    for dest, data, desc in ((args.dest, out, "高階白名單"),
                             (args.dest_all, {"source": API, "worlds": all_rows}, "全礦")):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        total = sum(len(v) for v in data["worlds"].values())
        print(f"寫入 {dest}：{total} 筆（{desc}）")


if __name__ == "__main__":
    main()
