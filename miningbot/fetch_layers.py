"""抓 REX wiki 各世界的層別深度區間，與 `game_data.LAYER_DEPTHS` 比對印 diff。

用法：
    python -m miningbot.fetch_layers            # 抓 WORLDS 內所有世界，印表＋diff
    python -m miningbot.fetch_layers --verbose  # 另印每層的判讀依據原文（人工覆核用）

**只印 diff、不寫檔**——比照 `fetch_ores.py` 的排除清單慣例：層深表是安全關鍵
（誤植會讓 ledger 記錯 ground truth），仍人工維護在 `game_data.LAYER_DEPTHS`，
遊戲更新後跑一次就知道要改什麼，改動要人工過目。

網路注意：fandom 網頁端擋非瀏覽器 UA（403/402），但 MediaWiki API 帶 Mozilla UA
可通——同 `fetch_ores.py`。

解析要點（都是踩過才知道的）：
- 世界頁 `|layers =` 用的是 **wiki 連結的顯示名**，不是頁名：World 1 的
  `[[Core Layer|Outer Core]]` 與 `[[Core Layer|Inner Core]]` 是兩個不同的層、
  共用同一個頁面。只看頁名會少一層並取到錯的深度。
- 同一頁可能列多個世界的深度（Jollystone infobox 並列 Wintera Isle 與 Aesteria
  兩段），所以判讀一律以「內文中點名本世界的那句」為準，infobox 只當退路。
- `depth = Variable` 的活動層（Frost）沒有固定區間，歸入
  `game_data.VARIABLE_DEPTH_LAYERS`，不列入深度表。
"""
import argparse
import json
import re
import urllib.parse
import urllib.request

from . import game_data
from .fetch_ores import API, DEPRECATED_WORLDS

# 世界名 → wiki 頁名（"World 0" → "World_0"）。
_PAGE_OF_WORLD = {w: w.replace(" ", "_") for w in game_data.WORLDS}

# 深度區間寫法：7000m – 7999m / 7000-7999m / 7,000 m to 7,999 m
_RANGE = re.compile(r"([\d,]+)\s*m?\s*(?:&ndash;|[–—-]|to)\s*([\d,]+)\s*m", re.I)
_LAYERS_FIELD = re.compile(r"\|\s*layers\s*=\s*(.+)")
_LINK = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]")
_DEPTH_FIELD = re.compile(r"\|\s*depth\s*=\s*([^\n|]*)", re.I)


def fetch_page_wikitext(page: str) -> str:
    """MediaWiki API 抓頁面 wikitext（fandom 需帶瀏覽器 UA）。缺頁拋 KeyError。"""
    url = f"{API}?action=parse&page={urllib.parse.quote(page)}&format=json&prop=wikitext"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if "error" in data:
        raise KeyError(f"{page}: {data['error'].get('info')}")
    return data["parse"]["wikitext"]["*"]


def parse_layer_links(world_wikitext: str) -> list:
    """世界頁 wikitext → [(頁名, 顯示名)]，保序去重。

    顯示名才是層名（見模組 docstring 的 Outer/Inner Core 例）。無管線時顯示名
    取頁名去掉尾綴 " Layer"。

    ⚠ 只有大小寫不同時採頁名：Subworld 1 的 `[[Rocc Layer|rocc]]` 是 wiki 筆誤
    （該頁本文與其餘 11 處都是 "Rocc"），不正規化的話 diff 會永遠報一筆假差異。
    大小寫以外的差異一律尊重顯示名——那是真的不同層（Outer/Inner Core）。
    """
    m = _LAYERS_FIELD.search(world_wikitext)
    if not m:
        return []
    out, seen = [], set()
    for page, shown in _LINK.findall(m.group(1).split("\n")[0]):
        page = page.strip()
        from_page = page[: -len(" Layer")] if page.endswith(" Layer") else page
        name = (shown or page).strip()
        if name.endswith(" Layer"):
            name = name[: -len(" Layer")]
        if name.casefold() == from_page.casefold():
            name = from_page
        if name and (page, name) not in seen:
            seen.add((page, name))
            out.append((page, name))
    return out


