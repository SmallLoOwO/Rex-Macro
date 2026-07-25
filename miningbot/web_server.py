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
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from miningbot.web_protocol import (
    WebMessage, parse_message, parse_fire_at_payload,
    parse_reentry_click_payload, serialize_message,
)
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
    config=None,
    overrides_path: str | None = None,
    ping_interval_s: float = 30.0,
) -> FastAPI:
    """建 FastAPI app。

    broadcast_callback：事件到達時呼叫（WebEventSink 用同一個 callback）。
        若傳 None，自動接到 registry.broadcast（production 路徑）；測試可注入
        自訂 callback 觀察廣播呼叫。
    on_startup：可選啟動回呼，在 uvicorn lifespan startup 階段（loop 已跑起來）
        被呼叫，傳入當下 event loop。WebIPCThread 用它把 loop 注入 registry，
        讓 broadcast 的 run_coroutine_threadsafe 有 loop 可 schedule。測試不傳。
    config：P3 玩家設定面板用——傳入 Config instance 時掛 `GET/POST /api/config`
        與 `GET /`（HTML）三條 route；不傳則只保留 P1 既有 routes（向下相容）。
    overrides_path：P3 持久化路徑；傳入時啟動讀回套用、POST 寫回。可選。
    ping_interval_s：P4 WebSocket heartbeat 間隔（秒）。> 0 時 ws_endpoint 啟動
        asyncio task 周期性送 `{"type":"ping"}`；client 不回 pong / 斷線時 send_text
        丟例外，task 自然結束。預設 30s（Config.websocket_ping_interval_s）；
        測試可傳 0 關閉、或傳極短值驗證 task 排程。

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

    @app.get("/intervention")
    def intervention():
        """P4 Task 6：介入面板 HTML（pinch-zoom canvas + tap UI）。

        純前端：連 /ws → 收 INTERVENTION_NEEDED event + binary PNG → 顯示 →
        玩家 pinch/scroll zoom + tap → 送 fire_at / reentry_click。
        不需 Config；unconditional mount（手機開瀏覽器直接連 URL）。
        """
        from miningbot.web_static import render_intervention_html
        return Response(
            content=render_intervention_html(),
            media_type="text/html",
        )

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        fallback.client_connected()
        registry.add(websocket)
        # P4: heartbeat task（防 half-open；spec §8）
        # 手機背景化／Tailscale 重連可能讓 TCP 半開著但 client 已不可達；
        # server 每 ping_interval_s 秒主動送一則 {"type":"ping"}，send_text 丟例外
        # 即視為斷線——task 自己結束，外層 receive_text 也會跟著 WebSocketDisconnect。
        ping_task = None
        if ping_interval_s > 0:
            async def _send_pings():
                try:
                    while True:
                        await asyncio.sleep(ping_interval_s)
                        try:
                            await websocket.send_text('{"type":"ping"}')
                        except Exception:
                            return  # 連線斷了
                except asyncio.CancelledError:
                    return
            ping_task = asyncio.create_task(_send_pings())
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
                # P4: ping/pong 訊息由 WebSocket 協議層處理，這裡只接 text 不特別回應
                # event type 由 server 發、client 收；client 不該送 event，忽略
        except WebSocketDisconnect:
            pass
        except Exception as e:
            _log.warning("web: WebSocket 連線例外: %s", e)
        finally:
            if ping_task is not None:
                ping_task.cancel()
            registry.remove(websocket)
            fallback.client_disconnected()

    # P3: 玩家設定面板 endpoints（僅在傳入 config 時掛上；既有呼叫端不受影響）
    if config is not None:
        from miningbot.web_config_whitelist import (
            is_web_configurable, validate_value, WEB_CONFIGURABLE_FIELDS,
        )
        from miningbot.web_config_persistence import (
            load_overrides, save_overrides, apply_overrides_to_config,
        )

        # 啟動時讀 overrides 套用（building blocks；main.py Task 4 也會做一次冪等）
        # 不快取 in-memory overrides——save_overrides 會重讀檔，避免 HTTP/WS 兩條路徑
        # 各自維護 cache 導致相互覆寫（P3 final-review Important 1）。
        if overrides_path:
            initial_overrides = load_overrides(overrides_path)
            apply_overrides_to_config(config, initial_overrides)
            app.state.overrides_path = overrides_path
        else:
            app.state.overrides_path = None

        @app.get("/api/config")
        def get_config():
            """回白名單 4 欄現值（不洩漏門檻/ROI/機密）。"""
            return {f: getattr(config, f) for f in WEB_CONFIGURABLE_FIELDS}

        @app.post("/api/config")
        def post_config(payload: dict):
            """驗證 → runtime 改 Config → 持久化 overrides JSON。

            三道閘：缺欄位 400、非白名單 400、值不通過 validate_value 400。
            """
            field = payload.get("field")
            value = payload.get("value")
            if field is None or value is None:
                return _err(400, "missing field or value")
            if not is_web_configurable(field):
                return _err(400, f"field not web-configurable: {field}")
            if not validate_value(field, value):
                return _err(400, f"invalid value for {field}: {value!r}")
            # runtime 即時生效
            setattr(config, field, value)
            # 持久化（若有指定路徑）——不帶 current_overrides，save_overrides 自會重讀檔
            if app.state.overrides_path:
                save_overrides(app.state.overrides_path, field, value)
            return {"ok": True, "field": field, "value": value}

        @app.get("/")
        def root():
            """玩家設定面板 HTML（Task 3 補完整內容）。"""
            from miningbot.web_static import render_index_html
            return Response(
                content=render_index_html(config),
                media_type="text/html",
            )

    return app


def _err(status: int, reason: str) -> JSONResponse:
    """統一 JSON 錯誤回應（HTTP 狀態碼 + reason）。"""
    return JSONResponse(status_code=status, content={"error": reason})


def _handle_command(payload: dict, pending: PendingReplies) -> None:
    """把 command payload 解析後 push 進 PendingReplies。

    P5 Task 1 協議重設：fire_at / reentry_click 改走 thin validator，
    client 端 JS 自己換算原生座標；server 不再收 canvas_size/zoom/pan_offset。
    其他命令沿用 P1 行為（control:* routing key）。

    payload 結構：
    - fire_at / reentry_click：必有 flow + harvest_id（或 attempt_id）+ x + y
      （P5 Task 1 schema；x/y 是 int 範圍 [0, 1920) / [0, 1080)）
    - config_set：必有 field + value（白名單驗證在 main.py 整合時做）
    - pause / resume / request_frame：控制類，無 routing key，用 "control:*"

    若 payload 缺 routing key 必要欄位或 parse 失敗，記 log 不 push（防護）。
    """
    cmd = payload.get("cmd")
    if cmd in ("fire_at", "reentry_click"):
        parser = parse_fire_at_payload if cmd == "fire_at" else parse_reentry_click_payload
        parsed = parser(payload)
        if parsed is None:
            _log.warning("web: %s payload invalid: %r", cmd, payload)
            return
        flow = parsed["flow"]
        ep_id = parsed.get("harvest_id") or parsed.get("attempt_id")
        if not flow or not ep_id:
            _log.warning("web: %s 缺 flow/episode_id", cmd)
            return
        key = f"{flow}:{ep_id}"
        pending.push(key, parsed)
        return
    # 既有 control:* 路徑（pause / resume / config_set / request_frame 等）
    if cmd is not None:
        pending.push(f"control:{cmd}", payload)


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
        config=None,
        overrides_path: str | None = None,
    ):
        self.pending = pending
        self.fallback = fallback
        self.port = port
        self.host = host  # 綁 127.0.0.1（spec §2：Tailscale Serve 在外層出 HTTPS）
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self.actual_port: int = 0
        # P4: 從 Config 讀 WebSocket heartbeat 間隔；未傳 config 走 create_app 預設 30s。
        ping_interval_s = (
            getattr(config, "websocket_ping_interval_s", 30.0)
            if config is not None else 30.0
        )
        # P3：config + overrides_path 傳給 create_app，讓 HTTP endpoints
        # （GET/POST /api/config、GET /）能在 thread 內掛上。不傳時向下相容（P1 既有測試）。
        self.app = create_app(
            pending, fallback, broadcast_callback=None,
            on_startup=self._on_startup,
            config=config, overrides_path=overrides_path,
            ping_interval_s=ping_interval_s,
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
        # 5s 超時仍無 actual_port：uvicorn 可能還在 init 或 bind 失敗（且沒有自己
        # 設 should_exit）。silent return 會讓呼叫端 log 出 http://127.0.0.1:0
        # 看似成功；這裡顯式警告＋請求 thread 退出，避免 daemon 殘留與假啟動訊息。
        if self.actual_port == 0:
            _log.warning(
                "WebIPC server 5s 內未 bind socket；uvicorn 可能還在 init 或綁失敗"
                "（should_exit=%s）——已請求 thread 退出，actual_port 留 0",
                self._server.should_exit,
            )
            self._server.should_exit = True

    def stop(self) -> None:
        """設 should_exit=True，uvicorn 主迴圈下一輪會收掉。"""
        if self._server is not None:
            self._server.should_exit = True

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
