"""網頁目標層 ↔ Discord `層` 指令同步（2026-07-26）。

## 背景

執行期真正生效的目標層優先序是：

    sticky_layers[world]  >  cfg.reentry_target_layer

`sticky_layers` 是每世界黏性層 map（`sticky_layers.json`），由 Discord `層` 指令
寫入（`main._apply_layer_change`）；`cfg.reentry_target_layer` 只是「該世界沒記錄過」
時的 fallback。

網頁設定頁先前**只讀寫 fallback**，於是實機上出現：Discord 已經把
`{"Lucernia": "Shamrock"}` 記起來、bot 也照著用，設定頁卻顯示 `Mantle Layer`，
而且在網頁改層完全不會生效（改的是永遠被 map 蓋掉的 fallback）。

修法兩側都要動：
- 讀：`layer_getter` 給執行期有效層，`GET /api/config` 與 `GET /` 都用它。
- 寫：POST 額外 push `control:set_layer`，由主迴圈走 `_apply_layer_change`
  ——跟 Discord `層` **同一條路徑**，才會真的寫進 map。
"""
import json
import types

import pytest
from fastapi.testclient import TestClient

from miningbot import game_data, reentry_remote
from miningbot.config import Config
from miningbot.web_ipc import PendingReplies, FallbackState
from miningbot.web_server import create_app
from miningbot.web_static import render_index_html

from tests.fake_bot import make_fake_bot


# ── server 端：讀 ──────────────────────────────────────────────────────────

@pytest.fixture
def parts(tmp_path):
    cfg = Config()
    cfg.reentry_target_layer = "Mantle Layer"
    pending = PendingReplies()
    overrides = str(tmp_path / "overrides.json")
    return cfg, pending, overrides


def _app(cfg, pending, overrides, layer_getter=None):
    return create_app(
        pending, FallbackState(), broadcast_callback=None,
        config=cfg, overrides_path=overrides, layer_getter=layer_getter,
    )


def test_get_config_prefers_effective_layer_over_config_fallback(parts):
    """實機症狀本體：Discord 記了 Shamrock，設定頁不能還顯示 Mantle Layer。"""
    cfg, pending, overrides = parts
    getter = lambda: {"effective": "Shamrock", "world": "Lucernia",
                      "from_world_map": True}
    client = TestClient(_app(cfg, pending, overrides, getter))
    data = client.get("/api/config").json()
    assert data["reentry_target_layer"] == "Shamrock"
    # 其他三欄不受影響
    assert data["reentry_mode"] == cfg.reentry_mode


def test_get_config_without_getter_keeps_old_behaviour(parts):
    """沒接 layer_getter（既有呼叫端／測試）→ 完全走舊行為。"""
    cfg, pending, overrides = parts
    client = TestClient(_app(cfg, pending, overrides))
    data = client.get("/api/config").json()
    assert data["reentry_target_layer"] == "Mantle Layer"


def test_get_config_survives_broken_getter(parts):
    """getter 丟例外不該讓設定頁 500——退回 config 值。"""
    cfg, pending, overrides = parts

    def boom():
        raise RuntimeError("bot 忙")

    client = TestClient(_app(cfg, pending, overrides, boom))
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["reentry_target_layer"] == "Mantle Layer"


# ── server 端：寫 ──────────────────────────────────────────────────────────

def test_post_layer_queues_set_layer_for_main_loop(parts):
    """寫入必須 push control:set_layer，否則只改到永遠被 map 蓋掉的 fallback。"""
    cfg, pending, overrides = parts
    getter = lambda: {"effective": "Mantle Layer", "world": "Lucernia",
                      "from_world_map": False}
    client = TestClient(_app(cfg, pending, overrides, getter))
    r = client.post("/api/config",
                    json={"field": "reentry_target_layer", "value": "Shamrock"})
    assert r.status_code == 200
    assert r.json()["layer_queued"] is True
    queued = pending.pop("control:set_layer")
    assert queued == {"layer": "Shamrock"}
    # fallback 也同步更新（世界未記錄時仍有意義）
    assert cfg.reentry_target_layer == "Shamrock"
    assert json.loads(open(overrides, encoding="utf-8").read())[
        "reentry_target_layer"] == "Shamrock"


def test_post_other_fields_do_not_queue_set_layer(parts):
    """只有目標層走 set_layer；其他三欄不該污染 control:set_layer slot。"""
    cfg, pending, overrides = parts
    getter = lambda: {"effective": "X", "world": None, "from_world_map": False}
    client = TestClient(_app(cfg, pending, overrides, getter))
    client.post("/api/config", json={"field": "reentry_mode", "value": "auto"})
    assert pending.pop("control:set_layer") is None


def test_post_layer_without_getter_does_not_queue(parts):
    """沒接 bot 時不該憑空 push 一個沒人消費的命令（會卡住 slot）。"""
    cfg, pending, overrides = parts
    client = TestClient(_app(cfg, pending, overrides))
    r = client.post("/api/config",
                    json={"field": "reentry_target_layer", "value": "Shamrock"})
    assert "layer_queued" not in r.json()
    assert pending.pop("control:set_layer") is None


# ── HTML 端 ───────────────────────────────────────────────────────────────

def test_index_html_shows_effective_layer_and_source_hint():
    cfg = Config()
    cfg.reentry_target_layer = "Mantle Layer"
    html = render_index_html(cfg, layer_info={
        "effective": "Shamrock", "world": "Lucernia", "from_world_map": True})
    assert 'value="Shamrock"' in html
    assert "Lucernia" in html          # 說明這個值是哪個世界的記憶值
    assert "Mantle Layer" in html      # 仍標示未記錄世界會用的預設


