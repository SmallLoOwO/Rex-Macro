"""P4 即時介入面板整合測試。

web_pending → main.py 整合點（manual_survey / reentry click）需要 fake bot 與
大量 monkeypatch 才能有意義地跑；本檔先放 skip skeleton，留 P5 或實機驗收補回。

會被執行的 web pipeline 整合測試（不靠 main.py）放 Task 7 補上。
"""
import logging
import types

import pytest


def test_get_intervention_returns_html():
    """GET /intervention 回 HTML：含 <img>（與標註工具同管線）+ fire_at/reentry_click + WebSocket。"""
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
    # <img> 渲染（2026-08-01：從 canvas 改成 img，與標註工具同管線，不壓縮）
    assert '<img id="snapshot"' in body
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


# ---------------------------------------------------------------------------
# main.py 整合測試（2026-07-26 補回 P4/P5 留下的三個 skip）
#
# 這三個測試從 P4 一路 skip 到 P5，理由都是「需要 fake bot」。harness 現在在
# tests/fake_bot.py；沒有它，所有 web 測試都只驗 standalone WebIPCThread，
# 「Bot 上的整合方法有沒有真的接起來」是完全的盲區——H061 就發生在這個盲區裡。
# ---------------------------------------------------------------------------


def _manual_survey_bot(monkeypatch, discord_calls, *, step_px=100, **over):
    """手動瞄準的 fake bot：D2/旋轉/俯仰/落盤全 stub，只留「拍了幾層、之後怎麼分流」。

    2026-08-05：plan_pitch_layers 恆回空 list → 永遠只拍 mid，step_px 不再影響行為。
    """
    import numpy as np
    import miningbot.main as main_mod
    from tests.fake_bot import make_fake_bot, FakeWebThread

    frame = np.zeros((8, 8, 3), np.uint8)
    monkeypatch.setattr(main_mod.capture, "grab", lambda: frame)
    monkeypatch.setattr(main_mod.notify, "send_images_message",
                        lambda *a, **kw: (discord_calls.append("images"), (True, "ok"))[1])
    monkeypatch.setattr(main_mod.notify, "send_message",
                        lambda *a, **kw: (discord_calls.append("text"), (True, "ok"))[1])
    monkeypatch.setattr(main_mod.harvester, "prepare_scan", lambda: None)
    monkeypatch.setattr(main_mod.cfg, "sweep_pitch_step_px", step_px)
    monkeypatch.setattr(main_mod.cfg, "sweep_pitch_center_back_px", 370)
    attrs = dict(
        _web_pending=object(),
        _web_thread=FakeWebThread(),
        _focus_roblox=lambda: True,
        _web_url=lambda: "http://test:8765",
        _web_intervention_mid={},
        _web_escalate={},
        _web_held_aim=None,
        _summarize_survey_ctx=lambda ctx: "summary",
        _await_scan_ready=lambda tag: None,
        _run_scan=lambda: None,
        _confirm_scan=lambda tag: True,
        _rotate_verified=lambda step: True,
        _pitch_goto_layer=lambda tag, nudge_px: True,
        _hsnap=lambda f, label: "",       # 落盤走非同步，測試不落地
        _encode_png=lambda f: b"png",
        _notify_web_intervention_pending=lambda key, headline, hint: None,
        _broadcast_intervention_result=lambda *a, **kw: None,
    )
    attrs.update(over)
    return make_fake_bot(
        bind=["_execute_manual_survey", "_await_manual_survey_web_click",
              "_release_web_held_aim", "_send_manual_survey_discord"],
        **attrs)


def test_main_manual_survey_pushes_single_layer_then_waits(monkeypatch):
    """2026-08-05：俯仰層掃描停用 → 只拍 mid 8 張。推網頁不看連線、等玩家點。

    舊版（三層）的測試邏輯保留，但期望值改成單層——plan_pitch_layers 恆回空 list。
    """
    from tests.fake_bot import FakeHarvestCtx
    pushed, discord_calls = [], []
    bot = _manual_survey_bot(
        monkeypatch, discord_calls,
        _send_web_intervention_frames=lambda **kw: (
            pushed.append((kw["routing_key"], kw["frames"])) or True),
        _await_web_action=lambda routing_key, controls=(): (
            "click", {"x": 851, "y": 189, "dir": 5}),
        _resolve_web_intervention_ping=lambda key: None,
    )
    ctx = FakeHarvestCtx(harvest_id="007")
    bot._execute_manual_survey(ctx)

    assert len(pushed) == 1 and pushed[0][0] == "harvest:007"
    frames = pushed[0][1]
    assert len(frames) == 8, f"應推 1 層 × 8 方位，實際：{len(frames)}"
    assert {lay for _d, lay, _p in frames} == {"mid"}
    # 俯仰停用 → 無「改拍三層」預告；網頁接手時不發 Discord 圖
    assert discord_calls == [], f"網頁接手時不該發 Discord，實際：{discord_calls}"
    # 點擊排進 _pending_aim（走 _execute_remote_fire 的完整對齊＋重掃）
    assert bot._pending_aim.kind == "point"
    assert bot._pending_aim.pos == (851, 189)
    assert bot._pending_aim.dir_idx == 4          # 介面 1-8 → 內部 0-based


def test_main_manual_survey_stays_single_layer_when_uncalibrated(monkeypatch):
    """2026-08-05：俯仰層全面停用，此測試驗證 step_px=0 和有校準值行為一致（都只拍 mid）。"""
    from tests.fake_bot import FakeHarvestCtx
    pushed, discord_calls = [], []
    bot = _manual_survey_bot(
        monkeypatch, discord_calls, step_px=0,
        _send_web_intervention_frames=lambda **kw: (
            pushed.append(kw["frames"]) or True),
        _await_web_action=lambda routing_key, controls=(): (
            "click", {"x": 1, "y": 1, "dir": 1}),
        _resolve_web_intervention_ping=lambda key: None,
    )
    bot._execute_manual_survey(FakeHarvestCtx(harvest_id="007"))

    assert len(pushed[0]) == 8
    assert {lay for _d, lay, _p in pushed[0]} == {"mid"}


def test_main_manual_survey_only_mid_layer(monkeypatch):
    """2026-08-05：俯仰層停用 → 永遠只拍 mid，沒有 up/down 可跳過。

    舊測試（skips_layer_whose_drag_was_eaten）驗的是 up 被吃後跳到 down；
    現在根本不拍 up/down，所以只驗 mid 8 張完整推送。
    """
    from tests.fake_bot import FakeHarvestCtx
    pushed, discord_calls = [], []

    bot = _manual_survey_bot(
        monkeypatch, discord_calls,
        _send_web_intervention_frames=lambda **kw: (
            pushed.append(kw["frames"]) or True),
        _await_web_action=lambda routing_key, controls=(): (
            "click", {"x": 1, "y": 1, "dir": 1}),
        _resolve_web_intervention_ping=lambda key: None,
    )
    bot._execute_manual_survey(FakeHarvestCtx(harvest_id="007"))

    assert {lay for _d, lay, _p in pushed[0]} == {"mid"}
    assert len(pushed[0]) == 8


def test_main_manual_survey_escalate_sends_discord_images(monkeypatch):
    """玩家按 🔀 → 才發 Discord 圖；mid 層 8 張分 2 則（每則 4 張）。

    2026-08-05：俯仰停用後只有 mid 一層，不再有三層預告文字。
    """
    from tests.fake_bot import FakeHarvestCtx
    discord_calls = []
    bot = _manual_survey_bot(
        monkeypatch, discord_calls,
        _send_web_intervention_frames=lambda **kw: True,
        _await_web_action=lambda routing_key, controls=(): ("force_discord", None),
        _resolve_web_intervention_ping=lambda key: None,
        _hsnap=lambda f, label: f"C:/tmp/{label}.png",
        _wait_snapshot_ready=lambda path, remaining: True,
    )
    import miningbot.main as main_mod
    import numpy as np
    import cv2
    monkeypatch.setattr(cv2, "imread", lambda p: np.zeros((8, 8, 3), np.uint8))
    monkeypatch.setattr(cv2, "imwrite", lambda p, img: True)
    monkeypatch.setattr(main_mod.diagnostics, "append_snapshot_index",
                        lambda *a, **kw: None)

    bot._execute_manual_survey(FakeHarvestCtx(harvest_id="007"))

    # mid 層 8 張、4 張/則 → 2 則圖；俯仰停用無「三層預告」文字
    assert discord_calls == ["images"] * 2, (
        f"mid 層 8 張分 2 則發，實際：{discord_calls}")


def test_main_manual_survey_without_web_server_goes_straight_to_discord(monkeypatch):
    """沒有網頁伺服器（缺件降級／設定關閉）→ 一路走既有 Discord 流程，不等任何人。"""
    from tests.fake_bot import FakeHarvestCtx
    discord_calls, waited = [], []
    bot = _manual_survey_bot(
        monkeypatch, discord_calls,
        _web_thread=None,
        _send_web_intervention_frames=lambda **kw: waited.append("push") or True,
        _await_web_action=lambda routing_key, controls=(): waited.append("await"),
        _focus_roblox=lambda: False,     # 立刻收尾，不必 stub 整條 Discord 鏈
    )
    bot._execute_manual_survey(FakeHarvestCtx(harvest_id="007"))

    assert waited == [], f"沒有網頁伺服器就不該碰 web 介入，實際：{waited}"


