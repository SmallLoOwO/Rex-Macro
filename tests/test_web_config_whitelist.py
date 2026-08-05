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
    def test_player_facing_fields_in_whitelist(self):
        # spec §6 原四個 play-style 欄位 ＋ detection_disabled_tiers（08-02 例外：
        # 玩家頻繁切換「哪些階級算稀有」，其他偵測門檻仍 AI-agent-only 不在此）。
        # sweep_pitch_enabled 已移除（2026-08-05 俯仰層掃描停用）。
        assert WEB_CONFIGURABLE_FIELDS == frozenset({
            "reentry_mode",
            "reentry_target_layer",
            "reentry_yaw_sample_sweep",
            "detection_disabled_tiers",
        })

    @pytest.mark.parametrize("field", [
        "reentry_mode", "reentry_target_layer",
        "reentry_yaw_sample_sweep",
        "detection_disabled_tiers",
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

    @pytest.mark.parametrize("value", [0, 1, "true", None, "yes"])
    def test_bool_fields_reject_non_bool(self, value):
        assert validate_value("reentry_yaw_sample_sweep", value) is False

    def test_detection_disabled_tiers_accepts_list_of_valid_tiers(self):
        # 合法值＝game_data.HIGH_TIER_NAMES（Exotic+）的 list 子集；空 list＝全啟用
        assert validate_value("detection_disabled_tiers", ["Exotic", "Zenith"]) is True
        assert validate_value("detection_disabled_tiers", []) is True

    @pytest.mark.parametrize("value", [
        "Exotic",                    # 單一字串不是 list
        ["Rare", "Common"],          # 不在 HIGH_TIER_NAMES（Exotic+）內
        123, None, True, ("Exotic",),  # 非 list
    ])
    def test_detection_disabled_tiers_rejects_invalid(self, value):
        assert validate_value("detection_disabled_tiers", value) is False

    def test_non_whitelisted_field_always_invalid(self):
        assert validate_value("tracker_core_min_area", 80) is False
        assert validate_value("nonexistent", "x") is False
