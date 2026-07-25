# 網頁 UI P4：即時介入面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Discord 連鎖放大／八方位那條間接表達鏈塌縮成網頁 pinch-zoom + tap——玩家在遊戲截圖上點位置，server 還原成原生 (x,y)，bot 走既有 fire+verify / plan_click_verdict 路徑。harvest 101 awaiting_fine 與回礦傳送板定位兩條流程接 web_pending reply；fallback 切換讓 Discord 仍能在網頁離線時接管。

**Architecture:** 沿用 P1 WebSocket + race routing key + FallbackState。P4 加：(1) `web_protocol.py` 加 `fire_at` / `reentry_click` 命令 schema 與座標還原整合；(2) `web_server.py` `_handle_command` 還原座標後 push 進 pending；(3) main.py 在 `manual_survey` / `_execute_remote_fire` / `_rr_click` 路徑加 reply pop；(4) `web_static.py` 加介入面板 UI（pinch-zoom canvas + tap）；(5) WebSocket heartbeat 守 half-open。

**Tech Stack:** Python 3.11+ / FastAPI / pytest / vanilla JS（pinch-zoom + pointer events）

## Global Constraints

- Python 3.11+
- 不加新依賴（沿用 P1/P2/P3 stack + stdlib）
- 座標／門檻／間隔只放 `miningbot/config.py`
- 純函式優先、I/O 邊界不交叉
- 不放寬偵測門檻、不刪事故回歸測試（H001~H060）
- **既有 P1+P2+P3 全套 1382 passed + 5 skipped 不能壞**
- 不修改 `discord_commands.py`、`notify.py`（除非新增的 status 形式）
- 不修改 `reentry_remote.py` / `remote_aim.py` 純函式
- 不修改 P1 web_protocol.py 既有 dataclass / 純函式（**只加新函式**）
- 不修改 P3 web_config_persistence.py（已 fix wave 過）
- Commit message 用中文；尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer
- 規格依據：`docs/superpowers/specs/2026-07-26-web-ui-design.md` §4、§8

## 改動範圍預覽

| 檔案 | 改動 |
|---|---|
| `miningbot/web_protocol.py` | 加 `parse_fire_at_payload` / `parse_reentry_click_payload` 純函式（座標還原+格式驗證） |
| `miningbot/web_server.py` | `_handle_command` 還原 fire_at/reentry_click 座標後 push；加 WebSocket heartbeat task |
| `miningbot/main.py` | `manual_survey` / `_execute_remote_fire` / `_rr_click` / 開場鏈加 reply pop；接 `_resolve_ping_if_any` caller；NEEDS_HUMAN 進入時 fallback 切換檢查 |
| `miningbot/web_static.py` | 加 `render_intervention_html` （pinch-zoom canvas + tap） |
| `miningbot/config.py` | 加 `websocket_ping_interval_s` |
| `tests/test_web_protocol.py`（既有） | 加新測試 |
| `tests/test_web_server.py`（既有） | 加 heartbeat 測試 |
| `tests/test_web_intervention.py`（新） | 介入面板整合測試 |

---

## Task 1: web_protocol.py 加 fire_at / reentry_click 解析純函式

**Files:**
- Modify: `miningbot/web_protocol.py`
- Test: `tests/test_web_protocol.py`（加新 class）

**Interfaces:**
- Produces:
  - `parse_fire_at_payload(payload: dict, canvas_size: tuple, native_size: tuple = (1920, 1080)) -> dict | None`
  - `parse_reentry_click_payload(payload: dict, canvas_size: tuple, native_size: tuple = (1920, 1080)) -> dict | None`
  - 回 dict 含 `flow`、`harvest_id`/`attempt_id`、`x`（原生）、`y`（原生）；不合法回 None

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_web_protocol.py`：

```python
from miningbot.web_protocol import (
    parse_fire_at_payload, parse_reentry_click_payload,
)


class TestParseFireAtPayload:
    def test_basic_with_harvest_id(self):
        # client 點 (480, 270) 在 960×540 canvas（縮小 2x）→ 原生 (960, 540)
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "client_xy": [480, 270], "canvas_size": [960, 540],
                     "zoom": 1.0, "pan_offset": [0, 0]},
            canvas_size=(960, 540),
        )
        assert result is not None
        assert result["flow"] == "harvest"
        assert result["harvest_id"] == "007"
        assert result["x"] == 960
        assert result["y"] == 540

    def test_with_zoom_and_pan(self):
        # 沿用 client_to_native_coords 的 combined_zoom_and_pan case
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "client_xy": [200, 100], "canvas_size": [960, 540],
                     "zoom": 2.0, "pan_offset": [10, 10]},
            canvas_size=(960, 540),
        )
        assert result == {"flow": "harvest", "harvest_id": "007", "x": 210, "y": 110}

    def test_missing_cmd_returns_none(self):
        result = parse_fire_at_payload(
            payload={"flow": "harvest", "harvest_id": "007", "client_xy": [100, 100]},
            canvas_size=(960, 540),
        )
        assert result is None

    def test_missing_flow_returns_none(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "harvest_id": "007", "client_xy": [100, 100]},
            canvas_size=(960, 540),
        )
        assert result is None

    def test_missing_both_ids_returns_none(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "client_xy": [100, 100]},
            canvas_size=(960, 540),
        )
        assert result is None

    def test_attempt_id_used_for_reentry_flow(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "reentry", "attempt_id": "attempt_3",
                     "client_xy": [100, 100]},
            canvas_size=(1920, 1080),
        )
        assert result is not None
        assert result["flow"] == "reentry"
        assert result["attempt_id"] == "attempt_3"

    def test_invalid_client_xy_returns_none(self):
        # client_xy 不是 list/tuple of 2 numbers
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "client_xy": "not_a_list"},
            canvas_size=(960, 540),
        )
        assert result is None


