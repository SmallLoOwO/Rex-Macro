"""Episode / snapshot / 標註三層資料讀取（純函式，僅檔案 I/O 邊界）。

snapshot_index.jsonl 是 ``diagnostics.append_snapshot_index`` 寫的：
``{"written_at": float, "label": str, "path": str, "harvest_id": str|None}``。

episode = 一次採集（harvest）或一輪回礦 attempt（reentry）。group 規則：
- harvest：``harvest_id`` 非空（label 數字前綴，例如 ``007_...``）
- reentry：``label`` 開頭 ``reentry_ep<N>_``（diagnostics 的 harvest_id=None）
- 其他（remote_check / chat_open_fail / ...）→ 無法分 episode，略過

load_episodes / load_episode_detail 只讀 snapshot_index.jsonl；
list_annotations_for_episode 掃 fixtures_dir 下符合命名規則的 ``.json`` 檔。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Iterator

# reentry_ep<N>_…；diagnostics 寫 label 時用 ctx.episode_id（int）。
_REENTRY_LABEL_RE = re.compile(r"^reentry_ep(\d+)(?:_|$)")


# ── 標註優先序（2026-07-26）────────────────────────────────────────────────
#
# episode 詳細頁先前把快照按 label **字母排序**，於是 `aim_overlay_*` 永遠排在
# `sweep_empty_*` 前面、而一整批已經很成熟的東西（聊天框、背包、chill）夾在中間，
# 玩家要標的圖散落在整頁各處。
#
# 排序依據改成「這張圖對改善偵測有多少價值」，來自使用者的實機判斷：
# **chill 標語、背包、聊天框都已經是成熟的 OCR 路徑**，標了也改善不了什麼；
# 真正還沒解決的是**八方位掃描**與**礦物／追蹤框偵測**——那兩條才需要人標。
#
# 每筆是 (regex, tier)；由上往下**第一個命中者勝**，都沒命中落到 _DEFAULT_TIER。
# 要調整優先序只改這張表，render 端不必動。
_ANNOTATION_TIERS: tuple[tuple[re.Pattern, int], ...] = (
    # tier 0：偵測未解決——八方位掃描全空、追蹤框被拒、瞄準失敗、交人工
    (re.compile(r"sweep_empty|sweep_seen_once|_rejected|aim_fail"
                r"|needs_human|manual_survey|_miss(_|$)|gone_unconfirmed"), 0),
    # tier 1：已知失敗但非上述兩條主線——OCR 讀不出、事件文字未知、聊天框沒開
    (re.compile(r"unreadable|unknown|_fail(_|$)"), 1),
    # tier 2：成功對照組——兩側夾的另一側，標註價值中等
    (re.compile(r"sweep_confirmed|sweep_accepted|_accepted|_fired"
                r"|aim_fire|_fire_|success"), 2),
)
# 其餘（聊天／背包／chill／rare_found／俯仰／重置／回礦 yaw 語料）＝成熟流程紀錄
_DEFAULT_TIER = 3

ANNOTATION_TIER_LABELS: tuple[str, ...] = (
    "🔴 待標註——偵測未解決（八方位掃描／追蹤框／瞄準）",
    "🟠 已知失敗——OCR 讀不出／事件未知",
    "🟡 成功對照組——兩側夾的另一側",
    "⚪ 成熟流程紀錄——聊天／背包／chill／俯仰／回礦語料",
)


def annotation_tier(label: str) -> int:
    """快照 label → 標註優先序 tier（數字越小越該先標）。

    純函式，只看 label 字串；episode 數字前綴（``113_``）不影響比對，因為所有
    pattern 都是子字串比對而非錨定開頭。

    回 0~3，對應 ``ANNOTATION_TIER_LABELS`` 的索引。
    """
    text = str(label or "")
    for pattern, tier in _ANNOTATION_TIERS:
        if pattern.search(text):
            return tier
    return _DEFAULT_TIER


def snapshot_stem(path: str) -> str:
    """快照路徑 → 標註素材的檔名主幹（`/annotate` 用 basename 當 `image` 欄位）。"""
    return os.path.splitext(os.path.basename(str(path or "")))[0]


def annotated_stems(fixtures_dir: str | None) -> set:
    """已經標過的素材主幹集合。佇列靠它去重——不然每次進去都從第一張重來。"""
    stems: set[str] = set()
    if not fixtures_dir or not os.path.isdir(fixtures_dir):
        return stems
    for _root, _dirs, files in os.walk(fixtures_dir):
        for name in files:
            if name.endswith(".json"):
                stems.add(os.path.splitext(name)[0])
    return stems


def build_queue(records, annotated=(), tier: int = 0) -> list:
    """快照記錄 → 指定 tier 的標註佇列（純函式）。

    排序：`written_at` 由新到舊——最近的失敗最可能還沒被修掉，先標它的資訊量最高。
    `written_at` 缺值排到最後（`snapshot_index` 是 append-only，理論上都有）。
    去重用 `annotated`（已標過的檔名主幹集合）。
    """
    done = set(annotated or ())
    out = []
    for record in records or ():
        path = record.get("path")
        if not isinstance(path, str) or not path:
            continue
        label = str(record.get("label") or "")
        if annotation_tier(label) != tier:
            continue
        stem = snapshot_stem(path)
        if stem in done:
            continue
        done.add(stem)                     # 同一張圖在索引裡出現兩次也只排一次
        out.append({"path": path, "label": label, "stem": stem,
                    "written_at": record.get("written_at"),
                    "tier": tier})
    out.sort(key=lambda r: (r["written_at"] is None, -(r["written_at"] or 0.0)))
    return out


def annotation_queue(snapshot_index_path: str, fixtures_dir: str | None = None,
                     tier: int = 0) -> list:
    """`build_queue` 的 I/O 版：讀索引 + 掃 fixtures 去重。"""
    return build_queue(_iter_snapshot_records(snapshot_index_path),
                       annotated_stems(fixtures_dir), tier)


def _iter_snapshot_records(path: str) -> Iterator[dict]:
    """逐行讀 snapshot_index.jsonl；壞行（含寫到一半的 partial line）靜默略過。

    diagnostics 用 append 寫——读到尾部正在寫的 partial line 機率存在，故對
    JSON 解析失敗要容忍（snapshot_index 是 append-only，沒有 overwrite 風險）。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        # 檔不存在 → 無記錄（首次啟動）
        return


