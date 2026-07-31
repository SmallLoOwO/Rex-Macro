"""預測點：bot 猜傳送板在哪，玩家確認或否定（2026-07-28）。

只做建議、不自動點——使用者明確不要 `reentry_mode=auto`（H043 虛空墜落是那條路
的代價）。價值不在省掉那一下點擊，在於把標註成本降到零：玩家為了回礦本來就要點，
順手就產生一筆「預測 vs 真實」的比對。
"""

import logging
import types

import pytest

from miningbot import corpus, reentry_remote
from miningbot.web_protocol import normalize_intervention_item


# ---- 幀項目正規化（三種歷史寫法）------------------------------------------

def test_normalize_item_two_tuple_is_dir_and_png():
    assert normalize_intervention_item((3, b"png")) == (3, None, b"png", None)


def test_normalize_item_three_tuple_is_harvest_layer_shape():
    """2026-07-27 harvest 候選清單多帶俯仰層。"""
    assert normalize_intervention_item((3, "up", b"png")) == (3, "up", b"png", None)


def test_normalize_item_dict_carries_prediction():
    got = normalize_intervention_item({"dir": 2, "png": b"p", "predict": (10, 20, 0.9)})
    assert got == (2, None, b"p", (10, 20, 0.9))


def test_normalize_item_dict_without_prediction():
    assert normalize_intervention_item({"dir": 0, "png": b"p"}) == (0, None, b"p", None)


# ---- 分數門檻（`_predict_teleport_board`）----------------------------------

def _predict_bot(detect):
    import miningbot.main as main_mod
    from miningbot.main import Bot
    bot = types.SimpleNamespace(logger=logging.getLogger("test_predict"))
    bot._predict_teleport_board = types.MethodType(Bot._predict_teleport_board, bot)
    return bot, main_mod


def test_prediction_below_threshold_is_dropped(monkeypatch):
    """畫一個亂猜的圈比不畫更糟。"""
    bot, main_mod = _predict_bot(None)
    monkeypatch.setattr(main_mod.cfg, "reentry_predict_min_score", 0.7)
    monkeypatch.setattr(main_mod.teleport_board, "detect",
                        lambda _f: (100, 200, 0.5))
    ctx = types.SimpleNamespace(episode_id=27)
    assert bot._predict_teleport_board(ctx, 0, object()) is None


def test_prediction_at_threshold_is_kept(monkeypatch):
    bot, main_mod = _predict_bot(None)
    monkeypatch.setattr(main_mod.cfg, "reentry_predict_min_score", 0.7)
    monkeypatch.setattr(main_mod.teleport_board, "detect",
                        lambda _f: (100, 200, 0.7))
    ctx = types.SimpleNamespace(episode_id=27)
    assert bot._predict_teleport_board(ctx, 0, object()) == (100, 200, 0.7)


def test_prediction_none_when_detector_finds_nothing(monkeypatch):
    bot, main_mod = _predict_bot(None)
    monkeypatch.setattr(main_mod.teleport_board, "detect", lambda _f: None)
    ctx = types.SimpleNamespace(episode_id=27)
    assert bot._predict_teleport_board(ctx, 0, object()) is None


def test_prediction_survives_detector_exception(monkeypatch, caplog):
    """偵測掛掉不可讓介入面板變難用：退回「沒有預測」並 log 一行。"""
    bot, main_mod = _predict_bot(None)

    def _boom(_frame):
        raise ValueError("bad frame")

    monkeypatch.setattr(main_mod.teleport_board, "detect", _boom)
    ctx = types.SimpleNamespace(episode_id=27)
    with caplog.at_level(logging.WARNING):
        assert bot._predict_teleport_board(ctx, 4, object()) is None
    assert any("傳送板偵測失敗" in r.getMessage() for r in caplog.records)


# ---- INTERVENTION_FRAME meta 帶預測 ----------------------------------------

class _FakeRegistry:
    def __init__(self):
        self.events = []
        self.binaries = []

    def begin_intervention_replay(self):
        pass

    def broadcast(self, msg):
        self.events.append(msg.payload)

    def broadcast_binary(self, data):
        self.binaries.append(data)