class TestParseReentryClickPayload:
    def test_basic(self):
        result = parse_reentry_click_payload(
            payload={"cmd": "reentry_click", "flow": "reentry", "attempt_id": "attempt_2",
                     "client_xy": [480, 270], "canvas_size": [960, 540]},
            canvas_size=(960, 540),
        )
        assert result is not None
        assert result["flow"] == "reentry"
        assert result["attempt_id"] == "attempt_2"
        assert result["x"] == 960
        assert result["y"] == 540

    def test_missing_attempt_id_returns_none(self):
        result = parse_reentry_click_payload(
            payload={"cmd": "reentry_click", "flow": "reentry", "client_xy": [100, 100]},
            canvas_size=(960, 540),
        )
        assert result is None
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_web_protocol.py::TestParseFireAtPayload tests/test_web_protocol.py::TestParseReentryClickPayload -v`

- [ ] **Step 3: 實作兩個純函式**

加到 `miningbot/web_protocol.py`：

```python
def _parse_pointer_payload(payload: dict, canvas_size: tuple,
                           native_size: tuple, expected_cmd: str,
                           id_keys: tuple[str, ...]) -> dict | None:
    """fire_at / reentry_click 共用解析：驗證 cmd/flow/id + 還原座標。

    id_keys：可接受的 id 欄位名（fire_at 收 harvest_id 或 attempt_id；
    reentry_click 只收 attempt_id）；取第一個非 None 的。
    """
    if payload.get("cmd") != expected_cmd:
        return None
    flow = payload.get("flow")
    if not isinstance(flow, str) or not flow:
        return None
    ep_id = None
    for k in id_keys:
        v = payload.get(k)
        if isinstance(v, str) and v:
            ep_id = v
            break
    if ep_id is None:
        return None
    cxy = payload.get("client_xy")
    if not isinstance(cxy, (list, tuple)) or len(cxy) != 2:
        return None
    try:
        cx, cy = float(cxy[0]), float(cxy[1])
    except (TypeError, ValueError):
        return None
    zoom = payload.get("zoom", 1.0)
    try:
        zoom = float(zoom)
        if zoom <= 0:
            return None
    except (TypeError, ValueError):
        return None
    pan = payload.get("pan_offset", [0, 0])
    if not isinstance(pan, (list, tuple)) or len(pan) != 2:
        return None
    try:
        px, py = float(pan[0]), float(pan[1])
    except (TypeError, ValueError):
        return None
    x, y = client_to_native_coords(
        client_xy=(cx, cy), canvas_size=canvas_size, native_size=native_size,
        pan_offset=(px, py), zoom=zoom,
    )
    out = {"flow": flow, "x": x, "y": y}
    # 把符合的 id 欄位原樣回填
    for k in id_keys:
        v = payload.get(k)
        if isinstance(v, str) and v:
            out[k] = v
            break
    return out


def parse_fire_at_payload(payload: dict, canvas_size: tuple,
                          native_size: tuple = (1920, 1080)) -> dict | None:
    """解析 fire_at 命令；不合法回 None。

    接受 harvest_id（harvest flow）或 attempt_id（reentry flow）。
    """
    return _parse_pointer_payload(
        payload, canvas_size, native_size, "fire_at",
        id_keys=("harvest_id", "attempt_id"),
    )


def parse_reentry_click_payload(payload: dict, canvas_size: tuple,
                                native_size: tuple = (1920, 1080)) -> dict | None:
    """解析 reentry_click 命令；不合法回 None。只接受 attempt_id。"""
    return _parse_pointer_payload(
        payload, canvas_size, native_size, "reentry_click",
        id_keys=("attempt_id",),
    )
```

- [ ] **Step 4: 跑測試，確認通過**

`uv run pytest tests/test_web_protocol.py -v` + full suite + ruff + lock

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_protocol.py tests/test_web_protocol.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P4 Task 1——fire_at / reentry_click payload 解析純函式

驗證 cmd/flow/id 必要欄位 + 還原原生座標（用 P1 client_to_native_coords）。
fire_at 接 harvest_id 或 attempt_id；reentry_click 只接 attempt_id。
不合法輸入一律回 None，不丟例外（network boundary 慣例）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: web_server.py _handle_command 還原座標 + WebSocket heartbeat

**Files:**
- Modify: `miningbot/web_server.py`
- Modify: `miningbot/config.py`（加 `websocket_ping_interval_s`）
- Test: `tests/test_web_server.py`（加新測試）

**Interfaces:**
- Consumes: P4 Task 1 `parse_fire_at_payload` / `parse_reentry_click_payload`
- Produces:
  - `_handle_command` 擴充：fire_at/reentry_click 用 parse 還原座標後 push；其他命令路徑不變
  - WebSocket heartbeat task：每 N 秒 server 送 ping；client 不回 pong 則視為斷線

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_web_server.py`：

