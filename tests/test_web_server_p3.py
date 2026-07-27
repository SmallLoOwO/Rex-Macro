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


# --- Task 4：main.py 整合（2026-07-26 補回；原留 P4 但一路 skip 到現在） ---


def test_main_init_loads_overrides(tmp_path, monkeypatch):
    """bot 啟動時讀 config_overrides.json 套用 Config（Bot._apply_startup_overrides）。

    這段原本內嵌在 run() 中段，前面隔著 focus/UI 檢查/歸位整串實機 I/O，測試永遠跑
    不到——所以從 P3 skip 到現在。2026-07-26 抽成獨立 method 後可直接驗。
    """
    import json
    import miningbot.main as main_mod
    from miningbot.config import DEFAULT as cfg
    from tests.fake_bot import make_fake_bot

    monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
    monkeypatch.setattr(cfg, "reentry_mode", "off")     # 起始值，之後應被 overrides 蓋掉
    (tmp_path / "config_overrides.json").write_text(
        json.dumps({"reentry_mode": "auto",
                    "not_whitelisted_field": "should_be_ignored"}),
        encoding="utf-8")

    bot = make_fake_bot(bind=["_apply_startup_overrides"])
    path = bot._apply_startup_overrides()

    assert cfg.reentry_mode == "auto", "白名單欄位應被 config_overrides.json 蓋掉"
    assert not hasattr(cfg, "not_whitelisted_field"), "白名單外的欄位不得被套用"
    assert path == str(tmp_path / "config_overrides.json")
    assert bot._overrides_path == path, "_overrides_path 要留給 _consume_web_pending 用"
    assert main_mod is not None


def test_main_init_overrides_tolerates_missing_file(tmp_path, monkeypatch):
    """檔案不存在 → 用 default 開機，不得拋例外（notify「失敗只回報不中斷」慣例）。"""
    from miningbot.config import DEFAULT as cfg
    from tests.fake_bot import make_fake_bot

    monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
    bot = make_fake_bot(bind=["_apply_startup_overrides"])
    assert bot._apply_startup_overrides() == str(tmp_path / "config_overrides.json")


def test_main_consume_web_pending_handles_config_set(tmp_path, monkeypatch):
    """web_pending 收到 control:config_set → runtime 改 Config + 寫進 overrides 檔。"""
    import json
    from miningbot.config import DEFAULT as cfg
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    monkeypatch.setattr(cfg, "reentry_mode", "off")
    overrides_path = tmp_path / "config_overrides.json"

    pending = PendingReplies()
    pending.push("control:config_set", {"field": "reentry_mode", "value": "remote"})

    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _overrides_path=str(overrides_path),
    )
    bot._consume_web_pending()

    assert cfg.reentry_mode == "remote", "runtime 應即時生效"
    assert json.loads(overrides_path.read_text(encoding="utf-8")) == {
        "reentry_mode": "remote"}, "應持久化到 config_overrides.json"


def test_main_consume_web_pending_rejects_non_whitelisted_field(tmp_path, monkeypatch):
    """白名單外欄位（例如門檻）一律拒絕——spec §6「門檻/ROI/偵測參數完全不暴露」。"""
    from miningbot.config import DEFAULT as cfg
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    overrides_path = tmp_path / "config_overrides.json"
    before = cfg.tracker_shape_confirm

    pending = PendingReplies()
    pending.push("control:config_set",
                 {"field": "tracker_shape_confirm", "value": False})

    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _overrides_path=str(overrides_path),
    )
    bot._consume_web_pending()

    assert cfg.tracker_shape_confirm is before, "偵測參數不得被網頁改動"
    assert not overrides_path.exists(), "拒絕的欄位不該寫進持久化檔"


def test_main_consume_web_pending_rejects_invalid_value(tmp_path, monkeypatch):
    """白名單內但值不合法（reentry_mode 只收 off/remote/auto）也要擋。"""
    from miningbot.config import DEFAULT as cfg
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    monkeypatch.setattr(cfg, "reentry_mode", "off")
    overrides_path = tmp_path / "config_overrides.json"

    pending = PendingReplies()
    pending.push("control:config_set", {"field": "reentry_mode", "value": "turbo"})

    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _overrides_path=str(overrides_path),
    )
    bot._consume_web_pending()

    assert cfg.reentry_mode == "off", "非法值不得套用"
    assert not overrides_path.exists()


