"""`miningbot/build_reentry_dataset.py`：MSIX 路徑重導 + 舊 ledger 殘骸搶救。

路徑重導是純函式 + 注入的 `exists`，不需要真檔（本專案唯一保留這段邏輯的地方；
建資料集之後只讀語料夾一種來源）。
"""

import json
import os

import pytest

from miningbot import build_reentry_dataset as brd
from miningbot import corpus

_RECORDED = (r"C:\Users\puppy\AppData\Local\RexMacro\logs\snapshots"
             r"\reentry\20260719_124908_reentry_ep3_dir1.png")
_REDIRECTED = (r"C:\Users\puppy\AppData\Local\Packages"
               r"\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0"
               r"\LocalCache\Local\RexMacro\logs\snapshots"
               r"\reentry\20260719_124908_reentry_ep3_dir1.png")


# ---- MSIX 雙路徑 -----------------------------------------------------------

def test_redirect_candidates_inserts_localcache_after_appdata_local():
    assert brd.redirect_candidates(_RECORDED) == [_RECORDED, _REDIRECTED]


def test_redirect_candidates_does_not_double_redirect():
    """已經是 LocalCache 路徑再插一層會得到不存在的雙重前綴。"""
    assert brd.redirect_candidates(_REDIRECTED) == [_REDIRECTED]


def test_redirect_candidates_leaves_repo_logs_alone():
    """`uv run` 啟動落 repo `logs/`，不在 %LOCALAPPDATA% 底下，沒有重導可言。"""
    p = r"C:\repo\logs\snapshots\reentry\a.png"
    assert brd.redirect_candidates(p) == [p]


def test_resolve_shot_path_prefers_recorded_value():
    got = brd.resolve_shot_path(_RECORDED, exists=lambda p: p == _RECORDED)
    assert got == _RECORDED


def test_resolve_shot_path_falls_back_to_localcache():
    """`pythonw` 場次：記錄值不存在，實體在 LocalCache。"""
    got = brd.resolve_shot_path(_RECORDED, exists=lambda p: p == _REDIRECTED)
    assert got == _REDIRECTED


def test_resolve_shot_path_returns_none_when_both_gone():
    """兩者皆無＝這張圖已被 retention 刪掉，計入「已消失」。"""
    assert brd.resolve_shot_path(_RECORDED, exists=lambda _p: False) is None


def test_prefer_redirected_picks_localcache_when_both_exist():
    """兩邊都有東西時取實機那份——production 走 pythonw。"""
    assert brd.prefer_redirected(_RECORDED, exists=lambda _p: True) == _REDIRECTED


def test_default_corpus_root_follows_redirected_log_dir():
    log_dir = r"C:\Users\puppy\AppData\Local\RexMacro\logs"
    got = brd.default_corpus_root(log_dir, isdir=lambda p: "LocalCache" in p)
    assert got == corpus.corpus_root(
        r"C:\Users\puppy\AppData\Local\Packages"
        r"\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0"
        r"\LocalCache\Local\RexMacro\logs")


# ---- ledger 解析 -----------------------------------------------------------

def _row(episode=3, attempt=4, outcome="confirmed_by_user", shots=None, clicks=None):
    return {"episode": episode, "t": 1784435535.6, "world": "Lucernia",
            "outcome": outcome, "attempt": attempt, "sticky_layer": "Shamrock",
            "shots": shots if shots is not None else [[0, "a.png"], [1, "b.png"]],
            "clicks": clicks or []}


def _lines(*objs):
    return [json.dumps(o, ensure_ascii=False) for o in objs]


def test_parse_ledger_drops_reservation_rows_without_shots():
    """`outcome="started"` 是佔號行（2026-07-26 起），沒有 shots。"""
    rows, _voids, bad = brd.parse_ledger(_lines(
        {"episode": 26, "t": 1.0, "outcome": "started", "trigger": "reset"},
        _row()))
    assert list(rows) == [(3, 4)] and bad == 0


def test_parse_ledger_tolerates_partial_trailing_line():
    """append-only，尾端可能是寫到一半的 partial line。"""
    rows, _voids, bad = brd.parse_ledger(_lines(_row()) + ['{"episode": 4, "sho'])
    assert list(rows) == [(3, 4)] and bad == 1


def test_parse_ledger_collects_void_rows():
    _rows, voids, _bad = brd.parse_ledger(_lines(
        {"type": "void", "episode": 2, "click_index": 0, "t": 1.0}))
    assert voids and voids[0]["episode"] == 2


