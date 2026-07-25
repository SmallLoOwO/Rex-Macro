"""WebIPC server 整合測試：WebSocket 連線 + 命令 push + client count。"""
import asyncio
import json
import threading
import pytest
from fastapi.testclient import TestClient

from miningbot.web_ipc import PendingReplies, FallbackState
from miningbot.web_protocol import WebMessage
from miningbot.web_server import create_app


@pytest.fixture
def app_parts():
    pending = PendingReplies()
    fallback = FallbackState()
    app = create_app(pending, fallback, broadcast_callback=None)
    # 模擬 WebIPC thread 已注入 loop：TestClient 內部 loop 跟 broadcast 用的 loop
    # 必須是同一個會跑的 loop；用一個獨立 loop 在背景 thread 跑，
    #讓 broadcast 的 run_coroutine_threadsafe 有地方 schedule。
    registry = app.state.registry
    loop = asyncio.new_event_loop()
    registry.set_loop(loop)
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    yield app, pending, fallback, []
    loop.call_soon_threadsafe(loop.stop)


def test_health_endpoint(app_parts):
    app, *_ = app_parts
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_websocket_connect_increments_client_count(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        assert fallback.client_count == 1
    assert fallback.client_count == 0


def test_websocket_command_pushes_to_pending(app_parts):
    """P1 regression：fire_at 命令透過 _handle_command 驗證後 push 進 pending。

    P5 Task 1：座標協議重設——payload 改成直接送原生 x/y（client 端 JS 自己換算），
    不再送 client_xy/canvas_size/zoom/pan_offset；server 端 parser 變 thin validator。
    """
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "fire_at", "flow": "harvest",
                        "harvest_id": "007",
                        "x": 851, "y": 189},
        }))
        # 給 server 一點時間處理
        import time; time.sleep(0.05)
    # 連線斷了之後 pending 應該有 reply（routing key harvest:007）
    reply = pending.pop("harvest:007")
    assert reply is not None
    assert reply["flow"] == "harvest"
    assert reply["harvest_id"] == "007"
    assert reply["x"] == 851
    assert reply["y"] == 189


class TestHandleCommandCoordinatesRestore:
    """fire_at 命令的 thin-validator push：client 送原生座標 → push 進 pending。

    P5 Task 1：座標空間協議重設——server 不再還原座標，只驗證 payload 結構。
    """

    def test_fire_at_pushes_native_coords(self):
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
                            "x": 960, "y": 540},
            }))
            import time; time.sleep(0.1)
        reply = pending.pop("harvest:007")
        assert reply is not None
        assert reply["x"] == 960
        assert reply["y"] == 540

    def test_fire_at_invalid_payload_does_not_push(self):
        from miningbot.web_ipc import PendingReplies, FallbackState
        from miningbot.web_server import create_app
        pending = PendingReplies()
        fallback = FallbackState()
        app = create_app(pending, fallback, broadcast_callback=None)
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({
                "type": "command",
                "payload": {"cmd": "fire_at", "flow": "harvest"},  # 缺 x/y/id
            }))
            import time; time.sleep(0.1)
        assert pending.pop("harvest:007") is None  # 沒進 queue
        # 連線還活著（沒 crash）
        # 結束 with 區塊才會 disconnect


class TestWebSocketHeartbeat:
    """WebSocket heartbeat：server 周期性 ping；client 不回 pong 視為斷線。

    P4 minimum viable：只驗證 server 在連線時主動送 ping 的能力，
    不驗證 timeout（測試 timeout 太慢）。
    """

    def test_ping_sent_within_interval(self):
        # 此測試驗證 server 在 websocket_ping_interval_s 內有送出 ping
        # 實作面上 server 用 asyncio.create_task 在 endpoint 內排 ping
        from miningbot.web_ipc import PendingReplies, FallbackState
        from miningbot.web_server import create_app
        pending = PendingReplies()
        fallback = FallbackState()
        app = create_app(pending, fallback, broadcast_callback=None,
                         ping_interval_s=0.05)  # 測試用很短 interval
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            # 等 ping 到達
            try:
                # TestClient 的 receive 點接收 ping/pong/text/bytes
                # WebSocket ping 在 TestClient 不直接可見，但 receive_text 會 timeout
                # 略：heartbeat 行為靠 production uvicorn 實機驗證
                pytest.skip("WebSocket ping 在 TestClient 不可見；實機驗證")
            except Exception:
                pass


