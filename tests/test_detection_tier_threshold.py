"""偵測階級門檻（detection_min_tier）回歸測試（2026-08-02）。

classify_found_ore 加階級閘：低於門檻的稀有 礦回 "common"，
效果蔓延到面板色檢／救援／採集驗證／通知標注。
色相閘也跟著門檻走（effective_whitelist_hues / effective_low_tier_hues）。
"""
import pytest

from miningbot import game_data
from miningbot.game_data import (
    classify_found_ore, set_detection_min_tier, get_detection_min_tier,
    effective_whitelist_hues, effective_low_tier_hues,
    TIER_HUES, _TIER_ORDER, _is_below_threshold, HIGH_TIER_NAMES,
)
from miningbot.web_config_whitelist import is_web_configurable, validate_value


@pytest.fixture(autouse=True)
def _reset_tier():
    """每個測試前後重設門檻，避免跨測試污染。"""
    set_detection_min_tier(None)
    yield
    set_detection_min_tier(None)


# ── classify_found_ore 階級閘 ──────────────────────────────────────────────

class TestClassifyTierFilter:
    def test_no_threshold_exotic_is_rare(self):
        """無門檻（預設）→ Exotic 判 rare（現行行為）。"""
        assert classify_found_ore("demonizine")[0] == "rare"

    def test_exquisite_threshold_exotic_becomes_common(self):
        """門檻 Exquisite → Exotic（demonizine, tier=Exotic）判 common。"""
        set_detection_min_tier("Exquisite")
        assert classify_found_ore("demonizine")[0] == "common"

    def test_exquisite_threshold_exquisite_still_rare(self):
        """門檻 Exquisite → Exquisite 礦仍判 rare。"""
        set_detection_min_tier("Exquisite")
        # rare_ores.json 裡應有 Exquisite tier 礦——用一個已知名字
        kind, info = classify_found_ore("confined cataclysm")
        assert kind == "rare", f"Exquisite 礦應判 rare，got {kind}"
        assert info is not None and info.get("tier") == "Exquisite"

    def test_exotic_threshold_is_noop(self):
        """門檻 Exotic（= 最低）→ 不過濾，等同無門檻。"""
        set_detection_min_tier("Exotic")
        assert classify_found_ore("demonizine")[0] == "rare"

    def test_threshold_does_not_affect_common(self):
        """門檻不影響 common 礦（Surreal/Mythic 排除清單）。"""
        set_detection_min_tier("Exquisite")
        # common 礦仍判 common（不是因為門檻，而是本來就在排除清單）
        assert classify_found_ore("peppermint core")[0] == "common"

    def test_threshold_does_not_affect_unknown(self):
        """門檻不影響 unknown 礦（不在任何表上）。"""
        set_detection_min_tier("Exquisite")
        kind, _ = classify_found_ore("zzzznonexistent")
        assert kind == "unknown"


# ── _is_below_threshold 純函式 ──────────────────────────────────────────────

class TestIsBelowThreshold:
    def test_no_threshold_never_below(self):
        assert not _is_below_threshold({"tier": "Exotic"})
        assert not _is_below_threshold({"tier": "Imaginary"})

    def test_below(self):
        set_detection_min_tier("Exquisite")
        assert _is_below_threshold({"tier": "Exotic"})

    def test_at_threshold_not_below(self):
        set_detection_min_tier("Exquisite")
        assert not _is_below_threshold({"tier": "Exquisite"})

    def test_above_threshold_not_below(self):
        set_detection_min_tier("Exquisite")
        assert not _is_below_threshold({"tier": "Transcendent"})

    def test_unknown_tier_below_when_threshold_above_exotic(self):
        """門檻高於 Exotic 時，未知 tier → below（安全方向：當低階）。"""
        set_detection_min_tier("Exquisite")
        assert _is_below_threshold({"tier": "Unknown"})

    def test_unknown_tier_not_below_at_exotic_default(self):
        """門檻 Exotic（預設）→ 不過濾，未知 tier 也不 below。"""
        set_detection_min_tier("Exotic")
        assert not _is_below_threshold({"tier": "Unknown"})


# ── effective_whitelist_hues / effective_low_tier_hues ─────────────────────

class TestEffectiveHues:
    BASE_WL = (46.0, 128.0, 210.0)
    BASE_LOW = (0.0, 30.0, 166.0, 280.0, 304.0)

    def test_no_threshold_unchanged(self):
        assert effective_whitelist_hues(None, self.BASE_WL) == self.BASE_WL
        assert effective_low_tier_hues(None, self.BASE_LOW) == self.BASE_LOW

    def test_exotic_threshold_unchanged(self):
        """Exotic = 最低 → 不過濾。"""
        assert effective_whitelist_hues("Exotic", self.BASE_WL) == self.BASE_WL
        assert effective_low_tier_hues("Exotic", self.BASE_LOW) == self.BASE_LOW

    def test_exquisite_drops_exotic_hue(self):
        wl = effective_whitelist_hues("Exquisite", self.BASE_WL)
        assert 46.0 not in wl, "Exotic 色相 46 不該在白名單"
        assert 128.0 in wl
        assert 210.0 in wl

    def test_exquisite_adds_exotic_to_low(self):
        low = effective_low_tier_hues("Exquisite", self.BASE_LOW)
        assert 46.0 in low, "Exotic 色相 46 應加入低階帶"

    def test_transcendent_drops_exotic_and_exquisite(self):
        wl = effective_whitelist_hues("Transcendent", self.BASE_WL)
        assert 46.0 not in wl
        assert 128.0 not in wl
        assert 210.0 in wl

    def test_enigmatic_empty_whitelist(self):
        """高於 Transcendent → 所有量測色相都降級。"""
        wl = effective_whitelist_hues("Enigmatic", self.BASE_WL)
        assert wl == ()

    def test_dedup_in_low_tier(self):
        """base_low 已有的色相不重複。"""
        low = effective_low_tier_hues("Exquisite", self.BASE_LOW)
        assert low.count(46.0) == 1


# ── web config 白名單 + 驗證 ─────────────────────────────────────────────────

class TestWebConfig:
    def test_field_is_configurable(self):
        assert is_web_configurable("detection_min_tier")

    def test_valid_tiers_accepted(self):
        for tier in ("Exotic", "Exquisite", "Transcendent", "Enigmatic",
                     "Unfathomable", "Otherworldly", "Imaginary", "Zenith"):
            assert validate_value("detection_min_tier", tier), f"{tier} 應合法"

    def test_invalid_tier_rejected(self):
        assert not validate_value("detection_min_tier", "exotic")  # 大小寫敏感
        assert not validate_value("detection_min_tier", "Rare")
        assert not validate_value("detection_min_tier", "")
        assert not validate_value("detection_min_tier", 123)


# ── Discord 階級指令 ────────────────────────────────────────────────────────

class TestHighTierNamesSingleSource:
    """HIGH_TIERS 來自唯一來源（fetch_ores），下游不得硬編碼。"""

    def test_high_tier_names_matches_fetch_ores(self):
        from miningbot.fetch_ores import HIGH_TIERS
        assert HIGH_TIER_NAMES == HIGH_TIERS