def test_apply_voids_marks_click_invalid():
    """玩家自己標作廢的那一筆不可當正樣本。"""
    rows = {(2, 1): _row(episode=2, attempt=1,
                         clicks=[{"pos": [1, 2], "dir": 0, "invalid": False}])}
    brd.apply_voids(rows, [{"type": "void", "episode": 2, "click_index": 0}])
    assert rows[(2, 1)]["clicks"][0]["invalid"] is True


def test_apply_voids_ignores_out_of_range_index():
    rows = {(2, 1): _row(episode=2, attempt=1, clicks=[])}
    brd.apply_voids(rows, [{"type": "void", "episode": 2, "click_index": 5}])
    assert rows[(2, 1)]["clicks"] == []


# ---- 搶救 ------------------------------------------------------------------

def _write_ledger(tmp_path, *objs):
    p = tmp_path / "ledger.jsonl"
    p.write_text("\n".join(_lines(*objs)) + "\n", encoding="utf-8")
    return str(p)


def _fake_snapshots(tmp_path, n=8, prefix="ep3"):
    src = tmp_path / "snapshots"
    src.mkdir(exist_ok=True)
    shots = []
    for i in range(n):
        f = src / f"{prefix}_dir{i + 1}.png"
        f.write_bytes(b"png" * 8)
        shots.append([i, str(f)])
    return shots


def test_rescue_writes_group_with_meta(tmp_path):
    shots = _fake_snapshots(tmp_path)
    ledger = _write_ledger(tmp_path, _row(
        shots=shots,
        clicks=[{"pos": [1604, 450], "dir": 2, "invalid": False,
                 "layer_seen": "Shamrock", "depth_m": 7100}]))
    root = str(tmp_path / "corpus")
    report = brd.rescue(ledger, root)

    assert report["groups_written"] == 1
    assert (report["shots_resolved"], report["shots_missing"]) == (8, 0)
    meta = json.loads((tmp_path / "corpus" / "ep3_attempt4"
                       / corpus.META_NAME).read_text(encoding="utf-8"))
    assert [s["file"] for s in meta["shots"]] == [f"dir{i}.png" for i in range(1, 9)]
    assert meta["clicks"][0]["dir"] == 3          # 內部 0-based 2 → 介面 3
    assert meta["outcome"] == "confirmed_by_user"


def test_rescue_counts_vanished_shots_and_skips_them(tmp_path):
    """已消失的那些筆計入報告，且 meta 不可指向不存在的檔案。"""
    shots = _fake_snapshots(tmp_path, n=3)
    shots.append([3, str(tmp_path / "snapshots" / "gone.png")])
    ledger = _write_ledger(tmp_path, _row(shots=shots))
    root = str(tmp_path / "corpus")
    report = brd.rescue(ledger, root)

    assert (report["shots_resolved"], report["shots_missing"]) == (3, 1)
    meta = json.loads((tmp_path / "corpus" / "ep3_attempt4"
                       / corpus.META_NAME).read_text(encoding="utf-8"))
    assert [s["file"] for s in meta["shots"]] == ["dir1.png", "dir2.png", "dir3.png"]


def test_rescue_skips_group_when_every_shot_vanished(tmp_path):
    """一張都不剩就不建組——空目錄 + 空 meta 是雜訊不是語料。"""
    ledger = _write_ledger(tmp_path, _row(shots=[[0, str(tmp_path / "gone.png")]]))
    root = str(tmp_path / "corpus")
    report = brd.rescue(ledger, root)
    assert report["groups_empty"] == 1 and report["groups_written"] == 0
    assert not os.path.exists(os.path.join(root, "ep3_attempt4"))


def test_rescue_is_idempotent(tmp_path):
    """重跑不重複、也不把已倒好的組覆蓋成殘缺版。"""
    shots = _fake_snapshots(tmp_path)
    ledger = _write_ledger(tmp_path, _row(shots=shots))
    root = str(tmp_path / "corpus")
    brd.rescue(ledger, root)
    # 第二次跑之前原始快照又少了幾張（retention 繼續刪）
    for i in range(4, 9):
        os.remove(tmp_path / "snapshots" / f"ep3_dir{i}.png")
    report = brd.rescue(ledger, root)

    assert report["groups_written"] == 0 and report["groups_skipped_existing"] == 1
    group = tmp_path / "corpus" / "ep3_attempt4"
    assert len(list(group.glob("dir*.png"))) == 8, "已倒好的組被覆蓋成殘缺版"


