"""WebIPC server：FastAPI app + WebSocket endpoint。

WebIPC thread（Task 10 整合進 main.py）跑 uvicorn server；client 連線維護
FallbackState.client_count；命令透過 parse_message 解析後 push 進 PendingReplies。
"""
import asyncio
import logging
import threading
from typing import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from miningbot.web_protocol import WebMessage, parse_message, serialize_message
from miningbot.web_ipc import PendingReplies, FallbackState


_log = logging.getLogger(__name__)


class ConnectionRegistry:
    """當下 WebSocket 連線池；thread-safe（WebIPC thread 跟事件 sink 都會呼叫）。

    broadcast 是 async（WebSocket send_text 是 async）；但事件 sink 是同步呼叫
    （WebEventSink.__call__ 在 bot 主迴圈 thread 上跑）。解法：維護 WebSocket
    物件清單，broadcast 用 asyncio.run_coroutine_threadsafe 把「逐一 send_text」
    的 coroutine 丟進 server 的 event loop（由 set_loop 注入）跑。

    廣播失敗（連線已斷）只 log 不丟，並把壞連線移出 registry——比照 notify.py
    既有「失敗只回報」慣例，避免冷啟／斷線抖動炸到主迴圈。
    """

    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """WebIPC thread 啟動後注入 event loop（broadcast 用）。

        Task 10 的 WebIPCThread.start 在 uvicorn server 起來後呼叫；
        在此之前 broadcast 直接 return（server 還沒跑起來，沒人可送）。
        """
        self._loop = loop

    def add(self, ws: WebSocket) -> None:
        with self._lock:
            self._connections.add(ws)

    def remove(self, ws: WebSocket) -> None:
        with self._lock:
            self._connections.discard(ws)

    def broadcast(self, msg: WebMessage) -> None:
        """同步呼叫介面（事件 sink 用）；內部丟進 event loop 跑。"""
        if self._loop is None:
            return  # server 還沒跑起來
        text = serialize_message(msg)
        asyncio.run_coroutine_threadsafe(self._broadcast_async(text), self._loop)

    async def _broadcast_async(self, text: str) -> None:
        with self._lock:
            conns = list(self._connections)
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception as e:
                _log.warning("web: broadcast send 失敗（連線可能已斷）: %s", e)
                self.remove(ws)

    def broadcast_binary(self, data: bytes) -> None:
        """截圖 push 用（Task 10 在 main.py 裡接）。"""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_binary_async(data), self._loop)

    async def _broadcast_binary_async(self, data: bytes) -> None:
        with self._lock:
            conns = list(self._connections)
        for ws in conns:
            try:
                await ws.send_bytes(data)
            except Exception as e:
                _log.warning("web: binary broadcast 失敗: %s", e)
                self.remove(ws)


def create_app(
    pending: PendingReplies,
    fallback: FallbackState,
    broadcast_callback: Callable[[WebMessage], None] | None,
) -> FastAPI:
    """建 FastAPI app。

    broadcast_callback：事件到達時呼叫（WebEventSink 用同一個 callback）。
    若傳 None，自動接到 registry.broadcast（production 路徑）；測試可注入
    自訂 callback 觀察廣播呼叫。
    """
    app = FastAPI(title="MiningBot Web IPC")
    registry = ConnectionRegistry()
    app.state.registry = registry
    if broadcast_callback is None:
        broadcast_callback = registry.broadcast
    app.state.broadcast = broadcast_callback  # 測試與 sink 直接呼叫

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        fallback.client_connected()
        registry.add(websocket)
        try:
            while True:
                text = await websocket.receive_text()
                msg = parse_message(text)
                if msg is None:
                    # 壞訊息不 crash，記 log
                    _log.warning("web: 收到不合法訊息，忽略: %r", text[:200])
                    continue
                if msg.type == "command":
                    _handle_command(msg.payload, pending)
                # event type 由 server 發、client 收；client 不該送 event，忽略
        except WebSocketDisconnect:
            pass
        except Exception as e:
            _log.warning("web: WebSocket 連線例外: %s", e)
        finally:
            registry.remove(websocket)
            fallback.client_disconnected()

    return app


def _handle_command(payload: dict, pending: PendingReplies) -> None:
    """把 command payload 推進 PendingReplies（用 flow + id 算 routing key）。

    payload 結構（spec §8）：
    - fire_at / reentry_click：必有 flow + harvest_id（或 attempt_id）+ (x, y)
    - config_set：必有 field + value（白名單驗證在 main.py 整合時做）
    - pause / resume / request_frame：控制類，無 routing key，用 "control:*"

    若 payload 缺 routing key 必要欄位，記 log 不 push（防護）。
    """
    cmd = payload.get("cmd")
    if cmd in ("fire_at", "reentry_click"):
        flow = payload.get("flow")
        ep_id = payload.get("harvest_id") or payload.get("attempt_id")
        if not flow or not ep_id:
            _log.warning("web: %s 缺 flow/episode_id，丟棄: %r", cmd, payload)
            return
        key = f"{flow}:{ep_id}"
    else:
        # 控制類：直接用 cmd 名當 key（不参與 race，主迴圈 safe point 直接讀）
        key = f"control:{cmd}"
    pending.push(key, payload)
