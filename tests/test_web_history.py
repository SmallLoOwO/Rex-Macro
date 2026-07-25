# tests/test_web_history.py
"""P5 Task 4：episode / snapshot / 標註三層資料讀取純函式。

episode = 採集一次（harvest）或回礦一輪 attempt（reentry）。snapshot_index.jsonl
是 diagnostics.append_snapshot_index 寫的：{written_at, label, path, harvest_id}；
harvest 標籤開頭是數字（harvest_id 帶數字），reentry 標籤是 ``reentry_ep<N>_…``。
"""
import json

from miningbot.web_history import (
    list_annotations_for_episode,
    load_episode_detail,
    load_episodes,
)


def _write_jsonl(path, lines):
    """把 list[dict] 寫成 jsonl（每行一個 JSON）。"""
    with open(path, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


class TestLoadEpisodes:
    def test_empty_file_returns_empty_list(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        idx.write_text("")
        assert load_episodes(str(idx)) == []

    def test_missing_file_returns_empty_list(self, tmp_path):
        # 沒寫過任何 snapshot（首次啟動）也該安全
        assert load_episodes(str(tmp_path / "absent.jsonl")) == []

    def test_corrupt_lines_are_skipped(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        idx.write_text(
            '{"written_at": 1000.0, "label": "007_needs_human", '
            '"path": "/a.png", "harvest_id": "007"}\n'
            "this line is not json\n"
            '{"written_at": 1001.0, "label": "007_aim_cell", '
            '"path": "/b.png", "harvest_id": "007"}\n'
            "{not even balanced\n"
        )
        episodes = load_episodes(str(idx))
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep["harvest_id"] == "007"
        assert ep["type"] == "harvest"
        assert ep["count"] == 2

    def test_multi_harvest_episodes_grouped(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png", "harvest_id": "007"},
            {"written_at": 1001.0, "label": "007_b", "path": "/b.png", "harvest_id": "007"},
            {"written_at": 2000.0, "label": "009_a", "path": "/c.png", "harvest_id": "009"},
        ])
        episodes = load_episodes(str(idx))
        assert len(episodes) == 2
        ids = sorted(e["harvest_id"] for e in episodes)
        assert ids == ["007", "009"]
        # 都被歸類為 harvest
        assert all(e["type"] == "harvest" for e in episodes)

    def test_reentry_episode_grouped_by_label_prefix(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 3000.0, "label": "reentry_ep5_dir1", "path": "/d.png", "harvest_id": None},
            {"written_at": 3001.0, "label": "reentry_ep5_dir2", "path": "/e.png", "harvest_id": None},
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png", "harvest_id": "007"},
        ])
        episodes = load_episodes(str(idx))
        assert len(episodes) == 2
        reentry = next(e for e in episodes if e["type"] == "reentry")
        assert reentry["harvest_id"] == "5"
        assert reentry["count"] == 2

    def test_sorts_by_last_ts_desc(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png", "harvest_id": "007"},
            {"written_at": 3000.0, "label": "009_a", "path": "/b.png", "harvest_id": "009"},
            {"written_at": 2000.0, "label": "012_a", "path": "/c.png", "harvest_id": "012"},
        ])
        episodes = load_episodes(str(idx))
        # 最新（largest ts）的排前面
        assert [e["harvest_id"] for e in episodes] == ["009", "012", "007"]

    def test_episode_has_required_fields(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png", "harvest_id": "007"},
            {"written_at": 1005.0, "label": "007_b", "path": "/b.png", "harvest_id": "007"},
        ])
        episodes = load_episodes(str(idx))
        ep = episodes[0]
        assert set(ep.keys()) >= {
            "harvest_id", "type", "snapshots", "first_ts", "last_ts", "count",
        }
        assert ep["first_ts"] == 1000.0
        assert ep["last_ts"] == 1005.0
        assert ep["count"] == 2
        assert len(ep["snapshots"]) == 2
        assert ep["snapshots"][0]["label"] in ("007_a", "007_b")

    def test_unknown_label_prefix_skipped(self, tmp_path):
        # 沒有 harvest_id 也不是 reentry_ep<N> 開頭 → 無法分 episode
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "remote_check", "path": "/a.png", "harvest_id": None},
            {"written_at": 1001.0, "label": "chat_open_fail", "path": "/b.png", "harvest_id": None},
        ])
        assert load_episodes(str(idx)) == []

    def test_harvest_log_optional(self, tmp_path):
        # harvest_log_path 是 optional；不傳或檔不存在不該炸
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png", "harvest_id": "007"},
        ])
        # 不傳第二個參數
        episodes = load_episodes(str(idx))
        assert len(episodes) == 1
        # 傳不存在路徑
        episodes2 = load_episodes(str(idx), str(tmp_path / "absent.log"))
        assert len(episodes2) == 1