def test_rescue_on_missing_ledger_reports_zero(tmp_path):
    report = brd.rescue(str(tmp_path / "nope.jsonl"), str(tmp_path / "corpus"))
    assert report["ledger_rows"] == 0 and report["groups_written"] == 0


def test_format_rescue_report_mentions_every_count(tmp_path):
    text = brd.format_rescue_report(brd.rescue(
        _write_ledger(tmp_path, _row(shots=_fake_snapshots(tmp_path))),
        str(tmp_path / "corpus")))
    for label in ("ledger 可用筆數", "快照總數", "解析得到", "已消失", "倒入語料組"):
        assert label in text


# ---- 資料集分類（純函式）---------------------------------------------------

def _meta(outcome="confirmed_by_user", clicks=None, shots=None,
          episode=27, attempt=2):
    return {
        "episode": episode, "attempt": attempt, "world": "Lucernia",
        "sticky_layer": "Shamrock", "outcome": outcome, "t": 1.0,
        "shots": shots if shots is not None else [
            {"dir": i, "file": f"dir{i}.png"} for i in range(1, 9)],
        "clicks": clicks if clicks is not None else [
            {"dir": 2, "pos": [1604, 450], "layer_seen": "Shamrock",
             "depth_m": 7100, "invalid": False}],
    }


def test_classify_group_marks_clicked_dir_positive_and_rest_negative():
    """玩家看過全部八張才選那一張——另外七個方位是天然負樣本。"""
    rows, reason = brd.classify_group(_meta())
    assert reason is None
    positives = [r for r in rows if r["label"] == "positive"]
    assert len(positives) == 1 and len(rows) == 8
    assert positives[0] == {
        "image": "ep27_attempt2/dir2.png", "dir": 2, "world": "Lucernia",
        "layer_seen": "Shamrock", "depth_m": 7100, "label": "positive",
        "xy": [1604, 450], "episode": 27, "attempt": 2,
        "outcome": "confirmed_by_user"}
    assert all(r["xy"] is None for r in rows if r["label"] == "negative")


def test_classify_group_accepts_descended_outcome():
    assert brd.classify_group(_meta(outcome="descended"))[1] is None


def test_classify_group_excludes_skip_outcome():
    """排除規則 1：outcome=skip／started／缺值，沒有玩家判斷可依。"""
    assert brd.classify_group(_meta(outcome="skip"))[1] == "outcome_not_confirmed"
    assert brd.classify_group(_meta(outcome="started"))[1] == "outcome_not_confirmed"
    assert brd.classify_group(_meta(outcome=None))[1] == "outcome_not_confirmed"


def test_classify_group_excludes_invalid_click():
    """排除規則 2：玩家自己標作廢的那一筆。"""
    rows, reason = brd.classify_group(_meta(clicks=[
        {"dir": 2, "pos": [1, 2], "invalid": True}]))
    assert (rows, reason) == ([], "invalid_click")


def test_classify_group_excludes_clicks_on_different_dirs():
    """排除規則 3：多次 click 落在不同 dir＝前幾次點錯，語意不明確。"""
    rows, reason = brd.classify_group(_meta(clicks=[
        {"dir": 2, "pos": [1, 2], "invalid": False},
        {"dir": 5, "pos": [3, 4], "invalid": False}]))
    assert (rows, reason) == ([], "multi_dir_clicks")


def test_classify_group_keeps_repeated_clicks_on_same_dir():
    """實測 19 筆有 click 的 row 裡，多次點擊都落在同一 dir（成功前的重試）。"""
    rows, reason = brd.classify_group(_meta(clicks=[
        {"dir": 2, "pos": [1, 2], "invalid": False},
        {"dir": 2, "pos": [3, 4], "invalid": False}]))
    assert reason is None
    assert [r["xy"] for r in rows if r["label"] == "positive"] == [[3, 4]]


def test_classify_group_without_clicks_is_excluded():
    assert brd.classify_group(_meta(clicks=[]))[1] == "no_click"


def test_classify_group_survives_missing_positive_image():
    """實機 ep20 只剩 2 張圖、click 的那張已消失——剩下的仍是有效負樣本。"""
    rows, reason = brd.classify_group(_meta(shots=[
        {"dir": 7, "file": "dir7.png"}, {"dir": 8, "file": "dir8.png"}]))
    assert reason is None
    assert [r["label"] for r in rows] == ["negative", "negative"]


# ---- 資料集落檔 ------------------------------------------------------------

