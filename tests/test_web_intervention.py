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


# ---------------------------------------------------------------------------
# P5 Task 3：frame-grab race——reply race sanity-check（_mine_resetting）
# ---------------------------------------------------------------------------


class _FakeHarvestCtx:
    """harvest 路徑的 ctx：只需要 harvest_id（_execute_remote_fire_from_web 用）。"""
    harvest_id = "test_harvest"


def _build_stub_bot_for_intervention():
    """組一個僅含 _broadcast_intervention_result / _resolve_ping_if_any 依賴的 stub bot。

    與 _build_stub_bot_for_reentry 不同：不綁 _reentry_await_player_click，只測試
    _execute_remote_fire_from_web / _rr_click_from_web 的 reply-race sanity-check。
    """
    import types
    from miningbot.main import Bot

    class _StubBot:
        pass

    bot = _StubBot()
    bot._web_thread = _FakeWebThread()
    bot.log_discord = logging.getLogger("test_intervention_race")
    bot.logger = logging.getLogger("test_intervention_race")
    # _resolve_ping_if_any no-op：測試不關心 PING 結案，但函式會呼叫它
    bot._ping_messenger = None
    # 把真實 method 綁到 stub——測試目標本身（_execute_remote_fire_from_web /
    # _rr_click_from_web / _broadcast_intervention_result / _resolve_ping_if_any）
    bot._execute_remote_fire_from_web = types.MethodType(
        Bot._execute_remote_fire_from_web, bot)
    bot._rr_click_from_web = types.MethodType(
        Bot._rr_click_from_web, bot)
    bot._broadcast_intervention_result = types.MethodType(
        Bot._broadcast_intervention_result, bot)
    bot._resolve_ping_if_any = types.MethodType(
        Bot._resolve_ping_if_any, bot)
    return bot


def test_execute_remote_fire_from_web_rejects_when_mine_resetting():
    """P5 Task 3: _execute_remote_fire_from_web 在 _mine_resetting=True 時應該：
    1. 不呼叫 _wait_for_d3_cooldown／_focus_roblox／_aim_fire_and_verify（不消耗 D3、不搶焦點）
    2. 廣播 INTERVENTION_RESULT（flow=harvest, verdict=rejected_reset）
    3. 回 (False, "礦坑重置中")
    """
    from miningbot.web_protocol import WebMessage

    bot = _build_stub_bot_for_intervention()
    bot._mine_resetting = True

    # 這些都不該被呼叫——設成會 raise 的 sentinel
    def _fail(*args, **kwargs):
        raise AssertionError("不該呼叫——_mine_resetting 應在這些之前 short-circuit")
    bot._wait_for_d3_cooldown = _fail
    bot._focus_roblox = _fail
    bot._aim_fire_and_verify = _fail

    ok, detail = bot._execute_remote_fire_from_web(_FakeHarvestCtx(), x=960, y=540)

    assert ok is False
    assert detail == "礦坑重置中"
    calls = bot._web_thread.app.state.registry.calls
    results = [c for c in calls
               if isinstance(c, WebMessage)
               and c.payload.get("event") == "INTERVENTION_RESULT"]
    assert len(results) == 1, (
        f"應廣播 1 次 INTERVENTION_RESULT，實際："
        f"{[c.payload for c in calls if isinstance(c, WebMessage)]}")
    payload = results[0].payload
    assert payload["flow"] == "harvest"
    assert payload["verdict"] == "rejected_reset"
    assert "重骰" in payload["summary"] or "跳過" in payload["summary"]


