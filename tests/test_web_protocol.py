"""WebSocket 訊息協議：dataclass、序列化、座標還原。"""
import json
import pytest
from miningbot.web_protocol import (
    WebMessage,
    serialize_message,
    parse_message,
    client_to_native_coords,
)


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


class TestClientToNativeCoords:
    def test_no_zoom_no_pan(self):
        # canvas 跟原生同尺寸，點哪是哪
        assert client_to_native_coords(
            client_xy=(960, 540),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
        ) == (960, 540)

    def test_canvas_half_size(self):
        # canvas 顯示 960×540（縮小 2x），點 (480, 270) → 原生 (960, 540)
        assert client_to_native_coords(
            client_xy=(480, 270),
            canvas_size=(960, 540),
            native_size=(1920, 1080),
        ) == (960, 540)

    def test_with_pan_offset(self):
        # 玩家 pinch-zoom 後平移了 canvas 內容（pan_offset 是 canvas 視口左上角相對原點的位移）
        # 點 canvas (100, 100)、pan_offset (50, 50)、canvas 跟原生同尺寸
        # → 原生座標 (100+50, 100+50) = (150, 150)
        assert client_to_native_coords(
            client_xy=(100, 100),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
            pan_offset=(50, 50),
        ) == (150, 150)

    def test_with_explicit_zoom(self):
        # canvas 顯示原圖 zoom=2（顯示更大），點 canvas (100, 100) →
        # canvas_size 仍 1920×1080，但原圖被 zoom 2x 後只顯示 1/2 區域
        # (100, 100) / zoom=2 → (50, 50) 原生；加 pan_offset (0,0) → (50, 50)
        assert client_to_native_coords(
            client_xy=(100, 100),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
            zoom=2.0,
        ) == (50, 50)

    def test_combined_zoom_and_pan(self):
        # canvas 顯示 960×540、zoom 2x、pan_offset (10, 10)
        # 玩家點 canvas (200, 100)
        # step1：把 canvas 座標還原到「未 zoom 的 canvas 座標」= (200, 100) / 2 = (100, 50)
        # step2：把「未 zoom 的 canvas 座標」映射到 native = (100, 50) * (1920/960, 1080/540) = (200, 100)
        # step3：加 pan_offset（在 native 空間加）= (200+10, 100+10) = (210, 110)
        # 簡化：演算法先除 zoom、再 scale、再加 pan
        assert client_to_native_coords(
            client_xy=(200, 100),
            canvas_size=(960, 540),
            native_size=(1920, 1080),
            pan_offset=(10, 10),
            zoom=2.0,
        ) == (210, 110)

    def test_clamps_to_native_bounds(self):
        # 點出界：clamp 到 [0, native_w-1] / [0, native_h-1]
        assert client_to_native_coords(
            client_xy=(-100, -100),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
        ) == (0, 0)
        assert client_to_native_coords(
            client_xy=(10000, 10000),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
        ) == (1919, 1079)