def _fake_corpus(tmp_path, *metas):
    root = tmp_path / "corpus"
    for meta in metas:
        group = root / corpus.group_name(meta["episode"], meta["attempt"])
        group.mkdir(parents=True, exist_ok=True)
        for shot in meta["shots"]:
            (group / shot["file"]).write_bytes(b"png")
        (group / corpus.META_NAME).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return str(root)


def test_build_dataset_counts_positives_negatives_and_exclusions(tmp_path):
    root = _fake_corpus(tmp_path, _meta(), _meta(outcome="skip", episode=21,
                                                 attempt=2, clicks=[]))
    rows, report = brd.build_dataset(root)
    assert (report["positives"], report["negatives"]) == (1, 7)
    assert report["groups"] == 2 and report["groups_used"] == 1
    assert report["excluded"] == {"outcome_not_confirmed": 1}
    assert len(rows) == 8


def test_build_dataset_excludes_unreadable_image(tmp_path):
    """排除規則 4：圖檔讀不到（meta 有紀錄但檔案被刪了）。"""
    root = _fake_corpus(tmp_path, _meta())
    os.remove(os.path.join(root, "ep27_attempt2", "dir2.png"))
    _rows, report = brd.build_dataset(root)
    assert report["excluded"] == {"image_missing": 1}
    assert (report["positives"], report["negatives"]) == (0, 7)


def test_build_dataset_on_empty_corpus_does_not_raise(tmp_path):
    rows, report = brd.build_dataset(str(tmp_path / "nope"))
    assert rows == [] and report["groups"] == 0
    assert "語料夾是空的" in brd.format_dataset_report(report)


def test_write_dataset_round_trips(tmp_path):
    root = _fake_corpus(tmp_path, _meta())
    rows, _report = brd.build_dataset(root)
    path = brd.write_dataset(root, rows)
    assert brd.read_dataset(path) == rows


def test_dataset_report_prints_known_biases(tmp_path):
    """報告要印出偏誤，不要讓 agent 自己踩（單一世界／隨機 yaw／螢幕空間 UI／layer）。"""
    text = brd.format_dataset_report(brd.build_dataset(
        _fake_corpus(tmp_path, _meta()))[1])
    assert "Lucernia" in text and "隨機化 yaw" in text
    assert "螢幕空間 UI" in text and "layer_seen 缺值標 null" in text


def test_main_builds_dataset_by_default(tmp_path, capsys):
    root = _fake_corpus(tmp_path, _meta())
    assert brd.main(["--corpus", root]) == 0
    assert os.path.exists(os.path.join(root, brd.DATASET_NAME))
    assert "正樣本" in capsys.readouterr().out


# ---- --eval 成績單（純函式；數字本身不當斷言，語料會長大）------------------

def _pos(xy=(100, 100), image="g/dir1.png", world="Lucernia", layer="Shamrock"):
    return {"image": image, "label": "positive", "xy": list(xy),
            "world": world, "layer_seen": layer}


def _neg(image="g/dir2.png", world="Lucernia", layer="Shamrock"):
    return {"image": image, "label": "negative", "xy": None,
            "world": world, "layer_seen": layer}


def test_eval_row_counts_prediction_inside_radius_as_hit():
    got = brd.eval_row(_pos(), (130, 100, 0.7), radius_px=80)
    assert got["verdict"] == "hit" and got["dist"] == pytest.approx(30.0)


def test_eval_row_distance_exactly_equal_to_radius_is_a_hit():
    """邊界：剛好等於半徑算命中（傳送板有大小，像素級精確沒有意義）。"""
    assert brd.eval_row(_pos(), (180, 100, 0.7), radius_px=80)["verdict"] == "hit"


def test_eval_row_distance_beyond_radius_is_a_miss():
    assert brd.eval_row(_pos(), (181, 100, 0.7), radius_px=80)["verdict"] == "miss"


def test_eval_row_no_prediction_on_positive_is_a_miss():
    got = brd.eval_row(_pos(), None, radius_px=80)
    assert got["verdict"] == "miss" and got["dist"] is None


def test_eval_row_any_prediction_on_negative_is_false_positive():
    assert brd.eval_row(_neg(), (5, 5, 0.9), radius_px=80)["verdict"] == "false_positive"


def test_eval_row_no_prediction_on_negative_is_clean():
    assert brd.eval_row(_neg(), None, radius_px=80)["verdict"] == "clean"


