# tests/test_web_config_whitelist.py
"""玩家可在網頁改的 Config 欄位白名單。

門檻、ROI、偵測參數完全不在此——AI agent 改 code，不在網頁。"""
import pytest
from miningbot.web_config_whitelist import (
    WEB_CONFIGURABLE_FIELDS,
    is_web_configurable,
    validate_value,
)


class TestWhitelist:
    def test_four_player_facing_fields_in_whitelist(self):
        # spec §6：就這四個
        assert WEB_CONFIGURABLE_FIELDS == frozenset({
            "reentry_mode",
            "reentry_target_layer",
            "reentry_yaw_sample_sweep",
            "sweep_pitch_enabled",
        })

    @pytest.mark.parametrize("field", [
        "reentry_mode", "reentry_target_layer",
        "reentry_yaw_sample_sweep", "sweep_pitch_enabled",
    ])
    def test_whitelisted_field_passes(self, field):
        assert is_web_configurable(field) is True

    @pytest.mark.parametrize("field", [
        "tracker_core_min_area",      # 偵測門檻
        "reentry_game_region",        # ROI
        "discord_bot_token",          # 機密
        "log_dir",                    # 系統路徑
        "reentry_teleport_diff",      # 偵測門檻
        "",        "nonexistent_field",
    ])
    def test_non_whitelisted_field_rejected(self, field):
        assert is_web_configurable(field) is False


class TestValidateValue:
    @pytest.mark.parametrize("value", ["off", "remote", "auto"])
    def test_reentry_mode_valid_values(self, value):
        assert validate_value("reentry_mode", value) is True

    @pytest.mark.parametrize("value", ["garbage", "", "OFF", "Remote", 123, None, True])
    def test_reentry_mode_invalid_values(self, value):
        assert validate_value("reentry_mode", value) is False

    @pytest.mark.parametrize("value", ["Mantle Layer", "Core Layer", ""])
    def test_reentry_target_layer_accepts_string(self, value):
        # 層名是任意字串，由 game_data 提供選項；空字串也允許（fallback）
        assert validate_value("reentry_target_layer", value) is True

    @pytest.mark.parametrize("value", [123, None, True, ["list"]])
    def test_reentry_target_layer_rejects_non_string(self, value):
        assert validate_value("reentry_target_layer", value) is False

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_fields_accept_bool(self, value):
        assert validate_value("reentry_yaw_sample_sweep", value) is True
        assert validate_value("sweep_pitch_enabled", value) is True

    @pytest.mark.parametrize("value", [0, 1, "true", None, "yes"])
    def test_bool_fields_reject_non_bool(self, value):
        assert validate_value("reentry_yaw_sample_sweep", value) is False
        assert validate_value("sweep_pitch_enabled", value) is False

    def test_non_whitelisted_field_always_invalid(self):
        assert validate_value("tracker_core_min_area", 80) is False
        assert validate_value("nonexistent", "x") is False