class TestLoadEpisodeDetail:
    def test_found_returns_episode(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png", "harvest_id": "007"},
            {"written_at": 1001.0, "label": "007_b", "path": "/b.png", "harvest_id": "007"},
            {"written_at": 2000.0, "label": "009_a", "path": "/c.png", "harvest_id": "009"},
        ])
        ep = load_episode_detail("007", str(idx))
        assert ep is not None
        assert ep["harvest_id"] == "007"
        assert ep["count"] == 2
        assert len(ep["snapshots"]) == 2

    def test_not_found_returns_none(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "007_a", "path": "/a.png", "harvest_id": "007"},
        ])
        assert load_episode_detail("999", str(idx)) is None

    def test_missing_index_file_returns_none(self, tmp_path):
        assert load_episode_detail("007", str(tmp_path / "absent.jsonl")) is None

    def test_reentry_episode_detail(self, tmp_path):
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 3000.0, "label": "reentry_ep5_dir1", "path": "/a.png", "harvest_id": None},
        ])
        ep = load_episode_detail("5", str(idx))
        assert ep is not None
        assert ep["type"] == "reentry"
        assert ep["harvest_id"] == "5"


class TestListAnnotationsForEpisode:
    def test_auto_pattern_match(self, tmp_path):
        # auto_<episode_id>_*.json
        (tmp_path / "auto_007_success.json").write_text(
            json.dumps({
                "image": "auto_007_success.png",
                "annotation": {"type": "square", "cx": 100, "cy": 100, "size": 30},
                "tier": None, "variant": None, "mineral": None,
                "source": {"kind": "auto"},
                "symptom": None, "related_incident": None,
            }),
            encoding="utf-8",
        )
        # 不符 episode 的不該被撈出
        (tmp_path / "auto_009_other.json").write_text("{}", encoding="utf-8")
        result = list_annotations_for_episode("007", str(tmp_path))
        assert len(result) == 1
        assert result[0]["image"] == "auto_007_success.png"

    def test_manual_pattern_match(self, tmp_path):
        # manual_*_<episode_id>_*.json
        (tmp_path / "manual_2026-07-26_007_terrain.json").write_text(
            json.dumps({"image": "manual_terrain.png"}),
            encoding="utf-8",
        )
        result = list_annotations_for_episode("007", str(tmp_path))
        assert len(result) == 1
        assert result[0]["image"] == "manual_terrain.png"

    def test_both_patterns_combined(self, tmp_path):
        (tmp_path / "auto_007_a.json").write_text(
            json.dumps({"image": "a.png"}), encoding="utf-8",
        )
        (tmp_path / "manual_x_007_b.json").write_text(
            json.dumps({"image": "b.png"}), encoding="utf-8",
        )
        (tmp_path / "auto_009_c.json").write_text(
            json.dumps({"image": "c.png"}), encoding="utf-8",
        )
        result = list_annotations_for_episode("007", str(tmp_path))
        images = sorted(r["image"] for r in result)
        assert images == ["a.png", "b.png"]

    def test_corrupt_json_skipped(self, tmp_path):
        (tmp_path / "auto_007_good.json").write_text(
            json.dumps({"image": "g.png"}), encoding="utf-8",
        )
        (tmp_path / "auto_007_bad.json").write_text(
            "not valid json {", encoding="utf-8",
        )
        result = list_annotations_for_episode("007", str(tmp_path))
        assert len(result) == 1
        assert result[0]["image"] == "g.png"

    def test_non_json_files_ignored(self, tmp_path):
        # PNG 不該被讀
        (tmp_path / "auto_007_pic.png").write_text("not json", encoding="utf-8")
        (tmp_path / "auto_007_pic.txt").write_text("nope", encoding="utf-8")
        (tmp_path / "auto_007_data.json").write_text(
            json.dumps({"image": "x.png"}), encoding="utf-8",
        )
        result = list_annotations_for_episode("007", str(tmp_path))
        assert len(result) == 1

    def test_missing_dir_returns_empty(self, tmp_path):
        # 沒有任何標註也該安全
        assert list_annotations_for_episode("007", str(tmp_path)) == []
        assert list_annotations_for_episode(
            "007", str(tmp_path / "does_not_exist"),
        ) == []

    def test_reentry_episode_annotations(self, tmp_path):
        # reentry episode_id 也用同樣 naming convention
        (tmp_path / "auto_5_landing.json").write_text(
            json.dumps({"image": "r.png"}), encoding="utf-8",
        )
        result = list_annotations_for_episode("5", str(tmp_path))
        assert len(result) == 1
        assert result[0]["image"] == "r.png"
