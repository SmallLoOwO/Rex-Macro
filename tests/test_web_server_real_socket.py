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