def test_rr_click_from_web_rejects_when_mine_resetting():
    """P5 Task 3: _rr_click_from_web 在 _mine_resetting=True 時應該：
    1. 不呼叫 _focus_roblox／_rr_click_and_verify／_rr_notify（short-circuit 在 cv2 import 前）
    2. 廣播 INTERVENTION_RESULT（flow=reentry, verdict=rejected_reset）
    3. 回 None（caller 視為不可 retry 的硬失敗）
    """
    from miningbot.web_protocol import WebMessage

    bot = _build_stub_bot_for_intervention()
    bot._mine_resetting = True

    def _fail(*args, **kwargs):
        raise AssertionError("不該呼叫——_mine_resetting 應在這些之前 short-circuit")
    # 函式內 `import cv2` 在 short-circuit 之後，不會觸及；只設下游协作sentinel
    bot._focus_roblox = _fail
    bot._rr_click_and_verify = _fail
    bot._rr_notify = _fail
    bot._rr_snap_dir = _fail

    verdict = bot._rr_click_from_web(_FakeCtx(), x=100, y=100)

    assert verdict is None
    calls = bot._web_thread.app.state.registry.calls
    results = [c for c in calls
               if isinstance(c, WebMessage)
               and c.payload.get("event") == "INTERVENTION_RESULT"]
    assert len(results) == 1, (
        f"應廣播 1 次 INTERVENTION_RESULT，實際："
        f"{[c.payload for c in calls if isinstance(c, WebMessage)]}")
    payload = results[0].payload
    assert payload["flow"] == "reentry"
    assert payload["verdict"] == "rejected_reset"
    assert "重骰" in payload["summary"] or "跳過" in payload["summary"]


# ---------------------------------------------------------------------------
# P5 Task 5：_save_auto_fixture（玩家 web 介入副產品——自動收集素材）
# spec §5：verify 通過 = 真框確認（symptom=null 對照組）；verify 失敗 symptom="unknown"
# PNG 經 cv2.imencode + numpy.tofile（CJK path safety）；JSON 經 tempfile + os.replace 原子寫
# best-effort：I/O 失敗只 log warning，不 raise
# ---------------------------------------------------------------------------


def _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path):
    """stub bot 僅含 _save_auto_fixture 依賴；_AUTO_FIXTURE_ROOT 改寫到 tmp_path。"""
    import miningbot.main as main_mod
    from miningbot.main import Bot

    monkeypatch.setattr(main_mod, "_AUTO_FIXTURE_ROOT", str(tmp_path))

    class _StubBot:
        pass

    bot = _StubBot()
    bot.logger = logging.getLogger("test_auto_fixture")
    bot.log_discord = logging.getLogger("test_auto_fixture")
    bot._save_auto_fixture = types.MethodType(Bot._save_auto_fixture, bot)
    return bot


def _zeros(h=270, w=320):
    import numpy as np
    return np.zeros((h, w, 3), dtype=np.uint8)