def test_main_execute_remote_fire_short_circuits_on_web_reply(monkeypatch):
    """_execute_remote_fire_from_web 收到 (x, y) 直接開火，不再跑偵測。

    斷言：_aim_fire_and_verify 收到的 pos 就是玩家點的原生座標；
    _detect_core_in_cell / _refind_tracker_near 一次都沒被呼叫（玩家點哪打哪）。
    """
    import numpy as np
    import miningbot.main as main_mod
    from tests.fake_bot import make_fake_bot, FakeWebThread, FakeHarvestCtx

    frame = np.zeros((1080, 1920, 3), np.uint8)
    monkeypatch.setattr(main_mod.capture, "grab", lambda: frame)
    monkeypatch.setattr(main_mod.capture, "crop", lambda f, r: f)

    fire_args = []
    detect_calls = []

    def _fire_and_verify(pos, *a, **kw):
        fire_args.append(pos)
        return True, "confirmed"

    bot = make_fake_bot(
        bind=["_execute_remote_fire_from_web", "_broadcast_intervention_result",
              "_resolve_ping_if_any"],
        _web_thread=FakeWebThread(),
        _wait_for_d3_cooldown=lambda deadline: (True, ""),
        _focus_roblox=lambda: True,
        _save_auto_fixture=lambda **kw: None,
        _detect_core_in_cell=lambda *a, **kw: detect_calls.append("core"),
        _refind_tracker_near=lambda *a, **kw: detect_calls.append("refind"),
        _aim_fire_and_verify=_fire_and_verify,
    )

    ok, _ = bot._execute_remote_fire_from_web(FakeHarvestCtx(), x=851, y=189)

    assert ok is True
    assert fire_args == [(851, 189)], f"開火座標應原封不動，實際：{fire_args}"
    assert detect_calls == [], (
        f"玩家已經點好位置，不該再跑偵測，實際：{detect_calls}")


def _reentry_bot(monkeypatch, **over):
    """回礦 web 介入用的 fake bot（八方位版）。

    `_web_client_online` 綁真方法，讓 FakeFallback 真的決定走不走 web 路徑。
    """
    from tests.fake_bot import make_fake_bot, FakeFallback, FakeWebThread
    import miningbot.main as main_mod

    monkeypatch.setattr(main_mod.notify, "send_message_with_id",
                        lambda *a, **kw: (True, "ok", "notify-mid"))
    monkeypatch.setattr(main_mod.notify, "delete_message",
                        lambda *a, **kw: (True, "HTTP 204"))
    attrs = dict(
        _web_pending=object(),
        _web_fallback=FakeFallback(fallback=False),
        _web_thread=FakeWebThread(),
        _focus_roblox=lambda: True,
        _web_url=lambda: "http://test:8765",
        _web_intervention_mid={},
        _pending_reentry=None,
    )
    attrs.update(over)
    return make_fake_bot(
        bind=["_reentry_await_player_click", "_web_client_online",
              "_queue_web_reentry_control", "_notify_web_intervention_pending",
              "_resolve_web_intervention_ping"],
        **attrs)


_PNGS = [(i, b"png%d" % i) for i in range(8)]


def test_main_reentry_pushes_all_eight_frames(monkeypatch):
    """核心修復：推的是**八方位整組**，不是「當下這一幀」。

    2026-07-26 實機：舊版只推當下一幀，而回礦開場站在地表、傳送板九成不在視野內
    ——玩家看著一張沒有目標的圖無從點起，白等 120s 逾時
    （log: `[RR#26] 回礦 web 介入：reply timeout（attempt 1/3）`）。
    """
    pushed = []
    bot = _reentry_bot(
        monkeypatch,
        _send_web_intervention_frames=lambda **kw: (
            pushed.append((kw["routing_key"], len(kw["frames"]))) or True),
        _await_web_reentry_action=lambda routing_key:(
            "click", {"x": 640, "y": 400, "dir": 3}),
        _rr_click_from_web=lambda ctx, x, y, dir_idx=None: "descended",
    )
    from tests.fake_bot import FakeReentryCtx
    ctx = FakeReentryCtx(episode_id="26")
    ctx.attempt, ctx.sticky_layer = 1, "Shamrock"

    assert bot._reentry_await_player_click(ctx, _PNGS) is True
    assert pushed == [("reentry:26", 8)], f"應推 8 張，實際：{pushed}"


def test_main_reentry_click_carries_direction(monkeypatch):
    """玩家點的是第幾張 → bot 必須先轉到那個方位再點。

    沒有 dir 就等於對著別的方向的畫面座標開槍。
    """
    clicked = []
    bot = _reentry_bot(
        monkeypatch,
        _send_web_intervention_frames=lambda **kw: True,
        _await_web_reentry_action=lambda routing_key:(
            "click", {"x": 851, "y": 189, "dir": 5}),
        _rr_click_from_web=lambda ctx, x, y, dir_idx=None: (
            clicked.append((x, y, dir_idx)) or "descended"),
    )
    from tests.fake_bot import FakeReentryCtx
    ctx = FakeReentryCtx(episode_id="26")
    ctx.attempt, ctx.sticky_layer = 1, "Shamrock"

    assert bot._reentry_await_player_click(ctx, _PNGS) is True
    assert clicked == [(851, 189, 5)]


def test_main_reentry_notifies_discord_that_web_is_waiting(monkeypatch):
    """網頁在等你點 → Discord 要發提醒（否則只有「剛好在看」才有用）。

    而且結束時要把提醒收回，不留一串殭屍訊息。
    """
    import miningbot.main as main_mod
    sent, deleted = [], []
    monkeypatch.setattr(main_mod.notify, "send_message_with_id",
                        lambda t, c, text: (sent.append(text), (True, "ok", "mid-1"))[1])
    monkeypatch.setattr(main_mod.notify, "delete_message",
                        lambda t, c, mid: (deleted.append(mid), (True, "HTTP 204"))[1])
    bot = _reentry_bot(
        monkeypatch,
        _send_web_intervention_frames=lambda **kw: True,
        _await_web_reentry_action=lambda routing_key:(
            "click", {"x": 1, "y": 1, "dir": 1}),
        _rr_click_from_web=lambda ctx, x, y, dir_idx=None: "descended",
    )
    # 上面的 _reentry_bot 也 patch 了這兩個，重新蓋掉以取得本測試的記錄器
    monkeypatch.setattr(main_mod.notify, "send_message_with_id",
                        lambda t, c, text: (sent.append(text), (True, "ok", "mid-1"))[1])
    monkeypatch.setattr(main_mod.notify, "delete_message",
                        lambda t, c, mid: (deleted.append(mid), (True, "HTTP 204"))[1])
    from tests.fake_bot import FakeReentryCtx
    ctx = FakeReentryCtx(episode_id="26")
    ctx.attempt, ctx.sticky_layer = 2, "Shamrock"

    bot._reentry_await_player_click(ctx, _PNGS)

    assert len(sent) == 1, "介入開始要發一則 Discord 提醒"
    assert "26" in sent[0] and "http://test:8765/intervention" in sent[0]
    assert deleted == ["mid-1"], "介入結束要把提醒收回"


def test_main_reentry_panel_buttons_queue_existing_commands(monkeypatch):
    """面板的 🎲重骰／⏭️跳過 走既有 reentry 指令佇列（與 Discord 打字等價）。"""
    queued = []
    bot = _reentry_bot(
        monkeypatch,
        _send_web_intervention_frames=lambda **kw: True,
        _await_web_reentry_action=lambda routing_key:("reroll", None),
        _queue_reentry_reply=lambda raw, reply, source: queued.append((raw, reply.kind, source)),
        _broadcast_intervention_result=lambda *a, **kw: None,
    )
    from tests.fake_bot import FakeReentryCtx
    ctx = FakeReentryCtx(episode_id="26")
    ctx.attempt, ctx.sticky_layer = 1, "Shamrock"

    assert bot._reentry_await_player_click(ctx, _PNGS) is True
    assert queued == [("重骰", "reroll", "web")]


def test_main_reentry_sweep_button_recaptures_and_repushes(monkeypatch):
    """⟳重掃 → 就地重掃一圈、重推新圖，不算失敗、也不退回 Discord。"""
    pushes = []
    actions = iter([("sweep", None), ("click", {"x": 5, "y": 5, "dir": 2})])
    bot = _reentry_bot(
        monkeypatch,
        _send_web_intervention_frames=lambda **kw: (
            pushes.append(len(kw["frames"])) or True),
        _await_web_reentry_action=lambda routing_key:next(actions),
        _rr_sweep_capture=lambda encode_for_web=False: ([], 0, _PNGS[:8]),
        _rr_click_from_web=lambda ctx, x, y, dir_idx=None: "descended",
    )
    from tests.fake_bot import FakeReentryCtx
    ctx = FakeReentryCtx(episode_id="26")
    ctx.attempt, ctx.sticky_layer = 1, "Shamrock"

    assert bot._reentry_await_player_click(ctx, _PNGS) is True
    assert pushes == [8, 8], f"重掃後要重推一次，實際：{pushes}"


def test_main_reentry_timeout_falls_back_to_discord(monkeypatch):
    """逾時＝人不在 → 回 False，caller 發 Discord 八方位（既有流程接手）。"""
    bot = _reentry_bot(
        monkeypatch,
        _send_web_intervention_frames=lambda **kw: True,
        _await_web_reentry_action=lambda routing_key:(None, None),
    )
    from tests.fake_bot import FakeReentryCtx
    ctx = FakeReentryCtx(episode_id="26")
    ctx.attempt, ctx.sticky_layer = 1, "Shamrock"

    assert bot._reentry_await_player_click(ctx, _PNGS) is False


