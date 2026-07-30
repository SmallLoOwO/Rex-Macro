# tests/test_web_history.py
"""P5 Task 4：episode / snapshot / 標註三層資料讀取純函式。

episode = 採集一次（harvest）或回礦一輪 attempt（reentry）。snapshot_index.jsonl
是 diagnostics.append_snapshot_index 寫的：{written_at, label, path, harvest_id}；
harvest 標籤開頭是數字（harvest_id 帶數字），reentry 標籤是 ``reentry_ep<N>_…``。
"""
import json

from miningbot.web_history import (
    episode_key,
    episode_label,
    list_annotations_for_episode,
    load_episode_detail,
    load_episodes,
    split_runs,
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


# ── 2026-07-26：episode 類型前綴 + 同編號分場 ────────────────────────────────
#
# 事故背景：13:15 與 18:34 兩場回礦都拿到 `#26`（ledger 佔號缺陷，見
# reentry_remote.next_episode_id_from_ledger），快照都叫 `reentry_ep26_dir1..8`
# ⇒ 詳細頁時間軸出現整組重複的 dir1~dir8。編號已在 bot 端修好，但**既有索引裡的
# 重複永遠在**，所以顯示層也要能把兩場切開。
#
# 另一個獨立缺陷：`harvest #26` 與 `reentry #26` 舊版共用裸編號當 key，
# `/episode?id=26` 只回其中一個，另一個永遠打不開。

_HOUR = 3600.0


class TestEpisodeKeyAndLabel:
    def test_key_includes_type(self):
        assert episode_key("harvest", "114") == "harvest:114"
        assert episode_key("reentry", "26") == "reentry:26"

    def test_label_has_type_prefix(self):
        assert episode_label("harvest", "114") == "採#114"
        assert episode_label("reentry", "26") == "回#26"

    def test_second_run_key_is_distinct_and_timestamp_anchored(self):
        """第 2 場附時間戳：綁定那一場本身，之後再多出幾場也不會位移。"""
        first = episode_key("reentry", "26", run_ts=1000.0, run_index=0)
        second = episode_key("reentry", "26", run_ts=20000.0, run_index=1)
        assert first == "reentry:26"
        assert second == "reentry:26@20000"
        assert first != second

    def test_second_run_label_shows_date(self):
        label = episode_label("reentry", "26", run_ts=1784000000.0, run_index=1)
        assert label.startswith("回#26（") and label.endswith("）")


class TestSplitRuns:
    def _snap(self, ts, label="reentry_ep26_dir1"):
        return {"written_at": ts, "label": label, "path": f"/{ts}.png"}

    def test_single_run_stays_whole(self):
        snaps = [self._snap(t) for t in (1000.0, 1002.0, 1004.0)]
        assert len(split_runs(snaps)) == 1

    def test_long_gap_splits(self):
        """實機值：13:15 與 18:34 相隔 5h19m，遠超 2 小時門檻。"""
        snaps = [self._snap(t) for t in (1000.0, 1002.0, 1000.0 + 5.3 * _HOUR)]
        runs = split_runs(snaps)
        assert len(runs) == 2
        assert len(runs[0]) == 2 and len(runs[1]) == 1

    def test_long_but_continuous_episode_not_split(self):
        """單一 episode 合法地可拖很久（reroll 無上限、H051 卡死 36 分）——
        只要中途仍在拍快照就不該被切開。"""
        snaps = [self._snap(1000.0 + i * 600.0) for i in range(8)]  # 每 10 分一張，共 70 分
        assert len(split_runs(snaps)) == 1

    def test_runs_sorted_by_time(self):
        snaps = [self._snap(t) for t in (5000.0, 1000.0)]
        runs = split_runs(snaps)
        assert runs[0][0]["written_at"] == 1000.0

    def test_untimed_snapshots_kept(self):
        snaps = [self._snap(1000.0), {"label": "x", "path": "/x.png"}]
        runs = split_runs(snaps)
        assert sum(len(r) for r in runs) == 2


class TestDuplicateEpisodeNumbers:
    def _dirs(self, base_ts, ep=26):
        return [
            {"written_at": base_ts + i, "label": f"reentry_ep{ep}_dir{i + 1}",
             "path": f"/{base_ts}_{i}.png", "harvest_id": None}
            for i in range(8)
        ]

    def test_two_runs_same_number_become_two_episodes(self, tmp_path):
        """事故本體的顯示修復：兩場不再併成一個 episode。"""
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), self._dirs(1000.0) + self._dirs(1000.0 + 5.3 * _HOUR))
        episodes = load_episodes(str(idx))
        assert len(episodes) == 2
        assert all(e["count"] == 8 for e in episodes), "每場各自 8 張，不再重複疊加"
        assert len({e["key"] for e in episodes}) == 2

    def test_each_run_timeline_has_no_duplicate_labels(self, tmp_path):
        """使用者看到的症狀：時間軸出現兩組 dir1~dir8。"""
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), self._dirs(1000.0) + self._dirs(1000.0 + 5.3 * _HOUR))
        for ep in load_episodes(str(idx)):
            labels = [s["label"] for s in ep["snapshots"]]
            assert len(labels) == len(set(labels))

    def test_harvest_and_reentry_same_number_do_not_collide(self, tmp_path):
        """採集 #26 與回礦 #26 並存時兩邊都要打得開（舊版只回得到一個）。"""
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "26_aim_cell", "path": "/h.png",
             "harvest_id": "26"},
            {"written_at": 2000.0, "label": "reentry_ep26_dir1", "path": "/r.png",
             "harvest_id": None},
        ])
        harvest = load_episode_detail("harvest:26", str(idx))
        reentry = load_episode_detail("reentry:26", str(idx))
        assert harvest is not None and harvest["type"] == "harvest"
        assert reentry is not None and reentry["type"] == "reentry"
        assert harvest["label"] == "採#26" and reentry["label"] == "回#26"

    def test_bare_id_still_resolves_for_old_links(self, tmp_path):
        """舊書籤 /episode?id=26 不該變 404。"""
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "26_a", "path": "/a.png", "harvest_id": "26"},
        ])
        assert load_episode_detail("26", str(idx)) is not None

    def test_harvest_id_field_stays_bare_for_fixture_lookup(self, tmp_path):
        """素材檔名是 `auto_26_*.json`——harvest_id 欄位不可被加上前綴。"""
        idx = tmp_path / "snapshot_index.jsonl"
        _write_jsonl(str(idx), [
            {"written_at": 1000.0, "label": "reentry_ep26_dir1", "path": "/r.png",
             "harvest_id": None},
        ])
        ep = load_episode_detail("reentry:26", str(idx))
        assert ep["harvest_id"] == "26"