class TestSaveAutoFixtureHarvest:
    """harvest flow：cell_crop + (cx, cy) 寫入 tests/fixtures/aim/。"""

    def test_success_writes_png_and_json_with_expected_schema(self, monkeypatch, tmp_path):
        """verify_ok=True → auto_<id>_success.{png,json}；symptom=null（對照組）。"""
        import cv2
        import json
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        cell_crop = _zeros(270, 320)

        bot._save_auto_fixture(
            flow="harvest", episode_id="007", frame=_zeros(1080, 1920),
            cell_crop=cell_crop, annotation_xy=(160, 135), verify_ok=True)

        aim_dir = tmp_path / "aim"
        png_path = aim_dir / "auto_007_success.png"
        json_path = aim_dir / "auto_007_success.json"
        assert png_path.exists(), f"PNG 未寫入：{png_path}"
        assert json_path.exists(), f"JSON 未寫入：{json_path}"
        # PNG 經 imencode + tofile；可用 cv2.imread 讀回且尺寸正確
        img = cv2.imread(str(png_path))
        assert img is not None, "PNG 無法 decode"
        assert img.shape[:2] == (270, 320), f"PNG shape 不對：{img.shape}"
        # JSON schema（spec §5）
        ann = json.loads(json_path.read_text(encoding="utf-8"))
        assert ann["image"] == "auto_007_success.png"
        assert ann["annotation"] == {
            "type": "square", "cx": 160, "cy": 135, "size": 50}
        assert ann["tier"] is None
        assert ann["variant"] is None
        assert ann["mineral"] is None
        assert ann["source"]["kind"] == "auto"
        assert ann["source"]["harvest_id"] == "007"
        assert ann["source"]["episode_result"] == "success"
        assert ann["source"]["verify"] == "passed"
        assert "timestamp" in ann["source"]
        assert ann["symptom"] is None
        assert ann["related_incident"] is None

    def test_fail_writes_unknown_symptom_and_failed_verify(self, monkeypatch, tmp_path):
        """verify_ok=False → auto_<id>_fail.{png,json}；symptom=unknown / verify=failed。"""
        import json
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)

        bot._save_auto_fixture(
            flow="harvest", episode_id="042", frame=_zeros(1080, 1920),
            cell_crop=_zeros(270, 320), annotation_xy=(100, 100),
            verify_ok=False)

        ann = json.loads(
            (tmp_path / "aim" / "auto_042_fail.json").read_text(encoding="utf-8"))
        assert ann["source"]["episode_result"] == "fail"
        assert ann["source"]["verify"] == "failed"
        assert ann["symptom"] == "unknown"

    def test_tier_variant_mineral_passed_through(self, monkeypatch, tmp_path):
        """可選 tier/variant/mineral 進得了 source JSON。"""
        import json
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)

        bot._save_auto_fixture(
            flow="harvest", episode_id="009", frame=_zeros(1080, 1920),
            cell_crop=_zeros(270, 320), annotation_xy=(100, 100),
            verify_ok=True, tier="Mythic", variant="Spectral", mineral="Tin")

        ann = json.loads(
            (tmp_path / "aim" / "auto_009_success.json").read_text(encoding="utf-8"))
        assert ann["tier"] == "Mythic"
        assert ann["variant"] == "Spectral"
        assert ann["mineral"] == "Tin"

    def test_json_atomic_write_no_tmp_residue(self, monkeypatch, tmp_path):
        """JSON 經 tempfile + os.replace；完成後 .tmp 不該殘留。"""
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        bot._save_auto_fixture(
            flow="harvest", episode_id="007", frame=_zeros(1080, 1920),
            cell_crop=_zeros(270, 320), annotation_xy=(160, 135), verify_ok=True)
        assert not (tmp_path / "aim" / "auto_007_success.json.tmp").exists()


class TestSaveAutoFixtureReentry:
    """reentry flow：frame + tap 座標 寫入 tests/fixtures/reentry/teleport_board/。"""

    def test_descended_writes_success_files(self, monkeypatch, tmp_path):
        """verify_ok=True（descended）→ auto_<ep>_success.{png,json}，verify=descended。"""
        import cv2
        import json
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        frame = _zeros(1080, 1920)

        bot._save_auto_fixture(
            flow="reentry", episode_id="5", frame=frame, cell_crop=None,
            annotation_xy=(960, 540), verify_ok=True)

        d = tmp_path / "reentry" / "teleport_board"
        png_path = d / "auto_5_success.png"
        json_path = d / "auto_5_success.json"
        assert png_path.exists()
        assert json_path.exists()
        # PNG = frame（全幀），不像 harvest 用 cell_crop
        img = cv2.imread(str(png_path))
        assert img is not None
        assert img.shape[:2] == (1080, 1920)
        ann = json.loads(json_path.read_text(encoding="utf-8"))
        assert ann["source"]["kind"] == "auto"
        # reentry 用 episode_id（不是 harvest_id）
        assert ann["source"]["episode_id"] == "5"
        assert ann["source"]["episode_result"] == "success"
        assert ann["source"]["verify"] == "descended"
        # annotation.cx/cy = tap 座標（全幀座標）
        assert ann["annotation"]["cx"] == 960
        assert ann["annotation"]["cy"] == 540
        assert ann["symptom"] is None

    def test_non_descended_writes_fail_files(self, monkeypatch, tmp_path):
        """verify_ok=False（still_surface/no_change/...）→ auto_<ep>_fail.{png,json}。"""
        import json
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        bot._save_auto_fixture(
            flow="reentry", episode_id="5", frame=_zeros(1080, 1920),
            cell_crop=None, annotation_xy=(960, 540), verify_ok=False)
        d = tmp_path / "reentry" / "teleport_board"
        ann = json.loads((d / "auto_5_fail.json").read_text(encoding="utf-8"))
        assert ann["source"]["verify"] == "failed"
        assert ann["symptom"] == "unknown"