# --- 2026-07-28：/api/player + /api/keep + /api/radar（保留清單/D2 開關網頁化）---


def _app_with_player_state(keep_ores=None, radar=None, ore_catalog=None, getter=True):
    cfg = Config()
    pending = PendingReplies()
    fallback = FallbackState()

    def player_state_getter():
        return {
            "keep_ores": keep_ores or [],
            "radar": radar or {},
            "ore_catalog": ore_catalog or [],
        }

    app = create_app(
        pending=pending, fallback=fallback, broadcast_callback=None,
        config=cfg, overrides_path=None,
        player_state_getter=player_state_getter if getter else None,
    )
    return TestClient(app), pending


def test_get_api_player_returns_state():
    client, _ = _app_with_player_state(
        keep_ores=["Riches"], radar={"scan": True, "cave": False},
        ore_catalog=["Riches", "Toppatrick"])
    r = client.get("/api/player")
    assert r.status_code == 200
    data = r.json()
    assert data == {
        "keep_ores": ["Riches"],
        "radar": {"scan": True, "cave": False},
        "ore_catalog": ["Riches", "Toppatrick"],
    }


def test_get_api_player_without_getter_returns_empty_shell():
    client, _ = _app_with_player_state(getter=False)
    r = client.get("/api/player")
    assert r.status_code == 200
    assert r.json() == {"keep_ores": [], "radar": {}, "ore_catalog": []}


def test_get_api_player_getter_exception_returns_empty_shell():
    cfg = Config()
    pending = PendingReplies()
    fallback = FallbackState()

    def boom():
        raise RuntimeError("bot 執行緒忙")

    app = create_app(
        pending=pending, fallback=fallback, broadcast_callback=None,
        config=cfg, overrides_path=None, player_state_getter=boom,
    )
    r = TestClient(app).get("/api/player")
    assert r.status_code == 200
    assert r.json() == {"keep_ores": [], "radar": {}, "ore_catalog": []}


def test_post_api_keep_add_pushes_pending():
    client, pending = _app_with_player_state()
    r = client.post("/api/keep", json={"action": "add", "ore": "Riches"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "action": "add", "ore": "Riches"}
    assert pending.pop("control:keep_add") == {"ore": "Riches"}


def test_post_api_keep_remove_pushes_pending():
    client, pending = _app_with_player_state()
    r = client.post("/api/keep", json={"action": "remove", "ore": "Riches"})
    assert r.status_code == 200
    assert pending.pop("control:keep_remove") == {"ore": "Riches"}


def test_post_api_keep_clear_pushes_pending_without_ore():
    client, pending = _app_with_player_state()
    r = client.post("/api/keep", json={"action": "clear"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "action": "clear"}
    assert pending.pop("control:keep_clear") == {}


def test_post_api_keep_rejects_bad_action():
    client, pending = _app_with_player_state()
    r = client.post("/api/keep", json={"action": "bogus"})
    assert r.status_code == 400
    assert pending.pop("control:keep_bogus") is None


def test_post_api_keep_add_missing_ore_rejected():
    client, pending = _app_with_player_state()
    r = client.post("/api/keep", json={"action": "add"})
    assert r.status_code == 400
    assert pending.pop("control:keep_add") is None


def test_post_api_radar_pushes_pending():
    client, pending = _app_with_player_state()
    r = client.post("/api/radar", json={"which": "cave", "value": True})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "which": "cave", "value": True}
    assert pending.pop("control:radar_toggle") == {"which": "cave", "value": True}


def test_post_api_radar_rejects_bad_which():
    client, pending = _app_with_player_state()
    r = client.post("/api/radar", json={"which": "bogus", "value": True})
    assert r.status_code == 400
    assert pending.pop("control:radar_toggle") is None


def test_post_api_radar_rejects_non_bool_value():
    client, pending = _app_with_player_state()
    r = client.post("/api/radar", json={"which": "scan", "value": "on"})
    assert r.status_code == 400
    assert pending.pop("control:radar_toggle") is None
