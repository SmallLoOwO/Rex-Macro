"""P3 玩家設定面板 HTTP endpoints 測試。"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from miningbot.config import Config
from miningbot.web_ipc import PendingReplies, FallbackState
from miningbot.web_server import create_app


@pytest.fixture
def app_parts(tmp_path):
    cfg = Config()
    pending = PendingReplies()
    fallback = FallbackState()
    overrides_path = str(tmp_path / "overrides.json")
    app = create_app(
        pending=pending, fallback=fallback,
        broadcast_callback=None,
        config=cfg, overrides_path=overrides_path,
    )
    client = TestClient(app)
    return client, cfg, overrides_path


def test_get_api_config_returns_whitelisted_fields(app_parts):
    client, cfg, _ = app_parts
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    # 4 個白名單欄位都該出現
    assert "reentry_mode" in data
    assert "reentry_target_layer" in data
    assert "reentry_yaw_sample_sweep" in data
    assert "sweep_pitch_enabled" in data
    # 現值 = Config 預設
    assert data["reentry_mode"] == cfg.reentry_mode


def test_get_api_config_does_not_leak_non_whitelisted(app_parts):
    client, _, _ = app_parts
    r = client.get("/api/config")
    data = r.json()
    # 門檻、ROI、機密不該出現
    assert "tracker_core_min_area" not in data
    assert "reentry_game_region" not in data
    assert "discord_bot_token" not in data
    assert "log_dir" not in data


def test_post_api_config_updates_runtime(app_parts):
    client, cfg, _ = app_parts
    r = client.post("/api/config", json={"field": "reentry_mode", "value": "auto"})
    assert r.status_code == 200
    assert cfg.reentry_mode == "auto"  # runtime 即時生效


def test_post_api_config_persists_to_file(app_parts):
    client, _, overrides_path = app_parts
    client.post("/api/config", json={"field": "reentry_mode", "value": "auto"})
    assert os.path.exists(overrides_path)
    with open(overrides_path) as f:
        assert json.load(f) == {"reentry_mode": "auto"}


def test_post_api_config_rejects_non_whitelisted(app_parts):
    client, cfg, _ = app_parts
    original = cfg.tracker_core_min_area
    r = client.post("/api/config", json={"field": "tracker_core_min_area", "value": 999})
    assert r.status_code == 400
    assert cfg.tracker_core_min_area == original  # 沒被改


def test_post_api_config_rejects_invalid_value(app_parts):
    client, cfg, _ = app_parts
    original = cfg.reentry_mode
    r = client.post("/api/config", json={"field": "reentry_mode", "value": "garbage"})
    assert r.status_code == 400
    assert cfg.reentry_mode == original


def test_post_api_config_rejects_missing_field(app_parts):
    client, _, _ = app_parts
    r = client.post("/api/config", json={"value": "auto"})
    assert r.status_code == 400


def test_post_api_config_rejects_missing_value(app_parts):
    client, _, _ = app_parts
    r = client.post("/api/config", json={"field": "reentry_mode"})
    assert r.status_code == 400


def test_get_root_returns_html(app_parts):
    client, _, _ = app_parts
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_get_root_returns_html_with_form(app_parts):
    client, _, _ = app_parts
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    # 4 個欄位 form 元素
    assert "reentry_mode" in body
    assert "reentry_target_layer" in body
    assert "reentry_yaw_sample_sweep" in body
    assert "sweep_pitch_enabled" in body
    # JS 提交邏輯（fetch /api/config）
    assert "/api/config" in body
    assert "fetch" in body.lower() or "XMLHttpRequest" in body


def test_get_root_html_has_submit_button(app_parts):
    client, _, _ = app_parts
    body = client.get("/").text
    assert "submit" in body.lower() or "type=\"submit\"" in body or "<button" in body.lower()


# --- Task 4：main.py 整合 smoke tests（留 P4 補；同 P1 Task 10 / P2 Task 7 慣例） ---


def test_main_init_loads_overrides(tmp_path, monkeypatch):
    """bot 啟動時讀 config_overrides.json 套用 Config。

    略——具體 fake bot 結構依 main.py；留 P4 整合時補回（同 P1 Task 10 / P2 Task 7 慣例）。
    """
    pytest.skip("main.py 整合 smoke test 留 P4 補")


def test_main_consume_web_pending_handles_config_set():
    """web_pending 收到 control:config_set 命令時，bot runtime 改 Config + 持久化。

    略——同上，留 P4 補。
    """
    pytest.skip("具體 fake bot 結構依 main.py；留 P4 補")
