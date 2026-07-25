"""WebIPC server：FastAPI app + WebSocket endpoint。

WebIPC thread（Task 10 整合進 main.py）跑 uvicorn server；client 連線維護
FallbackState.client_count；命令透過 parse_message 解析後 push 進 PendingReplies。
"""
import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Callable

import uvicorn
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
    on_startup: Callable[[asyncio.AbstractEventLoop], None] | None = None,
) -> FastAPI:
    """建 FastAPI app。

    broadcast_callback：事件到達時呼叫（WebEventSink 用同一個 callback）。
        若傳 None，自動接到 registry.broadcast（production 路徑）；測試可注入
        自訂 callback 觀察廣播呼叫。
    on_startup：可選啟動回呼，在 uvicorn lifespan startup 階段（loop 已跑起來）
        被呼叫，傳入當下 event loop。WebIPCThread 用它把 loop 注入 registry，
        讓 broadcast 的 run_coroutine_threadsafe 有 loop 可 schedule。測試不傳。

    lifespan 注入（uvicorn 0.51+）：原本 brief 的 `config.lifespan = patched` 行不通
    （uvicorn 0.51 的 config.lifespan 是字串 "auto"，不是 callable）；改用 FastAPI
    的 lifespan context manager，副作用是低且與 TestClient 相容。
    """
    @asynccontextmanager
    async def _lifespan(app):
        if on_startup is not None:
            on_startup(asyncio.get_running_loop())
        yield

    app = FastAPI(title="MiningBot Web IPC", lifespan=_lifespan)
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


class WebIPCThread:
    """WebIPC daemon thread：跑 uvicorn server（spec §8）。

    port=0：作業系統隨機分配；actual_port 在 server socket bind 完後填。
    bot 啟動時 start()（比照 Discord polling thread；main.py:2308 區段），
    關機時 stop()＋join()。

    loop 注入（uvicorn 0.51+）：brief 原本 `config.lifespan = patched` 在 uvicorn
    0.51 行不通（config.lifespan 是字串 "auto"，不是 callable）；改走 FastAPI
    lifespan——on_startup callback 在 uvicorn lifespan startup 內被呼叫，
    當下 loop 即 server loop，交給 registry.set_loop，broadcast 即可用
    run_coroutine_threadsafe 跨 thread 投遞。

    actual_port 不在 lifespan 內取（lifespan 啟動時 asyncio.Server 尚未建立，
    srv.sockets 是空的）；改在 start() 內 polling 等 socket bind 完（< 5s）。
    """

    def __init__(
        self,
        pending: PendingReplies,
        fallback: FallbackState,
        port: int = 8765,
        host: str = "127.0.0.1",
    ):
        self.pending = pending
        self.fallback = fallback
        self.port = port
        self.host = host  # 綁 127.0.0.1（spec §2：Tailscale Serve 在外層出 HTTPS）
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self.actual_port: int = 0
        self.app = create_app(
            pending, fallback, broadcast_callback=None,
            on_startup=self._on_startup,
        )

    def _on_startup(self, loop: asyncio.AbstractEventLoop) -> None:
        """在 uvicorn event loop 內被呼叫：把 loop 注入 registry。

        broadcast_callback 走 registry.broadcast→run_coroutine_threadsafe，
        需要這個 loop 當 schedule target。
        """
        self.app.state.registry.set_loop(loop)

    def start(self) -> None:
        """啟動 uvicorn daemon thread；阻塞到 actual_port 已知或 5s 超時。

        port=0 時 actual_port 是 OS 分配的隨機 port；呼叫端可接著 log 出 URL。
        """
        if self._thread is not None:
            return  # 已啟動（冪等）
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",  # uvicorn 預設 info 太吵；warning 即可
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name="web-ipc"
        )
        self._thread.start()
        # 等 uvicorn bind 完 socket 才能讀 actual_port（lifespan startup 階段
        # servers 還沒建立；這裡 polling 是簡單可靠的解法，< 5s）。
        # `servers` 屬性在 startup() 跑完前不存在，用 getattr 避免 AttributeError。
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            servers = getattr(self._server, "servers", None) or []
            for srv in servers:
                if srv.sockets:
                    self.actual_port = srv.sockets[0].getsockname()[1]
                    break
            if self.actual_port > 0:
                break
            if self._server.should_exit:
                break  # uvicorn 綁失敗（例如 port 被佔）；讓 actual_port 留 0
            time.sleep(0.02)

    def stop(self) -> None:
        """設 should_exit=True，uvicorn 主迴圈下一輪會收掉。"""
        if self._server is not None:
            self._server.should_exit = True

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