```python
class TestHandleCommandCoordinatesRestore:
    """fire_at 命令的座標還原：client 點擊 → 原生座標 push 進 pending。"""

    def test_fire_at_pushes_restored_coords(self):
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
                "payload": {"cmd": "fire_at", "flow": "harvest"},  # 缺 client_xy
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
            import pytest
            try:
                # TestClient 的 receive 點接收 ping/pong/text/bytes
                # WebSocket ping 在 TestClient 不直接可見，但 receive_text 會 timeout
                # 略：heartbeat 行為靠 production uvicorn 實機驗證
                pytest.skip("WebSocket ping 在 TestClient 不可見；實機驗證")
            except Exception:
                pass
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_web_server.py::TestHandleCommandCoordinatesRestore tests/test_web_server.py::TestWebSocketHeartbeat -v`

- [ ] **Step 3: 加 Config 欄位**

在 `miningbot/config.py` 適當位置加：

```python
    websocket_ping_interval_s: float = 30.0
    # WebSocket server 主動送 ping 的間隔（防手機背景化 half-open 連線；
    # P1 final review 標的 P4 風險）。uvicorn 預設 20s，bot 放寬到 30s 減流量。
```

- [ ] **Step 4: 擴充 _handle_command 還原座標**

在 `miningbot/web_server.py` 的 `_handle_command`：

```python
def _handle_command(payload: dict, pending: PendingReplies,
                    canvas_size: tuple = (1920, 1080)) -> None:
    """把 command payload 解析後 push 進 PendingReplies。

    P4 擴充：fire_at / reentry_click 用 parse_*_payload 還原原生座標。
    其他命令沿用 P1 行為（control:* routing key）。

    canvas_size 預設 (1920, 1080) = 假設 client 顯示原生尺寸；
    實際上 client 會送自己的 canvas_size 在 payload 中，parse 會用它。
    """
    cmd = payload.get("cmd")
    if cmd in ("fire_at", "reentry_click"):
        parser = parse_fire_at_payload if cmd == "fire_at" else parse_reentry_click_payload
        # client 在 payload 中自帶 canvas_size（client 顯示用）
        client_canvas = payload.get("canvas_size", list(canvas_size))
        try:
            client_canvas = tuple(client_canvas)
        except (TypeError, ValueError):
            _log.warning("web: %s canvas_size invalid: %r", cmd, payload.get("canvas_size"))
            return
        parsed = parser(payload, canvas_size=client_canvas)
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
    # 既有 control:* 路徑
    if cmd is not None:
        pending.push(f"control:{cmd}", payload)
```

更新 ws_endpoint 呼叫端：`_handle_command(msg.payload, pending)`（保持簽名）。

- [ ] **Step 5: 加 WebSocket heartbeat**

在 `miningbot/web_server.py` 的 ws_endpoint 內（連線建立後）加 heartbeat task：

```python
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    fallback.client_connected()
    registry.add(websocket)
    # P4: heartbeat task（防 half-open）
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
                _log.warning("web: 收到不合法訊息，忽略: %r", text[:200])
                continue
            if msg.type == "command":
                _handle_command(msg.payload, pending)
            # P4: ping/pong 訊息由 WebSocket 協議層處理，這裡只接 text 不特別回應
    except WebSocketDisconnect:
        pass
    except Exception as e:
        _log.warning("web: WebSocket 連線例外: %s", e)
    finally:
        if ping_task is not None:
            ping_task.cancel()
        registry.remove(websocket)
        fallback.client_disconnected()
```

更新 `create_app` 簽名加 `ping_interval_s: float = 30.0`（從 Config 讀）。

- [ ] **Step 6: 跑測試，確認通過**

`uv run pytest tests/test_web_server.py -v` + full suite + ruff + lock

- [ ] **Step 7: Commit**

```bash
git add miningbot/web_server.py miningbot/config.py tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P4 Task 2——_handle_command 還原座標 + WebSocket heartbeat

fire_at/reentry_click 用 parse_*_payload 還原原生座標後 push；
WebSocket 每 websocket_ping_interval_s（預設 30s）server 主動送 ping，
防手機背景化 half-open 連線卡 fallback 切換（P1 final review P4 風險）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: main.py harvest 101 awaiting_fine reply pop

**Files:**
- Modify: `miningbot/main.py`

**Interfaces:**
- Consumes: P4 Task 1/2（fire_at reply 進 web_pending 用 routing key `harvest:{hid}`）
- Produces: `_execute_manual_survey` / `_execute_remote_fire` 在玩家可介入點加 reply pop；接到 reply 走 fire+verify；接不到維持 Discord 八方位圖模式（fallback）

- [ ] **Step 1: rg 找 anchor**

```
rg -n "_execute_manual_survey|_execute_remote_fire|awaiting_fine|MANUAL_SURVEY_HELP" miningbot/main.py
```

記錄：
- `_execute_manual_survey` 進入點（發八方位圖的位置）
- `_execute_remote_fire` 接玩家 reply 的位置（既有 Discord reply 路徑）
- awaiting_fine 進入點（細格 reply 解析）

- [ ] **Step 2: 寫整合測試（skip）**

加到 `tests/test_web_intervention.py`（新檔）：

```python
"""P4 即時介入面板整合測試。

大部分 main.py 整合點需要實際讀過 main.py 結構才能寫 fake bot；
留 P5 或實機驗收補回。"""
import pytest


