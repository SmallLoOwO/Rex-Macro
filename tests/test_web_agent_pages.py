"""agent 面板（spec D4）：偵測失敗佇列 `/failures` + `/api/failures`。

讀者是 AI agent 不是玩家——排版可以醜，資料要全。索引不存在／讀不到回 **503**
（「還沒有資料」不是「伺服器壞了」）；單行壞掉略過不整頁掛掉。
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from miningbot import web_history, web_server


def _rec(label, path, ts):
    return {"written_at": ts, "label": label, "path": path, "harvest_id": None}


def _client(tmp_path, records=None, index_name="snapshot_index.jsonl",
            raw=None):
    from miningbot.web_ipc import FallbackState, PendingReplies
    index = tmp_path / index_name
    if raw is not None:
        index.write_text(raw, encoding="utf-8")
    elif records is not None:
        index.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                         encoding="utf-8")
    # annotation_queue 過濾掉檔案不存在的列（retention 死連結），
    # 測試必須造真的 PNG 讓 isfile 通過——_REAL_FRAME 是 tracked fixture 已存在。
    if records:
        for r in records:
            p = r.get("path")
            if p and os.path.exists(p):
                continue
            if p:
                d = os.path.dirname(p)
                if d:
                    os.makedirs(d, exist_ok=True)
                with open(p, "wb") as f:
                    f.write(b"x")
    if raw:
        # raw 裡的第一行是好記錄，造出它指向的檔
        import json as _json
        try:
            first = _json.loads(raw.split("\n")[0])
            p = first.get("path")
            if p and not os.path.exists(p):
                d = os.path.dirname(p)
                if d:
                    os.makedirs(d, exist_ok=True)
                with open(p, "wb") as f:
                    f.write(b"x")
        except (ValueError, KeyError):
            pass
    fixtures = tmp_path / "fx"
    fixtures.mkdir(exist_ok=True)
    app = web_server.create_app(
        PendingReplies(), FallbackState(), broadcast_callback=None,
        fixtures_dir=str(fixtures), snapshots_root=str(tmp_path),
        snapshot_index_path=str(index))
    return TestClient(app)


_REAL_FRAME = os.path.join(os.path.dirname(__file__), "fixtures", "reentry",
                           "teleport_board", "auto_27_success.png")


# ---- 該用哪一支偵測器（純函式）--------------------------------------------

def test_verdict_category_routes_reentry_frames_to_teleport_board():
    assert web_history.verdict_category("reentry_ep27_dir3") == "reentry"


def test_verdict_category_refuses_full_frame_tracker_snapshots():
    """追蹤框偵測器吃 320×270 粗格裁圖；餵全幀會拿到與 production 無關的答案。

    寧可不給判決，也不要給一個假的。
    """
    assert web_history.verdict_category("113_sweep_empty") is None
    assert web_history.verdict_category("120_aim_fail") is None


def test_index_readable_reports_missing_file(tmp_path):
    assert web_history.index_readable(str(tmp_path / "nope.jsonl")) is False
    assert web_history.index_readable(None) is False
    p = tmp_path / "x.jsonl"
    p.write_text("", encoding="utf-8")
    assert web_history.index_readable(str(p)) is True


# ---- /failures + /api/failures ---------------------------------------------

def test_failures_lists_tier0_only(tmp_path):
    client = _client(tmp_path, [
        _rec("113_sweep_empty", str(tmp_path / "a.png"), 3.0),
        _rec("120_rare_found", str(tmp_path / "b.png"), 2.0),
    ])
    data = client.get("/api/failures").json()
    assert [i["label"] for i in data["items"]] == ["113_sweep_empty"]
    assert data["total"] == 1


def test_failures_html_and_json_agree(tmp_path):
    client = _client(tmp_path, [
        _rec("113_sweep_empty", str(tmp_path / "a.png"), 3.0)])
    data = client.get("/api/failures").json()
    html = client.get("/failures").text
    assert data["items"][0]["label"] in html
    assert data["items"][0]["path"] in html


def test_failures_attaches_verdict_for_reentry_frames(tmp_path):
    client = _client(tmp_path, [
        _rec("reentry_ep27_dir3_rejected", _REAL_FRAME, 1.0)])
    item = client.get("/api/failures").json()["items"][0]
    assert item["verdict"]["detector"] == "accepted"
    assert item["verdict"]["score"]["score"] > 0


def test_failures_never_fabricates_agreement(tmp_path):
    """這頁沒有玩家標籤可比，agree 必須是 null。

    `None` 在標註 schema 裡是「對照組：玩家確認過的真框」，拿它當「還沒標」會讓
    唯讀頁憑空回一個「與不存在的標註不一致」給讀 JSON 的 agent（code review 抓到）。
    """
    client = _client(tmp_path, [
        _rec("reentry_ep27_dir3_rejected", _REAL_FRAME, 1.0)])
    verdict = client.get("/api/failures").json()["items"][0]["verdict"]
    assert verdict["detector"] == "accepted"
    assert verdict["agree"] is None and verdict["your_label"] is None


def test_annotate_control_sample_still_gets_agreement(tmp_path):
    """對照組（symptom=None）在標註路徑上仍要算 agree——兩者語意不可混用。"""
    from miningbot.web_annotation import NO_LABEL
    assert web_server.annotation_verdict(
        "reentry", None, _REAL_FRAME, None)["agree"] is True
    assert web_server.annotation_verdict(
        "reentry", None, _REAL_FRAME, NO_LABEL)["agree"] is None


def test_failures_explains_missing_verdict(tmp_path):
    """沒有判決要說清楚為什麼，不是留空。"""
    client = _client(tmp_path, [
        _rec("113_sweep_empty", str(tmp_path / "a.png"), 1.0)])
    item = client.get("/api/failures").json()["items"][0]
    assert item["verdict"] is None
    assert "粗格裁圖" in item["verdict_note"]
    assert "無判決" in client.get("/failures").text


def test_failures_survives_detector_failure(tmp_path, monkeypatch):
    """偵測模組缺件時頁面仍可用（該欄顯示無判決）。"""
    monkeypatch.setattr(web_server, "annotation_verdict", lambda *a, **kw: None)
    client = _client(tmp_path, [_rec("reentry_ep27_dir3_rejected", _REAL_FRAME, 1.0)])
    item = client.get("/api/failures").json()["items"][0]
    assert item["verdict"] is None and item["verdict_note"] == "偵測不可用（見 log）"
    assert client.get("/failures").status_code == 200


def test_failures_skips_broken_index_lines(tmp_path):
    """append-only 的 partial line 略過，不讓整頁掛掉。"""
    good = json.dumps(_rec("113_sweep_empty", str(tmp_path / "a.png"), 1.0))
    client = _client(tmp_path, raw=good + '\n{"label": "12_sweep_em')
    data = client.get("/api/failures").json()
    assert data["total"] == 1
    assert client.get("/failures").status_code == 200


def test_failures_returns_503_when_index_missing(tmp_path):
    client = _client(tmp_path)                   # 沒寫索引檔
    assert client.get("/api/failures").status_code == 503
    assert client.get("/failures").status_code == 503


def test_failures_limit_is_applied(tmp_path):
    client = _client(tmp_path, [
        _rec(f"1{i}_sweep_empty", str(tmp_path / f"{i}.png"), float(i))
        for i in range(5)])
    data = client.get("/api/failures?limit=2").json()
    assert (data["total"], data["shown"], data["limit"]) == (5, 2, 2)


def test_failures_reuses_the_annotate_verdict_function():
    """判決來源是 08 的同一支函式，沒有第二份實作。"""
    import inspect
    src = inspect.getsource(web_server.create_app)
    assert "annotation_verdict(" in src


# ---- 統計聚合（純函式）-----------------------------------------------------

_DAY = 86400.0


def test_label_kind_strips_variable_numbers():
    """不收斂就會得到幾百個只出現一次的鍵，看不出什麼最常爆。"""
    assert web_history.label_kind("113_sweep_empty") == "sweep_empty"
    assert web_history.label_kind("reentry_ep27_dir3") == "reentry_ep_dir"
    assert web_history.label_kind("") == "(unlabelled)"


def test_aggregate_counts_today_and_week():
    now = 1785000000.0
    got = web_history.aggregate_labels([
        _rec("113_sweep_empty", "a", now),
        _rec("114_sweep_empty", "b", now - 2 * _DAY),
        _rec("115_sweep_empty", "c", now - 30 * _DAY),
    ], now=now)
    row = got["labels"][0]
    assert (row["kind"], row["today"], row["week"], row["total"]) == (
        "sweep_empty", 1, 2, 3)


def test_aggregate_crosses_day_boundary_by_local_date():
    """跨日邊界：同一天內的都算今日，前一天的只算本週。"""
    now = 1785000000.0
    yesterday = now - _DAY
    got = web_history.aggregate_labels([
        _rec("a_needs_human", "a", now),
        _rec("b_needs_human", "b", yesterday),
    ], now=now)
    assert got["total_today"] == 1 and got["total_week"] == 2


def test_aggregate_on_empty_input():
    got = web_history.aggregate_labels([], now=1785000000.0)
    assert got["labels"] == [] and got["total"] == 0
    assert "0" in render_stats(got)


def test_aggregate_single_label_only():
    got = web_history.aggregate_labels(
        [_rec("113_sweep_empty", "a", 1785000000.0)], now=1785000000.0)
    assert len(got["labels"]) == 1


def test_aggregate_counts_records_without_timestamp_in_total_only():
    now = 1785000000.0
    got = web_history.aggregate_labels(
        [_rec("113_sweep_empty", "a", None)], now=now)
    row = got["labels"][0]
    assert (row["today"], row["week"], row["total"]) == (0, 0, 1)


def test_aggregate_sorts_most_frequent_first():
    now = 1785000000.0
    got = web_history.aggregate_labels(
        [_rec("a_needs_human", "a", now)]
        + [_rec(f"{i}_sweep_empty", "b", now) for i in range(3)], now=now)
    assert got["labels"][0]["kind"] == "sweep_empty"


def render_stats(data):
    from miningbot.web_static import render_stats_html
    return render_stats_html(data)


# ---- /stats + /api/stats ---------------------------------------------------

def test_stats_html_and_json_agree(tmp_path):
    import time as _t
    now = _t.time()
    client = _client(tmp_path, [
        _rec("113_sweep_empty", str(tmp_path / "a.png"), now),
        _rec("114_needs_human", str(tmp_path / "b.png"), now),
    ])
    data = client.get("/api/stats").json()
    html = client.get("/stats").text
    assert data["total_today"] == 2
    for row in data["labels"]:
        assert row["kind"] in html


def test_stats_returns_503_when_index_missing(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/stats").status_code == 503
    assert client.get("/stats").status_code == 503


def test_stats_skips_broken_index_lines(tmp_path):
    good = json.dumps(_rec("113_sweep_empty", "a", 1785000000.0))
    client = _client(tmp_path, raw=good + '\n{"label": "oops')
    assert client.get("/api/stats").json()["total"] == 1
    assert client.get("/stats").status_code == 200


def test_stats_never_reads_directory_mtime():
    """MSIX LocalCache 的目錄 metadata 會過期數小時，曾因此漏掉整段回礦場次。"""
    import inspect
    src = inspect.getsource(web_history.aggregate_labels)
    src += inspect.getsource(web_history.load_stats)
    for banned in ("getmtime", "st_mtime", "scandir", "listdir"):
        assert banned not in src


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
