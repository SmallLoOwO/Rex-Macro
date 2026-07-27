"""WebIPC server 整合測試：WebSocket 連線 + 命令 push + client count。"""
import asyncio
import json
import threading
import time
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
    """WebSocket heartbeat：app-level text ping 已退役（P5 Task 2）。

    P4 final-review Important 1：text-message "ping" 只在 TCP 全斷才拋，
    無法偵測手機背景化／Tailscale relay 半斷的 half-open 連線。改依賴
    uvicorn 預設 20s protocol-level ping frame（真正的 keep-alive）。

    ping_interval_s 參數保留（向後相容），但不再產生 app-level heartbeat task。
    """

    def test_no_app_level_heartbeat_task_scheduled(self, monkeypatch):
        # P5 Task 2：ws_endpoint 不該啟動 _send_pings 之類的 asyncio.create_task
        import asyncio
        import time
        from miningbot.web_ipc import PendingReplies, FallbackState
        from miningbot.web_server import create_app

        pending = PendingReplies()
        fallback = FallbackState()
        app = create_app(pending, fallback, broadcast_callback=None,
                         ping_interval_s=0.05)  # 即使 > 0 也不該排程 heartbeat

        scheduled = []
        orig_create_task = asyncio.create_task

        def tracking_create_task(coro, **kw):
            # coroutine object 的 __qualname__ 是函式完整名稱
            scheduled.append(getattr(coro, "__qualname__", ""))
            return orig_create_task(coro, **kw)
        monkeypatch.setattr(asyncio, "create_task", tracking_create_task)

        client = TestClient(app)
        with client.websocket_connect("/ws"):
            # 等過 ping_interval_s 數倍，確保舊實作會被觸發
            time.sleep(0.15)

        heartbeat_names = [
            name for name in scheduled if name and "_send_pings" in str(name)
        ]
        assert not heartbeat_names, (
            f"app-level heartbeat task 不該被排程（依賴 uvicorn protocol ping），"
            f"實際 schedule 的 heartbeat coroutines：{heartbeat_names}")


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


# --- WebSocket 廣播測試的兩個共用工具（2026-07-26 修 flaky）-------------------
#
# 舊寫法是 `websocket_connect` 之後 `time.sleep(0.05)` 賭連線已註冊，然後直接
# `ws.receive_text()`。兩個問題都實際發生過：
#   1. 0.05s 不夠時 broadcast 打在還沒註冊的連線上 → 訊息永遠不會來 →
#      `receive_text()` **無限阻塞**，整個 pytest suite 掛死（實測卡超過 20 分鐘，
#      要 py-spy dump 才知道卡在這裡）。比失敗更糟：CI 只會看到 timeout。
#   2. 偶爾又會收到前一則廣播 → `assert 'X' == 'Y'` 隨機紅燈。
#
# 改成：等真正的註冊信號（fallback.client_count），收訊息一律帶 timeout。