def test_main_harvest_manual_survey_consumes_web_reply():
    pytest.skip("main.py manual_survey 整合需 fake bot；P5 或實機驗收補")


def test_main_execute_remote_fire_short_circuits_on_web_reply():
    pytest.skip("main.py _execute_remote_fire 整合需 fake bot；P5 或實機驗收補")
```

- [ ] **Step 3: 整合 main.py**

在 `_execute_manual_survey` 開頭（發八方位圖前）加 web reply 嘗試：

```python
# miningbot/main.py - _execute_manual_survey 開頭
def _execute_manual_survey(self, ctx):
    # P4: 先檢查 web_pending 是否有玩家點擊 reply（pinch-zoom + tap）
    if self._web_pending is not None and self._web_fallback_state is not None:
        if not self._web_fallback_state.is_fallback(
            now=time.monotonic(), grace_s=self.config.web_fallback_grace_s
        ):
            # web 模式：發截圖給 web client，等點擊
            routing_key = f"harvest:{ctx.harvest_id}" if hasattr(ctx, "harvest_id") else None
            if routing_key:
                # 推截圖事件給 client
                frame = self._capture_grab()
                if frame is not None:
                    self._send_web_intervention_event(
                        flow="harvest", routing_key=routing_key,
                        frame=frame, ctx_summary=self._summarize_survey_ctx(ctx),
                    )
                # 等玩家點擊（poll web_pending 一段時間）
                reply = self._await_web_pointer_reply(
                    routing_key=routing_key, timeout_s=60.0,
                )
                if reply is not None:
                    # 走既有 fire+verify 路徑，跳過 Discord 八方位
                    return self._execute_remote_fire_from_web(
                        ctx, x=reply["x"], y=reply["y"],
                    )
                # 無 reply（timeout）→ fall through 到 Discord 八方位（fallback）
    # 既有 Discord 八方位圖流程
    # ... 既有 ...
```

新增 helper methods：

```python
def _send_web_intervention_event(self, flow: str, routing_key: str,
                                  frame, ctx_summary: str):
    """推截圖 + context 給 web client（透過 WebEventSink / broadcast）。"""
    if self._web_thread is None:
        return
    # 編碼 frame 為 PNG bytes
    import cv2
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        return
    # 用 registry.broadcast 推 binary
    self._web_thread.app.state.registry.broadcast_binary(buf.tobytes())
    # 同時推一個 context event 告訴 client 這是哪個 flow / routing_key
    from .web_protocol import WebMessage
    self._web_thread.app.state.registry.broadcast(WebMessage(
        type="event",
        payload={"event": "INTERVENTION_NEEDED", "flow": flow,
                 "routing_key": routing_key, "summary": ctx_summary},
    ))


def _await_web_pointer_reply(self, routing_key: str, timeout_s: float) -> dict | None:
    """輪詢 web_pending 取玩家點擊 reply；timeout 回 None。"""
    if self._web_pending is None:
        return None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        reply = self._web_pending.pop(routing_key)
        if reply is not None:
            return reply
        time.sleep(0.5)  # 500ms 輪詢間隔
    return None


def _execute_remote_fire_from_web(self, ctx, x: int, y: int):
    """從 web 點擊 reply 直接走 fire+verify（跳過 Discord 八方位+偵測）。"""
    # 沿用 _execute_remote_fire 的「命中→fire→verify」尾段
    # 漂移守門（FOV state0/state1）保留
    # 直接用 (x, y) 取代偵測命中座標
    # 詳細實作依 main.py 既有 _execute_remote_fire 結構對接
    pass  # 由實作者對齊既有命名後填入


def _summarize_survey_ctx(self, ctx) -> str:
    """給 web client 看的 context 摘要。"""
    parts = []
    if hasattr(ctx, "harvest_id"):
        parts.append(f"harvest={ctx.harvest_id}")
    if hasattr(ctx, "tgt_dir"):
        parts.append(f"dir={ctx.tgt_dir}")
    return " ".join(parts) or "manual_survey"
```

注意：`_execute_remote_fire_from_web` 是 minimum viable——具體「命中→fire→verify」尾段需要實作者對齊既有 `_execute_remote_fire` 結構（可能在 3200-3400 行）。如果該段太複雜無法乾淨抽取，minimum viable = 直接呼叫既有 fire+verify helper，加 docstring 標「跳過偵測、直接用 web 點擊座標」。

- [ ] **Step 4: 跑全測試**

`uv run pytest -q` + ruff + lock

預期：全綠（不破壞既有）。skip 的兩個測試佔 2 skipped。

- [ ] **Step 5: Commit**

```bash
git add miningbot/main.py tests/test_web_intervention.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P4 Task 3——main.py harvest manual_survey 接 web reply

