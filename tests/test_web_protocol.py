"""WebSocket 訊息協議：dataclass、序列化、座標還原。"""
import json
import pytest
from miningbot.web_protocol import (
    WebMessage,
    serialize_message,
    parse_message,
    client_to_native_coords,
    parse_fire_at_payload,
    parse_reentry_click_payload,
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


class TestParseFireAtPayload:
    """P5 Task 1：parser 變 thin validator——client 直接送原生 x/y，不再還原座標。

    schema：{cmd, flow, harvest_id|attempt_id, x: int[0,1920), y: int[0,1080)}。
    """

    def test_basic_with_harvest_id(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "x": 960, "y": 540},
        )
        assert result == {"flow": "harvest", "x": 960, "y": 540, "harvest_id": "007"}

    def test_attempt_id_used_for_reentry_flow(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "reentry", "attempt_id": "attempt_3",
                     "x": 100, "y": 100},
        )
        assert result is not None
        assert result["flow"] == "reentry"
        assert result["attempt_id"] == "attempt_3"
        assert result["x"] == 100
        assert result["y"] == 100

    def test_missing_cmd_returns_none(self):
        result = parse_fire_at_payload(
            payload={"flow": "harvest", "harvest_id": "007", "x": 100, "y": 100},
        )
        assert result is None

    def test_missing_flow_returns_none(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "harvest_id": "007", "x": 100, "y": 100},
        )
        assert result is None

    def test_missing_both_ids_returns_none(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "x": 100, "y": 100},
        )
        assert result is None

    def test_missing_x_returns_none(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007", "y": 100},
        )
        assert result is None

    def test_missing_y_returns_none(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007", "x": 100},
        )
        assert result is None

    def test_x_out_of_range_high_returns_none(self):
        # x=1920 超界（valid range [0, 1920)）
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "x": 1920, "y": 540},
        )
        assert result is None

    def test_x_negative_returns_none(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "x": -1, "y": 540},
        )
        assert result is None

    def test_y_out_of_range_high_returns_none(self):
        # y=1080 超界（valid range [0, 1080)）
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "x": 960, "y": 1080},
        )
        assert result is None

    def test_x_not_int_returns_none(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "x": "abc", "y": 540},
        )
        assert result is None

    def test_x_float_returns_none(self):
        # 嚴格 int；float 不可（避免 960.5 vs 960 模糊）
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "x": 960.5, "y": 540},
        )
        assert result is None

    def test_x_bool_returns_none(self):
        # bool 是 int 子類別，但語意不該被當座標
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "007",
                     "x": True, "y": 540},
        )
        assert result is None

    def test_dir_and_layer_carried_through(self):
        # 2026-07-27：harvest 候選清單點擊帶方位＋俯仰層，bot 要先轉/調再開火
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "115",
                     "x": 500, "y": 400, "dir": 3, "layer": "up"},
        )
        assert result["dir"] == 3
        assert result["layer"] == "up"

    def test_dir_out_of_range_omitted(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "115",
                     "x": 500, "y": 400, "dir": 9},
        )
        assert "dir" not in result

    def test_layer_invalid_value_omitted(self):
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "115",
                     "x": 500, "y": 400, "layer": "sideways"},
        )
        assert "layer" not in result

    def test_missing_dir_and_layer_still_works(self):
        # 舊 client（manual survey 單幀點擊）沒帶 dir/layer——向下相容
        result = parse_fire_at_payload(
            payload={"cmd": "fire_at", "flow": "harvest", "harvest_id": "115",
                     "x": 500, "y": 400},
        )
        assert "dir" not in result and "layer" not in result


class TestParseReentryClickPayload:
    """P5 Task 1：reentry_click 同樣只收 attempt_id + x/y（thin validator）。"""

    def test_basic(self):
        result = parse_reentry_click_payload(
            payload={"cmd": "reentry_click", "flow": "reentry",
                     "attempt_id": "attempt_2", "x": 960, "y": 540},
        )
        assert result == {"flow": "reentry", "x": 960, "y": 540,
                          "attempt_id": "attempt_2"}

    def test_missing_attempt_id_returns_none(self):
        result = parse_reentry_click_payload(
            payload={"cmd": "reentry_click", "flow": "reentry", "x": 100, "y": 100},
        )
        assert result is None

    def test_missing_xy_returns_none(self):
        result = parse_reentry_click_payload(
            payload={"cmd": "reentry_click", "flow": "reentry",
                     "attempt_id": "attempt_2"},
        )
        assert result is None


# ---------------------------------------------------------------------------
# 2026-07-26：reentry_click 多帶選用的 dir（1~8）。
#
# 面板顯示的是八方位掃描當下的畫面，玩家點的是「第 N 張裡的某個位置」。
# 沒有 dir，bot 只會在**當下面向**點那個座標——等於對著別的方向開槍。
# ---------------------------------------------------------------------------
from miningbot.web_protocol import parse_reentry_click_payload as _parse_rc


def _rc(**over):
    p = {"cmd": "reentry_click", "flow": "reentry", "attempt_id": "26",
         "x": 100, "y": 200}
    p.update(over)
    return p


class TestReentryClickDirection:
    def test_dir_passed_through(self):
        assert _parse_rc(_rc(dir=5))["dir"] == 5

    def test_dir_optional_for_single_frame_clients(self):
        """舊 client（單幀模式）不帶 dir——維持原行為，不可因此整包被拒。"""
        parsed = _parse_rc(_rc())
        assert parsed is not None and "dir" not in parsed

    def test_dir_boundaries_accepted(self):
        assert _parse_rc(_rc(dir=1))["dir"] == 1
        assert _parse_rc(_rc(dir=8))["dir"] == 8

    def test_out_of_range_dir_is_dropped_not_clamped(self):
        """超界寧可不轉，也不要轉到錯的方位（clamp 會靜默點錯地方）。"""
        for bad in (0, 9, -1, 100):
            assert "dir" not in _parse_rc(_rc(dir=bad))

    def test_non_integer_dir_dropped(self):
        for bad in ("3", 3.5, None, True, [3]):
            assert "dir" not in _parse_rc(_rc(dir=bad))

    def test_invalid_payload_still_rejected_with_dir(self):
        """dir 合法不能讓壞座標矇混過關。"""
        assert _parse_rc(_rc(dir=3, x=-5)) is None
        assert _parse_rc(_rc(dir=3, x=1920)) is None