def _frames_bot():
    from miningbot.main import Bot
    registry = _FakeRegistry()
    bot = types.SimpleNamespace(
        log_discord=logging.getLogger("test_predict"),
        _web_thread=types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace(registry=registry))))
    bot._send_web_intervention_frames = types.MethodType(
        Bot._send_web_intervention_frames, bot)
    return bot, registry


def test_frame_meta_carries_prediction():
    bot, registry = _frames_bot()
    bot._send_web_intervention_frames(
        flow="reentry", routing_key="reentry:27",
        frames=[{"dir": 1, "png": b"a", "predict": (1607, 413, 0.973)}],
        ctx_summary="s")
    meta = registry.events[0]
    assert meta["predict"] == {"x": 1607, "y": 413, "score": 0.973}
    assert meta["dir"] == 2                       # 內部 0-based → 介面 1-8


def test_frame_meta_omits_prediction_when_absent():
    """沒有預測時 meta 與舊版逐欄一致——前端據此不畫圈、不加鍵。"""
    bot, registry = _frames_bot()
    bot._send_web_intervention_frames(
        flow="reentry", routing_key="reentry:27",
        frames=[{"dir": 0, "png": b"a", "predict": None}], ctx_summary="s")
    assert "predict" not in registry.events[0]


def test_frames_bytes_are_pushed_unmodified():
    """預測圈由 client 畫在 overlay div 上；推出去的 PNG 與原始快照同一批位元組。"""
    bot, registry = _frames_bot()
    bot._send_web_intervention_frames(
        flow="reentry", routing_key="reentry:27",
        frames=[{"dir": 0, "png": b"\x89PNG-original", "predict": (5, 6, 0.9)}],
        ctx_summary="s")
    assert registry.binaries == [b"\x89PNG-original"]


# ---- 預測 vs 真實寫進 ctx.clicks / meta.json --------------------------------

def _ctx_with_click():
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=27, created_at=0.0, sticky_layer="Shamrock")
    ctx.attempt = 2
    reentry_remote.record_click(ctx, (1604, 450), "Shamrock", (), 1.0)
    return ctx


def test_record_prediction_stores_both_sides():
    ctx = _ctx_with_click()
    assert reentry_remote.record_prediction(ctx, (1607, 413, 0.9731)) is True
    assert ctx.clicks[-1]["predicted_xy"] == [1607, 413]
    assert ctx.clicks[-1]["predicted_score"] == 0.973
    assert ctx.clicks[-1]["pos"] == (1604, 450)


def test_record_prediction_writes_none_when_no_prediction():
    """沒有預測就寫 None，不影響資料集建立。"""
    ctx = _ctx_with_click()
    reentry_remote.record_prediction(ctx, None)
    assert ctx.clicks[-1]["predicted_xy"] is None


def test_discord_click_path_also_records_prediction():
    """web 逾時退回 Discord 時 ctx.predictions 明明有值，不記就白丟一筆比對樣本。"""
    import inspect

    from miningbot.main import Bot
    src = inspect.getsource(Bot._rr_click)
    assert "record_prediction" in src


def test_record_prediction_without_click_returns_false():
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=27, created_at=0.0, sticky_layer="Shamrock")
    assert reentry_remote.record_prediction(ctx, (1, 2, 0.9)) is False


def test_meta_carries_predicted_and_actual():
    ctx = _ctx_with_click()
    reentry_remote.record_prediction(ctx, (1607, 413, 0.973))
    got = corpus.normalize_click(ctx.clicks[-1])
    assert got["actual_xy"] == [1604, 450]
    assert got["predicted_xy"] == [1607, 413]


def test_dataset_still_builds_when_prediction_missing():
    """沒有預測時 predicted_xy 為 null，不影響正負樣本分類。"""
    from miningbot import build_reentry_dataset as brd
    meta = {"episode": 27, "attempt": 2, "world": "Lucernia", "outcome":
            "confirmed_by_user", "shots": [{"dir": 2, "file": "dir2.png"}],
            "clicks": [{"dir": 2, "actual_xy": [1604, 450],
                        "predicted_xy": None, "invalid": False}]}
    rows, reason = brd.classify_group(meta)
    assert reason is None and rows[0]["xy"] == [1604, 450]