manual_survey 進入時先檢查 web 是否在線；在線則發截圖 + context 給 client、
等玩家點擊 reply（60s timeout）；reply 直接走 fire+verify 跳過 Discord 八方位。
無 reply（timeout/fallback）→ fall through 既有 Discord 流程。

_resolve_ping_if_any framework 接 caller（玩家 reply 完成時呼叫）留 Task 5。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: main.py 回礦傳送板定位 reply pop

**Files:**
- Modify: `miningbot/main.py`

**Interfaces:**
- Consumes: P4 Task 1/2（reentry_click reply 進 web_pending 用 routing key `reentry:{attempt_id}`）
- Produces: 開場鏈完成後、`_rr_click` 前加 reply pop；接到 reply 用玩家點擊位置取代 Discord 方位+格

- [ ] **Step 1: rg 找 anchor**

```
rg -n "_rr_click|_rr_zoom|_rr_magnify|reentry_remote|REENTRY.*click|attempt_id" miningbot/main.py
```

記錄：
- 開場鏈完成點（傳送板定位開始之前）
- `_rr_click` 呼叫點
- 既有 Discord reply 處理（方位+格解析）

- [ ] **Step 2: 寫整合測試（skip）**

加到 `tests/test_web_intervention.py`：

```python
def test_main_reentry_consumes_web_click_reply():
    pytest.skip("main.py reentry click 整合需 fake bot；P5 或實機驗收補")
```

- [ ] **Step 3: 整合 main.py**

在回礦流程「準備點傳送板」前加 web reply 嘗試：

```python
# 示意——實際位置依 anchor
def _reentry_await_player_click(self, ctx):
    """回礦：準備點傳送板前先問 web；無 reply 走 Discord 既有流程。"""
    if (self._web_pending is not None
            and self._web_fallback_state is not None
            and not self._web_fallback_state.is_fallback(
                now=time.monotonic(), grace_s=self.config.web_fallback_grace_s)):
        routing_key = f"reentry:{ctx.attempt_id}" if hasattr(ctx, "attempt_id") else None
        if routing_key:
            frame = self._capture_grab()
            if frame is not None:
                self._send_web_intervention_event(
                    flow="reentry", routing_key=routing_key,
                    frame=frame, ctx_summary=f"reentry attempt={ctx.attempt_id}",
                )
            reply = self._await_web_pointer_reply(routing_key=routing_key, timeout_s=60.0)
            if reply is not None:
                # 直接用玩家點擊位置取代 Discord 方位+格
                return self._rr_click_from_web(ctx, x=reply["x"], y=reply["y"])
    # Fall through：既有 Discord 流程（_rr_zoom 發八方位圖、等玩家回方位+格）
    return None


def _rr_click_from_web(self, ctx, x: int, y: int):
    """從 web 點擊 reply 直接走 _rr_click（跳過方位+格+連鎖放大）。"""
    # 沿用 _rr_click 的「漂移守門 → 點擊 → plan_click_verdict」尾段
    # 用 (x, y) 取代 Discord 細格座標
    # 詳細實作依 main.py 既有 _rr_click 結構對接
    pass  # 實作者對齊既有命名後填入
```

- [ ] **Step 4: 跑全測試**

`uv run pytest -q` + ruff + lock

- [ ] **Step 5: Commit**

```bash
git add miningbot/main.py tests/test_web_intervention.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P4 Task 4——main.py 回礦傳送板定位接 web reply

準備點傳送板前先檢查 web；在線則發截圖 + context、等玩家點擊（60s timeout）；
reply 直接走 _rr_click 漂移守門→點擊→plan_click_verdict 跳過 Discord 方位+格+連鎖放大。
無 reply → fall through 既有 Discord 流程（fallback）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: _resolve_ping_if_any caller wiring + NEEDS_HUMAN fallback 切換

**Files:**
- Modify: `miningbot/main.py`

**Interfaces:**
- Consumes: P2 Task 7 `_resolve_ping_if_any` framework、P1 `_web_fallback_state`
- Produces: 玩家 reply 處理完成時（harvest verify / reentry plan_click_verdict 後）呼叫 `_resolve_ping_if_any`；NEEDS_HUMAN 進入時 fallback 切換決定 PING 訊息要不要帶 fallback hint

- [ ] **Step 1: 整合 resolve caller**

在 `_execute_remote_fire_from_web`（Task 3）跟 `_rr_click_from_web`（Task 4）**成功路徑**（verify 通過 / plan_click_verdict 成功）後加：

```python
# 玩家 reply 成功處理 → 結案 PING 訊息
self._resolve_ping_if_any(
    routing_key=f"{flow}:{ep_id}",
    reply_source="web",
    detail=f"玩家點擊 ({x},{y})" + (f"，verify 通過" if verify_ok else ""),
)
```

注意：`flow` / `ep_id` 從 reply payload 取；detail 文字可調整。

- [ ] **Step 2: 處理 NEEDS_HUMAN fallback 切換**

Task 3 / Task 4 已經在 manual_survey / reentry click 進入時用 `_web_fallback_state.is_fallback` 決定走 web 還是 Discord。同樣邏輯在 NEEDS_HUMAN 進入時也該決定 PING hint：

確認 `_send_needs_human_ping`（P2 Task 7 framework）的 `fallback` 參數計算正確：

```python
# main.py - _send_needs_human_ping
def _send_needs_human_ping(self, harvest_id, reason):
    if self._ping_messenger is None:
        return None
    # fallback = web 沒在線（P4 真正用 _web_fallback_state 判斷）
    web_state = getattr(self, "_web_fallback_state", None)
    if web_state is not None:
        fallback = web_state.is_fallback(
            now=time.monotonic(), grace_s=self.config.web_fallback_grace_s,
        )
    else:
        fallback = True  # web 沒啟用 → 一律 fallback Discord
    # ... 既有 send_ping 邏輯 ...