def test_main_reentry_pushes_even_when_nobody_connected(monkeypatch):
    """核心修復（2026-07-29）：沒人連著也要推圖 + 發提醒。

    舊版第一行就 `if not _web_client_online(): return False`——而使用者是被
    Discord 提醒才開網頁的人，掃描當下當然沒連線 → 網頁永遠拿不到圖，
    「網頁優先」在實機從來沒發生過（07-29 RR#32：掃完直接洗 Discord 八方位，
    log 連一行 `web 介入` 都沒有）。圖推進 registry replay 緩衝，人開頁面時補得到。
    """
    from tests.fake_bot import FakeFallback, FakeReentryCtx
    pushed, notified = [], []
    bot = _reentry_bot(
        monkeypatch,
        _web_fallback=FakeFallback(fallback=True),        # 沒有任何 client
        _send_web_intervention_frames=lambda **kw: (
            pushed.append(len(kw["frames"])) or True),
        _notify_web_intervention_pending=lambda key, headline, hint: notified.append(key),
        _await_web_reentry_action=lambda routing_key:(None, None),
        _broadcast_intervention_result=lambda ctx, verdict, summary, flow="reentry": None,
    )
    ctx = FakeReentryCtx(episode_id="32")
    ctx.attempt, ctx.sticky_layer = 1, "Shamrock"
    assert bot._reentry_await_player_click(ctx, _PNGS) is False
    assert pushed == [8], f"離線也要推 8 張進 replay 緩衝，實際：{pushed}"
    assert notified == ["reentry:32"], "要發 Discord 提醒叫人來開網頁"


def test_await_web_reentry_action_never_times_out(monkeypatch):
    """沒人連進來也不放棄——所有逾時預算已刪（2026-07-30 使用者指定）。

    RR#34 迴歸：18:28:23 推圖＋發 Discord 提醒，120s grace 到期就退場並清掉重播
    緩衝，使用者 18:41:45 才開網頁 → 面板全空。玩家是被推播叫來的，任何固定窗都
    會漏掉他。離場的唯一開關是提醒訊息上的 🔀（force_discord）。
    """
    import miningbot.main as main_mod
    from tests.fake_bot import make_fake_bot

    clock = [0.0]
    monkeypatch.setattr(main_mod.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main_mod.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + 10))

    class _EscalateAtOneHour:
        """一小時後玩家才按 🔀——在那之前不管等多久都不准自己走掉。"""

        def pop(self, key):
            if key == "control:force_discord:reentry:9" and clock[0] >= 3600.0:
                return {"ok": True}
            return None

    bot = make_fake_bot(
        bind=["_await_web_reentry_action"],
        _web_pending=_EscalateAtOneHour(),
        _web_client_online=lambda: False,
        _mine_resetting=False,
        _running=True,
        paused=False,
    )
    assert bot._await_web_reentry_action(routing_key="reentry:9") == ("force_discord", None)
    assert clock[0] >= 3600.0, f"不該提前放棄，實際只等了 {clock[0]}s"


def test_await_web_reentry_action_takes_late_click_from_offline_start(monkeypatch):
    """推圖當下離線、玩家 13 分鐘後才開網頁點下去 → 照樣收得到（RR#34 的實際時序）。"""
    import miningbot.main as main_mod
    from tests.fake_bot import make_fake_bot

    clock = [0.0]
    monkeypatch.setattr(main_mod.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main_mod.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + 10))

    class _ReplyAt800:
        """玩家 800s（>13 分）才點下去——舊 grace 早就把他擋在門外。"""

        def pop(self, key):
            if key == "reentry:9" and clock[0] >= 800.0:
                return {"x": 1, "y": 2, "dir": 3}
            return None

    bot = make_fake_bot(
        bind=["_await_web_reentry_action"],
        _web_pending=_ReplyAt800(),
        _web_client_online=lambda: clock[0] >= 780.0,   # 780s 時才開頁面
        _mine_resetting=False,
        _running=True,
        paused=False,
    )
    kind, reply = bot._await_web_reentry_action(routing_key="reentry:9")
    assert kind == "click" and reply["dir"] == 3


def test_await_web_reentry_action_aborts_on_shutdown(monkeypatch):
    """無限等的必要配套：_running 翻 False（F12 關閉）要放得掉主迴圈。"""
    import miningbot.main as main_mod
    from tests.fake_bot import make_fake_bot

    clock = [0.0]
    monkeypatch.setattr(main_mod.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main_mod.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + 10))

    holder = {}

    class _ShutdownAt100:
        """100s 時使用者按了 F12：_running 翻 False。"""

        def pop(self, key):
            if clock[0] >= 100.0:
                holder["bot"]._running = False
            return None

    bot = make_fake_bot(
        bind=["_await_web_reentry_action"],
        _web_pending=_ShutdownAt100(),
        _web_client_online=lambda: False,
        _mine_resetting=False,
        _running=True,
        paused=False,
    )
    holder["bot"] = bot
    assert bot._await_web_reentry_action(routing_key="reentry:9") == (None, None)
    assert clock[0] < 200.0, f"關閉後應立刻放手，實際等了 {clock[0]}s"


def test_main_reentry_returns_false_without_frames(monkeypatch):
    """一張都沒編碼成功（encode 全失敗）→ 不要推空面板給玩家看。"""
    from tests.fake_bot import FakeReentryCtx
    bot = _reentry_bot(monkeypatch)
    assert bot._reentry_await_player_click(FakeReentryCtx(), []) is False


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
        self.calls.append(data)

    def begin_intervention_replay(self):
        pass

    def end_intervention_replay(self):
        pass


class _FakeWebThread:
    """最低限度模擬 WebIPCThread.app.state.registry。"""

    def __init__(self):
        self.app = types.SimpleNamespace()
        self.app.state = types.SimpleNamespace()
        self.app.state.registry = _FakeRegistry()


class _FakeCtx:
    episode_id = "test_ep"
    attempt = 1
    sticky_layer = "Shamrock"


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
    bot._pending_reentry = None
    bot._web_intervention_mid = {}
    bot._web_escalate = {}
    bot._web_url = lambda: "http://test:8765"
    # capture.grab 在主迴圈 thread 上跑，monkeypatch module attr 即可
    monkeypatch.setattr(main_mod.capture, "grab", lambda: object())
    # Discord 提醒訊息（2026-07-26）：測試不打真 API
    monkeypatch.setattr(main_mod.notify, "send_message_with_id",
                        lambda *a, **kw: (True, "ok", "notify-mid"))
    monkeypatch.setattr(main_mod.notify, "delete_message",
                        lambda *a, **kw: (True, "HTTP 204"))
    # 2026-07-27：🔀 反應（_arm_web_escalate_reaction）也不打真 API
    monkeypatch.setattr(main_mod.notify, "add_reaction",
                        lambda *a, **kw: (True, "HTTP 204"))
    sent = []
    bot._send_web_intervention_frames = lambda **kw: (sent.append(kw) or True)
    bot._sent_intervention_events = sent
    # 重掃/retry 會就地再掃一圈——回固定的 8 張，不碰真實旋轉
    bot._rr_sweep_capture = lambda encode_for_web=False: ([], 0, _STUB_PNGS)
    bot._RR_WEB_CONTROLS = Bot._RR_WEB_CONTROLS

    # 把真實 method 綁到 stub
    for name in ("_reentry_await_player_click", "_broadcast_intervention_result",
                 "_web_client_online", "_notify_web_intervention_pending",
                 "_resolve_web_intervention_ping", "_arm_web_escalate_reaction",
                 "_poll_web_escalate_reactions"):
        setattr(bot, name, types.MethodType(getattr(Bot, name), bot))
    return bot


_STUB_PNGS = [(i, b"png") for i in range(8)]


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
    bot._await_web_reentry_action = lambda routing_key:("click", next(replies))
    # 三次都非 descended
    bot._rr_click_from_web = lambda ctx, x, y, dir_idx=None: "still_surface"

    result = bot._reentry_await_player_click(_FakeCtx(), _STUB_PNGS)

    # 2026-07-26 語意變更：三次都失敗改回 False＝退回 Discord 八方位。
    # 舊版回 True 讓 caller 不發 Discord 卡片，玩家等於兩邊都沒得操作。
    assert result is False
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
    assert any("重骰" in s or "跳過" in s or "Discord" in s for s in summaries), (
        f"INTERVENTION_RESULT summary 應告訴玩家接下來怎麼辦，實際：{summaries}")


def test_reentry_await_player_click_retries_until_descended(monkeypatch):
    """P5 Task 2: 第一次 still_surface → 廣播 INTERVENTION_RESULT → retry → descended。"""
    from miningbot.web_protocol import WebMessage

    bot = _build_stub_bot_for_reentry(monkeypatch)

    replies = iter([{"x": 100, "y": 100}, {"x": 200, "y": 200}])
    bot._await_web_reentry_action = lambda routing_key:("click", next(replies))
    verdicts = iter(["still_surface", "descended"])
    bot._rr_click_from_web = lambda ctx, x, y, dir_idx=None: next(verdicts)

    result = bot._reentry_await_player_click(_FakeCtx(), _STUB_PNGS)

    assert result is True  # descended 從 caller 角度仍是「web 已處理」
    calls = bot._web_thread.app.state.registry.calls
    results = [c for c in calls
               if isinstance(c, WebMessage)
               and c.payload.get("event") == "INTERVENTION_RESULT"]
    # descended 之前應該剛好一次 INTERVENTION_RESULT（still_surface 那次）
    assert len(results) == 1, f"應只廣播 1 次（descended 後不再 retry），實際：{len(results)}"
    assert results[0].payload["verdict"] == "still_surface"
    # 應該重發 INTERVENTION_NEEDED（2026-08-01：畫面沒動時推的是同一批圖，
    # 不重掃；重掃與否由 _rr_last_click_moved 決定，見下面兩個測試）
    assert len(bot._sent_intervention_events) >= 2, (
        f"retry 前應重推八方位，實際 push 次數："
        f"{len(bot._sent_intervention_events)}")