def _episode_id_and_type(record: dict) -> tuple[str, str] | None:
    """從單條 snapshot 記錄推 (episode_id, type)；無法分就回 None。

    harvest：``harvest_id`` 欄位（diagnostics 已撈出 label 數字前綴）
    reentry：從 label ``reentry_ep<N>_…`` 抽 N
    """
    hid = record.get("harvest_id")
    if isinstance(hid, str) and hid:
        return hid, "harvest"
    label = record.get("label")
    if isinstance(label, str):
        m = _REENTRY_LABEL_RE.match(label)
        if m:
            return m.group(1), "reentry"
    return None


# ── episode 分場門檻（2026-07-26）────────────────────────────────────────────
#
# 同一個編號可能對應**兩場不同的回礦**：ledger 佔號修好之前（見 reentry_remote.
# next_episode_id_from_ledger 的事故說明），沒收尾的 episode 不佔號，於是 07-26
# 的 13:15 與 18:34 兩場都叫 `reentry_ep26_*`。編號修好之後新資料不會再撞，但
# **既有快照索引裡的重複永遠在那裡**——時間軸照樣顯示兩組 dir1~dir8。
#
# 所以顯示層也要能分場：同編號的快照按時間排好，相鄰兩張間隔超過門檻就切一場。
# 門檻取 2 小時是保守值——單一 episode 合法地可以拖很久（reroll 無上限，ledger
# 實錄有 duration 12 分鐘、H051 有卡死 36 分鐘的紀錄），但沒有一場會在中間**完全
# 不拍任何快照**達兩小時。寧可把兩場併成一場（回到舊行為）也不要把一場切兩半。
_EPISODE_GAP_S = 2 * 60 * 60

# 類型 → (顯示前綴, 排序權重)。前綴讓「採集 #26」與「回礦 #26」在列表上一眼分得開，
# 也讓 episode key 不再互撞（舊版兩者都只用裸編號 "26"，/episode?id=26 會撈到
# last_ts 較新的那個、另一個永遠打不開）。
_TYPE_PREFIX: dict[str, str] = {"harvest": "採", "reentry": "回"}
_TYPE_LABEL: dict[str, str] = {"harvest": "採集", "reentry": "回礦"}