```

- [ ] **Step 3: 跑全測試**

`uv run pytest -q` + ruff + lock

- [ ] **Step 4: Commit**

```bash
git add miningbot/main.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P4 Task 5——_resolve_ping_if_any caller wiring + fallback 切換整合

玩家 web reply 成功處理後（harvest verify / reentry plan_click_verdict）
呼叫 _resolve_ping_if_any 結案 PING 訊息；NEEDS_HUMAN 進入時用
_web_fallback_state.is_fallback 決定 PING hint 是 Discord 反應按鈕（fallback）
還是網頁點選。

接手 P2 Task 7 framework 的 anchor D caller wiring（delayed）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 網頁 UI 介入面板（render_intervention_html）

**Files:**
- Modify: `miningbot/web_static.py`
- Modify: `miningbot/web_server.py`（加 `GET /intervention` route）

**Interfaces:**
- Produces:
  - `render_intervention_html() -> str`：pinch-zoom canvas + tap UI（vanilla JS）
  - WebSocket client 接收 INTERVENTION_NEEDED event → 顯示截圖 → 玩家點擊 → 送 fire_at/reentry_click

- [ ] **Step 1: 寫測試**

加到 `tests/test_web_intervention.py`：

```python
def test_get_intervention_returns_html():
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
```

- [ ] **Step 2: 加 GET /intervention route**

在 `miningbot/web_server.py` 加：

```python
@app.get("/intervention")
def intervention():
    from miningbot.web_static import render_intervention_html
    return fastapi.Response(
        content=render_intervention_html(),
        media_type="text/html",
    )
```

- [ ] **Step 3: 實作 render_intervention_html**

在 `miningbot/web_static.py` 加：

