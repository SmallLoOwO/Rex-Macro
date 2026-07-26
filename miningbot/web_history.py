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


def _build_episode(episode_id: str, ep_type: str, snapshots: list[dict]) -> dict:
    """把 group 後的 snapshot list 組成 episode dict。"""
    ts_list = [
        s.get("written_at") for s in snapshots
        if isinstance(s.get("written_at"), (int, float))
    ]
    return {
        "harvest_id": episode_id,  # 沿用 brief 欄位名；reentry episode 也用此欄位
        "type": ep_type,
        "snapshots": list(snapshots),
        "first_ts": min(ts_list) if ts_list else None,
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

    episodes = [
        _build_episode(ep_id, ep_type, snapshots)
        for (ep_id, ep_type), snapshots in groups.items()
    ]
    # last_ts 為 None 的排到尾部；其餘按 last_ts desc
    episodes.sort(
        key=lambda e: (e["last_ts"] is None, -(e["last_ts"] or 0.0)),
    )
    return episodes


def load_episode_detail(episode_id: str, snapshot_index_path: str) -> dict | None:
    """回單一 episode 詳細；找不到回 None。

    episode_id 比對 episode dict 的 ``harvest_id`` 欄位（純字串，例如 harvest
    的 "007" 或 reentry 的 "5"）。多個 episode 同 id（理論上不該發生：type
    不同的兩個 episode 也會被視為同一筆）→ 回 last_ts 最新那筆。
    """
    matches = [
        e for e in load_episodes(snapshot_index_path)
        if e["harvest_id"] == episode_id
    ]
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