def test_reentry_await_player_click_aborted_returns_false(monkeypatch):
    """等待被中止（礦坑重置／關閉／暫停）時 fall through Discord（return False）。

    2026-07-27 修正：先前這裡「不廣播」——面板連著的人只會看到畫面停在原地，
    之後才連上的人（使用者的實際用法是「有提醒才連」）靠重播緩衝也只會看到一份
    早就作廢的等待畫面。現在改成廣播一則結果，順便清掉重播緩衝。
    2026-07-30：回礦已無逾時，verdict 從 web_timeout 改名 web_aborted。
    """
    bot = _build_stub_bot_for_reentry(monkeypatch)
    bot._await_web_reentry_action = lambda routing_key:(None, None)

    result = bot._reentry_await_player_click(_FakeCtx(), _STUB_PNGS)

    assert result is False
    calls = bot._web_thread.app.state.registry.calls
    results = [c for c in calls
               if hasattr(c, "payload") and c.payload.get("event") == "INTERVENTION_RESULT"]
    assert len(results) == 1, "中止時該廣播一則結果，讓晚到的 client 看得到"
    assert results[0].payload["verdict"] == "web_aborted"


def test_web_panel_treats_aborted_as_done():
    """前端要認得 web_aborted，否則面板停在「等你點」不收（P5 稽核的老病）。"""
    from miningbot import web_static
    assert "web_aborted" in web_static.render_intervention_html()


def test_reentry_await_player_click_force_discord_returns_false_with_escalate_verdict(monkeypatch):
    """2026-07-27：玩家按提醒訊息上的 🔀（不想等 web 了）要立刻退回 Discord。

    跟逾時走同一條 fall-through 路徑（return False），但廣播的 verdict 要
    區分成 web_escalate（玩家主動選的），不是 web_timeout（真的等到逾時）。
    """
    bot = _build_stub_bot_for_reentry(monkeypatch)
    bot._await_web_reentry_action = lambda routing_key:("force_discord", None)

    result = bot._reentry_await_player_click(_FakeCtx(), _STUB_PNGS)

    assert result is False
    calls = bot._web_thread.app.state.registry.calls
    results = [c for c in calls
               if hasattr(c, "payload") and c.payload.get("event") == "INTERVENTION_RESULT"]
    assert len(results) == 1
    assert results[0].payload["verdict"] == "web_escalate"


def test_notify_web_intervention_pending_arms_escalate_reaction(monkeypatch):
    """發提醒訊息時要順便貼上 🔀 反應，並記住 routing_key -> mid 基線。"""
    bot = _build_stub_bot_for_reentry(monkeypatch)
    added_calls = []
    monkeypatch.setattr(
        "miningbot.main.notify.add_reaction",
        lambda token, ch, mid, emoji: (added_calls.append((mid, emoji)), (True, "HTTP 204"))[1])

    bot._notify_web_intervention_pending("reentry:test_ep", "回礦 #test_ep 已拍好 8 個方位", "點傳送板。")

    assert added_calls == [("notify-mid", "🔀")]
    assert bot._web_escalate.get("reentry:test_ep") == ("notify-mid", 1)
    assert bot._web_intervention_mid == {"reentry:test_ep": "notify-mid"}


def test_notify_web_intervention_pending_reaction_add_failure_does_not_arm(monkeypatch):
    """加反應失敗（例如權限問題）只記 log，不該假裝已武裝——不然 poll 永遠查不到東西。"""
    bot = _build_stub_bot_for_reentry(monkeypatch)
    monkeypatch.setattr(
        "miningbot.main.notify.add_reaction", lambda *a, **kw: (False, "HTTP 403"))

    bot._notify_web_intervention_pending("reentry:test_ep", "回礦 #test_ep", "點傳送板。")

    assert bot._web_escalate == {}


def test_poll_web_escalate_reactions_pushes_force_discord_on_extra_click(monkeypatch):
    """反應數超過基線（有人多按一次）→ push control:force_discord:<routing_key>。"""
    from miningbot.main import Bot
    from miningbot.web_ipc import PendingReplies

    bot = Bot.__new__(Bot)
    bot.log_discord = logging.getLogger("test_escalate_poll")
    bot._web_pending = PendingReplies()
    bot._web_escalate = {"reentry:26": ("mid-1", 1)}

    # `_poll_web_escalate_reactions` 內部是 `from . import notify` 拿真模組，
    # 所以要 patch 真模組上的函式屬性，換掉整顆 module 物件沒有用。
    monkeypatch.setattr(
        "miningbot.notify.get_reactions",
        lambda token, ch, mid, emoji: [{"id": "bot-self"}, {"id": "player-1"}])

    bot._poll_web_escalate_reactions()

    assert bot._web_escalate == {}, "觸發後要從等待清單移除，不能一直重複觸發"
    assert bot._web_pending.pop("control:force_discord:reentry:26") is True


def test_poll_web_escalate_reactions_no_push_when_count_at_baseline(monkeypatch):
    """只有機器人自己那下（count==baseline）不該誤觸發——那是按鈕本身，不是玩家點擊。"""
    from miningbot.main import Bot
    from miningbot.web_ipc import PendingReplies

    bot = Bot.__new__(Bot)
    bot.log_discord = logging.getLogger("test_escalate_poll")
    bot._web_pending = PendingReplies()
    bot._web_escalate = {"reentry:26": ("mid-1", 1)}

    monkeypatch.setattr(
        "miningbot.notify.get_reactions", lambda token, ch, mid, emoji: [{"id": "bot-self"}])

    bot._poll_web_escalate_reactions()

    assert bot._web_escalate == {"reentry:26": ("mid-1", 1)}, "沒人多按，武裝狀態要維持"
    assert bot._web_pending.pop("control:force_discord:reentry:26") is None


def test_resolve_web_intervention_ping_clears_escalate_entry(monkeypatch):
    """介入結束收回提醒訊息時，順便清掉 escalate 追蹤——訊息都要被刪了，
    再查那則訊息的反應只會白費一次 API。
    """
    bot = _build_stub_bot_for_reentry(monkeypatch)
    bot._web_intervention_mid = {"reentry:test_ep": "notify-mid"}
    bot._web_escalate = {"reentry:test_ep": ("notify-mid", 1)}

    bot._resolve_web_intervention_ping("reentry:test_ep")

    assert bot._web_escalate == {}
    assert bot._web_intervention_mid == {}


def test_await_web_reentry_action_returns_force_discord_on_control_key():
    """`_await_web_reentry_action` 要能認得 control:force_discord:<routing_key>。"""
    from miningbot.main import Bot
    from miningbot.web_ipc import PendingReplies

    bot = Bot.__new__(Bot)
    bot.logger = logging.getLogger("test_web_intervention")
    bot._web_pending = PendingReplies()
    bot._mine_resetting = False
    bot._running = True
    bot.paused = False
    bot._RR_WEB_CONTROLS = Bot._RR_WEB_CONTROLS
    bot._web_pending.push("control:force_discord:reentry:26", True)

    kind, reply = Bot._await_web_reentry_action(bot, routing_key="reentry:26")

    assert kind == "force_discord" and reply is None


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
    bot._reveal_chat = lambda: True          # H064：純 I/O，這裡不驗
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
    bot._reveal_chat = lambda: True          # H064：純 I/O，這裡不驗
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
    cur_dir = 0
    predictions = {}          # 2026-07-28：傳送板預測（`RemoteReentryContext` 有這兩欄）


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
    bot._reveal_chat = lambda: True          # H064：純 I/O，這裡不驗
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


# ---------------------------------------------------------------------------
# 2026-07-26：面板本身的三顆按鈕與八方位導覽。
#
# 使用者回報「回礦的功能依舊不能在網頁上使用」。查 log 是
# `[RR#26] 回礦 web 介入：reply timeout（attempt 1/3）`——網頁連著、但面板上
# 只有一張沒有傳送板的圖，玩家無從點起也沒有任何其他操作可做。
# ---------------------------------------------------------------------------


def _panel_html():
    from miningbot.web_static import render_intervention_html
    return render_intervention_html()


class TestPanelHasReentryControls:
    def test_direction_navigation_present(self):
        """左右切方位是整個回礦網頁流程可用與否的關鍵。"""
        html = _panel_html()
        assert "INTERVENTION_FRAME" in html, "缺多幀接收邏輯"
        assert "showFrame" in html and "curFrame" in html

    def test_three_action_buttons_present(self):
        html = _panel_html()
        for label in ("重掃", "重骰", "跳過"):
            assert label in html, f"面板缺 {label} 按鈕"
        for cmd in ("'sweep'", "'reroll'", "'skip'"):
            assert cmd in html, f"面板沒送出 {cmd} 命令"

    def test_click_carries_direction(self):
        html = _panel_html()
        assert "payload.dir" in html, "點擊必須帶上方位，否則 bot 會在錯的面向點下去"

    def test_notification_affordances_present(self):
        """玩家不會一直盯著這頁：標題閃爍 + 提示音。"""
        html = _panel_html()
        assert "startFlashing" in html and "document.title" in html
        assert "AudioContext" in html, "提示音要用 Web Audio 合成（CSP 擋外部音檔）"

    def test_no_external_resources(self):
        """CSP 會擋掉所有外部資源——面板必須完全自足。"""
        html = _panel_html()
        for bad in ("http://cdn", "https://cdn", "<script src=", "<link rel=\"stylesheet\""):
            assert bad not in html, f"面板引用了外部資源：{bad}"


class TestPanelControlCommandsReachPending:
    """三顆按鈕送出的命令要真的進得了 PendingReplies（不然按了沒反應）。"""

    def _push(self, cmd):
        import json
        import time
        from fastapi.testclient import TestClient
        from miningbot.web_ipc import PendingReplies, FallbackState
        from miningbot.web_server import create_app
        pending = PendingReplies()
        app = create_app(pending, FallbackState(), broadcast_callback=None)
        with TestClient(app).websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "command", "payload": {"cmd": cmd}}))
            time.sleep(0.1)
        return pending.pop(f"control:{cmd}")

    def test_sweep_reaches_pending(self):
        assert self._push("sweep") is not None

    def test_reroll_reaches_pending(self):
        assert self._push("reroll") is not None

    def test_skip_reaches_pending(self):
        assert self._push("skip") is not None