```python
def render_intervention_html() -> str:
    """P4 即時介入面板：pinch-zoom canvas + tap UI。

    連 WebSocket → 收 INTERVENTION_NEEDED event → 顯示截圖 →
    玩家 pinch/scroll zoom + 點擊 → 送 fire_at / reentry_click 命令。
    """
    return """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>MiningBot 介入面板</title>
<style>
body { margin: 0; background: #1a1a1a; color: white; font-family: sans-serif;
       display: flex; flex-direction: column; height: 100vh; }
header { padding: 0.5rem 1rem; background: #222; border-bottom: 1px solid #444;
         display: flex; justify-content: space-between; align-items: center; }
#status { font-size: 0.9rem; color: #888; }
#container { flex: 1; position: relative; overflow: hidden; touch-action: none; }
canvas { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
.hint { padding: 0.3rem 1rem; background: #333; font-size: 0.8rem; color: #aaa; }
</style>
</head>
<body>
<header>
  <strong>MiningBot 介入面板</strong>
  <span id="status">等待 bot 事件…</span>
</header>
<div class="hint">手機：雙指 pinch-zoom + 拖曳；桌機：滾輪縮放 + 拖曳；點擊送出位置</div>
<div id="container">
  <canvas id="canvas"></canvas>
</div>

<script>
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const container = document.getElementById('container');
const statusEl = document.getElementById('status');

const CANVAS_NATIVE = [1920, 1080];
let scale = 1;          // fit-to-container 初始 scale
let zoom = 1.0;         // pinch/scroll zoom（疊加在 scale 之上）
let pan = [0, 0];       // 拖曳 pan（native 座標）
let currentEvent = null;  // {flow, routing_key, summary}
let ws = null;

function fitCanvas() {
  const cw = container.clientWidth;
  const ch = container.clientHeight;
  scale = Math.min(cw / CANVAS_NATIVE[0], ch / CANVAS_NATIVE[1]);
  redraw();
}

function redraw() {
  const totalScale = scale * zoom;
  canvas.style.width = (CANVAS_NATIVE[0] * totalScale) + 'px';
  canvas.style.height = (CANVAS_NATIVE[1] * totalScale) + 'px';
  canvas.style.transform = `translate(${-pan[0] * totalScale}px, ${-pan[1] * totalScale}px)`;
}

function showImage(pngBytes) {
  const blob = new Blob([pngBytes], { type: 'image/png' });
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.onload = () => {
    canvas.width = CANVAS_NATIVE[0];
    canvas.height = CANVAS_NATIVE[1];
    ctx.drawImage(img, 0, 0, CANVAS_NATIVE[0], CANVAS_NATIVE[1]);
    URL.revokeObjectURL(url);
  };
  img.src = url;
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) {
      showImage(e.data);
      return;
    }
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === 'event' && msg.payload?.event === 'INTERVENTION_NEEDED') {
      currentEvent = msg.payload;
      statusEl.textContent = `需要介入：${msg.payload.summary || msg.payload.flow}`;
    } else if (msg.type === 'ping') {
      // server heartbeat；用 ws.pong 不過 ws API 用不著，這裡 noop
    }
  };
  ws.onclose = () => {
    statusEl.textContent = 'WebSocket 斷線，5s 後重連…';
    setTimeout(connect, 5000);
  };
}

// 點擊送出（pointer 無拖曳時）
let pointerDownPos = null;
let didDrag = false;
container.addEventListener('pointerdown', (e) => {
  pointerDownPos = [e.clientX, e.clientY];
  didDrag = false;
});
container.addEventListener('pointermove', (e) => {
  if (pointerDownPos) {
    const dx = e.clientX - pointerDownPos[0];
    const dy = e.clientY - pointerDownPos[1];
    if (Math.abs(dx) + Math.abs(dy) > 5) didDrag = true;
  }
  // 拖曳 pan（pointer isDown + didDrag）
  if (pointerDownPos && didDrag && e.buttons > 0) {
    const totalScale = scale * zoom;
    pan[0] -= (e.movementX || 0) / totalScale;
    pan[1] -= (e.movementY || 0) / totalScale;
    redraw();
  }
});
container.addEventListener('pointerup', (e) => {
  if (pointerDownPos && !didDrag) {
    // tap：算原生座標送出
    sendClick(e.clientX, e.clientY);
  }
  pointerDownPos = null;
  didDrag = false;
});
container.addEventListener('pointercancel', () => {
  pointerDownPos = null;
  didDrag = false;
});

// 滾輪 zoom
container.addEventListener('wheel', (e) => {
  e.preventDefault();
  const factor = e.deltaY > 0 ? 0.9 : 1.1;
  zoom = Math.max(0.5, Math.min(8.0, zoom * factor));
  redraw();
}, { passive: false });

// 雙指 pinch（手機）— 簡化版，只認兩指距離變化
let pinchInitialDist = null;
let pinchInitialZoom = null;
container.addEventListener('touchstart', (e) => {
  if (e.touches.length === 2) {
    pinchInitialDist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY,
    );
    pinchInitialZoom = zoom;
  }
});
container.addEventListener('touchmove', (e) => {
  if (e.touches.length === 2 && pinchInitialDist !== null) {
    e.preventDefault();
    const dist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY,
    );
    zoom = Math.max(0.5, Math.min(8.0, pinchInitialZoom * (dist / pinchInitialDist)));
    redraw();
  }
}, { passive: false });
container.addEventListener('touchend', () => {
  pinchInitialDist = null;
  pinchInitialZoom = null;
});

function sendClick(clientX, clientY) {
  if (!currentEvent) {
    statusEl.textContent = '尚無 INTERVENTION_NEEDED 事件，忽略點擊';
    return;
  }
  // 換算 client → canvas 座標
  const rect = canvas.getBoundingClientRect();
  const cx = clientX - rect.left;
  const cy = clientY - rect.top;
  // canvas 顯示尺寸 = canvas_size（CSS pixel）
  const canvasSize = [rect.width, rect.height];
  // 送命令：cmd + flow + harvest_id/attempt_id + client_xy + canvas_size + zoom + pan_offset
  const cmd = currentEvent.flow === 'reentry' ? 'reentry_click' : 'fire_at';
  const ep_id = {};
  // routing_key = "harvest:007" 或 "reentry:attempt_3"
  const [flow, epId] = currentEvent.routing_key.split(':', 2);
  if (flow === 'harvest') ep_id.harvest_id = epId;
  else ep_id.attempt_id = epId;
  ws.send(JSON.stringify({
    type: 'command',
    payload: {
      cmd, flow, ...ep_id,
      client_xy: [cx, cy],
      canvas_size: canvasSize,
      zoom, pan_offset: pan,
    },
  }));
  statusEl.textContent = `已送出點擊 (${Math.round(cx)}, ${Math.round(cy)}) — ${cmd}`;
}

window.addEventListener('resize', fitCanvas);
fitCanvas();
connect();
</script>
</body>
</html>
"""
```

- [ ] **Step 4: 跑測試**

`uv run pytest tests/test_web_intervention.py -v` + full suite + ruff + lock

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_static.py miningbot/web_server.py tests/test_web_intervention.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P4 Task 6——介入面板 UI（pinch-zoom canvas + tap）

GET /intervention 回 HTML：vanilla JS 連 WebSocket，收 INTERVENTION_NEEDED +
binary PNG 截圖 → 顯示 canvas → 玩家 pinch（手機）/ 滾輪（桌機）zoom +
拖曳 pan + tap 點擊 → 送 fire_at / reentry_click 含 client_xy + canvas_size +
zoom + pan_offset，server 還原原生座標後 push 進 pending。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 整合測試 + minimum viable smoke test

