"""真 socket 的 WebIPC 迴歸測試（2026-07-26）。

## 為什麼一定要有這一份

其他 web 測試全部用 `fastapi.testclient.TestClient`。它的 `websocket_connect`
是 **Starlette 的 in-process ASGI shim**——直接呼叫 app 的 ASGI callable，
根本不經過 uvicorn 的 HTTP 解析與 Upgrade 協商。後果是：

環境裡**完全沒有 WebSocket 實作**（`websockets` / `wsproto` 都沒裝）時，
TestClient 的 WebSocket 測試照樣全綠，但真實瀏覽器連 `ws://.../ws` 會拿到
**HTTP 404**——uvicorn 的 `_should_upgrade_to_ws()` 看到 `ws_protocol_class is None`
就把 Upgrade 請求當普通 HTTP 走，而 FastAPI 沒有 `GET /ws` 這條路由。

2026-07-26 實機就是這樣：`pyproject.toml` 只宣告裸的 `uvicorn>=0.27`
（不是 `uvicorn[standard]`，也沒列 `websockets`），於是 `.venv` 與實機 Store Python
兩邊都沒有 WS 實作——介入面板恆顯示「WebSocket 斷線」、`FallbackState.client_count`
恆 0 → `is_fallback()` 恆 True → 介入全部照舊只走 Discord。網頁 UI 的核心功能
從來沒有在任何環境跑起來過，而整套測試是綠的。

所以這裡刻意**起一個真的 uvicorn（WebIPCThread）並用真 TCP socket 連**。
只要有人再把 `websockets` 依賴弄掉，這份會紅。
"""
import json
import socket
import time

import pytest

from miningbot.web_ipc import PendingReplies, FallbackState
from miningbot.web_server import WebIPCThread


def test_websockets_implementation_is_installed():
    """依賴守門：缺 WS 實作時 uvicorn 只會讓 /ws 回 404，不會有任何紅燈。

    刻意獨立成一條並放最前面——它壞掉時，下面的 socket 測試會以
    「404」而不是「缺套件」的形式失敗，訊息不夠指向根因。
    """
    import importlib.util
    has_ws = importlib.util.find_spec("websockets") is not None
    has_wsproto = importlib.util.find_spec("wsproto") is not None
    assert has_ws or has_wsproto, (
        "沒有任何 WebSocket 實作：uvicorn 會把 Upgrade 當普通 HTTP 處理，"
        "/ws 回 404，介入面板永遠連不上。請 `uv add websockets`"
        "（或改用 uvicorn[standard]），並記得實機的 Store Python 也要裝。"
    )


@pytest.fixture
def server():
    """真的起 uvicorn（port=0 讓 OS 配），測完收掉。"""
    pending = PendingReplies()
    fallback = FallbackState()
    thread = WebIPCThread(pending, fallback, port=0, host="127.0.0.1")
    thread.start()
    assert thread.actual_port > 0, "uvicorn 沒能 bind socket"
    try:
        yield thread, pending, fallback
    finally:
        thread.stop()
        thread.join(timeout=5.0)


def _ws_handshake(port: int, path: str = "/ws") -> str:
    """手打一次 WebSocket 升級握手，回 status line。

    不用 websockets client library——這裡要驗的正是「伺服器端有沒有能力升級」，
    用最低階的方式問最直接。
    """
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as s:
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        s.sendall(req.encode("ascii"))
        data = s.recv(4096)
    return data.decode("latin-1", errors="replace").split("\r\n", 1)[0]


def test_ws_upgrade_returns_101_not_404(server):
    """核心迴歸：/ws 必須真的升級（101），不能是 404。

    404 就是「uvicorn 沒有 WS 實作、把 Upgrade 當普通 HTTP」的指紋。
    """
    thread, _, _ = server
    status = _ws_handshake(thread.actual_port)
    assert "101" in status, (
        f"/ws 握手沒有回 101，而是 {status!r}。"
        "回 404 代表 uvicorn 缺 WebSocket 實作（見本檔開頭）。"
    )


