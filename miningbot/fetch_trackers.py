"""下載 REX wiki 的各階級 tracker 圖到 assets/markers/，當作標記比對模板。

用法：
    python -m miningbot.fetch_trackers              # 下載「會觸發 chill」的高階級（Exotic 以上）
    python -m miningbot.fetch_trackers --all        # 連低階級一起下載
    python -m miningbot.fetch_trackers --dest x/y   # 指定輸出資料夾

下載後用 find_best_marker 多模板比對；顏色會被忽略（只比形狀），尺寸用多尺度容忍。
note: wiki 圖只是「起點」，若實機對不準，改用遊戲內掃描後截圖最可靠。
"""
import argparse
import os
import urllib.request

_BASE = "https://static.wikia.nocookie.net/rex-3/images"

# 會觸發 chill 的高階級（Exotic 以上）
HIGH_TIER = {
    "exotic":       f"{_BASE}/7/79/ExoticTracker.png/revision/latest",
    "exquisite":    f"{_BASE}/1/1b/ExquisiteTracker.png/revision/latest",
    "transcendent": f"{_BASE}/3/32/TranscendentTracker.png/revision/latest",
    "enigmatic":    f"{_BASE}/d/d3/EnigmaticTracker.png/revision/latest",
    "unfathomable": f"{_BASE}/3/3b/UnfathomableTracker.png/revision/latest",
    "otherworldly": f"{_BASE}/8/86/OtherworldlyTracker.png/revision/latest",
    "exclusive":    f"{_BASE}/f/fb/ExclusiveTracker.png/revision/latest",
}

# 低階級（一般不需採集，加 --all 才下載）
LOW_TIER = {
    "common":   f"{_BASE}/3/33/CommonTracker.png/revision/latest",
    "uncommon": f"{_BASE}/4/4e/UncommonTracker.png/revision/latest",
    "rare":     f"{_BASE}/3/3d/RareTracker.png/revision/latest",
    "master":   f"{_BASE}/b/b4/MasterTracker.png/revision/latest",
    "surreal":  f"{_BASE}/3/33/SurrealTracker.png/revision/latest",
    "mythic":   f"{_BASE}/8/87/MythicTracker.png/revision/latest",
}


def download(urls: dict, dest: str) -> tuple:
    """下載 urls 到 dest，回 (成功數, 失敗清單)。"""
    os.makedirs(dest, exist_ok=True)
    ok, failed = 0, []
    for name, url in urls.items():
        path = os.path.join(dest, f"{name}.png")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
            print(f"OK   {name:14s} -> {path} ({len(data)} bytes)")
            ok += 1
        except Exception as e:
            print(f"FAIL {name:14s}: {e}")
            failed.append(name)
    return ok, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="連低階級一起下載")
    ap.add_argument("--dest", default="assets/markers", help="輸出資料夾")
    args = ap.parse_args()
    urls = dict(HIGH_TIER)
    if args.all:
        urls.update(LOW_TIER)
    ok, failed = download(urls, args.dest)
    print(f"\n完成：{ok} 成功、{len(failed)} 失敗。")
    if failed:
        print("失敗：", ", ".join(failed), "（可手動到 wiki 下載放進", args.dest, "）")


if __name__ == "__main__":
    main()
