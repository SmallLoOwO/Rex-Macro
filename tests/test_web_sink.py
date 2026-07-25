"""WebEventSink：EventLog 事件 → WebSocket 廣播純函式。"""
import pytest
from miningbot.web_sink import WebEventSink, format_event_for_web


class TestFormatEventForWeb:
    def test_needs_human_event_formats(self):
        # 模擬 EventLog record（看 miningbot.events 結構）
        rec = type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {"reason": "稀有礦未自動命中", "harvest_id": "007"},
        })()
        msg = format_event_for_web(rec)
        assert msg is not None
        assert msg.type == "event"
        assert msg.payload["event"] == "NEEDS_HUMAN"
        assert msg.payload["harvest_id"] == "007"
        assert msg.payload["flow"] == "harvest"

    def test_harvest_success_formats(self):
        rec = type("Rec", (), {
            "type": "HARVEST_SUCCESS",
            "meta": {"mineral": "Mythic Tin", "harvest_id": "007"},
        })()
        msg = format_event_for_web(rec)
        assert msg is not None
        assert msg.payload["event"] == "HARVEST_SUCCESS"
        assert msg.payload["mineral"] == "Mythic Tin"

    def test_reentry_start_formats_with_attempt(self):
        rec = type("Rec", (), {
            "type": "REENTRY_START",
            "meta": {"attempts": 2},
        })()
        msg = format_event_for_web(rec)
        assert msg is not None
        assert msg.payload["flow"] == "reentry"
        assert msg.payload["attempts"] == 2  # 與 notify.py m.get('attempts', '?') 同慣例

    def test_unknown_event_returns_none(self):
        # 不在白名單的事件（PAUSED / RESUMED / 心跳）不送，避免洗 web client
        rec = type("Rec", (), {"type": "PAUSED", "meta": {}})()
        assert format_event_for_web(rec) is None

    def test_event_meta_carried_through(self):
        rec = type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {"reason": "X", "harvest_id": "007", "rotation_hint": "（試試方位 3）"},
        })()
        msg = format_event_for_web(rec)
        assert msg is not None
        assert msg.payload["reason"] == "X"
        assert msg.payload["rotation_hint"] == "（試試方位 3）"


class TestWebEventSinkCall:
    def test_sink_calls_broadcast_for_relevant_event(self):
        calls = []
        sink = WebEventSink(broadcast_callback=lambda msg: calls.append(msg))
        rec = type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {"reason": "X", "harvest_id": "007"},
        })()
        sink(rec)
        assert len(calls) == 1
        assert calls[0].payload["event"] == "NEEDS_HUMAN"

    def test_sink_skips_irrelevant_event(self):
        calls = []
        sink = WebEventSink(broadcast_callback=lambda msg: calls.append(msg))
        rec = type("Rec", (), {"type": "PAUSED", "meta": {}})()
        sink(rec)
        assert calls == []

    def test_sink_broadcast_exception_does_not_raise(self):
        # 廣播失敗（client 斷線等）不該炸主迴圈
        def explode(msg):
            raise RuntimeError("client gone")
        sink = WebEventSink(broadcast_callback=explode)
        rec = type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {"reason": "X", "harvest_id": "007"},
        })()
        sink(rec)  # 不該丟例外