def strip_markup(wikitext: str) -> str:
    """wiki 標記 → 純文字（連結取顯示字、去粗體與 HTML 標籤、空白正規化）。"""
    s = _LINK.sub(lambda m: m.group(2) or m.group(1), wikitext)
    s = re.sub(r"'''?|<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s)


def parse_depth_for(layer_wikitext: str, layer: str, world: str) -> tuple:
    """層頁 wikitext → (lo, hi, 依據)；抓不到回 (None, None, 原因)。

    以「內文中點名本世界的那句」為準（同頁多世界／多層時只有這句能區分），
    infobox 單段 depth 只當退路。
    """
    text = strip_markup(layer_wikitext)
    sentence = re.compile(
        r"The\s+" + re.escape(layer) + r"\s+Layer\b[^.]*?\blayer\s+in\s+"
        + re.escape(world) + r"\b[^.]*", re.I)
    m = sentence.search(text)
    if m:
        r = _RANGE.search(m.group(0))
        if r:
            return (int(r.group(1).replace(",", "")),
                    int(r.group(2).replace(",", "")), m.group(0).strip()[:160])
        return None, None, f"內文有句子但沒有深度：{m.group(0).strip()[:100]}"

    fields = [f.strip() for f in _DEPTH_FIELD.findall(layer_wikitext)]
    if any(f.lower() == "variable" for f in fields):
        return None, None, "infobox depth=Variable（活動層，無固定區間）"
    segs = [s for f in fields for s in re.split(r"<br\s*/?>", f) if _RANGE.search(s)]
    if len(segs) > 1:                      # 多段 → 只收標註本世界那段
        segs = [s for s in segs if world.lower() in s.lower()]
    if len(segs) == 1:
        r = _RANGE.search(segs[0])
        return (int(r.group(1).replace(",", "")),
                int(r.group(2).replace(",", "")), f"infobox: {segs[0].strip()[:80]}")
    return None, None, ("infobox 多段且無法對應本世界" if segs else "找不到深度")


def fetch_world_layers(world: str, verbose: bool = False) -> list:
    """單一世界 → [(層名, lo, hi)]；無固定深度或抓不到的層只印警告、不列入。"""
    page = _PAGE_OF_WORLD.get(world, world.replace(" ", "_"))
    try:
        world_wt = fetch_page_wikitext(page)
    except Exception as e:                 # noqa: BLE001 — 單一世界失敗不該中斷整輪
        print(f"  !! 世界頁 {page} 抓取失敗：{e}")
        return []
    rows = []
    for layer_page, layer in parse_layer_links(world_wt):
        try:
            layer_wt = fetch_page_wikitext(layer_page)
        except Exception as e:             # noqa: BLE001
            print(f"  !! {layer}（頁 {layer_page}）抓取失敗：{e}")
            continue
        lo, hi, why = parse_depth_for(layer_wt, layer, world)
        if lo is None:
            known = layer in game_data.VARIABLE_DEPTH_LAYERS
            print(f"  {'--' if known else '!!'} {layer}：{why}"
                  + ("（已知變動層，符合預期）" if known else ""))
            continue
        rows.append((layer, lo, hi))
        if verbose:
            print(f"     {layer}: {why}")
    return rows


def diff_world(world: str, fetched: list) -> list:
    """wiki 結果 vs game_data.LAYER_DEPTHS[world] → 差異描述清單（空＝一致）。"""
    have = {name: (lo, hi) for name, lo, hi in game_data.LAYER_DEPTHS.get(world, ())}
    want = {name: (lo, hi) for name, lo, hi in fetched}
    out = []
    for name, span in want.items():
        if name not in have:
            out.append(f"wiki 有、game_data 缺：{name} {span[0]}-{span[1]}m")
        elif have[name] != span:
            out.append(f"深度不一致：{name} game_data {have[name][0]}-{have[name][1]}m"
                       f" vs wiki {span[0]}-{span[1]}m")
    for name in have:
        if name not in want and name not in game_data.VARIABLE_DEPTH_LAYERS:
            out.append(f"game_data 有、wiki 缺：{name}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="同步 REX wiki 層別深度區間並印 diff")
    ap.add_argument("--verbose", action="store_true", help="另印每層的判讀依據原文")
    args = ap.parse_args(argv)

    all_diffs = []
    for world in game_data.WORLDS:
        if world in DEPRECATED_WORLDS:
            continue
        print(f"## {world}")
        rows = fetch_world_layers(world, verbose=args.verbose)
        for name, lo, hi in rows:
            print(f"   {name:<16} {lo:>5} - {hi:>5} m")
        for line in diff_world(world, rows):
            all_diffs.append(f"{world}: {line}")

    print("\n=== diff vs game_data.LAYER_DEPTHS ===")
    if all_diffs:
        for line in all_diffs:
            print("  " + line)
        # 主控台是 cp950，避免 ⚠ 之類非 cp950 字元（會 UnicodeEncodeError 中斷）。
        print("\n[!] 有差異。層深表是安全關鍵，請人工過目後手動改 game_data.LAYER_DEPTHS。")
        return 1
    print("  一致，無需改動。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