def test_index_html_hint_when_world_unknown():
    cfg = Config()
    html = render_index_html(cfg, layer_info={
        "effective": "Mantle Layer", "world": None, "from_world_map": False})
    assert "世界尚未偵測到" in html


def test_index_html_without_layer_info_is_unchanged():
    """既有呼叫端不傳 layer_info → 不得出現任何同步提示。"""
    cfg = Config()
    cfg.reentry_target_layer = "Mantle Layer"
    html = render_index_html(cfg)
    assert 'value="Mantle Layer"' in html
    assert "世界尚未偵測到" not in html


# ── bot 端：_apply_layer_change / _effective_layer_info ────────────────────

def _layer_bot(sticky=None, ctx=None, world="Lucernia", monkeypatch=None):
    notes = []
    writes = []
    bot = make_fake_bot(
        bind=["_apply_layer_change", "_effective_layer_info"],
        _rr_sticky_layer="Mantle Layer",
        _rr_sticky_layers=dict(sticky or {}),
        _rr_layer_user_pinned=False,
        _rr_ctx=ctx,
        _rr_notify=lambda text, image_paths=None: notes.append(text),
        _write_sticky_layers=lambda: writes.append(dict(bot._rr_sticky_layers)),
    )
    monkeypatch.setattr(game_data, "current_world_name", lambda: world)
    return bot, notes, writes


def test_apply_layer_change_writes_world_map(monkeypatch):
    """網頁改層必須寫進每世界 map——這才是執行期真正被讀的那份。"""
    bot, notes, writes = _layer_bot(monkeypatch=monkeypatch)
    bot._apply_layer_change("Shamrock", source="web")
    assert bot._rr_sticky_layer == "Shamrock"
    assert bot._rr_sticky_layers == {"Lucernia": "Shamrock"}
    assert bot._rr_layer_user_pinned is True     # 之後世界偵測不得覆寫
    assert writes == [{"Lucernia": "Shamrock"}]  # 有落盤
    assert "Shamrock" in notes[0] and "來自網頁" in notes[0]


def test_apply_layer_change_survives_no_reentry_ctx(monkeypatch):
    """回歸：網頁可在任何狀態改層，ctx=None 不得 AttributeError。

    Discord `層` 一定在回礦 episode 內下達（ctx 必有），舊碼因此直接寫
    `ctx.sticky_layer`。網頁沒有這個前提。
    """
    bot, notes, _ = _layer_bot(ctx=None, monkeypatch=monkeypatch)
    bot._apply_layer_change("Shamrock", source="web")   # 不得丟例外
    assert bot._rr_sticky_layer == "Shamrock"


def test_apply_layer_change_updates_ctx_when_present(monkeypatch):
    """在 episode 內改層時，ctx 也要跟上（沿用 Discord 既有行為）。"""
    ctx = types.SimpleNamespace(sticky_layer="Mantle Layer")
    bot, _, _ = _layer_bot(ctx=ctx, monkeypatch=monkeypatch)
    bot._apply_layer_change("Shamrock", source="discord")
    assert ctx.sticky_layer == "Shamrock"


def test_apply_layer_change_world_unknown_does_not_write_file(monkeypatch):
    """世界未偵測到 → 只改 session，不得亂寫 map（會記到錯的世界頭上）。"""
    bot, notes, writes = _layer_bot(world=None, monkeypatch=monkeypatch)
    bot._apply_layer_change("Shamrock", source="web")
    assert bot._rr_sticky_layer == "Shamrock"
    assert bot._rr_sticky_layers == {}
    assert writes == []
    assert "世界尚未偵測到" in notes[0]


def test_effective_layer_info_reports_world_map_source(monkeypatch):
    bot, _, _ = _layer_bot(sticky={"Lucernia": "Shamrock"}, monkeypatch=monkeypatch)
    bot._rr_sticky_layer = "Shamrock"
    info = bot._effective_layer_info()
    assert info == {"effective": "Shamrock", "world": "Lucernia",
                    "from_world_map": True}


def test_effective_layer_info_marks_fallback_when_not_in_map(monkeypatch):
    """現行值不是該世界的記憶值時，不得謊稱來自 map。"""
    bot, _, _ = _layer_bot(sticky={"Elysium": "Deep"}, monkeypatch=monkeypatch)
    info = bot._effective_layer_info()
    assert info["effective"] == "Mantle Layer"
    assert info["from_world_map"] is False


def test_effective_layer_info_matches_reentry_remote_resolution(monkeypatch):
    """與 bot 真正查層的函式對齊：兩者對同一份 map 必須給同一個答案。"""
    bot, _, _ = _layer_bot(sticky={"Lucernia": "Shamrock"}, monkeypatch=monkeypatch)
    bot._rr_sticky_layer = reentry_remote.effective_sticky_layer(
        "Lucernia", bot._rr_sticky_layers, "Mantle Layer")
    assert bot._effective_layer_info()["effective"] == "Shamrock"


# ── 主迴圈消費 ─────────────────────────────────────────────────────────────

def test_consume_web_pending_applies_queued_layer(monkeypatch):
    """端到端接線：push control:set_layer → 主迴圈套用（走 _apply_layer_change）。"""
    applied = []
    pending = PendingReplies()
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _apply_layer_change=lambda layer, source="discord": applied.append(
            (layer, source)),
    )
    pending.push("control:set_layer", {"layer": "  Shamrock  "})
    bot._consume_web_pending()
    assert applied == [("Shamrock", "web")]     # 前後空白要 strip


def test_consume_web_pending_ignores_bad_layer_value():
    """空字串／非字串不得被套用（會把目標層洗成空的）。"""
    applied = []
    pending = PendingReplies()
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _apply_layer_change=lambda layer, source="discord": applied.append(layer),
    )
    pending.push("control:set_layer", {"layer": "   "})
    bot._consume_web_pending()
    assert applied == []