def test_reentry_click_with_dir_reaches_pending():
    """端到端：帶 dir 的點擊要完整送達 bot 端。"""
    import json
    import time
    from fastapi.testclient import TestClient
    from miningbot.web_ipc import PendingReplies, FallbackState
    from miningbot.web_server import create_app
    pending = PendingReplies()
    app = create_app(pending, FallbackState(), broadcast_callback=None)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "reentry_click", "flow": "reentry",
                        "attempt_id": "26", "x": 851, "y": 189, "dir": 4},
        }))
        time.sleep(0.1)
    reply = pending.pop("reentry:26")
    assert reply is not None
    assert reply["dir"] == 4 and reply["x"] == 851 and reply["y"] == 189


# ---------------------------------------------------------------------------
# 2026-07-27：harvest 採集放棄候選清單也推 web（原本只發 Discord，網頁介入
# 明明連著也沒收到這批圖，玩家只能切回 Discord 打編號——本檔補這段接線）。
# ---------------------------------------------------------------------------


def test_handle_web_aim_click_queues_point_reply_with_dir_and_layer():
    """點擊排進 `_pending_aim`（kind="point"）——走跟 Discord 回編號同一條
    `_tick_remote_aim` 尾段（`_execute_remote_fire` 內建 D2 重掃/D5 守門/
    `_refind_tracker_near`），不在這裡直接開火、不比對候選標號。

    07-27 實機：候選都是弱信號（分數 0.2~0.3x），玩家點的位置離最近候選
    超過門檻就被舊版忽略；後來改成直接開火但繞過了 D2/D5 檢查，一樣打不到
    （候選清單可能是好幾分鐘前掃的，效果早過期）。改走 _pending_aim 才是
    真正跟 Discord 同一條路——兩邊共用 _execute_remote_fire，不重寫一份。
    """
    from miningbot import remote_aim
    from tests.fake_bot import make_fake_bot

    ctx = types.SimpleNamespace(harvest_id="115", awaiting_fine=False,
                                pose_net_rotations=0, pose_pitch_layer="mid")
    bot = make_fake_bot(
        bind=["_handle_web_aim_click"],
        _aim_context=ctx,
        _aim_busy=False,
        _pending_aim=None,
    )
    bot._handle_web_aim_click({"x": 510, "y": 410, "dir": 3, "layer": "up"})
    assert bot._pending_aim == remote_aim.AimReply(
        "point", dir_idx=2, layer="up", pos=(510, 410))


def test_handle_web_aim_click_missing_dir_layer_uses_current_pose():
    """缺 dir/layer（舊 client／資料不全）退回「當下姿態」，而不是丟棄。"""
    from miningbot import remote_aim
    from tests.fake_bot import make_fake_bot

    ctx = types.SimpleNamespace(harvest_id="115", awaiting_fine=False,
                                pose_net_rotations=5, pose_pitch_layer="down")
    bot = make_fake_bot(
        bind=["_handle_web_aim_click"],
        _aim_context=ctx,
        _aim_busy=False,
        _pending_aim=None,
    )
    bot._handle_web_aim_click({"x": 500, "y": 400})
    assert bot._pending_aim == remote_aim.AimReply(
        "point", dir_idx=5, layer="down", pos=(500, 400))


def test_handle_web_aim_click_dropped_when_busy_or_already_pending():
    """先到先贏：正在跑或已排隊的回覆不該被 web 點擊蓋掉。"""
    from tests.fake_bot import make_fake_bot

    ctx = types.SimpleNamespace(harvest_id="115", awaiting_fine=False,
                                pose_net_rotations=0, pose_pitch_layer="mid")
    bot = make_fake_bot(
        bind=["_handle_web_aim_click"],
        _aim_context=ctx,
        _aim_busy=True,
        _pending_aim=None,
    )
    bot._handle_web_aim_click({"x": 500, "y": 400, "dir": 1, "layer": "mid"})
    assert bot._pending_aim is None

    bot._aim_busy = False
    bot._pending_aim = "已有一則排隊"
    bot._handle_web_aim_click({"x": 500, "y": 400, "dir": 1, "layer": "mid"})
    assert bot._pending_aim == "已有一則排隊"


class TestTickRemoteAimPointKind:
    """`_tick_remote_aim` 的 kind="point" 分支——驗證它走的是跟 candidate 分支
    一樣的 `_execute_remote_fire`（D2/D5 全套對齊+重掃+重找），而不是自己另開
    一條淺路徑。"""

    def test_point_reply_calls_execute_remote_fire_with_click_pos_as_prior(self):
        from miningbot import remote_aim
        from tests.fake_bot import make_fake_bot

        ctx = types.SimpleNamespace(
            harvest_id="115", candidates=[], shots=[], pose_net_rotations=0,
            pose_pitch_layer="mid")
        calls = []
        bot = make_fake_bot(
            bind=["_tick_remote_aim"],
            _aim_context=ctx,
            _aim_busy=False,
            _execute_remote_fire=lambda c, layer, dir_, prior, cell="":
                (calls.append((layer, dir_, prior, cell)), (True, "confirmed"))[1],
            _broadcast_intervention_result=lambda *a, **kw: None,
        )
        reply = remote_aim.AimReply("point", dir_idx=3, layer="up", pos=(500, 400))

        bot._tick_remote_aim(None, reply)

        assert calls == [("up", 3, (500, 400), "")]
        assert bot._aim_context is None  # 成功收尾


def test_consume_web_pending_routes_harvest_fire_at_to_aim_click():
    """_consume_web_pending 是 NEEDS_HUMAN 這段的 safe point——沒有專屬 blocking
    等待器（不像 manual_survey/reentry 自己在函式內等），要靠這裡撿 reply。
    """
    from miningbot.main import State
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    pending = PendingReplies()
    pending.push("harvest:115", {"x": 500, "y": 400, "dir": 3, "layer": "mid"})
    ctx = types.SimpleNamespace(harvest_id="115", candidates=[], awaiting_fine=False)
    routed = []
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _aim_context=ctx,
        state=State.NEEDS_HUMAN,
        _handle_web_aim_click=lambda reply: routed.append(reply),
    )
    bot._consume_web_pending()
    assert routed == [{"x": 500, "y": 400, "dir": 3, "layer": "mid"}]
    assert pending.pop("harvest:115") is None  # 取過一次就清空


def test_consume_web_pending_skips_during_awaiting_fine():
    """awaiting_fine 期間候選清單已經是舊的（放大手選退路用另一批圖）——不要誤配對。"""
    from miningbot.main import State
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    pending = PendingReplies()
    pending.push("harvest:115", {"x": 500, "y": 400, "dir": 3, "layer": "mid"})
    ctx = types.SimpleNamespace(harvest_id="115", candidates=[], awaiting_fine=True)
    routed = []
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _aim_context=ctx,
        state=State.NEEDS_HUMAN,
        _handle_web_aim_click=lambda reply: routed.append(reply),
    )
    bot._consume_web_pending()
    assert routed == []
    assert pending.pop("harvest:115") is not None  # 沒被撿走，留給下一輪/其他消費者


# ---------------------------------------------------------------------------
# 2026-07-31：交人工候選清單「無條件推網頁 + 扣住 Discord 圖等 🔀」
# ---------------------------------------------------------------------------


def test_push_web_aim_candidates_pushes_when_nobody_connected(monkeypatch):
    """連線閘拿掉：沒人連著也要推進 replay 緩衝（玩家是被 PING 叫來才開網頁的）。"""
    import numpy as np
    from tests.fake_bot import make_fake_bot, FakeFallback, FakeWebThread, FakeHarvestCtx
    import cv2
    monkeypatch.setattr(cv2, "imread", lambda p: np.zeros((8, 8, 3), np.uint8))
    pushed = []
    bot = make_fake_bot(
        bind=["_push_web_aim_candidates"],
        _web_thread=FakeWebThread(),
        _web_fallback=FakeFallback(fallback=True),     # 一條連線都沒有
        _encode_png=lambda img: b"png",
        _send_web_intervention_frames=lambda **kw: (
            pushed.append((kw["routing_key"], len(kw["frames"]))) or True),
    )
    rendered = [((1,), 0, "mid", "a.png"), ((2,), 3, "up", "b.png")]

    assert bot._push_web_aim_candidates(
        FakeHarvestCtx(harvest_id="144"), rendered, "summary") is True
    assert pushed == [("harvest:144", 2)]


def test_push_web_aim_candidates_pushes_every_swept_direction(monkeypatch):
    """採 158：整輪八個方位都要推，網頁才有方位切換列可以左右翻。

    實錄只有一顆歷史復原候選 → `_render_aim_shots` 只畫一張 → 網頁面板只有一張圖、
    切不到其他七個方位，玩家連上 27 秒後就按 🔀 退回 Discord。沒有候選的方位推原幀。
    """
    import numpy as np
    from miningbot.remote_aim import SweepShot
    from tests.fake_bot import make_fake_bot, FakeWebThread, FakeHarvestCtx
    import cv2
    monkeypatch.setattr(cv2, "imread", lambda p: np.zeros((8, 8, 3), np.uint8))
    pushed = []
    bot = make_fake_bot(
        bind=["_push_web_aim_candidates"],
        _web_thread=FakeWebThread(),
        _encode_png=lambda img: b"png",
        _wait_snapshot_ready=lambda path, budget: True,
        _send_web_intervention_frames=lambda **kw: (
            pushed.append(kw["frames"]) or True),
    )
    shots = [SweepShot("mid", d, "dir%d.png" % d, []) for d in range(8)]
    rendered = [((1,), 5, "mid", "dir5_aim.png")]      # 只有 dir5 有候選

    assert bot._push_web_aim_candidates(
        FakeHarvestCtx(harvest_id="158", shots=shots), rendered, "summary") is True
    frames = pushed[0]
    assert [dir_idx for dir_idx, _layer, _png in frames] == list(range(8))


