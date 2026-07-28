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


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
