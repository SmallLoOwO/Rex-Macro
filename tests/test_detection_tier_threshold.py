"""偵測階級勾選系統（detection_disabled_tiers）回歸測試（2026-08-02）。

classify_found_ore 在 rare 命中後檢查 tier 是否被排除（在 disabled set 裡）；
效果蔓延到面板色檢／救援／採集驗證／通知標注。
色相閘也跟著 disabled set 走（effective_whitelist_hues / effective_low_tier_hues）。
支援非連續選擇（例如只關 Exquisite 但保留 Exotic + Transcendent+）。
"""
import pytest

from miningbot import game_data
from miningbot.game_data import (
    classify_found_ore, set_detection_disabled_tiers,
    get_detection_disabled_tiers, format_detection_status,
    effective_whitelist_hues, effective_low_tier_hues,
    TIER_HUES, HIGH_TIER_NAMES, _is_detection_disabled,
)
from miningbot.web_config_whitelist import is_web_configurable, validate_value


@pytest.fixture(autouse=True)
def _reset_tier():
    """每個測試前後重設排除清單，避免跨測試污染。"""
    set_detection_disabled_tiers(set())
    yield
    set_detection_disabled_tiers(set())


# ── classify_found_ore 階級閘 ──────────────────────────────────────────────

class TestClassifyTierFilter:
    def test_no_disabled_exotic_is_rare(self):
        """無排除（預設）→ Exotic 判 rare。"""
        assert classify_found_ore("demonizine")[0] == "rare"

    def test_disabled_exotic_becomes_common(self):
        """排除 Exotic → demonizine(Exotic) 判 common。"""
        set_detection_disabled_tiers({"Exotic"})
        assert classify_found_ore("demonizine")[0] == "common"

    def test_disabled_exotic_exquisite_still_rare(self):
        """排除 Exotic → Exquisite 礦仍判 rare。"""
        set_detection_disabled_tiers({"Exotic"})
        kind, info = classify_found_ore("confined cataclysm")
        assert kind == "rare"
        assert info.get("tier") == "Exquisite"

    def test_non_contiguous_exotic_on_exquisite_off(self):
        """非連續：Exotic 開、Exquisite 關 → Exotic=rare、Exquisite=common。"""
        set_detection_disabled_tiers({"Exquisite"})
        assert classify_found_ore("demonizine")[0] == "rare"      # Exotic
        assert classify_found_ore("confined cataclysm")[0] == "common"  # Exquisite

    def test_disabled_does_not_affect_common(self):
        """排除清單不影響 common 礦（Surreal/Mythic 排除清單）。"""
        set_detection_disabled_tiers({"Exotic"})
        assert classify_found_ore("peppermint core")[0] == "common"

    def test_disabled_does_not_affect_unknown(self):
        """排除清單不影響 unknown 礦。"""
        set_detection_disabled_tiers({"Exotic"})
        assert classify_found_ore("zzzznonexistent")[0] == "unknown"


# ── _is_detection_disabled 純函式 ───────────────────────────────────────────

class TestIsDetectionDisabled:
    def test_not_disabled(self):
        set_detection_disabled_tiers({"Exotic"})
        assert not _is_detection_disabled({"tier": "Exquisite"})

    def test_disabled(self):
        set_detection_disabled_tiers({"Exotic"})
        assert _is_detection_disabled({"tier": "Exotic"})

    def test_empty_disabled_set(self):
        assert not _is_detection_disabled({"tier": "Exotic"})


# ── effective_whitelist_hues / effective_low_tier_hues ─────────────────────

class TestEffectiveHues:
    BASE_WL = (46.0, 70.0, 128.0, 210.0, 219.0, 334.0)
    BASE_LOW = (0.0, 30.0, 165.0, 280.0, 305.0)

    def test_no_disabled_unchanged(self):
        assert effective_whitelist_hues(set(), self.BASE_WL) == self.BASE_WL
        assert effective_low_tier_hues(set(), self.BASE_LOW) == self.BASE_LOW

    def test_disabled_exotic_drops_46(self):
        wl = effective_whitelist_hues({"Exotic"}, self.BASE_WL)
        assert 46.0 not in wl
        assert 128.0 in wl

    def test_disabled_exotic_adds_46_to_low(self):
        low = effective_low_tier_hues({"Exotic"}, self.BASE_LOW)
        assert 46.0 in low

    def test_disabled_exotic_exquisite_drops_both(self):
        wl = effective_whitelist_hues({"Exotic", "Exquisite"}, self.BASE_WL)
        assert 46.0 not in wl
        assert 128.0 not in wl
        assert 210.0 in wl

    def test_non_contiguous_disabled(self):
        """排除 Exquisite（但 Exotic 未排除）→ 只掉 128。"""
        wl = effective_whitelist_hues({"Exquisite"}, self.BASE_WL)
        assert 46.0 in wl   # Exotic still in
        assert 128.0 not in wl  # Exquisite dropped
        assert 210.0 in wl


# ── format_detection_status ────────────────────────────────────────────────

class TestFormatStatus:
    def test_all_on(self):
        assert format_detection_status(set()) == "全部（Exotic+）"

    def test_contiguous_exotic_off(self):
        assert "Exquisite" in format_detection_status({"Exotic"})

    def test_contiguous_two_off(self):
        assert "Transcendent" in format_detection_status({"Exotic", "Exquisite"})

    def test_non_contiguous(self):
        s = format_detection_status({"Exquisite"})
        assert "Exotic" in s
        assert "Transcendent" in s

    def test_all_high_disabled_warning(self):
        """Trans+ 全關 → 警告。"""
        trans_plus = {t for t in HIGH_TIER_NAMES
                      if game_data._TIER_ORDER[t] >= game_data._TIER_ORDER["Transcendent"]}
        s = format_detection_status(trans_plus)
        assert "Transcendent" in s  # has warning text


# ── web config 白名單 + 驗證 ─────────────────────────────────────────────────

class TestWebConfig:
    def test_field_is_configurable(self):
        assert is_web_configurable("detection_disabled_tiers")

    def test_valid_list_accepted(self):
        assert validate_value("detection_disabled_tiers", ["Exotic"])
        assert validate_value("detection_disabled_tiers", ["Exotic", "Exquisite"])
        assert validate_value("detection_disabled_tiers", [])

    def test_invalid_value_rejected(self):
        assert not validate_value("detection_disabled_tiers", "Exotic")  # must be list
        assert not validate_value("detection_disabled_tiers", ["exotic"])  # case
        assert not validate_value("detection_disabled_tiers", ["Rare"])  # not high tier
        assert not validate_value("detection_disabled_tiers", 123)


# ── HIGH_TIERS 唯一來源 ─────────────────────────────────────────────────────

class TestHighTierNamesSingleSource:
    def test_high_tier_names_matches_fetch_ores(self):
        from miningbot.fetch_ores import HIGH_TIERS
        assert HIGH_TIER_NAMES == HIGH_TIERS