# ---- bot 當下判定（2026-07-31）---------------------------------------------
#
# 「bot 有沒有接受」寫在 label 裡（main.py 的 _hsnap 呼叫點），標註頁不該叫玩家猜。


class TestLabelVerdict:
    def test_accepted_labels_carry_coordinates(self):
        from miningbot.web_history import label_verdict
        assert label_verdict("138_sweep_accepted_dir4_947_520") == {
            "verdict": "accepted", "x": 947, "y": 520}
        # d3_fire 用 `%dx%d` 寫法（同一件事、兩種分隔字元）
        assert label_verdict("138_d3_fire_dir3_1397x513") == {
            "verdict": "accepted", "x": 1397, "y": 513}

    def test_sweep_empty_is_rejected_without_mark(self):
        from miningbot.web_history import label_verdict
        assert label_verdict("137_sweep_empty_dir4") == {
            "verdict": "rejected", "x": None, "y": None}

    def test_seen_once_is_rejected_but_keeps_its_mark(self):
        """看到一次沒過雙幀穩定＝掃描照樣繼續、沒開火，就 bot 的行為是拒絕；
        座標仍要留著，頁面才畫得出「看到但沒採信」的圈。"""
        from miningbot.web_history import label_verdict
        assert label_verdict("123_sweep_seen_once_dir0_1208_476") == {
            "verdict": "rejected", "x": 1208, "y": 476}

    def test_unrelated_labels_have_no_verdict(self):
        """俯仰／boost／回礦那些不是追蹤框那條路的快照＝不知道，不可當成拒絕以外的東西。"""
        from miningbot.web_history import label_verdict
        for label in ("reentry_ep27_dir3", "pitch_ok_before",
                      "134_boost_count_unreadable", ""):
            assert label_verdict(label)["verdict"] is None

    def test_filename_stem_works_too(self):
        """單張模式只有檔名可推——檔名尾端就是 label，奈秒序號不可被誤讀成座標。"""
        from miningbot.web_history import label_verdict
        got = label_verdict(
            "20260731_001105_587684100_000172_133_sweep_empty_dir4")
        assert got == {"verdict": "rejected", "x": None, "y": None}

    def test_after_the_fact_frames_are_not_accepted(self):
        """採集成功／框消失後才拍的畫面：bot 當下判定是「框已經不在」。

        使用者 2026-07-31 看到 `139_harvest_success` 提出：那張圖是採完之後拍的
        （`_harvest_success(after_frame)`），畫面裡本來就不該有框；先前歸
        accepted 會把玩家標的「什麼都沒有」推成「誤判」，於是任何標註都套不上。
        """
        from miningbot.web_history import label_verdict
        for label in ("139_harvest_success", "139_harvest_success_special",
                      "131_d3_gone_unconfirmed", "113_d3_after"):
            assert label_verdict(label)["verdict"] == "after", label

    def test_d3_miss_stays_accepted_because_the_tracker_is_still_there(self):
        """`d3_miss` 是 gone=False 那一支（框還在、只是沒打中）——bot 確實接受了。"""
        from miningbot.web_history import label_verdict
        assert label_verdict("119_d3_miss_1")["verdict"] == "accepted"


class TestQueueEpisodeField:
    def test_rows_carry_display_episode_label(self):
        """同一場沿用稀有度要靠它；順便當顯示名（`採#139` / `回#27`）。"""
        from miningbot.web_history import build_queue
        rows = build_queue(
            [{"written_at": 2.0, "label": "139_harvest_success",
              "path": "a.png", "harvest_id": "139"},
             {"written_at": 1.0, "label": "reentry_ep27_dir3",
              "path": "b.png", "harvest_id": None}],
            tier=(2, 3), exists=lambda p: True)
        got = {r["label"]: r["episode"] for r in rows}
        assert got["139_harvest_success"] == "採#139"
        assert got["reentry_ep27_dir3"] == "回#27"

    def test_row_without_episode_is_none(self):
        from miningbot.web_history import build_queue
        rows = build_queue(
            [{"written_at": 1.0, "label": "chat_open_fail", "path": "c.png",
              "harvest_id": None}],
            tier=1, exists=lambda p: True)
        assert rows[0]["episode"] is None