class TestSaveAutoFixtureBestEffort:
    """best-effort：所有失敗路徑只 log warning，不 raise。"""

    def test_imencode_failure_logs_and_does_not_raise(self, monkeypatch, tmp_path, caplog):
        """cv2.imencode 回 (False, ...) → log warning，不 raise，不寫 JSON。"""
        import cv2
        import numpy as np
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        monkeypatch.setattr(cv2, "imencode", lambda *a, **kw: (False, None))

        with caplog.at_level(logging.WARNING, logger="test_auto_fixture"):
            bot._save_auto_fixture(
                flow="harvest", episode_id="007", frame=_zeros(1080, 1920),
                cell_crop=_zeros(270, 320), annotation_xy=(160, 135), verify_ok=True)

        assert not (tmp_path / "aim" / "auto_007_success.json").exists()
        assert any("imencode" in r.getMessage() for r in caplog.records), (
            f"應 log imencode 失敗；實際：{[r.getMessage() for r in caplog.records]}")

    def test_harvest_with_none_cell_crop_skips_silently(self, monkeypatch, tmp_path):
        """cell_crop=None（harvest flow）→ skip，不寫檔，不 raise。"""
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        bot._save_auto_fixture(
            flow="harvest", episode_id="007", frame=_zeros(1080, 1920),
            cell_crop=None, annotation_xy=(160, 135), verify_ok=True)
        # 沒寫任何東西
        assert not (tmp_path / "aim").exists() or not any(
            (tmp_path / "aim").iterdir())

    def test_reentry_with_none_frame_skips_silently(self, monkeypatch, tmp_path):
        """frame=None（reentry flow）→ skip，不寫檔，不 raise。"""
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        bot._save_auto_fixture(
            flow="reentry", episode_id="5", frame=None, cell_crop=None,
            annotation_xy=(960, 540), verify_ok=True)
        assert not (tmp_path / "reentry").exists() or not any(
            (tmp_path / "reentry").rglob("auto_5_*"))

    def test_unknown_flow_skips_silently(self, monkeypatch, tmp_path):
        """flow 不在 {harvest, reentry} → skip，不 raise。"""
        bot = _build_stub_bot_for_auto_fixture(monkeypatch, tmp_path)
        bot._save_auto_fixture(
            flow="garbage", episode_id="x", frame=None, cell_crop=None,
            annotation_xy=(0, 0), verify_ok=True)
        # 沒任何東西
        assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# 整合：_execute_remote_fire_from_web / _rr_click_from_web 內接線
# 用 stub + mocked _save_auto_fixture 驗證 caller 確實呼叫 helper（args 符合 API contract）
# ---------------------------------------------------------------------------


class _FakeHarvestCtxWithPose:
    harvest_id = "007"
    pose_net_rotations = 0
    pose_pitch_layer = "mid"