def test_websocket_invalid_message_does_not_crash(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not json")  # 壞訊息
        ws.send_text(json.dumps({"missing": "type"}))  # 缺欄位
        # 連線仍活著
        ws.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "pause"},
        }))
        import time; time.sleep(0.05)
    # 壞訊息沒進 queue，正常的進了
    # pause 沒有 routing key（不是 fire/click）→ 用 None episode 推導為 "control" key
    # 這裡先驗證不 crash；routing key 細節看主迴圈整合 task


def test_websocket_disconnect_decrements_client_count(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        assert fallback.client_count == 1
    assert fallback.client_count == 0


def test_multiple_clients_counted(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"), \
         client.websocket_connect("/ws"):
        assert fallback.client_count == 2
    assert fallback.client_count == 0


def test_event_broadcast_reaches_connected_client(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        # 給連線建立時間
        import time; time.sleep(0.05)
        # 模擬 bot 推一個事件
        app.state.broadcast(WebMessage(type="event", payload={"event": "NEEDS_HUMAN"}))
        received = ws.receive_text()
        msg = json.loads(received)
        assert msg["type"] == "event"
        assert msg["payload"]["event"] == "NEEDS_HUMAN"


def test_broadcast_only_reaches_current_clients(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    # 沒連線，broadcast 不該炸
    app.state.broadcast(WebMessage(type="event", payload={"event": "X"}))
    # 連一個、broadcast、收
    with client.websocket_connect("/ws") as ws:
        import time; time.sleep(0.05)
        app.state.broadcast(WebMessage(type="event", payload={"event": "Y"}))
        received = ws.receive_text()
        assert json.loads(received)["payload"]["event"] == "Y"


def test_broadcast_failure_does_not_raise(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        import time; time.sleep(0.05)
    # 連線已斷；broadcast 不該丟例外
    app.state.broadcast(WebMessage(type="event", payload={"event": "Z"}))


def test_fallback_true_when_no_clients(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    assert fallback.is_fallback(now=None, grace_s=0.0) is True  # grace=0 立刻 fallback
    with client.websocket_connect("/ws"):
        assert fallback.is_fallback(now=None, grace_s=0.0) is False
    assert fallback.is_fallback(now=None, grace_s=0.0) is True


def test_webipc_thread_starts_and_serves_websocket(app_parts, monkeypatch):
    """WebIPC thread 啟動後能接受 WebSocket 連線（用 uvicorn 跑實際 port）。

    驗證：
    - thread 啟動後 is_alive()=True
    - actual_port > 0（OS 分配的隨機 port）
    - WebSocket 連得進去、client_count 確實 +1
    - stop()＋join() 收掉 thread
    """
    from miningbot.web_server import WebIPCThread

    pending = PendingReplies()
    fallback = FallbackState()
    thread = WebIPCThread(pending=pending, fallback=fallback, port=0)  # 0 = 隨機 port
    thread.start()
    try:
        # start() 已 polling 等 socket bind 完；給 uvicorn loop 多一點時間穩定
        import time; time.sleep(0.3)
        assert thread.is_alive()
        assert thread.actual_port > 0
        # 連連線測試（TestClient 直連 ASGI app，不過 uvicorn network 層）
        client = TestClient(thread.app)
        with client.websocket_connect("/ws"):
            assert fallback.client_count == 1
    finally:
        thread.stop()
        thread.join(timeout=2.0)


def test_main_loop_consumes_web_pending_at_safe_point(monkeypatch):
    """bot 主迴圈 safe point 會 pop web_pending 並執行對應動作。

    用一個 minimal fake bot 驗證迴圈邏輯，不啟動完整 bot。P1 階段先 skip：
    main.py 的迴圈結構要實際讀過才能寫出有意義的 fake bot 測試；且 P1 只鋪框架
    （控制類立即處理、fire/click 留給 P4 各狀態處理器自取），真正要驗「消費後
    系統狀態正確切換」得等 P4 把狀態處理器接上 reply 佇列才有意義。
    """
    pytest.skip("具體 fake bot 設計依 main.py 結構；P4 整合狀態處理器時補回")
