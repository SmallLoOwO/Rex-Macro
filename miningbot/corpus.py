"""回礦語料夾：有 ground truth 的八方位圖不受 snapshot retention 管。

**為什麼需要這一層**（2026-07-28 實測）：`logs/reentry_remote/ledger.jsonl` 記了
30 筆 200 張八方位快照，磁碟上只剩 58 張讀得到，能配成 (圖, 座標) 的僅 1 正 7 負。
根因是 `snapshot_max_total_mb` 到頂之後從最舊刪起，**不分那張圖有沒有 click
ground truth**；帳還在，圖沒了，而且不可再生。

放寬 retention 上限不是解法（總量無界，OneDrive 同步夾 632MB 已是實測痛點）。
正確做法是**在刪之前把有價值的那一組搬走**：語料夾放在 `snapshots/` 之外，
`Bot._snapshot_cleanup_once` 只掃 `<log_dir>/snapshots`，掃不到這裡；語料夾自己
另有一個上限（`corpus_max_total_mb`），到頂時**優先刪無 click 的組**。

版面：``<log_dir>/corpus/reentry/ep<N>_attempt<M>/{dir1..8.png, meta.json}``。

`meta.json` 一律存**相對檔名**——語料夾要能整包搬到別台機器，絕對路徑一搬就死，
而且會踩 MSIX 虛擬化重導（`pythonw` 走 Store 版 Python，寫入被重導到
`…\\Packages\\PythonSoftwareFoundation.Python.3.11_…\\LocalCache\\Local\\…`，
見 AGENTS.md LIVE-RUN TROUBLESHOOTING）。方位一律 **1-8**，與檔名 `dirN.png`
對齊（`ctx` 內部仍是 0-based，只在這一層翻面）。
"""

from __future__ import annotations

import json
import os
import shutil

CORPUS_DIRNAME = "corpus"
META_NAME = "meta.json"


def corpus_root(log_dir: str) -> str:
    """語料夾根目錄。刻意與 `snapshots/` 同層而非其下——retention 只掃 snapshots。"""
    return os.path.join(log_dir, CORPUS_DIRNAME, "reentry")


def group_name(episode, attempt) -> str:
    """一組＝一輪 sweep 的八張圖（`ctx.shots` 每次 sweep 清空，reroll 也算新一輪）。"""
    return f"ep{int(episode)}_attempt{int(attempt)}"


def shot_filename(dir_idx: int) -> str:
    """內部 0-based dir_idx → 檔名 1-based（2026-07-18 起的玩家介面慣例）。"""
    return f"dir{(int(dir_idx) % 8) + 1}.png"


def normalize_click(click: dict) -> dict:
    """`ctx.clicks` 一筆 → `meta.json` 一筆（方位翻成 1-8、只留離線分析用得到的欄位）。

    `layer_seen` 是 (世界, Depth) 反推的實測值；**不退回玩家宣告的 `layer` 字串**
    ——實測 20 筆點擊有 5 筆宣告成 "Mantle Layer" 但落地畫面實為 Shamrock。
    缺值照實寫 `None`，不補值：寫 None 才看得出當時量不到。
    """
    pos = click.get("pos") or ()
    return {
        "dir": (int(click.get("dir", 0)) % 8) + 1,
        "pos": [int(pos[0]), int(pos[1])] if len(pos) >= 2 else None,
        "layer_seen": click.get("layer_seen"),
        "depth_m": click.get("depth_m"),
        "invalid": bool(click.get("invalid", False)),
    }


def clicks_for_attempt(clicks, attempt) -> list:
    """只留這一輪 attempt 的點擊（純函式）。

    `ctx.shots` 每次 sweep 清空，`ctx.clicks` 卻整個 episode 累積——不篩就會把
    attempt 1 點的座標配到 attempt 3 的圖上，語料直接變毒。`attempt` 欄位是
    2026-07-28 才加進 `record_click` 的，舊筆沒有就一律不要（寧可少一筆正樣本，
    不要一筆錯配）。
    """
    return [c for c in clicks or () if c.get("attempt") == attempt]