def test_push_web_aim_candidates_returns_false_without_web_server():
    """沒有網頁伺服器 → 回 False，呼叫端照舊把候選疊圖發 Discord。"""
    from tests.fake_bot import make_fake_bot, FakeHarvestCtx
    bot = make_fake_bot(bind=["_push_web_aim_candidates"], _web_thread=None)
    assert bot._push_web_aim_candidates(
        FakeHarvestCtx(harvest_id="144"), [((1,), 0, "mid", "a.png")], "s") is False


def test_needs_human_ping_carries_url_and_arms_escalate(monkeypatch):
    """扣住候選疊圖時，交人工 PING 就是那條流程的「網頁在等你點」提醒。

    只吵一次：不另發提醒訊息，網址與 🔀 都掛在同一則 PING 上。
    """
    import miningbot.main as main_mod
    from tests.fake_bot import make_fake_bot
    sent = {}

    class _Messenger:
        def send_ping(self, harvest_id, reason, fallback, now, web_url=None):
            sent["web_url"] = web_url
            return "ping-mid"

    monkeypatch.setattr(main_mod.notify, "add_reaction",
                        lambda *a, **kw: (True, "HTTP 204"))
    bot = make_fake_bot(
        bind=["_send_needs_human_ping", "_arm_web_escalate_reaction"],
        _ping_messenger=_Messenger(),
        _web_url=lambda: "http://test:8765",
        _web_escalate={},
        _web_held_aim=("harvest:144", [("cap", ["a.png"])]),
    )
    assert bot._send_needs_human_ping(harvest_id="144", reason="全方位皆空") == "ping-mid"
    assert sent["web_url"] == "http://test:8765/intervention"
    assert bot._web_escalate == {"harvest:144": ("ping-mid", 1)}
    assert bot._web_held_aim is not None, "PING 發成功時要繼續扣著，等 🔀"


def test_needs_human_ping_failure_releases_held_images(monkeypatch):
    """PING 發不出去＝沒有 🔀 可按 → 扣住的圖立刻補發，不能永遠鎖在記憶體。"""
    import miningbot.main as main_mod
    from tests.fake_bot import make_fake_bot
    images = []
    monkeypatch.setattr(main_mod.notify, "send_images_message",
                        lambda t, c, cap, paths: images.append((cap, paths)))

    class _Messenger:
        def send_ping(self, **kw):
            return None

    bot = make_fake_bot(
        bind=["_send_needs_human_ping", "_release_web_held_aim"],
        _ping_messenger=_Messenger(),
        _web_url=lambda: "http://test:8765",
        _web_escalate={},
        _web_held_aim=("harvest:144", [("🎯 近失候選", ["a.png", "b.png"])]),
    )
    bot._send_needs_human_ping(harvest_id="144", reason="全方位皆空")

    assert images == [("🎯 近失候選", ["a.png", "b.png"])]
    assert bot._web_held_aim is None


def test_consume_web_pending_force_discord_releases_held_aim_images(monkeypatch):
    """玩家按 🔀 → 補發扣住的候選疊圖（NEEDS_HUMAN 不阻塞，靠這個 safe point 撿）。"""
    import miningbot.main as main_mod
    from miningbot.main import State
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot
    images = []
    monkeypatch.setattr(main_mod.notify, "send_images_message",
                        lambda t, c, cap, paths: images.append(cap))

    pending = PendingReplies()
    pending.push("control:force_discord:harvest:144", True)
    bot = make_fake_bot(
        bind=["_consume_web_pending", "_release_web_held_aim"],
        _web_pending=pending,
        _aim_context=None,
        state=State.NEEDS_HUMAN,
        _web_held_aim=("harvest:144", [("🎯 近失候選", ["a.png"])]),
    )
    bot._consume_web_pending()

    assert images == ["🎯 近失候選"]
    assert bot._web_held_aim is None


def test_web_aim_click_drops_held_images(monkeypatch):
    """玩家改在網頁點了 → Discord 那批扣住的圖直接丟掉，別事後才冒出來洗版。"""
    from tests.fake_bot import make_fake_bot
    bot = make_fake_bot(
        bind=["_handle_web_aim_click", "_release_web_held_aim"],
        _aim_context=types.SimpleNamespace(
            harvest_id="144", pose_net_rotations=0, pose_pitch_layer="mid"),
        _aim_busy=False,
        _web_escalate={"harvest:144": ("ping-mid", 1)},
        _web_held_aim=("harvest:144", [("cap", ["a.png"])]),
    )
    bot._handle_web_aim_click({"x": 10, "y": 20, "dir": 2, "layer": "mid"})

    assert bot._pending_aim is not None
    assert bot._web_held_aim is None
    assert bot._web_escalate == {}, "已在網頁處理，不必再輪詢那則 PING 的反應"


# ---------------------------------------------------------------------------
# 2026-07-28：回礦 awaiting_confirm 階段（Depth 已確認下礦，但
# cfg.reentry_remote_auto_resume=False 安全預設要求人工放行）補上網頁「好」／
# 「作廢」——原本這步只能切回 Discord 打字，玩家已經在網頁面板上卻被踢出去。
# ---------------------------------------------------------------------------


def test_consume_web_pending_routes_confirm_to_reentry_queue():
    """網頁「好」按鈕——跟 `跳過` 走同一條 reentry 指令路徑（同一個 pending slot）。"""
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    pending = PendingReplies()
    pending.push("control:confirm", {"cmd": "confirm"})
    calls = []
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _pending_reentry=None,
        _queue_reentry_reply=lambda raw, reply, source: calls.append((raw, reply.kind, source)),
    )
    bot._consume_web_pending()
    assert calls == [("好", "confirm", "web")]


def test_consume_web_pending_routes_void_to_reentry_queue():
    """網頁「作廢」按鈕——同上，換一個關鍵字。"""
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    pending = PendingReplies()
    pending.push("control:void", {"cmd": "void"})
    calls = []
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _pending_reentry=None,
        _queue_reentry_reply=lambda raw, reply, source: calls.append((raw, reply.kind, source)),
    )
    bot._consume_web_pending()
    assert calls == [("作廢", "void", "web")]


@pytest.mark.parametrize("cmd,raw,kind", [
    ("reroll", "重骰", "reroll"),
    ("sweep", "掃", "sweep"),
])
def test_consume_web_pending_routes_reroll_and_sweep(cmd, raw, kind):
    """網頁「重骰」／「重掃」按鈕——前端有按鈕但後端原本沒接，按了靜默消失。

    2026-08-01 使用者反映重骰沒作用；根因＝_consume_web_pending 只認
    confirm/void/skip，不認 reroll/sweep。
    """
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    pending = PendingReplies()
    pending.push(f"control:{cmd}", {"cmd": cmd})
    calls = []
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _pending_reentry=None,
        _queue_reentry_reply=lambda r, reply, source: calls.append((r, reply.kind, source)),
    )
    bot._consume_web_pending()
    assert calls == [(raw, kind, "web")]


def test_consume_web_pending_ignores_confirm_when_pending_reentry_busy():
    """上一則指令還沒被主迴圈消費——不搶隊，等下一輪（同 skip 既有慣例）。"""
    from miningbot.web_ipc import PendingReplies
    from tests.fake_bot import make_fake_bot

    pending = PendingReplies()
    pending.push("control:confirm", {"cmd": "confirm"})
    calls = []
    bot = make_fake_bot(
        bind=["_consume_web_pending"],
        _web_pending=pending,
        _pending_reentry=("上一則", object()),
        _queue_reentry_reply=lambda *a, **kw: calls.append(a),
    )
    bot._consume_web_pending()
    assert calls == []