def episode_key(ep_type: str, episode_no: str, run_ts: float | None = None,
                run_index: int = 0) -> str:
    """episode 的唯一識別（URL 用）。``harvest:114`` / ``reentry:26``。

    同編號被切成多場時，第 2 場起附上該場起始時間戳 ``reentry:26@1784...``——
    用時間戳而不是流水號，是因為流水號會隨「之後又多出一場」而整批位移，
    玩家收藏的網址就失效了；時間戳綁定那一場本身，永遠穩定。
    """
    base = f"{ep_type}:{episode_no}"
    if run_index > 0 and run_ts is not None:
        return f"{base}@{int(run_ts)}"
    return base


def episode_label(ep_type: str, episode_no: str, run_ts: float | None = None,
                  run_index: int = 0) -> str:
    """列表/詳細頁顯示用的人話標題：``採#114``、``回#26``。

    同編號多場時附日期時間區分（``回#26（07-26 13:15）``）——玩家看到重複編號
    不會再以為是同一場的快照重複了。
    """
    prefix = _TYPE_PREFIX.get(ep_type, "")
    base = f"{prefix}#{episode_no}" if prefix else str(episode_no)
    if run_index > 0 and run_ts is not None:
        import time as _time
        stamp = _time.strftime("%m-%d %H:%M", _time.localtime(run_ts))
        return f"{base}（{stamp}）"
    return base


def type_label(ep_type: str) -> str:
    """type 代碼 → 中文（表格「類型」欄用）。未知類型原樣回傳。"""
    return _TYPE_LABEL.get(ep_type, ep_type or "")


def split_runs(snapshots: list[dict], gap_s: float = _EPISODE_GAP_S) -> list[list[dict]]:
    """同編號的快照按時間排序後，依 ``gap_s`` 切成多場；回 [[snap, ...], ...]。

    沒有 written_at 的記錄排在最後、且不參與切分（時間未知 ⇒ 無從判斷屬於哪場，
    歸進最後一場即可，總比整筆丟掉好）。
    """
    timed = [s for s in snapshots if isinstance(s.get("written_at"), (int, float))]
    untimed = [s for s in snapshots if not isinstance(s.get("written_at"), (int, float))]
    timed.sort(key=lambda s: s["written_at"])
    runs: list[list[dict]] = []
    for snap in timed:
        if runs and snap["written_at"] - runs[-1][-1]["written_at"] < gap_s:
            runs[-1].append(snap)
        else:
            runs.append([snap])
    if untimed:
        if runs:
            runs[-1].extend(untimed)
        else:
            runs.append(untimed)
    return runs


def _build_episode(episode_id: str, ep_type: str, snapshots: list[dict],
                   run_index: int = 0) -> dict:
    """把 group 後的 snapshot list 組成 episode dict。

    ``harvest_id`` 保留為**裸編號**（不加前綴）——素材檔名用它比對
    （``auto_<id>_*.json``，見 list_annotations_for_episode），加了前綴就撈不到了。
    顯示與路由改用 ``key`` / ``label``。
    """
    ts_list = [
        s.get("written_at") for s in snapshots
        if isinstance(s.get("written_at"), (int, float))
    ]
    first_ts = min(ts_list) if ts_list else None
    return {
        "harvest_id": episode_id,  # 沿用 brief 欄位名；reentry episode 也用此欄位
        "type": ep_type,
        "key": episode_key(ep_type, episode_id, first_ts, run_index),
        "label": episode_label(ep_type, episode_id, first_ts, run_index),
        "type_label": type_label(ep_type),
        "run_index": run_index,
        "snapshots": list(snapshots),
        "first_ts": first_ts,
        "last_ts": max(ts_list) if ts_list else None,
        "count": len(snapshots),
    }