def build_meta(*, episode, attempt, world, sticky_layer, outcome, t,
               shots, clicks) -> dict:
    """語料組的 `meta.json`（純函式）。

    `shots`＝**實際複製成功**的 ``[(dir_idx, filename)]``；沒複製到的不列進去，
    免得 meta 指向不存在的檔案。`clicks` 已由 `clicks_for_attempt` 篩過。
    """
    return {
        "episode": int(episode),
        "attempt": int(attempt),
        "world": world,
        "sticky_layer": sticky_layer,
        "outcome": outcome,
        "t": float(t),
        "shots": [{"dir": (int(i) % 8) + 1, "file": name} for i, name in shots],
        "clicks": [normalize_click(c) for c in clicks or ()],
    }


def plan_corpus_cleanup(groups, max_total_mb) -> list:
    """語料夾到頂時該刪哪幾組（純函式）。

    `groups`＝``[(name, has_click, mtime, size_bytes)]``。刪除順序：**先刪無 click
    的**（只有負樣本，下一輪回礦就能再生），同類內從最舊刪起；有 click 的組是
    不可再生的 (圖, 座標) 配對，只有在無 click 的組全刪光還超標時才動它。
    """
    total = sum(size for _, _, _, size in groups)
    cap = max(0, int(max_total_mb)) * 1024 * 1024
    doomed = []
    for name, _has_click, _mtime, size in sorted(
            groups, key=lambda g: (bool(g[1]), g[2])):
        if total <= cap:
            break
        doomed.append(name)
        total -= size
    return doomed


def _write_json(path: str, data: dict) -> None:
    """原子寫（tmp + os.replace）：離線 script 可能正在讀同一份 meta。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def write_group(root: str, *, episode, attempt, world, sticky_layer, outcome, t,
                shots, clicks) -> tuple:
    """複製整組八方位圖 + 寫 `meta.json`；回 ``(group_dir, copied, requested)``。

    `shots`＝``ctx.shots``（``[(dir_idx, 絕對快照路徑)]``）。單張複製失敗只跳過那張
    （meta 就不列它），不讓整組陪葬；整組失敗留給呼叫端的 try/except——素材收集
    是加值路徑，不能炸回礦主流程（沿用 `_save_auto_fixture` 的既有慣例）。
    """
    group_dir = os.path.join(root, group_name(episode, attempt))
    os.makedirs(group_dir, exist_ok=True)
    requested = 0
    copied = []
    for dir_idx, src in shots or ():
        if not src:
            continue
        requested += 1
        name = shot_filename(dir_idx)
        try:
            shutil.copyfile(src, os.path.join(group_dir, name))
        except OSError:
            continue
        copied.append((dir_idx, name))
    _write_json(os.path.join(group_dir, META_NAME), build_meta(
        episode=episode, attempt=attempt, world=world,
        sticky_layer=sticky_layer, outcome=outcome, t=t,
        shots=copied, clicks=clicks))
    return group_dir, len(copied), requested


def scan_groups(root: str) -> list:
    """掃語料夾回 ``[(name, has_click, mtime, size_bytes)]``（`plan_corpus_cleanup` 的輸入）。

    `has_click` 讀該組 `meta.json` 的 `clicks`；讀不到就當**有** click——寧可誤留
    也不要誤刪不可再生的配對。
    """
    groups = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return groups
    for name in names:
        group_dir = os.path.join(root, name)
        if not os.path.isdir(group_dir):
            continue
        size = 0
        mtime = 0.0
        for entry in os.scandir(group_dir):
            try:
                st = entry.stat()
            except OSError:
                continue
            size += st.st_size
            mtime = max(mtime, st.st_mtime)
        groups.append((name, _group_has_click(group_dir), mtime, size))
    return groups


def _group_has_click(group_dir: str) -> bool:
    try:
        with open(os.path.join(group_dir, META_NAME), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return True                    # 讀不到 → 保守當有 ground truth，不刪
    return bool(meta.get("clicks"))


def enforce_cap(root: str, max_total_mb) -> int:
    """語料夾容量上限：算出該刪哪幾組並刪掉，回傳刪掉的組數。"""
    doomed = plan_corpus_cleanup(scan_groups(root), max_total_mb)
    removed = 0
    for name in doomed:
        try:
            shutil.rmtree(os.path.join(root, name))
            removed += 1
        except OSError:
            pass
    return removed