def test_real_client_can_connect_and_send_command(server):
    """端到端：真 client 連上 → client_count 上升 → 送命令 → 進 PendingReplies。

    用 websockets 的同步 client（sync API），跟瀏覽器走同一條協議路徑。
    """
    from websockets.sync.client import connect

    thread, pending, fallback = server
    url = f"ws://127.0.0.1:{thread.actual_port}/ws"
    with connect(url, open_timeout=5) as ws:
        # 連線註冊是非同步的：輪詢等它反映到 client_count，不用固定 sleep
        # （固定 sleep 賭輸不是紅燈，是整個 suite 掛死——H061 那次的教訓）。
        deadline = time.monotonic() + 5.0
        while fallback.client_count == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert fallback.client_count == 1
        assert fallback.is_fallback() is False   # 有 web client → 不走 Discord fallback

        ws.send(json.dumps({
            "type": "command",
            "payload": {"cmd": "fire_at", "flow": "harvest",
                        "harvest_id": "113", "x": 960, "y": 540},
        }))
        deadline = time.monotonic() + 5.0
        got = None
        while got is None and time.monotonic() < deadline:
            got = pending.pop("harvest:113")
            if got is None:
                time.sleep(0.02)
    assert got is not None, "命令沒有進到 PendingReplies"
    assert got["x"] == 960 and got["y"] == 540

    # 斷線後 client_count 要回到 0（grace period 由 is_fallback 另外管）
    deadline = time.monotonic() + 5.0
    while fallback.client_count != 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert fallback.client_count == 0


def test_http_routes_still_work_on_real_server(server):
    """同一顆真 server 上 HTTP 也要正常（確認沒有為了 WS 破壞既有路由）。"""
    import urllib.request

    thread, _, _ = server
    url = f"http://127.0.0.1:{thread.actual_port}/health"
    with urllib.request.urlopen(url, timeout=5) as r:
        assert r.status == 200
        assert json.loads(r.read().decode("utf-8")) == {"ok": True}


# ---------------------------------------------------------------------------
# 2026-07-26：八方位推送的 wire contract（真 socket）。
#
# 面板把「meta 之後緊接著的那個 binary」配成一張圖。這個假設完全建立在
# server 真的照 meta→binary→meta→binary… 的順序送達。順序一旦錯位，
# 玩家點的方位就跟 bot 轉過去的方位不一致——會直接點在錯的地方。
# ---------------------------------------------------------------------------


def _recv_sequence(ws, n, timeout=10.0):
    """收 n 則訊息，回 [("text", payload) | ("bytes", data)]。"""
    out = []
    deadline = time.monotonic() + timeout
    while len(out) < n and time.monotonic() < deadline:
        msg = ws.recv(timeout=max(0.1, deadline - time.monotonic()))
        if isinstance(msg, (bytes, bytearray)):
            out.append(("bytes", bytes(msg)))
        else:
            out.append(("text", json.loads(msg)["payload"]))
    return out


def test_sweep_frames_arrive_as_meta_then_binary_pairs(server):
    """三張圖 → meta/binary 交錯到達，且 index 與圖內容對得起來。"""
    from websockets.sync.client import connect
    from miningbot.web_protocol import WebMessage

    thread, _, fallback = server
    registry = thread.app.state.registry
    url = f"ws://127.0.0.1:{thread.actual_port}/ws"
    with connect(url, open_timeout=5) as ws:
        deadline = time.monotonic() + 5.0
        while fallback.client_count == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        for seq in range(3):
            registry.broadcast(WebMessage(type="event", payload={
                "event": "INTERVENTION_FRAME", "flow": "reentry",
                "routing_key": "reentry:26", "index": seq, "total": 3,
                "dir": seq + 1}))
            registry.broadcast_binary(b"PNG-%d" % seq)
        registry.broadcast(WebMessage(type="event", payload={
            "event": "INTERVENTION_NEEDED", "flow": "reentry",
            "routing_key": "reentry:26", "summary": "回礦 #26",
            "mode": "sweep", "frame_count": 3}))
        got = _recv_sequence(ws, 7)

    kinds = [p["event"] if k == "text" else "BINARY" for k, p in got]
    assert kinds == [
        "INTERVENTION_FRAME", "BINARY",
        "INTERVENTION_FRAME", "BINARY",
        "INTERVENTION_FRAME", "BINARY",
        "INTERVENTION_NEEDED",
    ], f"順序錯位，前端會把圖配到錯的方位：{kinds}"
    for seq in range(3):
        meta = got[seq * 2][1]
        assert meta["index"] == seq and meta["dir"] == seq + 1
        assert got[seq * 2 + 1][1] == b"PNG-%d" % seq


