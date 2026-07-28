"""回礦傳送板語料工具：舊 ledger 殘骸搶救（`--rescue`）。

離線 script，`uv run python -m miningbot.build_reentry_dataset --rescue`。
bot 沒在跑也要能用，所以不掛網頁、不 import `main`。

**為什麼要搶救**：`corpus.py` 的止血只對「之後」的回礦有效；2026-04~07 三個月的
語料只剩 ledger 帳目與磁碟上零星幾張圖。倒進語料夾之後這批就不會再少，而且後面
所有工具只要認語料夾一種來源——**路徑重導邏輯只留在這一支**。

⚠ MSIX 雙路徑（AGENTS.md LIVE-RUN TROUBLESHOOTING）：ledger 記的快照路徑很可能
**不存在**。`pythonw -m miningbot`（`.bat` 啟動路徑）跑的是 Store 版 Python，
寫入 `%LOCALAPPDATA%\\RexMacro` 被 MSIX 虛擬化重導到
`…\\Packages\\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\\LocalCache\\Local\\…`；
`uv run` 啟動則落 repo `logs/`。**同一份 ledger 裡兩種路徑混存**（依當時用哪個
直譯器啟動），所以解析順序是「記錄值 → 重導後的 LocalCache 路徑 → 都不在＝已消失」。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import corpus
from .config import DEFAULT as cfg
from .config import resolve_runtime_log_path

# Store 版 Python 的 MSIX 虛擬化寫入落點（相對 %LOCALAPPDATA%）
MSIX_LOCALCACHE = ("Packages\\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0"
                   "\\LocalCache\\Local")
_APPDATA_LOCAL = "\\appdata\\local\\"


def redirect_candidates(path: str) -> list:
    """記錄值 → 依序要試的實體路徑（純函式，不碰檔案系統）。

    只在路徑真的落在 `%LOCALAPPDATA%` 底下、且**還沒**經過重導時才加候選；
    已含 `LocalCache` 的路徑再加一層會得到不存在的雙重前綴。
    """
    if not path:
        return []
    norm = path.replace("/", "\\")
    cands = [path]
    low = norm.lower()
    idx = low.find(_APPDATA_LOCAL)
    if idx >= 0 and "\\localcache\\" not in low:
        cut = idx + len(_APPDATA_LOCAL)
        cands.append(norm[:cut] + MSIX_LOCALCACHE + "\\" + norm[cut:])
    return cands


def resolve_shot_path(path: str, exists=os.path.exists):
    """回第一個真的存在的候選路徑；全都不在回 None（＝這張圖已被 retention 刪了）。"""
    for cand in redirect_candidates(path):
        if exists(cand):
            return cand
    return None


def prefer_redirected(path: str, exists=os.path.exists) -> str:
    """同一個設定值的兩個實體位置中，挑 MSIX 重導後那份（不存在才退回原值）。

    `Config` 兩種啟動法算出來的字串是同一個（`%LOCALAPPDATA%\\RexMacro\\logs\\…`），
    差別在 Store 版 Python 的寫入被虛擬化重導。production 走 `.bat` → `pythonw`，
    所以實機資料在 LocalCache 那份；agent 這邊走 `uv run` 預設看到的卻是原路徑。
    不在這裡對齊，離線工具就會對著一個空資料夾說「語料 0 筆」。
    """
    for cand in reversed(redirect_candidates(path)):
        if exists(cand):
            return cand
    return path


def default_corpus_root(log_dir=None, isdir=os.path.isdir) -> str:
    """語料夾**實體**位置（同 `prefer_redirected` 的理由，但語料夾可能還不存在，
    所以是拿 `log_dir` 去探而不是拿語料夾本身）。"""
    log_dir = log_dir or cfg.log_dir
    return corpus.corpus_root(prefer_redirected(log_dir, exists=isdir))


# ---- ledger 解析 -----------------------------------------------------------

def parse_ledger(lines) -> tuple:
    """`[(episode, attempt) → row]` + void 清單 + 壞行數（純函式）。

    ledger 是 append-only，尾端可能是寫到一半的 partial line——壞行略過不算錯
    （比照 `web_history._iter_snapshot_records` 與 `next_episode_id_from_ledger`）。
    `outcome="started"` 是佔號行（2026-07-26 起每個 episode 建 ctx 就寫一行），
    沒有 shots，直接不收。
    """
    rows, voids, bad = {}, [], 0
    for line in lines or ():
        if isinstance(line, bytes):
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError:
                bad += 1
                continue
        if not line or not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if not isinstance(row, dict):
            bad += 1
            continue
        if row.get("type") == "void":
            voids.append(row)
            continue
        if not row.get("shots"):
            continue
        key = (row.get("episode"), row.get("attempt"))
        rows[key] = row                   # 同 key 後寫的覆蓋前寫的
    return rows, voids, bad


def apply_voids(rows: dict, voids) -> dict:
    """把 `{"type":"void"}` 追加行套進對應 episode 的第 N 筆點擊（玩家自己標作廢）。"""
    for void in voids:
        episode, idx = void.get("episode"), void.get("click_index")
        if not isinstance(idx, int):
            continue
        for (ep, _attempt), row in rows.items():
            if ep != episode:
                continue
            clicks = row.get("clicks") or []
            if 0 <= idx < len(clicks):
                clicks[idx]["invalid"] = True
    return rows


# ---- 搶救 ------------------------------------------------------------------

def rescue(ledger_path: str, root: str, *, exists=os.path.exists) -> dict:
    """把 ledger 裡還讀得到的快照倒進語料夾；回報告 dict。

    冪等：目標組已有 `meta.json` 就整組跳過——重跑既不重複也不會把倒好的組覆蓋
    成殘缺版（第二次跑時原始快照可能又少幾張）。

    舊筆的 click **沒有 `attempt` 欄位**（2026-07-28 才加），所以無法判斷那一筆
    屬於哪一輪；這裡照實把整列 click 都寫進該組。實測 19 筆有 click 的 row 裡，
    多次點擊全部落在同一個 dir（成功前的重試），沒有跨方位的情形；真有跨方位的
    組會被建資料集那一步以「語意不明確」排除，不會污染訓練資料。
    """
    try:
        with open(ledger_path, "rb") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    rows, voids, bad = parse_ledger(lines)
    apply_voids(rows, voids)

    report = {"ledger_rows": len(rows), "bad_lines": bad, "shots_total": 0,
              "shots_resolved": 0, "shots_missing": 0, "groups_written": 0,
              "groups_skipped_existing": 0, "groups_empty": 0}
    for (episode, attempt), row in sorted(
            rows.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0)):
        shots = row.get("shots") or []
        report["shots_total"] += len(shots)
        group_dir = os.path.join(root, corpus.group_name(episode, attempt or 1))
        if os.path.exists(os.path.join(group_dir, corpus.META_NAME)):
            report["groups_skipped_existing"] += 1
            # 已倒過的組仍要算圖數，報告的 resolved/missing 才對得起 shots_total
            for _dir_idx, src in shots:
                if resolve_shot_path(src, exists=exists):
                    report["shots_resolved"] += 1
                else:
                    report["shots_missing"] += 1
            continue
        resolved = []
        for dir_idx, src in shots:
            real = resolve_shot_path(src, exists=exists)
            if real is None:
                report["shots_missing"] += 1
                continue
            report["shots_resolved"] += 1
            resolved.append((dir_idx, real))
        if not resolved:
            # 一張都不剩就不建組——絕不寫出指向不存在檔案的 meta.json
            report["groups_empty"] += 1
            continue
        corpus.write_group(
            root, episode=episode, attempt=attempt or 1, world=row.get("world"),
            sticky_layer=row.get("sticky_layer"), outcome=row.get("outcome"),
            t=row.get("t") or 0.0, shots=resolved, clicks=row.get("clicks") or [])
        report["groups_written"] += 1
    return report


def format_rescue_report(report: dict) -> str:
    return "\n".join([
        f"ledger 可用筆數   {report['ledger_rows']}"
        + (f"（壞行 {report['bad_lines']} 略過）" if report["bad_lines"] else ""),
        f"快照總數          {report['shots_total']}",
        f"解析得到          {report['shots_resolved']}",
        f"已消失            {report['shots_missing']}",
        f"倒入語料組        {report['groups_written']}"
        + (f"（已存在跳過 {report['groups_skipped_existing']}）"
           if report["groups_skipped_existing"] else "")
        + (f"（一張都不剩 {report['groups_empty']}）"
           if report["groups_empty"] else ""),
    ])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m miningbot.build_reentry_dataset",
        description="回礦傳送板語料工具")
    parser.add_argument("--rescue", action="store_true",
                        help="把舊 ledger 裡還讀得到的快照倒進語料夾（冪等）")
    parser.add_argument("--ledger", default=None,
                        help="ledger.jsonl 路徑（預設取 Config，MSIX 重導後那份優先）")
    parser.add_argument("--corpus", default=None,
                        help="語料夾根目錄（預設 <log_dir>/corpus/reentry）")
    args = parser.parse_args(argv)
    root = args.corpus or default_corpus_root()
    # Config 的 ledger 是相對 `logs/…`（`main._apply_startup_overrides` 才會錨到
    # log_dir）；離線 script 不 import main，所以在這裡自己錨一次再走 MSIX 重導。
    ledger = args.ledger or prefer_redirected(
        resolve_runtime_log_path(cfg.reentry_remote_ledger, cfg.log_dir))
    if not args.rescue:
        parser.print_help()
        return 2
    print(f"ledger  {ledger}")
    print(f"語料夾  {root}")
    print(format_rescue_report(rescue(ledger, root)))
    return 0


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())