def _wait_for_clients(fallback, n, timeout=5.0):
    """等到 server 端真的把連線註冊進去；逾時直接 fail（不要靜默往下跑）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fallback.client_count >= n:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"{timeout}s 內 client_count 沒到 {n}（實際 {fallback.client_count}）")


def _receive_text(ws, timeout=10.0):
    """帶 timeout 的 receive_text——絕不讓測試無限阻塞。"""
    box = {}

    def _recv():
        try:
            box["value"] = ws.receive_text()
        except BaseException as e:      # noqa: BLE001 - 原樣帶回主執行緒
            box["error"] = e

    t = threading.Thread(target=_recv, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise AssertionError(f"{timeout}s 內沒收到任何 WebSocket 訊息")
    if "error" in box:
        raise box["error"]
    return box["value"]


def test_event_broadcast_reaches_connected_client(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        _wait_for_clients(fallback, 1)
        # 模擬 bot 推一個事件
        app.state.broadcast(WebMessage(type="event", payload={"event": "NEEDS_HUMAN"}))
        msg = json.loads(_receive_text(ws))
        assert msg["type"] == "event"
        assert msg["payload"]["event"] == "NEEDS_HUMAN"


def test_broadcast_only_reaches_current_clients(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    # 沒連線，broadcast 不該炸
    app.state.broadcast(WebMessage(type="event", payload={"event": "X"}))
    # 連一個、broadcast、收——收到的必須是 Y（X 是連線前廣播的，不該補送）
    with client.websocket_connect("/ws") as ws:
        _wait_for_clients(fallback, 1)
        app.state.broadcast(WebMessage(type="event", payload={"event": "Y"}))
        assert json.loads(_receive_text(ws))["payload"]["event"] == "Y"


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


def test_main_loop_consumes_web_pending_at_safe_point(tmp_path):
    """bot 主迴圈 safe point 會 pop web_pending 的控制類命令。

    2026-07-26 補回（原 P1 skip，理由「fake bot 設計依 main.py 結構」）。
    控制類（pause / resume / request_frame）目前只記 log 不接業務邏輯——這是**設計**
    而非未完成：spec §2 的分工表明列「挖礦中遙控器（暫停…）Discord ✅ 主用／網頁
    不接手」，網頁端也沒有這幾顆按鈕。本測試鎖住的是「pop 得到、且不會漏進佇列」。

    fire_at / reentry_click 不在這裡消費（各狀態處理器自取），一併驗它們**留著**。
    """
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    pending = PendingReplies()
    pending.push("control:pause", {"cmd": "pause"})
    pending.push("control:resume", {"cmd": "resume"})
    pending.push("control:request_frame", {"cmd": "request_frame"})
    pending.push("harvest:007", {"x": 1, "y": 2})      # 狀態處理器自取，不該被清掉

    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _overrides_path=str(tmp_path / "config_overrides.json"),
    )
    bot._consume_web_pending()

    assert pending.pop("control:pause") is None, "pause 應已被主迴圈消費"
    assert pending.pop("control:resume") is None
    assert pending.pop("control:request_frame") is None
    assert pending.pop("harvest:007") == {"x": 1, "y": 2}, (
        "fire_at reply 必須留給 awaiting_fine 狀態處理器自取，不可在 safe point 清掉")


def test_consume_web_pending_noop_without_web():
    """web_server_enabled=False 時 _web_pending is None → 直接 return，不得炸。"""
    from tests.fake_bot import make_fake_bot

    bot = make_fake_bot(bind=["_consume_web_pending"], _web_pending=None)
    bot._consume_web_pending()   # 不拋例外即通過


# ---------------------------------------------------------------------------
# 2026-07-27：ConnectionRegistry 重播緩衝。
#
# 使用者的實際用法是「有提醒才連進來」，不會整場開著分頁盯——舊設計純廣播，
# 推播那當下如果玩家還沒連上（就是這個用法的常態），訊息直接消失，連進來只看到
# 空白 idle（07-27 harvest 115／reentry #26 實錄，晚到的分頁什麼都沒收到）。
# ---------------------------------------------------------------------------


class _FakeWs:
    """假 WebSocket：只記錄收到的 send_text/send_bytes 呼叫，不用真的 asyncio 連線。"""

    def __init__(self):
        self.received: list = []

    async def send_text(self, text):
        self.received.append(("text", text))

    async def send_bytes(self, data):
        self.received.append(("binary", data))


class TestConnectionRegistryReplay:
    def test_broadcast_after_begin_is_recorded(self):
        from miningbot.web_server import ConnectionRegistry

        registry = ConnectionRegistry()
        registry.begin_intervention_replay()
        registry.broadcast(WebMessage(type="event", payload={"event": "X"}))
        registry.broadcast_binary(b"png-bytes")
        assert len(registry._replay) == 2

    def test_broadcast_before_begin_is_not_recorded(self):
        """沒開始 recording（idle 狀態）的一般 broadcast 不該被存——不然緩衝會
        無限累積不相干事件（設定變更、狀態通知等）。"""
        from miningbot.web_server import ConnectionRegistry

        registry = ConnectionRegistry()
        registry.broadcast(WebMessage(type="event", payload={"event": "X"}))
        assert registry._replay == []

    def test_replay_to_sends_buffered_sequence_in_order(self):
        import asyncio
        from miningbot.web_server import ConnectionRegistry

        registry = ConnectionRegistry()
        registry.begin_intervention_replay()
        registry.broadcast(WebMessage(
            type="event", payload={"event": "INTERVENTION_FRAME", "index": 0}))
        registry.broadcast_binary(b"frame-0-png")
        registry.broadcast(WebMessage(
            type="event", payload={"event": "INTERVENTION_NEEDED"}))

        ws = _FakeWs()
        asyncio.run(registry.replay_to(ws))

        kinds = [k for k, _ in ws.received]
        assert kinds == ["text", "binary", "text"]
        assert ws.received[1][1] == b"frame-0-png"
        assert json.loads(ws.received[2][1])["payload"]["event"] == "INTERVENTION_NEEDED"

    def test_end_intervention_replay_clears_buffer(self):
        import asyncio
        from miningbot.web_server import ConnectionRegistry

        registry = ConnectionRegistry()
        registry.begin_intervention_replay()
        registry.broadcast(WebMessage(type="event", payload={"event": "X"}))
        registry.end_intervention_replay()

        ws = _FakeWs()
        asyncio.run(registry.replay_to(ws))
        assert ws.received == [], "結束的介入不該再重播給晚到的 client"

    def test_begin_again_discards_previous_buffer(self):
        """新一輪介入（重掃/重試）開始要蓋掉舊緩衝，不是疊加——不然晚到的 client
        會先收到一批已經作廢的舊圖，再收到新圖，畫面會閃一輪錯的。"""
        import asyncio
        from miningbot.web_server import ConnectionRegistry

        registry = ConnectionRegistry()
        registry.begin_intervention_replay()
        registry.broadcast(WebMessage(type="event", payload={"event": "OLD"}))
        registry.begin_intervention_replay()
        registry.broadcast(WebMessage(type="event", payload={"event": "NEW"}))

        ws = _FakeWs()
        asyncio.run(registry.replay_to(ws))
        events = [json.loads(t)["payload"]["event"]
                 for k, t in ws.received if k == "text"]
        assert events == ["NEW"]

    def test_ws_endpoint_replays_to_late_joiner(self):
        """端到端：先推播（沒人連著），之後才連上的 client 也要收到完整序列。

        這是 07-27 實機問題的直接回歸測試——「有提醒才連」是使用者的實際用法，
        連上時機晚於 push 不該等於什麼都看不到。
        """
        from miningbot.web_ipc import PendingReplies, FallbackState
        from miningbot.web_server import create_app

        pending = PendingReplies()
        fallback = FallbackState()
        app = create_app(pending, fallback, broadcast_callback=None)
        registry = app.state.registry

        import asyncio
        loop = asyncio.new_event_loop()
        registry.set_loop(loop)
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()
        try:
            # push 發生在任何人連上之前（模擬「觸發時沒人在看」）
            registry.begin_intervention_replay()
            registry.broadcast(WebMessage(
                type="event",
                payload={"event": "INTERVENTION_NEEDED", "flow": "harvest",
                         "routing_key": "harvest:115", "summary": "候選清單"}))
            time.sleep(0.2)   # 讓 broadcast 的 coroutine 真的跑過（沒人收也沒差，只為過帳）

            with TestClient(app).websocket_connect("/ws") as ws:
                msg = ws.receive_json()
                assert msg["payload"]["event"] == "INTERVENTION_NEEDED"
                assert msg["payload"]["routing_key"] == "harvest:115"
        finally:
            loop.call_soon_threadsafe(loop.stop)