def test_dataset_reads_legacy_pos_key():
    """--rescue 在 2026-07-28 之前倒進來的舊 meta 用 `pos`。"""
    from miningbot import build_reentry_dataset as brd
    meta = {"episode": 23, "attempt": 3, "world": "Lucernia", "outcome":
            "confirmed_by_user", "shots": [{"dir": 8, "file": "dir8.png"}],
            "clicks": [{"dir": 8, "pos": [1589, 443], "invalid": False}]}
    rows, _reason = brd.classify_group(meta)
    assert rows[0]["xy"] == [1589, 443]


# ---- 前端：圈與「採用建議」鍵 ----------------------------------------------

def test_panel_html_draws_prediction_and_offers_adopt():
    from miningbot.web_static import render_intervention_html
    html = render_intervention_html()
    # 2026-08-01：canvas drawPrediction → div overlay positionPredictMark（與標註工具同管線）
    assert "positionPredictMark" in html
    assert 'id="adopt"' in html and "採用建議" in html
    # 採用建議與手動點擊共用同一條座標鏈（沒有第二套換算）
    assert "sendClickNative(p.x, p.y)" in html
    assert html.count("function sendClickNative") == 1


def test_panel_hides_adopt_button_without_prediction():
    from miningbot.web_static import render_intervention_html
    html = render_intervention_html()
    assert "adoptBtn.hidden = !(currentEvent" in html
    assert '<button id="adopt" class="confirm" type="button" hidden' in html


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ---- 傳送板偵測器：玩家標註素材回歸（2026-08-01）--------------------------

def test_teleport_board_detector_hits_every_annotated_fixture():
    """7 張玩家標註的實機幀，`teleport_board.detect` 必須全中且分數過門檻。

    素材是玩家為了回礦本來就要點的那一下（`_save_auto_fixture` 自動收）＋網頁標註
    補的板子座標，兩檔一組在 `tests/fixtures/reentry/teleport_board/`。2026-08-01
    新收的 39/40/41 三組把樣本從 4 擴到 7，重放結果 7/7 命中、分數 0.84~0.97，
    對 `reentry_predict_min_score=0.7` 兩側有 0.14 餘裕——這條測試守的是「下次動
    HSV 百分位表或門檻時，別把已經全中的樣本弄丟」。

    容許 60px：標註是玩家框的板子中心，偵測器回的是板面錨點，實測系統性偏上約 40px
    （這條測試不管那個偏差，`_predict_teleport_board` 只做建議、不自動點）。
    """
    import glob
    import json
    import os

    import cv2
    import numpy as np

    from miningbot import teleport_board
    from miningbot.config import DEFAULT as cfg

    here = os.path.dirname(__file__)
    metas = sorted(glob.glob(os.path.join(here, "fixtures", "reentry",
                                          "teleport_board", "*.json")))
    assert len(metas) >= 7, "素材遺失（應有 auto_27/35/37/38/39/40/41 七組）"
    misses = []
    for meta in metas:
        with open(meta, encoding="utf-8") as f:
            ann = json.load(f).get("annotation") or {}
        # cv2.imread 吃不了非 ASCII 路徑（專案資料夾是中文名）→ fromfile+imdecode
        img = cv2.imdecode(np.fromfile(meta[:-5] + ".png", dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        got = teleport_board.detect(img)
        name = os.path.basename(meta)[:-5]
        if got is None or got[2] < cfg.reentry_predict_min_score:
            misses.append("%s -> %s" % (name, got))
            continue
        if abs(got[0] - ann["cx"]) >= 60 or abs(got[1] - ann["cy"]) >= 60:
            misses.append("%s -> %s 偏離標註 (%d,%d)"
                          % (name, got, ann["cx"], ann["cy"]))
    assert not misses, "傳送板偵測退步：" + "；".join(misses)
