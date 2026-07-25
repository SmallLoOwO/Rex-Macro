"""WebIPC server：FastAPI app + WebSocket endpoint。

WebIPC thread（Task 10 整合進 main.py）跑 uvicorn server；client 連線維護
FallbackState.client_count；命令透過 parse_message 解析後 push 進 PendingReplies。

事件廣播與截圖 push 在 Task 9 加。
"""
import logging
from typing import Callable

import fastapi
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from miningbot.web_protocol import WebMessage, parse_message, serialize_message
from miningbot.web_ipc import PendingReplies, FallbackState


_log = logging.getLogger(__name__)


def create_app(
    pending: PendingReplies,
    fallback: FallbackState,
    broadcast_callback: Callable[[WebMessage], None],
) -> FastAPI:
    """建 FastAPI app。

    broadcast_callback：事件到達時呼叫（WebEventSink 用同一個 callback）。
    本 task 不實作廣播，callback 在 Task 9 才接到 WebSocket 連線池。
    """
    app = FastAPI(title="MiningBot Web IPC")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        fallback.client_connected()
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
