"""標註即時回判決（spec D3a）：標完當下就知道有沒有戳到 bug。

現在標註對玩家零回報，三個月只標了 2 張。有了回判決，玩家標的當下就知道這張圖
是不是真的暴露 bug、還是偵測器其實已經修好了。

降級規則（H061）：偵測模組出問題時**存檔照樣成功、回應不附 verdict、log 一行**。
"""

import json
import logging
import os

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from miningbot import web_server
from miningbot.web_annotation import verdict_agrees


# ---- agree/disagree（純函式）------------------------------------------------

def test_agrees_when_detector_rejects_a_false_positive_report():
    """玩家說「沒框你卻抓了」，偵測器現在 rejected → 兩邊都說沒有 → 一致。"""
    assert verdict_agrees("rejected", "false_positive") is True


def test_disagrees_when_detector_rejects_a_false_negative_report():
    """spec D3a 的例子：現行判拒絕／你標漏判 → ❌ 不一致（bug 還在）。"""
    assert verdict_agrees("rejected", "false_negative") is False


def test_agrees_when_detector_accepts_a_false_negative_report():
    """偵測器現在抓到了＝這張圖已經不再暴露當初那個 bug。"""
    assert verdict_agrees("accepted", "false_negative") is True


def test_control_sample_agrees_only_when_accepted():
    """symptom=None 是對照組（玩家確認過的真框）。"""
    assert verdict_agrees("accepted", None) is True
    assert verdict_agrees("rejected", None) is False


def test_should_reject_failed_matches_false_positive_semantics():
    assert verdict_agrees("accepted", "should_reject_failed") is False
    assert verdict_agrees("rejected", "should_reject_failed") is True


def test_unknown_symptom_has_no_comparison():
    assert verdict_agrees("accepted", "unknown") is None
    assert verdict_agrees("rejected", "unknown") is None


# ---- annotation_verdict：降級不靜默 ----------------------------------------

def test_verdict_is_none_and_logged_when_detector_import_fails(monkeypatch, caplog):
    """偵測模組 import 失敗 → 回 None（呼叫端因此不附 verdict），但一定 log。"""
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **kw):
        if name == "miningbot.vision" or name.endswith("vision"):
            raise ImportError("no cv2 in this interpreter")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _boom)
    with caplog.at_level(logging.WARNING):
        got = web_server.annotation_verdict("aim", "x.png", None, None)
    monkeypatch.undo()
    assert got is None
    assert any("回判決降級" in r.getMessage() for r in caplog.records)


def test_verdict_is_none_when_detector_raises(monkeypatch, caplog, tmp_path):
    png = tmp_path / "crop.png"
    cv2.imencode(".png", np.zeros((270, 320, 3), np.uint8))[1].tofile(str(png))

    from miningbot import vision

    def _boom(*_a, **_kw):
        raise ValueError("bad crop")

    monkeypatch.setattr(vision, "detect_tracker_core", _boom)
    with caplog.at_level(logging.WARNING):
        got = web_server.annotation_verdict("aim", str(png), None, None)
    assert got is None
    assert any("回判決降級" in r.getMessage() for r in caplog.records)


def test_verdict_is_none_when_image_cannot_be_read(tmp_path):
    assert web_server.annotation_verdict(
        "aim", str(tmp_path / "missing.png"), None, None) is None


def test_verdict_rejects_blank_crop():
    """全黑裁圖沒有框心 → rejected；玩家若標「漏判」就會顯示不一致。"""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        cv2.imencode(".png", np.zeros((270, 320, 3), np.uint8))[1].tofile(path)
        got = web_server.annotation_verdict("aim", path, None, "false_negative")
    finally:
        os.unlink(path)
    assert got["detector"] == "rejected"
    assert got["agree"] is False and got["your_label"] == "false_negative"


def test_reentry_verdict_uses_full_frame_not_crop():
    """teleport_board 的 ROI 是螢幕座標，餵 320×270 裁圖判什麼都沒意義。"""
    full = os.path.join(os.path.dirname(__file__), "fixtures", "reentry",
                        "teleport_board", "auto_27_success.png")
    got = web_server.annotation_verdict(
        "reentry/teleport_board", None, full, None)
    assert got["detector"] == "accepted"
    assert got["agree"] is True and got["score"]["score"] > 0


# ---- POST /api/annotate 端到端 ---------------------------------------------

def _client(tmp_path):
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    from miningbot.web_ipc import FallbackState, PendingReplies
    app = web_server.create_app(
        PendingReplies(), FallbackState(), broadcast_callback=None,
        fixtures_dir=str(fixtures), snapshots_root=str(snaps))
    return TestClient(app), snaps, fixtures


def _payload(source_path, symptom=None):
    return {
        "image": "shot.png", "source_path": source_path,
        "annotation": {"type": "square", "cx": 400, "cy": 300, "size": 50},
        "tier": None, "variant": None, "mineral": None,
        "source": {"kind": "manual"}, "symptom": symptom,
        "related_incident": None,
    }


def test_post_annotate_returns_verdict(tmp_path):
    client, snaps, fixtures = _client(tmp_path)
    src = snaps / "shot.png"
    cv2.imencode(".png", np.zeros((1080, 1920, 3), np.uint8))[1].tofile(str(src))

    r = client.post("/api/annotate", json=_payload(str(src), "false_negative"))
    assert r.status_code == 201
    body = r.json()
    assert body["verdict"]["detector"] == "rejected"
    assert body["verdict"]["agree"] is False
    # 既有存檔行為不變：同名 png + json 落在 category 目錄下
    assert (fixtures / "aim" / "shot.png").exists()
    assert (fixtures / "aim" / "shot.json").exists()


def test_post_annotate_still_saves_when_verdict_unavailable(tmp_path, monkeypatch):
    client, snaps, fixtures = _client(tmp_path)
    src = snaps / "shot.png"
    cv2.imencode(".png", np.zeros((1080, 1920, 3), np.uint8))[1].tofile(str(src))
    monkeypatch.setattr(web_server, "annotation_verdict", lambda *a, **kw: None)

    r = client.post("/api/annotate", json=_payload(str(src)))
    assert r.status_code == 201
    body = r.json()
    assert "verdict" not in body
    saved = json.loads((fixtures / "aim" / "shot.json").read_text(encoding="utf-8"))
    assert saved["source"]["kind"] == "manual"


def test_annotate_page_renders_verdict_text():
    from miningbot.web_static import render_annotate_html
    html = render_annotate_html(episode_id="1", snapshot_path="a.png",
                                rarity_choices=([], []))
    assert "function verdictText" in html
    assert "現行判" in html and "不一致" in html


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
