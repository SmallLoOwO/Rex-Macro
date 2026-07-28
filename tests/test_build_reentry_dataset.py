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


def test_main_without_mode_prints_help(capsys):
    assert brd.main([]) == 2
    assert "--rescue" in capsys.readouterr().out


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
