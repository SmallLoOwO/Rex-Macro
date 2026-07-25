"""P4 即時介入面板整合測試。

web_pending → main.py 整合點（manual_survey / reentry click）需要 fake bot 與
大量 monkeypatch 才能有意義地跑；本檔先放 skip skeleton，留 P5 或實機驗收補回。

會被執行的 web pipeline 整合測試（不靠 main.py）放 Task 7 補上。
"""
import logging
import types

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
    """完整 pipeline：client 送 fire_at（已含原生 x/y）→ server 驗證 → pending push。

    P5 Task 1：座標空間協議重設——client 端 JS 自己用 canvas.width/rect.width
    換算成原生座標，server 只做 thin validator；不再送 client_xy/canvas_size/zoom/pan。
    """
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
                        "x": 960, "y": 540},
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
                        "x": 100, "y": 100},
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
            "payload": {"cmd": "fire_at", "flow": "harvest"},  # 缺 id / x / y
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


# ---------------------------------------------------------------------------
# P5 Task 2：_reentry_await_player_click verdict retry + INTERVENTION_RESULT
# ---------------------------------------------------------------------------


class _FakeWebFallback:
    """is_fallback 永遠回 False（web 在線）。"""

    def is_fallback(self, now, grace_s):
        return False


class _FakeRegistry:
    """記錄所有 broadcast / broadcast_binary 呼叫以供斷言。"""

    def __init__(self):
        self.calls = []

    def broadcast(self, msg):
        self.calls.append(msg)

    def broadcast_binary(self, data):
        pass


class _FakeWebThread:
    """最低限度模擬 WebIPCThread.app.state.registry。"""

    def __init__(self):
        self.app = types.SimpleNamespace()
        self.app.state = types.SimpleNamespace()
        self.app.state.registry = _FakeRegistry()


class _FakeCtx:
    episode_id = "test_ep"


def _build_stub_bot_for_reentry(monkeypatch):
    """組一個僅含 _reentry_await_player_click 依賴的 stub bot。"""
    import miningbot.main as main_mod
    from miningbot.main import Bot

    class _StubBot:
        pass

    bot = _StubBot()
    bot._web_fallback = _FakeWebFallback()
    bot._web_pending = object()  # truthy：代表 web 在線
    bot._web_thread = _FakeWebThread()
    bot.log_discord = logging.getLogger("test_rr_intervention")

    # _reentry_await_player_click 的協作物件
    bot._focus_roblox = lambda: True
    # capture.grab 在主迴圈 thread 上跑，monkeypatch module attr 即可
    monkeypatch.setattr(main_mod.capture, "grab", lambda: object())
    sent = []
    bot._send_web_intervention_event = lambda **kw: sent.append(kw)
    bot._sent_intervention_events = sent

    # 把真實 method 綁到 stub
    bot._reentry_await_player_click = types.MethodType(
        Bot._reentry_await_player_click, bot)
    bot._broadcast_intervention_result = types.MethodType(
        Bot._broadcast_intervention_result, bot)
    return bot


def test_reentry_await_player_click_broadcasts_intervention_result_on_non_descended(monkeypatch):
    """P5 Task 2: 非 descended verdict 時廣播 INTERVENTION_RESULT 給 web client。

    模擬三次 _rr_click_from_web 都回 still_surface：
    - 前兩次：廣播 INTERVENTION_RESULT（verdict=still_surface）並 retry
    - 第三次：廣播 INTERVENTION_RESULT（verdict=放棄）並 return True
    """
    from miningbot.web_protocol import WebMessage

    bot = _build_stub_bot_for_reentry(monkeypatch)

    replies = iter([{"x": 100, "y": 100},
                    {"x": 200, "y": 200},
                    {"x": 300, "y": 300}])
    bot._await_web_pointer_reply = lambda routing_key, timeout_s: next(replies)
    # 三次都非 descended
    bot._rr_click_from_web = lambda ctx, x, y: "still_surface"

    result = bot._reentry_await_player_click(_FakeCtx())

    assert result is True  # 三次失敗仍 return True（跳過 Discord sweep）
    calls = bot._web_thread.app.state.registry.calls
    results = [c for c in calls
               if isinstance(c, WebMessage)
               and c.payload.get("event") == "INTERVENTION_RESULT"]
    assert len(results) >= 2, (
        f"應該至少廣播兩次 INTERVENTION_RESULT（每次 retry 前＋最終放棄），"
        f"實際：{[c.payload for c in calls if isinstance(c, WebMessage)]}")
    verdicts = [r.payload["verdict"] for r in results]
    assert "still_surface" in verdicts
    assert "放棄" in verdicts
    # summary 含玩家可行動資訊
    summaries = [r.payload.get("summary", "") for r in results]
    assert any("重骰" in s or "跳過" in s for s in summaries), (
        f"INTERVENTION_RESULT summary 應提示玩家可用 `重骰`／`跳過`，實際：{summaries}")


def test_reentry_await_player_click_retries_until_descended(monkeypatch):
    """P5 Task 2: 第一次 still_surface → 廣播 INTERVENTION_RESULT → retry → descended。"""
    from miningbot.web_protocol import WebMessage

    bot = _build_stub_bot_for_reentry(monkeypatch)

    replies = iter([{"x": 100, "y": 100}, {"x": 200, "y": 200}])
    bot._await_web_pointer_reply = lambda routing_key, timeout_s: next(replies)
    verdicts = iter(["still_surface", "descended"])
    bot._rr_click_from_web = lambda ctx, x, y: next(verdicts)

    result = bot._reentry_await_player_click(_FakeCtx())

    assert result is True  # descended 從 caller 角度仍是「web 已處理」
    calls = bot._web_thread.app.state.registry.calls
    results = [c for c in calls
               if isinstance(c, WebMessage)
               and c.payload.get("event") == "INTERVENTION_RESULT"]
    # descended 之前應該剛好一次 INTERVENTION_RESULT（still_surface 那次）
    assert len(results) == 1, f"應只廣播 1 次（descended 後不再 retry），實際：{len(results)}"
    assert results[0].payload["verdict"] == "still_surface"
    # 應該重新 grab + 重發 INTERVENTION_NEEDED
    assert len(bot._sent_intervention_events) >= 2, (
        f"retry 前應重發 INTERVENTION_NEEDED，實際 send 次數："
        f"{len(bot._sent_intervention_events)}")


def test_reentry_await_player_click_timeout_returns_false(monkeypatch):
    """P5 Task 2: reply timeout 時 fall through Discord（return False），不廣播放棄。"""
    bot = _build_stub_bot_for_reentry(monkeypatch)
    bot._await_web_pointer_reply = lambda routing_key, timeout_s: None

    result = bot._reentry_await_player_click(_FakeCtx())

    assert result is False
    calls = bot._web_thread.app.state.registry.calls
    results = [c for c in calls
               if hasattr(c, "payload") and c.payload.get("event") == "INTERVENTION_RESULT"]
    assert len(results) == 0, "timeout 不該廣播 INTERVENTION_RESULT"