def test_execute_remote_fire_from_web_calls_save_auto_fixture_on_success(monkeypatch):
    """verify 通過後應呼叫 _save_auto_fixture（flow=harvest, verify_ok=True）。"""
    import numpy as np
    import miningbot.main as main_mod
    from miningbot.main import Bot

    class _StubBot:
        pass

    bot = _StubBot()
    bot._web_thread = None
    bot.logger = logging.getLogger("test_wiring")
    bot.log_discord = logging.getLogger("test_wiring")
    bot._ping_messenger = None
    bot._mine_resetting = False
    bot._wait_for_d3_cooldown = lambda deadline: (True, "")
    bot._focus_roblox = lambda: True
    bot._aim_fire_and_verify = lambda *a, **kw: (True, "confirmed")
    fake_frame = np.zeros((1080, 1920, 3), np.uint8)
    monkeypatch.setattr(main_mod.capture, "grab", lambda: fake_frame)
    monkeypatch.setattr(main_mod.capture, "crop", lambda f, r: f)

    save_calls = []
    bot._save_auto_fixture = lambda **kw: save_calls.append(kw)

    bot._execute_remote_fire_from_web = types.MethodType(
        Bot._execute_remote_fire_from_web, bot)
    bot._resolve_ping_if_any = types.MethodType(
        Bot._resolve_ping_if_any, bot)
    # 2026-07-26：開火結果現在會推 INTERVENTION_RESULT 回 web client；
    # 本測試 _web_thread=None → 該方法 no-op，但仍需綁上去才不會 AttributeError。
    bot._broadcast_intervention_result = types.MethodType(
        Bot._broadcast_intervention_result, bot)

    ok, _ = bot._execute_remote_fire_from_web(
        _FakeHarvestCtxWithPose(), x=960, y=540)

    assert ok is True
    assert len(save_calls) == 1, (
        f"應呼叫 _save_auto_fixture 一次，實際：{len(save_calls)}")
    sc = save_calls[0]
    assert sc["flow"] == "harvest"
    assert sc["episode_id"] == "007"
    assert sc["verify_ok"] is True
    # cell_crop 不為 None（harvest flow 一定要帶 crop）
    assert sc["cell_crop"] is not None
    # annotation_xy 是 cell_crop local 座標——tap (960,540) 在 320x270 crop 內
    assert sc["annotation_xy"] == (160, 135), (
        f"annotation_xy 應為 (160, 135)，實際：{sc['annotation_xy']}")


def test_execute_remote_fire_from_web_calls_save_auto_fixture_on_failure(monkeypatch):
    """verify 失敗也應呼叫 _save_auto_fixture（verify_ok=False），寫 fail 素材。"""
    import numpy as np
    import miningbot.main as main_mod
    from miningbot.main import Bot

    class _StubBot:
        pass

    bot = _StubBot()
    bot._web_thread = None
    bot.logger = logging.getLogger("test_wiring")
    bot.log_discord = logging.getLogger("test_wiring")
    bot._ping_messenger = None
    bot._mine_resetting = False
    bot._wait_for_d3_cooldown = lambda deadline: (True, "")
    bot._focus_roblox = lambda: True
    bot._aim_fire_and_verify = lambda *a, **kw: (False, "verify 窗口內聊天未確認")
    fake_frame = np.zeros((1080, 1920, 3), np.uint8)
    monkeypatch.setattr(main_mod.capture, "grab", lambda: fake_frame)
    monkeypatch.setattr(main_mod.capture, "crop", lambda f, r: f)

    save_calls = []
    bot._save_auto_fixture = lambda **kw: save_calls.append(kw)

    bot._execute_remote_fire_from_web = types.MethodType(
        Bot._execute_remote_fire_from_web, bot)
    bot._resolve_ping_if_any = types.MethodType(
        Bot._resolve_ping_if_any, bot)
    # 2026-07-26：開火結果現在會推 INTERVENTION_RESULT 回 web client；
    # 本測試 _web_thread=None → 該方法 no-op，但仍需綁上去才不會 AttributeError。
    bot._broadcast_intervention_result = types.MethodType(
        Bot._broadcast_intervention_result, bot)

    ok, _ = bot._execute_remote_fire_from_web(
        _FakeHarvestCtxWithPose(), x=960, y=540)

    assert ok is False
    assert len(save_calls) == 1
    assert save_calls[0]["verify_ok"] is False


class _FakeReentryCtxClick:
    episode_id = "5"
    sticky_layer = "mid"
    clicks = []
    net_zoom = 0