class TestRrClickAndVerifyWebBroadcast:
    """_rr_click_and_verify 是 Discord/web 點擊共用尾段（_rr_click／_rr_click_from_web
    都會走到）；下礦後续步驟過去只靠 _rr_notify（Discord 純文字），網頁介入面板
    完全收不到——玩家點了圖之後看得到「下礦成功」卻不知道還要不要按什麼，
    只能切回 Discord。這裡驗證兩個分支都補上 _broadcast_intervention_result。
    """

    def _bot(self, monkeypatch):
        import numpy as np
        import miningbot.main as main_mod
        from miningbot.main import Bot

        class _StubBot:
            pass

        bot = _StubBot()
        bot._web_thread = None
        bot.logger = logging.getLogger("test_rr_verify")
        bot.log_discord = logging.getLogger("test_rr_verify")
        fake_frame = np.zeros((1080, 1920, 3), np.uint8)
        monkeypatch.setattr(main_mod.time, "sleep", lambda s: None)
        monkeypatch.setattr(main_mod.capture, "grab", lambda: fake_frame)
        monkeypatch.setattr(main_mod.ic, "click_at", lambda x, y: None)
        monkeypatch.setattr(main_mod.vision, "frame_mean_diff", lambda a, b: 0.0)
        monkeypatch.setattr(main_mod.ocr, "read_depth_is_surface", lambda *a, **kw: False)
        monkeypatch.setattr(main_mod.ocr, "read_depth_meters", lambda *a, **kw: 7100)
        monkeypatch.setattr(main_mod.game_data, "current_world_name", lambda: "Lucernia")
        monkeypatch.setattr(main_mod.game_data, "layer_for_depth", lambda w, d: "Shamrock")
        monkeypatch.setattr(main_mod.reentry_remote, "record_landing", lambda *a, **kw: None)
        import cv2
        monkeypatch.setattr(cv2, "imwrite", lambda *a, **kw: True)
        bot._rr_notify = lambda *a, **kw: (True, "")
        bot._rr_snap_dir = lambda: "."
        bot._rr_click_and_verify = types.MethodType(Bot._rr_click_and_verify, bot)
        # RR#42 點擊吸附走真實偵測器沒意義（fake_frame 是全黑）——這組測的是點擊後
        # 的三態驗證與廣播，吸附本身在 test_reentry_prediction.py 有自己的兩側夾。
        bot._rr_snap_click_to_board = lambda ctx, pos, frame: pos
        bot._broadcast_intervention_result = types.MethodType(
            Bot._broadcast_intervention_result, bot)
        bot._rr_ask_confirm_on_web = types.MethodType(Bot._rr_ask_confirm_on_web, bot)
        bot._send_web_intervention_frames = types.MethodType(
            Bot._send_web_intervention_frames, bot)
        return bot

    def test_descended_with_auto_resume_broadcasts_descended(self, monkeypatch):
        import miningbot.main as main_mod
        monkeypatch.setattr(main_mod.cfg, "reentry_remote_auto_resume", True)
        monkeypatch.setattr(main_mod.reentry_remote, "plan_click_verdict",
                            lambda *a, **kw: "descended")
        bot = self._bot(monkeypatch)
        results = []
        bot._broadcast_intervention_result = lambda ctx, verdict, summary, flow="reentry": (
            results.append((verdict, flow)))
        bot._rr_success = lambda ctx, outcome: None
        from tests.fake_bot import FakeReentryCtx
        ctx = FakeReentryCtx(episode_id="27")

        verdict = bot._rr_click_and_verify(ctx, (960, 540), None, "Shamrock", "m.png", "")

        assert verdict == "descended"
        assert results == [("descended", "reentry")]

    def test_descended_without_auto_resume_broadcasts_awaiting_confirm(self, monkeypatch):
        import miningbot.main as main_mod
        monkeypatch.setattr(main_mod.cfg, "reentry_remote_auto_resume", False)
        monkeypatch.setattr(main_mod.reentry_remote, "plan_click_verdict",
                            lambda *a, **kw: "descended")
        bot = self._bot(monkeypatch)
        results = []
        bot._broadcast_intervention_result = lambda ctx, verdict, summary, flow="reentry": (
            results.append((verdict, flow)))
        from tests.fake_bot import FakeReentryCtx
        ctx = FakeReentryCtx(episode_id="27")

        verdict = bot._rr_click_and_verify(ctx, (960, 540), None, "Shamrock", "m.png", "")

        assert verdict == "descended"
        assert results == [("awaiting_confirm", "reentry")]
        assert ctx.phase == "awaiting_confirm"

    def test_moved_unconfirmed_broadcasts_awaiting_confirm(self, monkeypatch):
        import miningbot.main as main_mod
        monkeypatch.setattr(main_mod.reentry_remote, "plan_click_verdict",
                            lambda *a, **kw: "moved_unconfirmed")
        bot = self._bot(monkeypatch)
        results = []
        bot._broadcast_intervention_result = lambda ctx, verdict, summary, flow="reentry": (
            results.append((verdict, flow)))
        from tests.fake_bot import FakeReentryCtx
        ctx = FakeReentryCtx(episode_id="27")

        verdict = bot._rr_click_and_verify(ctx, (960, 540), None, "Shamrock", "m.png", "")

        assert verdict == "moved_unconfirmed"
        assert results == [("awaiting_confirm", "reentry")]


def test_rr_execute_confirm_broadcasts_descended(monkeypatch):
    """awaiting_confirm 階段按「好」→ 廣播 descended，網頁面板才會收起。

    2026-08-01 使用者反映：確認後面板「不會消失」、還是活躍狀態，擔心誤點。
    根因＝_rr_execute 的 confirm 分支只呼叫 _rr_success、沒廣播 INTERVENTION_RESULT，
    前端 done=true 分支不觸發 → currentEvent 不清 → 點畫面仍送 reentry_click。
    """
    from tests.fake_bot import make_fake_bot, FakeReentryCtx
    import miningbot.reentry_remote as reentry_remote
    bot = make_fake_bot(bind=["_rr_execute"])
    ctx = FakeReentryCtx(episode_id="42")
    ctx.phase = "awaiting_confirm"
    bot._rr_ctx = ctx
    bot._pending_reentry = None
    bot._rr_embed_mid = None
    results = []
    bot._broadcast_intervention_result = lambda ctx, verdict, summary, flow="reentry": (
        results.append((verdict, flow)))
    bot._rr_success = lambda c, outcome: None
    bot._rr_notify = lambda *a, **kw: None
    bot._rr_edit_embed = lambda: None

    bot._rr_execute(reentry_remote.RemoteReply("confirm"))

    assert results == [("descended", "reentry")], (
        "確認後必須廣播 descended 讓網頁面板收起（done=true）")


# ---------------------------------------------------------------------------
# 2026-08-01 使用者反映：網頁走到 awaiting_confirm 只有一行字、一張圖都沒有，
# 「並不知道是不是真的下礦」。Discord 那條路一直有附「點擊處＋落點」兩張。
# ---------------------------------------------------------------------------


class TestAwaitingConfirmEvidenceOnWeb:

    def _bot_with_web(self, monkeypatch, tmp_path):
        bot = TestRrClickAndVerifyWebBroadcast()._bot(monkeypatch)
        bot._web_thread = _FakeWebThread()
        bot._rr_snap_dir = lambda: str(tmp_path)
        return bot

    def _paths(self, tmp_path):
        """marker 由 caller 傳進 `_rr_click_and_verify`；landing 是函式自己算的檔名
        （`ep{episode_id}_click{len(clicks)-1}_landing{zs}.png`，ctx.clicks 空＝-1）。"""
        mpath = tmp_path / "marker.png"
        lpath = tmp_path / "ep27_click-1_landing.png"
        mpath.write_bytes(b"marker-bytes")
        lpath.write_bytes(b"landing-bytes")
        return str(mpath), str(lpath)

    def test_confirm_pushes_two_labelled_frames_in_confirm_mode(
            self, monkeypatch, tmp_path):
        """證據圖要真的送到網頁，而且帶得出「哪張是哪張」＋確認模式。"""
        import miningbot.main as main_mod
        from miningbot.web_protocol import WebMessage
        from tests.fake_bot import FakeReentryCtx

        monkeypatch.setattr(main_mod.cfg, "reentry_remote_auto_resume", False)
        monkeypatch.setattr(main_mod.reentry_remote, "plan_click_verdict",
                            lambda *a, **kw: "descended")
        bot = self._bot_with_web(monkeypatch, tmp_path)
        mpath, lpath = self._paths(tmp_path)
        ctx = FakeReentryCtx(episode_id="27")

        bot._rr_click_and_verify(ctx, (960, 540), None, "Shamrock", mpath, "")

        calls = bot._web_thread.app.state.registry.calls
        metas = [c.payload for c in calls if isinstance(c, WebMessage)
                 and c.payload.get("event") == "INTERVENTION_FRAME"]
        assert [m.get("label") for m in metas] == ["點擊處", "落點"], (
            f"兩張證據圖要各自標名，實際：{metas}")
        needed = [c.payload for c in calls if isinstance(c, WebMessage)
                  and c.payload.get("event") == "INTERVENTION_NEEDED"]
        assert needed and needed[-1]["mode"] == "confirm", (
            "confirm 模式讓 client 顯示 好/重骰/作廢 而不是掃描那組鍵")
        assert b"landing-bytes" in calls, "落點圖的位元組要真的送出去"

    def test_result_broadcast_before_frames_push(self, monkeypatch, tmp_path):
        """順序不可對調：`_broadcast_intervention_result` 內含
        `end_intervention_replay()`，反過來寫會把剛推的證據圖清掉，晚到的連線
        又只剩空白面板（RR#34 同型）。"""
        import miningbot.main as main_mod
        from miningbot.web_protocol import WebMessage
        from tests.fake_bot import FakeReentryCtx

        monkeypatch.setattr(main_mod.cfg, "reentry_remote_auto_resume", False)
        monkeypatch.setattr(main_mod.reentry_remote, "plan_click_verdict",
                            lambda *a, **kw: "descended")
        bot = self._bot_with_web(monkeypatch, tmp_path)
        mpath, lpath = self._paths(tmp_path)

        bot._rr_click_and_verify(
            FakeReentryCtx(episode_id="27"), (960, 540), None, "Shamrock", mpath, "")

        events = [c.payload.get("event") for c in bot._web_thread.app.state.registry.calls
                  if isinstance(c, WebMessage)]
        assert events.index("INTERVENTION_RESULT") < events.index("INTERVENTION_FRAME")

    def test_summary_carries_measured_depth_not_just_declared_layer(
            self, monkeypatch, tmp_path):
        """玩家要判斷的是「有沒有點錯層」，bot 早就量到 depth/layer_seen 卻沒給看。"""
        import miningbot.main as main_mod
        from tests.fake_bot import FakeReentryCtx

        monkeypatch.setattr(main_mod.cfg, "reentry_remote_auto_resume", False)
        monkeypatch.setattr(main_mod.reentry_remote, "plan_click_verdict",
                            lambda *a, **kw: "descended")
        bot = self._bot_with_web(monkeypatch, tmp_path)
        mpath, _lpath = self._paths(tmp_path)
        summaries = []
        bot._broadcast_intervention_result = lambda ctx, verdict, summary, flow="reentry": (
            summaries.append(summary))

        bot._rr_click_and_verify(
            FakeReentryCtx(episode_id="27"), (960, 540), None, "Shamrock", mpath, "")

        assert summaries and "7100m" in summaries[0], summaries
        assert "相符" in summaries[0]
        # 不確定時的答案是「好」（原地不動），不是重骰
        assert "不確定也按好" in summaries[0]

    def test_missing_evidence_file_does_not_break_confirm(self, monkeypatch, tmp_path):
        """證據圖是加值路徑：讀不到就只送文字，不能炸掉確認流程。"""
        import miningbot.main as main_mod
        from tests.fake_bot import FakeReentryCtx

        monkeypatch.setattr(main_mod.cfg, "reentry_remote_auto_resume", False)
        monkeypatch.setattr(main_mod.reentry_remote, "plan_click_verdict",
                            lambda *a, **kw: "descended")
        bot = self._bot_with_web(monkeypatch, tmp_path)
        ctx = FakeReentryCtx(episode_id="27")

        verdict = bot._rr_click_and_verify(
            ctx, (960, 540), None, "Shamrock", str(tmp_path / "nope.png"), "")

        assert verdict == "descended"
        assert ctx.phase == "awaiting_confirm"