def test_main_push_helper_sends_needs_last(server):
    """`Bot._send_web_intervention_frames` 真的走完整條路：8 張圖 + 最後一則 NEEDS。

    NEEDS 是「開工訊號」——它到的時候 8 張必須都已經在 client 手上，
    否則玩家看到「需要介入」卻是空白畫面。
    """
    import logging
    import types as _types
    from websockets.sync.client import connect
    from miningbot.main import Bot

    thread, _, fallback = server

    class _Bot:
        pass

    bot = _Bot()
    bot._web_thread = thread
    bot.logger = logging.getLogger("test_sweep_wire")
    bot.log_discord = logging.getLogger("test_sweep_wire")
    bot._send_web_intervention_frames = _types.MethodType(
        Bot._send_web_intervention_frames, bot)

    url = f"ws://127.0.0.1:{thread.actual_port}/ws"
    with connect(url, open_timeout=5) as ws:
        deadline = time.monotonic() + 5.0
        while fallback.client_count == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        pushed = bot._send_web_intervention_frames(
            flow="reentry", routing_key="reentry:26",
            frames=[(i, b"x%d" % i) for i in range(8)],
            ctx_summary="回礦 #26（attempt 2）｜目標層：Shamrock",
            note="")
        got = _recv_sequence(ws, 17)

    assert pushed is True
    assert len([1 for k, _ in got if k == "bytes"]) == 8
    last_kind, last = got[-1]
    assert last_kind == "text" and last["event"] == "INTERVENTION_NEEDED"
    assert last["frame_count"] == 8 and last["routing_key"] == "reentry:26"
    # dir 是 1 起算的介面值（與 Discord「方位 1-8」一致）
    dirs = [p["dir"] for k, p in got if k == "text" and p["event"] == "INTERVENTION_FRAME"]
    assert dirs == [1, 2, 3, 4, 5, 6, 7, 8]


def test_main_push_helper_carries_layer_for_harvest_candidates(server):
    """2026-07-27：harvest 候選清單推 web 時帶 layer（3-tuple frames）。

    候選疊圖可能來自不同俯仰層（up/mid/down）；玩家點圖時 client 要把 layer
    一起回報，bot 才知道除了轉方位還要不要調俯仰。舊 2-tuple（reentry 用，
    無 layer 概念）必須維持不受影響——這裡只驗證 3-tuple 這條新路。
    """
    import logging
    import types as _types
    from websockets.sync.client import connect
    from miningbot.main import Bot

    thread, _, fallback = server

    class _Bot:
        pass

    bot = _Bot()
    bot._web_thread = thread
    bot.logger = logging.getLogger("test_layer_wire")
    bot.log_discord = logging.getLogger("test_layer_wire")
    bot._send_web_intervention_frames = _types.MethodType(
        Bot._send_web_intervention_frames, bot)

    url = f"ws://127.0.0.1:{thread.actual_port}/ws"
    with connect(url, open_timeout=5) as ws:
        deadline = time.monotonic() + 5.0
        while fallback.client_count == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        pushed = bot._send_web_intervention_frames(
            flow="harvest", routing_key="harvest:115",
            frames=[(0, "mid", b"x0"), (0, "up", b"x1")],
            ctx_summary="[115] 候選清單", note="")
        got = _recv_sequence(ws, 5)

    assert pushed is True
    metas = [p for k, p in got if k == "text" and p["event"] == "INTERVENTION_FRAME"]
    assert [m["layer"] for m in metas] == ["mid", "up"]
    assert [m["dir"] for m in metas] == [1, 1]


def test_panel_control_buttons_reach_pending_over_real_socket(server):
    """面板三顆按鈕（重掃/重骰/跳過）經真 socket 要能送達 PendingReplies。"""
    from websockets.sync.client import connect

    thread, pending, _ = server
    url = f"ws://127.0.0.1:{thread.actual_port}/ws"
    with connect(url, open_timeout=5) as ws:
        for cmd in ("sweep", "reroll", "skip"):
            ws.send(json.dumps({"type": "command", "payload": {"cmd": cmd}}))
        deadline = time.monotonic() + 5.0
        got = {}
        while len(got) < 3 and time.monotonic() < deadline:
            for cmd in ("sweep", "reroll", "skip"):
                if cmd not in got:
                    v = pending.pop(f"control:{cmd}")
                    if v is not None:
                        got[cmd] = v
            time.sleep(0.02)
    assert set(got) == {"sweep", "reroll", "skip"}, f"按鈕沒送達：{sorted(got)}"