def test_rr_click_from_web_calls_save_auto_fixture_on_descended(monkeypatch, tmp_path):
    """verdict=descended 後應呼叫 _save_auto_fixture（flow=reentry, verify_ok=True）。"""
    import numpy as np
    import miningbot.main as main_mod
    from miningbot.main import Bot

    class _StubBot:
        pass

    bot = _StubBot()
    bot._web_thread = None
    bot.logger = logging.getLogger("test_wiring")
    bot.log_discord = logging.getLogger("test_wiring")
    bot._ping_messenger = None
    bot._mine_resetting = False
    bot._focus_roblox = lambda: True
    # _rr_click_and_verify 內部會 cv2.imwrite + capture.grab —— mock 掉
    bot._rr_click_and_verify = lambda ctx, pos, cur, layer, mpath, zs: "descended"
    bot._rr_snap_dir = lambda: str(tmp_path)
    # reentry_remote 兩個 pure helper 直接換成 identity / no-op
    monkeypatch.setattr(main_mod.reentry_remote, "draw_click_marker",
                        lambda frame, pos: frame)
    monkeypatch.setattr(main_mod.reentry_remote, "record_click",
                        lambda *a, **kw: None)
    fake_frame = np.zeros((1080, 1920, 3), np.uint8)
    monkeypatch.setattr(main_mod.capture, "grab", lambda: fake_frame)

    save_calls = []
    bot._save_auto_fixture = lambda **kw: save_calls.append(kw)

    bot._rr_click_from_web = types.MethodType(Bot._rr_click_from_web, bot)
    bot._resolve_ping_if_any = types.MethodType(Bot._resolve_ping_if_any, bot)

    verdict = bot._rr_click_from_web(_FakeReentryCtxClick(), x=100, y=200)

    assert verdict == "descended"
    assert len(save_calls) == 1, (
        f"應呼叫 _save_auto_fixture 一次，實際：{len(save_calls)}")
    sc = save_calls[0]
    assert sc["flow"] == "reentry"
    assert sc["episode_id"] == "5"
    assert sc["verify_ok"] is True
    assert sc["cell_crop"] is None
    assert sc["annotation_xy"] == (100, 200)


def test_rr_click_from_web_calls_save_auto_fixture_on_non_descended(monkeypatch, tmp_path):
    """verdict=still_surface 應呼叫 _save_auto_fixture（verify_ok=False）。"""
    import numpy as np
    import miningbot.main as main_mod
    from miningbot.main import Bot

    class _StubBot:
        pass

    bot = _StubBot()
    bot._web_thread = None
    bot.logger = logging.getLogger("test_wiring")
    bot.log_discord = logging.getLogger("test_wiring")
    bot._ping_messenger = None
    bot._mine_resetting = False
    bot._focus_roblox = lambda: True
    bot._rr_click_and_verify = lambda ctx, pos, cur, layer, mpath, zs: "still_surface"
    bot._rr_snap_dir = lambda: str(tmp_path)
    monkeypatch.setattr(main_mod.reentry_remote, "draw_click_marker",
                        lambda frame, pos: frame)
    monkeypatch.setattr(main_mod.reentry_remote, "record_click",
                        lambda *a, **kw: None)
    monkeypatch.setattr(main_mod.capture, "grab",
                        lambda: np.zeros((1080, 1920, 3), np.uint8))

    save_calls = []
    bot._save_auto_fixture = lambda **kw: save_calls.append(kw)

    bot._rr_click_from_web = types.MethodType(Bot._rr_click_from_web, bot)
    bot._resolve_ping_if_any = types.MethodType(Bot._resolve_ping_if_any, bot)

    verdict = bot._rr_click_from_web(_FakeReentryCtxClick(), x=100, y=200)

    assert verdict == "still_surface"
    assert len(save_calls) == 1
    assert save_calls[0]["verify_ok"] is False


# ---------------------------------------------------------------------------
# 2026-07-26 計畫稽核補洞：harvest 開火結果必須回報 web client
#
# spec 驗收 A 明列「verify 結果回傳網頁顯示（✅ 或 ❌）」，但
# _execute_remote_fire_from_web 原本只有「礦坑重置中」那條 reject 會廣播
# INTERVENTION_RESULT——D3 冷卻未就緒／聚焦失敗／verify 完成三條都 silent return，
# 玩家在手機上點完完全沒有下文。（reentry 路徑三條出口本來就都有廣播，兩邊不一致。）
# ---------------------------------------------------------------------------