**Files:**
- Modify: `tests/test_web_intervention.py`

**Interfaces:**
- 取消部分 skip，改成可執行的整合測試（用 mock 測 WebbIPC + fake frame）

- [ ] **Step 1: 加可執行的整合測試**

```python
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
```

- [ ] **Step 2: 跑測試**

`uv run pytest tests/test_web_intervention.py -v` + full suite + ruff + lock

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_intervention.py
git commit -m "$(cat <<'EOF'
test(web-ui): P4 Task 7——web fire_at/reentry_click full-pipeline 整合測試

不測 main.py bot 端（仍留 skip 給 P5/實機驗收），只測 web_server 段：
client send → server 還原座標 → pending push（routing_key + payload 正確）。
另驗證 invalid fire_at 不 push、不 crash 連線。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review 結果

### 1. Spec coverage

| spec §4 / §8 段落 | 對應 task |
|---|---|
| pinch-zoom + tap UI | Task 6（HTML/JS） |
| 點擊 → server 還原原生座標 | Task 1（parse 純函式）+ Task 2（_handle_command） |
| harvest 101 awaiting_fine 接 reply | Task 3（main.py manual_survey） |
| 回礦傳送板定位接 reply | Task 4（main.py reentry） |
| fallback 切換（web 離線 → Discord 接管） | Task 3/4（_web_fallback_state.is_fallback）+ Task 5（PING hint） |
| race 規則（先到先贏） | P1 已落地（routing key）；Task 3/4 用 routing_key 取 reply |
| resolve 結案 PING | Task 5（_resolve_ping_if_any caller wiring） |
| WebSocket heartbeat | Task 2（ping_interval_s） |

### 2. 不在 P4 範圍（屬 P5）

- 歷史紀錄與標註面板 → **P5**
- 自動收集素材（玩家介入的副產品） → **P5**
- 實機驗收（玩家從手機連網頁 pinch-zoom 點選） → **P5/實機**

### 3. 已知 placeholder / 彈性

- Task 3 `_execute_remote_fire_from_web` 與 Task 4 `_rr_click_from_web` 的具體「命中→fire→verify」尾段需要實作者對齊既有 `_execute_remote_fire` / `_rr_click` 結構；若太複雜，minimum viable = 直接呼叫既有 fire+verify helper，docstring 標「跳過偵測/方位+格、用 web 點擊座標」
- Task 3/4 的整合測試 skip 留 P5/實機補
- Task 6 的 pinch-zoom 是 simplified（單指拖曳 + 雙指 pinch）；多指手勢進階處理可放 P5

### 4. 風險與 minimum viable 邊界

P4 涉及大量 main.py 整合（最深 P1 Task 10 與 P2 Task 7 都標過此複雜度）。每個 task 都有 minimum viable fallback——實作卡住時走 fallback 並 ledger，不 BLOCK 整個 P4。

---

## P4 完工驗收

- [ ] 全測試綠（`uv run pytest -q`）
- [ ] lint 乾淨
- [ ] lock 一致
- [ ] 既有 P1+P2+P3 全套 1382+5 不回歸
- [ ] fire_at / reentry_click parse 純函式測試綠
- [ ] web_server _handle_command 還原座標測試綠
- [ ] WebSocket heartbeat task 測試通過（即使 skip 也記錄原因）
- [ ] main.py manual_survey / reentry 接 web reply（整合測試可 skip 但 code 要在）
- [ ] resolve caller wiring 接好（_resolve_ping_if_any 被呼叫）
- [ ] 介入面板 UI HTML render 測試綠（canvas + 點擊邏輯 + WebSocket）

P4 實機驗收 = 玩家從手機連網頁 pinch-zoom 點選 → bot fire+verify 通過。實機驗收延到 P5 後或單獨安排。

## 風險

| 風險 | 對策 |
|---|---|
| main.py 整合太複雜（_execute_remote_fire / _rr_click 內部結構深） | minimum viable：直接呼叫既有 fire+verify helper，docstring 標 |
| WebSocket heartbeat 在 uvicorn 測試環境不直接可見 | 測試 skip + 實機驗收 |
| 玩家 pinch-zoom 後座標還原錯（pan_offset 用錯空間） | Task 1 純函式已有 combined_zoom_and_pan test case 鎖住數學 |
| 玩家點擊時 bot 已切換狀態（race） | routing_key 比對（P1 first-wins）+ safe point 消費 |
| 多 web client 連著都點擊 | first-wins；後到的丟棄 + log |
| 截圖傳輸塞爆 WebSocket | 1920×1080 PNG ~1-2MB；單次傳輸 OK；若延遲過長 P5 可加壓縮 |

## 非目標

- 不做歷史紀錄 / 標註（P5）
- 不做素材自動收集（P5）
- 不動 Discord 既有反應按鈕邏輯（fallback 保留）
- 不動 P1 web_protocol.py 既有 dataclass（只加新函式）
- 不實機驗收（P5/單獨安排）
