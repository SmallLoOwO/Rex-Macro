# tests/test_web_server_p5.py
"""P5 Task 6：歷史紀錄與標註面板 HTTP endpoints 測試（spec §5）。

5 條 routes（unconditional mount；snapshot_index_path/fixtures_dir 缺時回 503）：
- GET  /api/history                 → episode 列表
- GET  /api/episode/{episode_id}    → episode 詳細（404 if None）
- POST /api/annotate                → 寫入素材 .json（400/201/503）
- GET  /history                     → 歷史面板 HTML
- GET  /annotate?episode=&snapshot= → 標註工具 HTML
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from miningbot.web_ipc import FallbackState, PendingReplies
from miningbot.web_server import create_app


def _write_jsonl(path: str, lines: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _make_app(
    *,
    snapshot_index_path: str | None = None,
    fixtures_dir: str | None = None,
) -> TestClient:
    return TestClient(create_app(
        pending=PendingReplies(),
        fallback=FallbackState(),
        broadcast_callback=None,
        snapshot_index_path=snapshot_index_path,
        fixtures_dir=fixtures_dir,
    ))


@pytest.fixture
def history_app(tmp_path):
    """snapshot_index_path + fixtures_dir 已綁的 TestClient。"""
    idx = tmp_path / "snapshot_index.jsonl"
    _write_jsonl(str(idx), [
        {"written_at": 1000.0, "label": "007_a", "path": "/a.png", "harvest_id": "007"},
        {"written_at": 1001.0, "label": "007_b", "path": "/b.png", "harvest_id": "007"},
        {"written_at": 2000.0, "label": "009_a", "path": "/c.png", "harvest_id": "009"},
    ])
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    client = _make_app(
        snapshot_index_path=str(idx),
        fixtures_dir=str(fixtures),
    )
    return client, str(idx), str(fixtures)


# ── GET /api/history ──────────────────────────────────────────────────────


def test_get_api_history_returns_episode_list(history_app):
    client, _, _ = history_app
    r = client.get("/api/history")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2
    ids = sorted(e["harvest_id"] for e in data)
    assert ids == ["007", "009"]


def test_get_api_history_empty_when_index_empty(tmp_path):
    idx = tmp_path / "snapshot_index.jsonl"
    idx.write_text("", encoding="utf-8")
    client = _make_app(snapshot_index_path=str(idx))
    r = client.get("/api/history")
    assert r.status_code == 200
    assert r.json() == []


def test_get_api_history_503_when_not_configured():
    client = _make_app()
    r = client.get("/api/history")
    assert r.status_code == 503
    assert "not configured" in r.json()["error"]


# ── GET /api/episode/{episode_id} ─────────────────────────────────────────


def test_get_api_episode_returns_detail(history_app):
    client, _, _ = history_app
    r = client.get("/api/episode/007")
    assert r.status_code == 200
    data = r.json()
    assert data["harvest_id"] == "007"
    assert data["count"] == 2
    assert len(data["snapshots"]) == 2


def test_get_api_episode_404_on_missing(history_app):
    client, _, _ = history_app
    r = client.get("/api/episode/999")
    assert r.status_code == 404


def test_get_api_episode_503_when_not_configured():
    client = _make_app()
    r = client.get("/api/episode/007")
    assert r.status_code == 503


# ── POST /api/annotate ────────────────────────────────────────────────────


def _valid_payload() -> dict:
    return {
        "image": "auto_007_terrain_fp.png",
        "annotation": {"type": "square", "cx": 211, "cy": 189, "size": 50},
        "tier": None,
        "variant": None,
        "mineral": None,
        "source": {"kind": "manual"},
        "symptom": "false_positive",
        "related_incident": None,
    }


def test_post_api_annotate_writes_json(history_app):
    client, _, fixtures = history_app
    r = client.post("/api/annotate", json=_valid_payload())
    assert r.status_code == 201
    # 預設 category=aim；檔名 = image stem swap
    written = os.path.join(fixtures, "aim", "auto_007_terrain_fp.json")
    assert os.path.exists(written)
    with open(written, encoding="utf-8") as f:
        data = json.load(f)
    assert data["image"] == "auto_007_terrain_fp.png"
    assert data["symptom"] == "false_positive"
    assert data["annotation"]["cx"] == 211


def test_post_api_annotate_atomic_write(history_app):
    """no .tmp file left after write（tempfile + os.replace 模式）。"""
    client, _, fixtures = history_app
    client.post("/api/annotate", json=_valid_payload())
    aim_dir = os.path.join(fixtures, "aim")
    leftover_tmp = [n for n in os.listdir(aim_dir) if n.endswith(".tmp")]
    assert leftover_tmp == []


def test_post_api_annotate_400_on_invalid(history_app):
    client, _, _ = history_app
    bad = _valid_payload()
    del bad["annotation"]  # 缺必填
    r = client.post("/api/annotate", json=bad)
    assert r.status_code == 400


def test_post_api_annotate_400_on_bad_symptom(history_app):
    client, _, _ = history_app
    bad = _valid_payload()
    bad["symptom"] = "garbage_symptom"
    r = client.post("/api/annotate", json=bad)
    assert r.status_code == 400


def test_post_api_annotate_503_when_not_configured():
    client = _make_app()
    r = client.post("/api/annotate", json=_valid_payload())
    assert r.status_code == 503


def test_post_api_annotate_category_override(history_app):
    """payload 帶 category 欄位時寫入對應子目錄。"""
    client, _, fixtures = history_app
    payload = _valid_payload()
    payload["category"] = "reentry/teleport_board"
    r = client.post("/api/annotate", json=payload)
    assert r.status_code == 201
    written = os.path.join(
        fixtures, "reentry", "teleport_board", "auto_007_terrain_fp.json",
    )
    assert os.path.exists(written)


def test_post_api_annotate_default_category_when_no_image_prefix(history_app):
    """image 不含路徑前綴 → 預設 aim/。"""
    client, _, fixtures = history_app
    payload = _valid_payload()
    payload["image"] = "manual_terrain.png"
    r = client.post("/api/annotate", json=payload)
    assert r.status_code == 201
    written = os.path.join(fixtures, "aim", "manual_terrain.json")
    assert os.path.exists(written)


# ── GET /history ──────────────────────────────────────────────────────────


def test_get_history_returns_html(history_app):
    client, _, _ = history_app
    r = client.get("/history")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_get_history_503_when_not_configured():
    client = _make_app()
    r = client.get("/history")
    assert r.status_code == 503


# ── GET /annotate ─────────────────────────────────────────────────────────


def test_get_annotate_returns_html(history_app):
    client, _, _ = history_app
    r = client.get("/annotate", params={"episode": "007", "snapshot": "/a.png"})
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_get_annotate_returns_html_without_snapshot_param(history_app):
    """snapshot query optional；只給 episode 也要能 render。"""
    client, _, _ = history_app
    r = client.get("/annotate", params={"episode": "007"})
    assert r.status_code == 200


def test_get_annotate_works_even_when_not_configured():
    """標註工具 UI 只需 rarity_choices（game_data 撈）；不需 snapshot_index。"""
    client = _make_app()
    r = client.get("/annotate", params={"episode": "007"})
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