def _build_fire_stub(monkeypatch, *, verify_ok=True, d3_ready=True, focus_ok=True):
    import numpy as np
    import miningbot.main as main_mod
    from miningbot.main import Bot

    class _StubBot:
        pass

    bot = _StubBot()
    bot._web_thread = _FakeWebThread()
    bot.logger = logging.getLogger("test_fire_result")
    bot.log_discord = logging.getLogger("test_fire_result")
    bot._ping_messenger = None
    bot._mine_resetting = False
    bot._wait_for_d3_cooldown = lambda deadline: (d3_ready, "" if d3_ready else "冷卻中 4.2s")
    bot._focus_roblox = lambda: focus_ok
    bot._aim_fire_and_verify = lambda *a, **kw: (
        verify_ok, "confirmed" if verify_ok else "無新稀有聊天")
    fake_frame = np.zeros((1080, 1920, 3), np.uint8)
    monkeypatch.setattr(main_mod.capture, "grab", lambda: fake_frame)
    monkeypatch.setattr(main_mod.capture, "crop", lambda f, r: f)
    bot._save_auto_fixture = lambda **kw: None
    bot._execute_remote_fire_from_web = types.MethodType(
        Bot._execute_remote_fire_from_web, bot)
    bot._resolve_ping_if_any = types.MethodType(Bot._resolve_ping_if_any, bot)
    bot._broadcast_intervention_result = types.MethodType(
        Bot._broadcast_intervention_result, bot)
    return bot


def _results(bot):
    return [c.payload for c in bot._web_thread.app.state.registry.calls
            if hasattr(c, "payload")
            and c.payload.get("event") == "INTERVENTION_RESULT"]


def test_fire_broadcasts_result_on_verify_success(monkeypatch):
    bot = _build_fire_stub(monkeypatch, verify_ok=True)
    ok, _ = bot._execute_remote_fire_from_web(_FakeHarvestCtxWithPose(), x=960, y=540)
    assert ok is True
    res = _results(bot)
    assert len(res) == 1, f"verify 通過應廣播 1 次結果，實際：{res}"
    assert res[0]["verdict"] == "fire_ok"
    assert res[0]["flow"] == "harvest"
    assert "✅" in res[0]["summary"]


def test_fire_broadcasts_result_on_verify_failure(monkeypatch):
    bot = _build_fire_stub(monkeypatch, verify_ok=False)
    ok, _ = bot._execute_remote_fire_from_web(_FakeHarvestCtxWithPose(), x=960, y=540)
    assert ok is False
    res = _results(bot)
    assert len(res) == 1, f"verify 失敗應廣播 1 次結果，實際：{res}"
    assert res[0]["verdict"] == "fire_failed"
    assert "❌" in res[0]["summary"]


def test_fire_broadcasts_result_when_d3_not_ready(monkeypatch):
    bot = _build_fire_stub(monkeypatch, d3_ready=False)
    ok, _ = bot._execute_remote_fire_from_web(_FakeHarvestCtxWithPose(), x=960, y=540)
    assert ok is False
    res = _results(bot)
    assert len(res) == 1 and res[0]["verdict"] == "fire_aborted", res
    assert "冷卻" in res[0]["summary"]


def test_fire_broadcasts_result_when_focus_fails(monkeypatch):
    bot = _build_fire_stub(monkeypatch, focus_ok=False)
    ok, _ = bot._execute_remote_fire_from_web(_FakeHarvestCtxWithPose(), x=960, y=540)
    assert ok is False
    res = _results(bot)
    assert len(res) == 1 and res[0]["verdict"] == "fire_aborted", res
    assert "聚焦" in res[0]["summary"]


def test_intervention_panel_js_handles_result_event():
    """網頁前端必須真的接 INTERVENTION_RESULT——bot 廣播了但 JS 沒接等於沒做。

    稽核當下的實況：render_intervention_html 的 ws.onmessage 只認
    INTERVENTION_NEEDED 與 ping，玩家點完永遠停在「已送出點擊…」。
    """
    from miningbot.web_static import render_intervention_html
    html = render_intervention_html()
    assert "INTERVENTION_RESULT" in html, "介入面板 JS 沒處理 INTERVENTION_RESULT"
    assert "fire_ok" in html and "descended" in html, (
        "成功 verdict 判定沒寫進 JS——無法區分 ✅／❌")
