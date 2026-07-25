# tests/test_web_config_persistence.py
"""P3 玩家設定面板：config_overrides.json 讀寫純函式。"""
import json
from miningbot.web_config_persistence import (
    load_overrides, save_overrides, apply_overrides_to_config,
)


class TestLoadOverrides:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_overrides(str(tmp_path / "nonexistent.json")) == {}

    def test_valid_json_returns_dict(self, tmp_path):
        p = tmp_path / "overrides.json"
        p.write_text(json.dumps({"reentry_mode": "auto", "sweep_pitch_enabled": True}))
        result = load_overrides(str(p))
        assert result == {"reentry_mode": "auto", "sweep_pitch_enabled": True}

    def test_corrupted_json_returns_empty(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {")
        assert load_overrides(str(p)) == {}

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("")
        assert load_overrides(str(p)) == {}


class TestSaveOverrides:
    def test_save_new_field(self, tmp_path):
        p = str(tmp_path / "overrides.json")
        new = save_overrides(p, "reentry_mode", "auto", current_overrides={})
        assert new == {"reentry_mode": "auto"}
        # 檔案寫入
        with open(p) as f:
            assert json.load(f) == {"reentry_mode": "auto"}

    def test_save_merges_existing(self, tmp_path):
        p = str(tmp_path / "overrides.json")
        # 第一次存 reentry_mode
        first = save_overrides(p, "reentry_mode", "auto", current_overrides={})
        # 第二次存 sweep_pitch_enabled，保留既有
        second = save_overrides(p, "sweep_pitch_enabled", True, current_overrides=first)
        assert second == {"reentry_mode": "auto", "sweep_pitch_enabled": True}

    def test_save_overwrites_same_field(self, tmp_path):
        p = str(tmp_path / "overrides.json")
        first = save_overrides(p, "reentry_mode", "auto", current_overrides={})
        second = save_overrides(p, "reentry_mode", "off", current_overrides=first)
        assert second == {"reentry_mode": "off"}

    def test_save_does_not_mutate_input(self, tmp_path):
        p = str(tmp_path / "overrides.json")
        original = {"reentry_mode": "auto"}
        result = save_overrides(p, "sweep_pitch_enabled", True, current_overrides=original)
        # 輸入 dict 不該被改
        assert original == {"reentry_mode": "auto"}
        assert result == {"reentry_mode": "auto", "sweep_pitch_enabled": True}

    def test_save_overrides_reloads_when_current_overrides_none(self, tmp_path):
        """current_overrides=None 時重讀檔；不依賴 caller 維護 in-memory cache。

        場景：HTTP POST 存了 reentry_mode=auto，稍後 WS config_set 存另一欄——
        WS caller 不知道 HTTP 那次寫了什麼，傳 None 該重讀檔，不能覆掉 reentry_mode。
        """
        p = str(tmp_path / "overrides.json")
        # 先寫一個既有 override（模擬另一條路徑已寫檔）
        save_overrides(p, "reentry_mode", "auto", current_overrides={})
        # 另一個 caller 不知道前一個，傳 None → 該重讀
        result = save_overrides(p, "sweep_pitch_enabled", True)
        assert result == {"reentry_mode": "auto", "sweep_pitch_enabled": True}


class TestApplyOverridesToConfig:
    def test_apply_whitelisted_field(self):
        from miningbot.config import Config
        cfg = Config()
        cfg.reentry_mode = "off"  # 先設非預設值
        applied = apply_overrides_to_config(cfg, {"reentry_mode": "auto"})
        assert "reentry_mode" in applied
        assert cfg.reentry_mode == "auto"

    def test_apply_skips_non_whitelisted(self):
        from miningbot.config import Config
        cfg = Config()
        original_threshold = cfg.tracker_core_min_area
        applied = apply_overrides_to_config(
            cfg, {"tracker_core_min_area": 999, "reentry_mode": "auto"},
        )
        # 非白名單欄位略過
        assert cfg.tracker_core_min_area == original_threshold
        assert "tracker_core_min_area" not in applied
        assert "reentry_mode" in applied

    def test_apply_skips_invalid_value(self):
        # reentry_mode 只接 off/remote/auto；"garbage" 該被 web_config_whitelist 拒
        from miningbot.config import Config
        cfg = Config()
        original = cfg.reentry_mode
        applied = apply_overrides_to_config(cfg, {"reentry_mode": "garbage"})
        assert cfg.reentry_mode == original  # 沒被改
        assert applied == []

    def test_apply_multiple_whitelisted(self):
        from miningbot.config import Config
        cfg = Config()
        applied = apply_overrides_to_config(cfg, {
            "reentry_mode": "auto",
            "sweep_pitch_enabled": True,
        })
        assert set(applied) == {"reentry_mode", "sweep_pitch_enabled"}
        assert cfg.reentry_mode == "auto"
        assert cfg.sweep_pitch_enabled is True