def test_summarize_eval_with_zero_hits_does_not_divide_by_zero():
    """零命中端：報告合法印 0%（本票驗收時偵測器是空的，這是那條路的驗證）。"""
    results = [brd.eval_row(_pos(), None, 80), brd.eval_row(_neg(), None, 80)]
    s = brd.summarize_eval(results)
    assert (s["hits"], s["misses"], s["hit_rate"]) == (0, 1, 0.0)
    assert s["median_error_px"] is None
    assert "0.0%" in brd.format_eval_report(s)


def test_summarize_eval_with_all_hits_does_not_divide_by_zero():
    results = [brd.eval_row(_pos(), (100, 100, 1.0), 80),
               brd.eval_row(_neg(), None, 80)]
    s = brd.summarize_eval(results)
    assert (s["hits"], s["hit_rate"], s["false_positives"]) == (1, 1.0, 0)
    assert s["median_error_px"] == pytest.approx(0.0)


def test_summarize_eval_with_no_positives_reports_none_rate():
    """退化輸入：正樣本 0 筆。"""
    s = brd.summarize_eval([brd.eval_row(_neg(), None, 80)])
    assert s["positives"] == 0 and s["hit_rate"] is None
    assert "—" in brd.format_eval_report(s)


def test_summarize_eval_with_no_negatives_does_not_raise():
    s = brd.summarize_eval([brd.eval_row(_pos(), (100, 100, 1.0), 80)])
    assert s["negatives"] == 0 and s["false_positives"] == 0


def test_summarize_eval_on_empty_input_is_all_zero():
    s = brd.summarize_eval([])
    assert (s["positives"], s["negatives"]) == (0, 0)
    assert brd.format_eval_report(s)          # 印得出來，不拋例外


def test_summarize_eval_median_uses_hits_only():
    results = [brd.eval_row(_pos(), (110, 100, 1.0), 80),
               brd.eval_row(_pos(), (140, 100, 1.0), 80),
               brd.eval_row(_pos(), (999, 999, 1.0), 80)]     # miss 不算進中位數
    assert brd.summarize_eval(results)["median_error_px"] == pytest.approx(25.0)


def test_group_eval_splits_by_world():
    results = [brd.eval_row(_pos(world="Lucernia"), (100, 100, 1.0), 80),
               brd.eval_row(_pos(world="Zephyr"), None, 80)]
    table = brd.group_eval(results, "world")
    assert table["Lucernia"]["hits"] == 1 and table["Zephyr"]["hits"] == 0


def test_hit_radius_comes_from_config_and_changes_the_verdict():
    from miningbot.config import Config
    assert Config().reentry_dataset_hit_radius_px == 80
    far = (100 + 120, 100, 0.5)
    assert brd.eval_row(_pos(), far, radius_px=80)["verdict"] == "miss"
    assert brd.eval_row(_pos(), far, radius_px=150)["verdict"] == "hit"


def test_run_eval_skips_unreadable_images(tmp_path):
    rows = [_pos(image="g/dir1.png"), _neg(image="g/dir2.png")]
    results = brd.run_eval(str(tmp_path), rows, 80,
                           detect=lambda _f: None,
                           load=lambda p: None if p.endswith("dir1.png") else object())
    assert [r["image"] for r in results] == ["g/dir2.png"]


def test_run_eval_survives_detector_exception(tmp_path, capsys):
    def _boom(_frame):
        raise ValueError("bad frame")

    results = brd.run_eval(str(tmp_path), [_pos()], 80,
                           detect=_boom, load=lambda _p: object())
    assert results[0]["verdict"] == "miss"
    assert "偵測失敗" in capsys.readouterr().out


def test_default_detector_returns_nothing_without_raising():
    """v0 入口形狀：吃一張圖回 (x, y, score) 或空。"""
    from miningbot import teleport_board
    import numpy as np
    assert teleport_board.detect(np.zeros((16, 16, 3), dtype=np.uint8)) is None


def test_write_eval_detail_records_prediction_truth_distance_verdict(tmp_path):
    results = [brd.eval_row(_pos(), (130, 100, 0.7), 80)]
    path = brd.write_eval_detail(str(tmp_path), results, now=0)
    assert os.path.basename(path).startswith(brd.EVAL_PREFIX)
    row = json.loads(open(path, encoding="utf-8").readline())
    assert row["pred"] == [130, 100] and row["xy"] == [100, 100]
    assert row["dist"] == pytest.approx(30.0) and row["verdict"] == "hit"


def test_main_eval_prints_report_with_empty_detector(tmp_path, capsys):
    root = _fake_corpus(tmp_path, _meta())
    assert brd.main(["--corpus", root, "--eval"]) == 0
    out = capsys.readouterr().out
    assert "positives" in out and "逐張明細" in out


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
