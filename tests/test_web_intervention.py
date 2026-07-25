"""P4 即時介入面板整合測試。

web_pending → main.py 整合點（manual_survey / reentry click）需要 fake bot 與
大量 monkeypatch 才能有意義地跑；本檔先放 skip skeleton，留 P5 或實機驗收補回。

會被執行的 web pipeline 整合測試（不靠 main.py）放 Task 7 補上。
"""
import pytest


def test_get_intervention_returns_html():
    """GET /intervention 回 HTML：含 canvas + fire_at/reentry_click + WebSocket。"""
    from fastapi.testclient import TestClient
    from miningbot.web_ipc import PendingReplies, FallbackState
    from miningbot.web_server import create_app
    pending = PendingReplies()
    fallback = FallbackState()
    app = create_app(pending, fallback, broadcast_callback=None)
    client = TestClient(app)
    r = client.get("/intervention")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    # canvas + 點擊邏輯
    assert "<canvas" in body.lower() or "canvas" in body
    assert "fire_at" in body or "reentry_click" in body
    assert "WebSocket" in body or "websocket" in body.lower() or "ws://" in body or "/ws" in body


def test_intervention_html_has_pinch_zoom_or_scroll_zoom():
    """pinch-zoom（手機）+ scroll-wheel zoom（桌機）至少一個。"""
    from fastapi.testclient import TestClient
    from miningbot.web_ipc import PendingReplies, FallbackState
    from miningbot.web_server import create_app
    pending = PendingReplies()
    fallback = FallbackState()
    app = create_app(pending, fallback, broadcast_callback=None)
    client = TestClient(app)
    body = client.get("/intervention").text
    # 至少有一個 zoom 手勢實作（wheel 事件 / touchmove / pointermove）
    has_zoom = ("wheel" in body.lower() or "touchmove" in body.lower()
                or "touchstart" in body.lower() or "pointermove" in body.lower())
    assert has_zoom


def test_main_harvest_manual_survey_consumes_web_reply():
    """manual_survey 進入時應檢查 web_pending，若有玩家 reply 直接走 fire+verify。

    fake bot 需模擬：_web_pending 在線、_web_fallback.is_fallback()=False、
    capture.grab() 回固定幀、_send_web_intervention_event / _focus_roblox no-op、
    _await_web_pointer_reply 回 {x, y}、_execute_remote_fire_from_web stub 回 (True, ...)。
    斷言：未進入既有 Discord 八方位流程（notify.send_images_message 不被呼叫）。
    """
    pytest.skip("main.py manual_survey 整合需 fake bot；P5 或實機驗收補")


def test_main_execute_remote_fire_short_circuits_on_web_reply():
    """_execute_remote_fire_from_web 收到 (x, y) 應直接呼叫 _aim_fire_and_verify。

    fake bot 需模擬：_wait_for_d3_cooldown 回 (True, "")、_focus_roblox 回 True、
    _mine_resetting=False、capture.grab / capture.crop 回固定幀、
    _aim_fire_and_verify stub 記錄被呼叫的 pos+deadline+chat_base_crop。
    斷言：pos == (x, y)；未呼叫 _detect_core_in_cell / _refind_tracker_near。
    """
    pytest.skip("main.py _execute_remote_fire 整合需 fake bot；P5 或實機驗收補")


def test_main_reentry_consumes_web_click_reply():
    """回礦 _rr_open_episode 開場鏈全閘通過後應先檢查 web_pending，若有玩家 reply
    直接走 _rr_click_from_web。

    fake bot 需模擬：_web_pending 在線、_web_fallback.is_fallback()=False、
    capture.grab() 回固定幀、_send_web_intervention_event / _focus_roblox no-op、
    _await_web_pointer_reply 回 {x, y, attempt_id}、_rr_click_from_web stub 記錄
    被呼叫的 (x, y)。
    斷言：未進入既有 Discord 八方位流程（_rr_sweep_and_send 不被呼叫、未貼 embed）。
    """
    pytest.skip("main.py reentry click 整合需 fake bot；P5 或實機驗收補")


def test_web_fire_at_full_pipeline():
    """完整 pipeline：client send fire_at → server 還原 → pending push。
    不測 main.py bot 端，只測 web_server 段。"""
    import json
    import time
    from fastapi.testclient import TestClient
    from miningbot.web_ipc import PendingReplies, FallbackState
    from miningbot.web_server import create_app
    pending = PendingReplies()
    fallback = FallbackState()
    app = create_app(pending, fallback, broadcast_callback=None)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                        "client_xy": [480, 270], "canvas_size": [960, 540],
                        "zoom": 1.0, "pan_offset": [0, 0]},
        }))
        time.sleep(0.1)
    reply = pending.pop("harvest:007")
    assert reply is not None
    assert reply["x"] == 960
    assert reply["y"] == 540
    assert reply["flow"] == "harvest"
    assert reply["harvest_id"] == "007"


def test_web_reentry_click_full_pipeline():
    import json
    import time
    from fastapi.testclient import TestClient
    from miningbot.web_ipc import PendingReplies, FallbackState
    from miningbot.web_server import create_app
    pending = PendingReplies()
    fallback = FallbackState()
    app = create_app(pending, fallback, broadcast_callback=None)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "reentry_click", "flow": "reentry", "attempt_id": "attempt_2",
                        "client_xy": [100, 100], "canvas_size": [1920, 1080],
                        "zoom": 1.0, "pan_offset": [0, 0]},
        }))
        time.sleep(0.1)
    reply = pending.pop("reentry:attempt_2")
    assert reply is not None
    assert reply["flow"] == "reentry"
    assert reply["attempt_id"] == "attempt_2"


def test_web_fire_at_invalid_does_not_push():
    """缺欄位的 fire_at 不該 push；連線仍活著。"""
    import json
    import time
    from fastapi.testclient import TestClient
    from miningbot.web_ipc import PendingReplies, FallbackState
    from miningbot.web_server import create_app
    pending = PendingReplies()
    fallback = FallbackState()
    app = create_app(pending, fallback, broadcast_callback=None)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "fire_at", "flow": "harvest"},  # 缺 client_xy/id
        }))
        time.sleep(0.1)
        # 連線還活著，可以再送正常命令
        ws.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "pause"},
        }))
        time.sleep(0.1)
    assert pending.pop("harvest:007") is None
    assert pending.pop("control:pause") is not None
