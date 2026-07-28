"""回礦傳送板語料工具：語料夾 → `dataset.jsonl`，外加舊 ledger 殘骸搶救（`--rescue`）。

離線 script，`uv run python -m miningbot.build_reentry_dataset`。bot 沒在跑也要能用，
所以不掛網頁、不 import `main`；agent 直接 `uv run` 就拿得到資料集。

**資料來源只有語料夾**：`--rescue` 已把舊 ledger 的可讀殘骸倒進去，再讀一次 ledger
是同一批資料走兩條路徑，路徑重導邏輯留在這裡一處就好。

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


# ---- 資料集 ----------------------------------------------------------------

DATASET_NAME = "dataset.jsonl"
# 「玩家點下去而且真的下到礦」才算 ground truth。其餘 outcome（skip／started／缺值）
# 沒有玩家判斷可依——`skip` 不等於「八張裡都沒有傳送板」，也可能是他懶得找。
POSITIVE_OUTCOMES = ("confirmed_by_user", "descended")

KNOWN_BIASES = (
    "100% Lucernia、幾乎 100% Shamrock、100% 夜晚（Lucernia 設定上恆夜）。"
    "單一世界單一層讓「名牌＝當前層」這類假說不可否證。",
    "每輪 attempt 都會「回到地表」換重生點＝隨機化 yaw，所以 dir=1 不是固定方向，"
    "只有 attempt 1 例外（見 2026-07-21-reentry-yaw-investigation-findings.md）。",
    "LIMIT 徽章／層名牌是螢幕空間 UI，不是世界物件，不可拿來判朝向。",
    "layer_seen 缺值標 null，不要退回玩家宣告的 layer（實測 20 筆錯 5 筆）。",
)


def classify_group(meta: dict) -> tuple:
    """一組 `meta.json` → ``(rows, skip_reason)``（純函式，不碰檔案系統）。

    正負樣本定義**寫死在這裡不給參數**——定義漂移比資料少更危險。

    - `positive`：該組有 click、`invalid=False`、outcome 在 `POSITIVE_OUTCOMES`，
      且 click 的 dir 對上這張圖。
    - `negative`：同一組裡其他七個方位。理由：玩家看過全部八張才選那一張。
    - 整組排除：outcome 不對／沒有 click／click 被標作廢／多次 click 落在不同 dir
      （表示前幾次點錯，語意不明確）。
    """
    outcome = meta.get("outcome")
    if outcome not in POSITIVE_OUTCOMES:
        return [], "outcome_not_confirmed"
    clicks = meta.get("clicks") or []
    if not clicks:
        return [], "no_click"
    if any(c.get("invalid") for c in clicks):
        return [], "invalid_click"
    if len({c.get("dir") for c in clicks}) > 1:
        return [], "multi_dir_clicks"
    click = clicks[-1]
    group = corpus.group_name(meta.get("episode"), meta.get("attempt"))
    rows = []
    for shot in meta.get("shots") or ():
        positive = shot.get("dir") == click.get("dir")
        rows.append({
            "image": f"{group}/{shot.get('file')}",
            "dir": shot.get("dir"),
            "world": meta.get("world"),
            "layer_seen": click.get("layer_seen"),
            "depth_m": click.get("depth_m"),
            "label": "positive" if positive else "negative",
            "xy": list(click.get("pos")) if positive and click.get("pos") else None,
            "episode": meta.get("episode"),
            "attempt": meta.get("attempt"),
            "outcome": outcome,
        })
    return rows, None


def load_group_metas(root: str) -> list:
    """掃語料夾回 `[meta dict]`；讀不到／壞掉的組略過（append-only 慣例的延伸）。"""
    metas = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return metas
    for name in names:
        path = os.path.join(root, name, corpus.META_NAME)
        try:
            with open(path, encoding="utf-8") as f:
                metas.append(json.load(f))
        except (OSError, ValueError):
            continue
    return metas


def build_dataset(root: str, *, exists=os.path.exists) -> tuple:
    """語料夾 → ``(rows, report)``。空語料夾回空 list，不炸。"""
    report = {"groups": 0, "groups_used": 0, "positives": 0, "negatives": 0,
              "excluded": {}}
    rows_all = []
    for meta in load_group_metas(root):
        report["groups"] += 1
        rows, reason = classify_group(meta)
        if reason:
            report["excluded"][reason] = report["excluded"].get(reason, 0) + 1
            continue
        report["groups_used"] += 1
        for row in rows:
            if not exists(os.path.join(root, *row["image"].split("/"))):
                report["excluded"]["image_missing"] = (
                    report["excluded"].get("image_missing", 0) + 1)
                continue
            report["positives" if row["label"] == "positive" else "negatives"] += 1
            rows_all.append(row)
    return rows_all, report


def write_dataset(root: str, rows) -> str:
    path = os.path.join(root, DATASET_NAME)
    os.makedirs(root, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path


def read_dataset(path: str) -> list:
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return rows


def format_dataset_report(report: dict) -> str:
    lines = [
        f"語料組            {report['groups']}（採用 {report['groups_used']}）",
        f"正樣本            {report['positives']}",
        f"負樣本            {report['negatives']}",
    ]
    if report["excluded"]:
        lines.append("排除明細")
        for reason, count in sorted(report["excluded"].items()):
            lines.append(f"  {reason:<22}{count}")
    if not report["positives"] and not report["negatives"]:
        lines.append("（語料夾是空的或全被排除——先跑 --rescue，或等下一輪回礦）")
    lines.append("")
    lines.append("⚠ 已知資料偏誤（調偵測器前先讀）")
    lines += [f"  - {b}" for b in KNOWN_BIASES]
    return "\n".join(lines)


# ---- 評估報告 --------------------------------------------------------------

EVAL_PREFIX = "eval_"


def eval_row(row: dict, prediction, radius_px) -> dict:
    """一張圖的判定（純函式）。`prediction`＝``(x, y, score)`` 或 `None`。

    - 正樣本：預測落在真實座標 `radius_px` **內**（含等於）＝`hit`，否則 `miss`
      （沒有預測也是 miss——漏掉就是漏掉）。
    - 負樣本：有任何預測就是 `false_positive`，沒有才 `clean`。分數門檻是偵測器
      自己的事，它回 `None` 就代表它自己也不信。
    """
    px = py = score = None
    if prediction:
        px, py, score = prediction
    truth = row.get("xy")
    dist = None
    if truth and prediction:
        dist = ((px - truth[0]) ** 2 + (py - truth[1]) ** 2) ** 0.5
    if row.get("label") == "positive":
        verdict = "hit" if dist is not None and dist <= radius_px else "miss"
    else:
        verdict = "false_positive" if prediction else "clean"
    return {"image": row.get("image"), "label": row.get("label"),
            "world": row.get("world"), "layer_seen": row.get("layer_seen"),
            "xy": truth, "pred": [px, py] if prediction else None,
            "score": score, "dist": dist, "verdict": verdict}


def summarize_eval(results) -> dict:
    """逐張判定 → 成績單（純函式）。空輸入、零命中、全命中都不除以零。"""
    results = list(results or ())
    hits = [r for r in results if r["verdict"] == "hit"]
    positives = hits + [r for r in results if r["verdict"] == "miss"]
    negatives = [r for r in results if r["verdict"] in ("clean", "false_positive")]
    false_positives = [r for r in negatives if r["verdict"] == "false_positive"]
    dists = sorted(r["dist"] for r in hits if r["dist"] is not None)
    median = None
    if dists:
        mid = len(dists) // 2
        median = (dists[mid] if len(dists) % 2
                  else (dists[mid - 1] + dists[mid]) / 2.0)
    return {
        "positives": len(positives), "hits": len(hits),
        "misses": len(positives) - len(hits),
        "hit_rate": (len(hits) / len(positives)) if positives else None,
        "negatives": len(negatives), "clean": len(negatives) - len(false_positives),
        "false_positives": len(false_positives),
        "median_error_px": median,
    }


def group_eval(results, key: str) -> dict:
    """按 `world`／`layer_seen` 分組的成績單（純函式）。"""
    buckets = {}
    for r in results or ():
        buckets.setdefault(r.get(key), []).append(r)
    return {k: summarize_eval(v) for k, v in sorted(
        buckets.items(), key=lambda kv: str(kv[0]))}


def _pct(rate) -> str:
    return "—" if rate is None else f"{rate * 100:.1f}%"


def format_eval_report(summary: dict, by_world=None, by_layer=None,
                       radius_px=None) -> str:
    lines = [
        f"positives {summary['positives']:<4} hit {summary['hits']} "
        f"({_pct(summary['hit_rate'])})   miss {summary['misses']}",
        f"negatives {summary['negatives']:<4} clean {summary['clean']}        "
        f"false-positive {summary['false_positives']}",
        "中位誤差 " + ("—（無命中）" if summary["median_error_px"] is None
                       else f"{summary['median_error_px']:.0f}px（命中者）"),
    ]
    if radius_px is not None:
        lines.append(f"命中半徑 {radius_px}px（reentry_dataset_hit_radius_px）")
    for label, table in (("world", by_world), ("layer", by_layer)):
        if not table:
            continue
        lines.append(f"按 {label} 分組")
        for key, s in table.items():
            lines.append(
                f"  {str(key):<14}正 {s['positives']:<3} 中 {s['hits']:<3}"
                f"({_pct(s['hit_rate']):>6})   負 {s['negatives']:<3}"
                f" 誤報 {s['false_positives']}")
    return "\n".join(lines)


def load_image(path: str):
    """CJK 路徑安全的讀圖（`cv2.imread` 在中文路徑下靜默回 None）。"""
    import cv2
    import numpy as np
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def run_eval(root: str, rows, radius_px, *, detect=None, load=load_image) -> list:
    """把偵測器跑過整份資料集，回逐張判定。讀不到的圖略過（不計入分母）。"""
    if detect is None:
        from .teleport_board import detect as detect
    results = []
    for row in rows:
        frame = load(os.path.join(root, *row["image"].split("/")))
        if frame is None:
            continue
        try:
            prediction = detect(frame)
        except Exception as e:                    # 偵測器炸掉不該讓整份評估中止
            print(f"⚠ 偵測失敗 {row['image']}：{e}")
            prediction = None
        results.append(eval_row(row, prediction, radius_px))
    return results


def write_eval_detail(root: str, results, now=None) -> str:
    """逐張明細（含預測、真值、距離、判定）——成績單只給趨勢，追查要看這份。"""
    import time as _time
    stamp = _time.strftime("%Y%m%d_%H%M%S", _time.localtime(now or _time.time()))
    path = os.path.join(root, f"{EVAL_PREFIX}{stamp}.jsonl")
    os.makedirs(root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m miningbot.build_reentry_dataset",
        description="回礦傳送板語料工具（預設：語料夾 → dataset.jsonl）")
    parser.add_argument("--rescue", action="store_true",
                        help="把舊 ledger 裡還讀得到的快照倒進語料夾（冪等）")
    parser.add_argument("--eval", action="store_true",
                        help="把現行偵測器跑過整份資料集，印成績單 + 落逐張明細")
    parser.add_argument("--hit-radius", type=int,
                        default=cfg.reentry_dataset_hit_radius_px,
                        help="判「命中」的半徑 px（預設取 Config）")
    parser.add_argument("--ledger", default=None,
                        help="ledger.jsonl 路徑（預設取 Config，MSIX 重導後那份優先）")
    parser.add_argument("--corpus", default=None,
                        help="語料夾根目錄（預設 <log_dir>/corpus/reentry）")
    args = parser.parse_args(argv)
    root = args.corpus or default_corpus_root()
    print(f"語料夾  {root}")
    if args.rescue:
        # Config 的 ledger 是相對 `logs/…`（`main._apply_startup_overrides` 才會錨到
        # log_dir）；離線 script 不 import main，所以在這裡自己錨一次再走 MSIX 重導。
        ledger = args.ledger or prefer_redirected(
            resolve_runtime_log_path(cfg.reentry_remote_ledger, cfg.log_dir))
        print(f"ledger  {ledger}")
        print(format_rescue_report(rescue(ledger, root)))
        return 0
    rows, report = build_dataset(root)
    print(f"輸出      {write_dataset(root, rows)}")
    print(format_dataset_report(report))
    if not args.eval:
        return 0
    print()
    results = run_eval(root, rows, args.hit_radius)
    print(format_eval_report(summarize_eval(results),
                             group_eval(results, "world"),
                             group_eval(results, "layer_seen"),
                             radius_px=args.hit_radius))
    print(f"逐張明細 → {write_eval_detail(root, results)}")
    return 0


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())