# ---------------------------------------------------------------------------
# 2026-08-01 使用者反映：點歪／指令被吃時人根本沒離開原地，重掃一圈＝多轉 8 次
# 45°、多花 ~25s，拍回來還是同一批畫面。「應該保持原地即可」。
# ---------------------------------------------------------------------------


def test_retry_reuses_frames_when_click_did_not_move_the_screen(monkeypatch):
    bot = _build_stub_bot_for_reentry(monkeypatch)
    replies = iter([{"x": 100, "y": 100}, {"x": 200, "y": 200}])
    bot._await_web_reentry_action = lambda routing_key: ("click", next(replies))
    verdicts = iter(["still_surface", "descended"])
    bot._rr_click_from_web = lambda ctx, x, y, dir_idx=None: next(verdicts)
    bot._rr_last_click_moved = False
    swept = []
    bot._rr_sweep_capture = lambda encode_for_web=False: (
        swept.append(1) or ([], 0, _STUB_PNGS))

    assert bot._reentry_await_player_click(_FakeCtx(), _STUB_PNGS) is True
    assert swept == [], "畫面沒動就別重掃——舊圖仍然有效"
    # 但還是要重推（清過重播緩衝，晚到的連線才補得到同一批圖）
    assert len(bot._sent_intervention_events) >= 2
    assert bot._sent_intervention_events[-1]["frames"] is _STUB_PNGS


def test_retry_resweeps_when_click_moved_the_screen(monkeypatch):
    """畫面有動＝可能被傳到別的重生點，舊圖作廢，那才非重掃不可。"""
    bot = _build_stub_bot_for_reentry(monkeypatch)
    replies = iter([{"x": 100, "y": 100}, {"x": 200, "y": 200}])
    bot._await_web_reentry_action = lambda routing_key: ("click", next(replies))
    verdicts = iter(["still_surface", "descended"])
    bot._rr_click_from_web = lambda ctx, x, y, dir_idx=None: next(verdicts)
    bot._rr_last_click_moved = True
    swept = []
    bot._rr_sweep_capture = lambda encode_for_web=False: (
        swept.append(1) or ([], 0, _STUB_PNGS))

    assert bot._reentry_await_player_click(_FakeCtx(), _STUB_PNGS) is True
    assert swept == [1]


def test_moved_unconfirmed_hands_over_to_confirm_instead_of_retrying(monkeypatch):
    """moved_unconfirmed 已經把 phase 設成 awaiting_confirm 並推了證據圖；
    再 retry 等於當場把確認面板洗掉，還一邊問「再點一次」一邊等「好」。"""
    bot = _build_stub_bot_for_reentry(monkeypatch)
    bot._await_web_reentry_action = lambda routing_key: ("click", {"x": 1, "y": 2})
    bot._rr_click_from_web = lambda ctx, x, y, dir_idx=None: "moved_unconfirmed"
    swept = []
    bot._rr_sweep_capture = lambda encode_for_web=False: (
        swept.append(1) or ([], 0, _STUB_PNGS))

    assert bot._reentry_await_player_click(_FakeCtx(), _STUB_PNGS) is True
    assert swept == []
    assert len(bot._sent_intervention_events) == 1, "只有開場那次推送"


def test_panel_confirm_mode_switches_buttons_and_blocks_clicks():
    """mode='confirm' 的那批圖是證據，不是要玩家點位置的掃描圖。"""
    html = _panel_html()
    assert "confirmMode = p.mode === 'confirm'" in html
    assert "sweepBtn.hidden = !isReentry || confirmMode" in html
    assert "confirmBtn.hidden = !confirmMode" in html
    # 點畫面在這階段沒有消費端，靜靜躺到 TTL 過期比直接說清楚更糟
    assert "if (confirmMode) {" in html
    assert "CONFIRM_HINT" in html
    # 兩張證據圖各自標名（標「方位 1/2」玩家分不出哪張是哪張）
    assert "frames[curFrame].label" in html


def test_panel_done_branch_clears_evidence_frames():
    """介入結束（done=true）清掉證據圖，否則面板「不會消失」、玩家以為還能點。

    2026-08-01 使用者反映：確認後訊息一直卡在頁面上、還是活躍狀態。
    """
    html = _panel_html()
    done_block = html.split("else if (done)")[1].split("} else if")[0]
    assert "currentEvent = null" in done_block
    assert "frames = []" in done_block
    assert "removeAttribute('src')" in done_block


def test_panel_centers_letterboxed_frame():
    """2026-07-27 瀏覽器實測：畫面靠左上貼齊，寬螢幕黑邊全擠在右側像沒載完。

    2026-08-01：canvas 改 <img>（與標註工具同管線）。置中靠 fitToView 計算
    pan = [(cw - natW * zoom) / 2, ...]——負值讓圖偏移到容器正中央。
    `sendClick` 靠 `snapshotImg.getBoundingClientRect()` 換算原生座標，
    transform 會被 rect 反映，座標自動跟著對。
    """
    html = _panel_html()
    assert "naturalWidth" in html and "naturalHeight" in html
    # 置中公式（fitToView）：cw/ch - naturalW/H * zoom → pan 偏移
    assert "container.clientWidth" in html and "container.clientHeight" in html
    # CSS transform 套在 <img> 上（不是 canvas）
    assert "snapshotImg.style.transform" in html
    # 點擊換算用 img 的 rect，不是 canvas
    assert "snapshotImg.getBoundingClientRect()" in html


# ---------------------------------------------------------------------------
# 防掛機：_await_web_action 阻塞期間必須照常按 Space 保活
# ---------------------------------------------------------------------------

def test_await_web_action_calls_antiafk_during_wait(monkeypatch):
    """無限等待迴圈阻塞主迴圈 → 防掛機分支（line 3164）跑不到。

    2026-08-04：使用者在回礦網頁介入等待期間被 Roblox 踢出。根因是
    `_await_web_action` 的 `while True` 卡住 `_tick()`，主迴圈防掛機
    永遠不執行。修法＝在等待迴圈內直接呼叫 `_antiafk_tick`。
    """
    import miningbot.main as main_mod
    from tests.fake_bot import make_fake_bot
    from miningbot.web_ipc import PendingReplies

    pending = PendingReplies()
    antiafk_calls = []

    def fake_antiafk(context):
        antiafk_calls.append(context)
        # 首次呼叫就推 force_discord，讓迴圈下一輪跳出
        if len(antiafk_calls) == 1:
            pending.push(f"control:force_discord:reentry:ep1", "stop")

    # time.sleep 不真睡——antiafk 回呼裡已推了 reply，下一輪立即返回
    monkeypatch.setattr(main_mod.time, "sleep", lambda s: None)

    bot = make_fake_bot(
        bind=["_await_web_action"],
        _web_pending=pending,
        _running=True,
        paused=False,
        _mine_resetting=False,
        _antiafk_tick=fake_antiafk,
    )

    kind, reply = bot._await_web_action("reentry:ep1")
    assert kind == "force_discord"
    assert antiafk_calls == ["網頁介入等待"]


# ---------------------------------------------------------------------------
# 手機直向介入面板（mobile-intervention-panel tickets 03~08）
#
# seam：render_intervention_html() 渲染字串 marker（同 TestPanelHasReentryControls
# 等既有面板測試標準）。實作策略：桌機的 #side 側欄與手機抽屜共用同一個 DOM
# 元素——CSS media query（窄寬＋直向）把 #side 從右側欄重打造成底部抽屜，
# 所以只有一組按鍵、不需複製、不需 location-independent binding（ticket 02 因此
# 不需要）。手勢行為（展開／收回）不在此自動化，留實機驗收。
# ---------------------------------------------------------------------------


class TestPanelMobilePortraitLayout:
    """ticket 03：窄寬＋直向時圖全螢幕、底部把手；桌機版面不退步。"""

    def test_narrow_portrait_media_query_present(self):
        html = _panel_html()
        assert "@media" in html
        # 直向條件——區分手機版與桌機版的關鍵 marker
        assert "orientation: portrait" in html or "orientation:portrait" in html

    def test_drawer_handle_element_present(self):
        html = _panel_html()
        assert 'id="drawer-handle"' in html

    def test_desktop_sidebar_and_main_still_present(self):
        """桌機版面不退步：側欄、主體、容器都在（手機版是疊加、不是取代）。"""
        html = _panel_html()
        assert 'id="side"' in html
        assert 'id="main"' in html
        assert 'id="container"' in html


class TestPanelHandleStatusBar:
    """ticket 04：把手身兼狀態列——顯示方位／狀態／連線，並隨狀態更新。"""

    def test_handle_has_status_text_element(self):
        html = _panel_html()
        assert 'handle-text' in html

    def test_handle_update_function_present(self):
        """把手文字由 JS 從方位／狀態／連線組合，並在狀態變更時更新（marker）。"""
        html = _panel_html()
        assert 'updateHandle' in html


class TestPanelDrawerExpandCollapse:
    """ticket 05：把手上拉／點擊展開抽屜、再點收回。"""

    def test_drawer_toggle_function_present(self):
        html = _panel_html()
        assert 'toggleDrawer' in html

    def test_drawer_open_toggled_via_classlist(self):
        """JS 用 classList 操作 drawer-open（CSS 已備 .drawer-open 規則）。"""
        html = _panel_html()
        assert 'classList' in html
        assert "drawer-open" in html
