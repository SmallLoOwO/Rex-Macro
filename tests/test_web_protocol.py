"""WebSocket 訊息協議：dataclass、序列化、座標還原。"""
import json
import pytest
from miningbot.web_protocol import WebMessage, serialize_message, parse_message


class TestMessageRoundtrip:
    def test_event_message_serializes(self):
        msg = WebMessage(type="event", payload={"event": "NEEDS_HUMAN", "harvest_id": "007"})
        s = serialize_message(msg)
        assert json.loads(s) == {"type": "event", "payload": {"event": "NEEDS_HUMAN", "harvest_id": "007"}}

    def test_command_message_serializes(self):
        msg = WebMessage(type="command", payload={"cmd": "fire_at", "x": 851, "y": 189})
        s = serialize_message(msg)
        parsed = json.loads(s)
        assert parsed["type"] == "command"
        assert parsed["payload"]["cmd"] == "fire_at"

    def test_roundtrip_preserves_message(self):
        msg = WebMessage(type="event", payload={"event": "HARVEST_SUCCESS"})
        assert parse_message(serialize_message(msg)) == msg


class TestParseValidation:
    def test_parse_invalid_json_returns_none(self):
        assert parse_message("not json") is None

    def test_parse_missing_type_returns_none(self):
        assert parse_message('{"payload": {}}') is None

    def test_parse_missing_payload_returns_none(self):
        assert parse_message('{"type": "event"}') is None

    def test_parse_payload_not_dict_returns_none(self):
        assert parse_message('{"type": "event", "payload": "string"}') is None

    def test_parse_type_not_string_returns_none(self):
        assert parse_message('{"type": 123, "payload": {}}') is None