def load_episodes(
    snapshot_index_path: str,
    harvest_log_path: str | None = None,
) -> list[dict]:
    """讀 snapshot_index.jsonl，按 episode 分組；回 list 按 last_ts desc 排序。

    每個 episode dict：
    ``{harvest_id, type:"harvest"|"reentry", snapshots:[...], first_ts, last_ts, count}``

    ``harvest_log_path`` 目前未使用（保留以相容未來從 harvest.log 撈結果/事件的擴充）；
    存在/不存在都不影響行為。

   壞行/partial line 略過（檔案可能正在被 append）；無法分 episode 的 label（如
    ``remote_check``）也略過——它們不屬於任何 episode。
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in _iter_snapshot_records(snapshot_index_path):
        key = _episode_id_and_type(record)
        if key is None:
            continue
        groups.setdefault(key, []).append(record)

    episodes = []
    for (ep_id, ep_type), snapshots in groups.items():
        # 同編號可能是兩場（2026-07-26 事故的既有資料）→ 依時間間隔切開，
        # 否則詳細頁的時間軸會把兩場的 dir1~dir8 疊成一份「重複」清單。
        for run_index, run in enumerate(split_runs(snapshots)):
            episodes.append(_build_episode(ep_id, ep_type, run, run_index))
    # last_ts 為 None 的排到尾部；其餘按 last_ts desc
    episodes.sort(
        key=lambda e: (e["last_ts"] is None, -(e["last_ts"] or 0.0)),
    )
    return episodes


def load_episode_detail(episode_id: str, snapshot_index_path: str) -> dict | None:
    """回單一 episode 詳細；找不到回 None。

    接受兩種識別（2026-07-26）：
    - **完整 key**（現行）：``harvest:114`` / ``reentry:26`` / ``reentry:26@1784...``
      ——精確指到一場，type 不同或分場不同都不會互相蓋掉。
    - **裸編號**（舊網址／舊書籤）：``26``。同編號可能同時存在採集與回礦、也可能
      被切成多場，一律回 last_ts 最新那筆（維持舊行為，不讓舊連結變 404）。

    舊版只吃裸編號，且註解寫「多個 episode 同 id 理論上不該發生」——實際上
    `harvest #26` 與 `reentry #26` 完全可以並存，另一筆從此打不開。
    """
    episodes = load_episodes(snapshot_index_path)
    matches = [e for e in episodes if e["key"] == episode_id]
    if not matches:
        # 舊網址相容：裸編號比對 harvest_id
        matches = [e for e in episodes if e["harvest_id"] == episode_id]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    matches.sort(key=lambda e: (e["last_ts"] is None, -(e["last_ts"] or 0.0)))
    return matches[0]


def list_annotations_for_episode(
    episode_id: str,
    fixtures_dir: str,
) -> list[dict]:
    """遞迴掃 fixtures_dir 找該 episode 已標註的素材 .json 黨。

    命名規則（spec §5）：
    - 自動收集：``auto_<episode_id>_*.json``
    - 玩家手動：``manual_*_<episode_id>_*.json``

    壞 JSON 略過（玩家可能寫到一半、編輯器存錯）；非 ``.json`` 檔略過。
    沒有 fixtures_dir / 目錄空 → 回空 list。

    P5 final-review：``POST /api/annotate`` 預設寫 ``aim/`` 子目錄、
    ``_save_auto_fixture`` 寫 ``aim/`` 或 ``reentry/teleport_board/``。
    故此函式走 ``os.walk`` 遞迴；caller 不必預知子目錄結構即可撈回所有標註。
    """
    if not episode_id or not os.path.isdir(fixtures_dir):
        return []
    eid = str(episode_id)
    auto_prefix = f"auto_{eid}_"
    manual_suffix_prefix = f"_{eid}_"

    out: list[dict] = []
    seen_paths: set[str] = set()  # 防同一檔被多個 symlink 路徑重複算
    for root, _dirs, files in os.walk(fixtures_dir):
        for name in sorted(files):
            if not name.endswith(".json"):
                continue
            if not (
                name.startswith(auto_prefix)
                or (name.startswith("manual_") and manual_suffix_prefix in name)
            ):
                continue
            full_path = os.path.join(root, name)
            try:
                real = os.path.realpath(full_path)
            except OSError:
                real = full_path
            if real in seen_paths:
                continue
            seen_paths.add(real)
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (ValueError, OSError):
                continue
            if isinstance(data, dict):
                # 附上來源檔名方便 UI 顯示；不覆寫素材本身的 image 欄位
                data.setdefault("_source_file", name)
                out.append(data)
    return out
