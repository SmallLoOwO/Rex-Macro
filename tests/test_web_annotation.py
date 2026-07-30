# tests/test_web_annotation.py
"""P5 Task 4：素材標註 schema + helpers 純函式。

spec §5：玩家在網頁介入時自動或手動產出 .json 素材描述黨；只存症狀標籤
（漏判/誤判），根因屬 docs/incidents.md 範疇，不進素材。
"""
import pytest

from miningbot.web_annotation import (
    build_annotation,
    normalize_symptom,
    rarity_choices_from_game_data,
    validate_annotation,
)


class TestNormalizeSymptom:
    """5 player-facing labels + None + unknown string → None."""

    def test_chinese_false_negative(self):
        assert normalize_symptom("漏判") == "false_negative"

    def test_chinese_false_positive(self):
        assert normalize_symptom("誤判") == "false_positive"

    def test_chinese_should_reject_failed(self):
        assert normalize_symptom("該拒沒拒") == "should_reject_failed"

    def test_chinese_unknown(self):
        assert normalize_symptom("不確定") == "unknown"

    def test_empty_string_returns_none(self):
        assert normalize_symptom("") is None

    def test_none_returns_none(self):
        assert normalize_symptom(None) is None

    def test_english_aliases(self):
        assert normalize_symptom("FN") == "false_negative"
        assert normalize_symptom("FP") == "false_positive"
        assert normalize_symptom("false_negative") == "false_negative"
        assert normalize_symptom("false_positive") == "false_positive"
        assert normalize_symptom("should_reject_failed") == "should_reject_failed"
        assert normalize_symptom("unknown") == "unknown"

    def test_unknown_string_returns_none(self):
        # 不認得的字串不該被當成症狀；素材留 null（不確定時玩家顯式選「不確定」）
        assert normalize_symptom("隨便說說") is None
        assert normalize_symptom("garbage") is None


class TestRarityChoicesFromGameData:
    """tiers = 從 special_ores 撈出的唯一排序字串；variants 固定四個（含「原色」）。"""

    def test_empty_list_returns_empty_tiers(self):
        tiers, variants = rarity_choices_from_game_data([])
        assert tiers == []
        assert variants == ["原色", "Spectral", "Ionized"]

    def test_dedupes_and_sorts_tiers(self):
        special_ores = [
            {"ore": "A", "tier": "Mythic"},
            {"ore": "B", "tier": "Surreal"},
            {"ore": "C", "tier": "Mythic"},
            {"ore": "D", "tier": "Exotic"},
        ]
        tiers, variants = rarity_choices_from_game_data(special_ores)
        # 排序後唯一
        assert tiers == ["Exotic", "Mythic", "Surreal"]
        assert variants == ["原色", "Spectral", "Ionized"]

    def test_orders_tiers_by_rarity_not_alphabetically(self):
        """稀有度由低到高，不是字母序（2026-07-29）。

        實機 game_data 的字母序是 ``Enigmatic, Exotic, Exquisite, Imaginary,
        Otherworldly, Transcendent, Unfathomable``——跟遊戲階級毫無關係，
        玩家標註時等於在無序名詞裡找字。
        """
        special_ores = [
            {"ore": "A", "tier": "Unfathomable", "rarity": 2_332_960},
            {"ore": "B", "tier": "Exquisite", "rarity": 111_112},
            {"ore": "C", "tier": "Exotic", "rarity": 180_000},
            {"ore": "D", "tier": "Exquisite", "rarity": 15_001_500},  # 同階高價不影響
        ]
        tiers, _ = rarity_choices_from_game_data(special_ores)
        assert tiers == ["Exquisite", "Exotic", "Unfathomable"]

    def test_tier_without_rarity_sorts_last(self):
        """缺 rarity 的 tier 排最後，同鍵按名字穩定排序（不是隨機掉進中間）。"""
        special_ores = [
            {"ore": "A", "tier": "Zeta"},          # 無 rarity
            {"ore": "B", "tier": "Priced", "rarity": 500},
            {"ore": "C", "tier": "Alpha"},         # 無 rarity
        ]
        tiers, _ = rarity_choices_from_game_data(special_ores)
        assert tiers == ["Priced", "Alpha", "Zeta"]

    def test_skips_entries_without_tier(self):
        special_ores = [
            {"ore": "A", "tier": "Mythic"},
            {"ore": "B"},  # 無 tier
            {"ore": "C", "tier": ""},
            {"ore": "D", "tier": None},
        ]
        tiers, _ = rarity_choices_from_game_data(special_ores)
        assert tiers == ["Mythic"]

    def test_variants_always_fixed_list(self):
        # variants 不從 game_data 撈——遊戲機制只有原色/Spectral/Ionized
        _, variants = rarity_choices_from_game_data(
            [{"ore": "X", "tier": "Mythic"}]
        )
        assert variants == ["原色", "Spectral", "Ionized"]


class TestBuildAnnotation:
    """建素材 .json schema（spec §5）。"""

    def _annotation(self):
        return {"type": "square", "cx": 211, "cy": 189, "size": 50}

    def _source(self):
        return {
            "kind": "auto",
            "harvest_id": "007",
            "episode_result": "fail",
            "verify": "failed",
            "timestamp": "2026-07-26T14:23:00+08:00",
        }

    def test_full_annotation(self):
        ann = build_annotation(
            image="auto_007_terrain_fp.png",
            annotation=self._annotation(),
            tier="Mythic",
            variant="Spectral",
            mineral="Tin",
            source=self._source(),
            symptom="false_positive",
            related_incident="H057",
        )
        assert ann["image"] == "auto_007_terrain_fp.png"
        assert ann["annotation"] == self._annotation()
        assert ann["tier"] == "Mythic"
        assert ann["variant"] == "Spectral"
        assert ann["mineral"] == "Tin"
        assert ann["source"] == self._source()
        assert ann["symptom"] == "false_positive"
        assert ann["related_incident"] == "H057"

    def test_optional_fields_none(self):
        ann = build_annotation(
            image="auto_007_success.png",
            annotation=self._annotation(),
            tier=None,
            variant=None,
            mineral=None,
            source=self._source(),
            symptom=None,
            related_incident=None,
        )
        assert ann["tier"] is None
        assert ann["variant"] is None
        assert ann["mineral"] is None
        assert ann["symptom"] is None
        assert ann["related_incident"] is None

    def test_normalizes_chinese_symptom(self):
        # 玩家從 UI 選「漏判」也該被轉成標準 enum
        ann = build_annotation(
            image="auto_007_fn.png",
            annotation=self._annotation(),
            tier=None,
            variant=None,
            mineral=None,
            source=self._source(),
            symptom="漏判",
            related_incident=None,
        )
        assert ann["symptom"] == "false_negative"

    def test_unknown_symptom_becomes_none(self):
        ann = build_annotation(
            image="x.png",
            annotation=self._annotation(),
            tier=None,
            variant=None,
            mineral=None,
            source=self._source(),
            symptom="隨便說說",
            related_incident=None,
        )
        assert ann["symptom"] is None

    def test_does_not_mutate_input_annotation(self):
        src_ann = self._annotation()
        original = dict(src_ann)
        build_annotation(
            image="x.png",
            annotation=src_ann,
            tier=None,
            variant=None,
            mineral=None,
            source=self._source(),
            symptom=None,
            related_incident=None,
        )
        assert src_ann == original

    def test_does_not_mutate_input_source(self):
        src = self._source()
        original = dict(src)
        build_annotation(
            image="x.png",
            annotation=self._annotation(),
            tier=None,
            variant=None,
            mineral=None,
            source=src,
            symptom=None,
            related_incident=None,
        )
        assert src == original


class TestValidateAnnotation:
    """schema 驗證：required keys + types。"""

    def _valid(self):
        return {
            "image": "auto_007_terrain_fp.png",
            "annotation": {"type": "square", "cx": 211, "cy": 189, "size": 50},
            "tier": None,
            "variant": None,
            "mineral": None,
            "source": {
                "kind": "auto",
                "harvest_id": "007",
                "episode_result": "fail",
                "verify": "failed",
                "timestamp": "2026-07-26T14:23:00+08:00",
            },
            "symptom": "false_positive",
            "related_incident": None,
        }

    def test_valid_annotation(self):
        assert validate_annotation(self._valid()) is True

    def test_valid_with_all_optional_strings(self):
        ann = self._valid()
        ann["tier"] = "Mythic"
        ann["variant"] = "Spectral"
        ann["mineral"] = "Tin"
        ann["related_incident"] = "H057"
        assert validate_annotation(ann) is True

    def test_valid_with_symptom_none(self):
        ann = self._valid()
        ann["symptom"] = None
        assert validate_annotation(ann) is True

    def test_reject_missing_image(self):
        ann = self._valid()
        del ann["image"]
        assert validate_annotation(ann) is False

    def test_reject_image_not_string(self):
        ann = self._valid()
        ann["image"] = 123
        assert validate_annotation(ann) is False

    def test_reject_missing_annotation(self):
        ann = self._valid()
        del ann["annotation"]
        assert validate_annotation(ann) is False

    def test_reject_annotation_not_dict(self):
        ann = self._valid()
        ann["annotation"] = "square"
        assert validate_annotation(ann) is False

    def test_reject_annotation_wrong_type(self):
        ann = self._valid()
        ann["annotation"]["type"] = "circle"
        assert validate_annotation(ann) is False

    def test_reject_annotation_missing_coord(self):
        ann = self._valid()
        del ann["annotation"]["cx"]
        assert validate_annotation(ann) is False

    def test_reject_annotation_coord_not_int(self):
        ann = self._valid()
        ann["annotation"]["cx"] = 1.5
        assert validate_annotation(ann) is False

    def test_reject_annotation_size_not_int(self):
        ann = self._valid()
        ann["annotation"]["size"] = "50"
        assert validate_annotation(ann) is False

    def test_reject_missing_source(self):
        ann = self._valid()
        del ann["source"]
        assert validate_annotation(ann) is False

    def test_reject_source_not_dict(self):
        ann = self._valid()
        ann["source"] = []
        assert validate_annotation(ann) is False

    def test_reject_source_missing_kind(self):
        ann = self._valid()
        del ann["source"]["kind"]
        assert validate_annotation(ann) is False

    def test_reject_source_kind_not_auto_or_manual(self):
        ann = self._valid()
        ann["source"]["kind"] = "guess"
        assert validate_annotation(ann) is False

    def test_reject_tier_not_string(self):
        ann = self._valid()
        ann["tier"] = 123
        assert validate_annotation(ann) is False

    def test_reject_symptom_unknown_string(self):
        ann = self._valid()
        ann["symptom"] = "garbage_symptom"
        assert validate_annotation(ann) is False

    def test_reject_not_dict(self):
        assert validate_annotation("not a dict") is False
        assert validate_annotation(None) is False
        assert validate_annotation([]) is False


# ---- 看到什麼 × bot 判定 → 症狀（2026-07-31）---------------------------------


class TestSymptomFromObservation:
    """玩家只描述畫面，症狀由 bot 當下判定推出來。

    使用者原話：「給予的圖片大部分只有 1 與 4，所以我也不知道 2 與 3 的差別，
    並且 bot 有沒有接受，我認為這部分腳本在記錄圖片的時候應該就會有了」。
    """

    def test_ore_accepted_is_the_control_group(self):
        from miningbot.web_annotation import symptom_from_observation
        assert symptom_from_observation("ore", "accepted") is None

    def test_ore_rejected_is_false_negative(self):
        from miningbot.web_annotation import symptom_from_observation
        assert symptom_from_observation("ore", "rejected") == "false_negative"

    def test_decoy_accepted_is_should_reject_failed(self):
        from miningbot.web_annotation import symptom_from_observation
        assert symptom_from_observation("decoy", "accepted") == "should_reject_failed"

    def test_empty_accepted_is_false_positive(self):
        from miningbot.web_annotation import symptom_from_observation
        assert symptom_from_observation("empty", "accepted") == "false_positive"

    def test_decoy_and_empty_are_true_negatives_when_bot_rejected(self):
        from miningbot.web_annotation import symptom_from_observation
        assert symptom_from_observation("decoy", "rejected") == "no_target"
        assert symptom_from_observation("empty", "rejected") == "no_target"

    def test_missing_verdict_never_claims_bot_accepted(self):
        """沒記判定就不可以推出需要「接受」才成立的症狀（誤判／該拒沒拒）。"""
        from miningbot.web_annotation import symptom_from_observation
        assert symptom_from_observation("empty", None) == "no_target"
        assert symptom_from_observation("decoy", "") == "no_target"
        assert symptom_from_observation("ore", None) == "false_negative"

    def test_unknown_observation_falls_back_to_unsure(self):
        from miningbot.web_annotation import symptom_from_observation
        assert symptom_from_observation("garbage", "accepted") == "unknown"
        assert symptom_from_observation(None, "rejected") == "unknown"

    def test_every_derived_symptom_passes_validate(self):
        """推導出來的值一定要是 validate_annotation 收得下的 enum。"""
        from miningbot.web_annotation import (
            SYMPTOM_BY_OBSERVATION, symptom_from_observation,
            validate_annotation,
        )
        for obs in SYMPTOM_BY_OBSERVATION:
            for verdict in ("accepted", "rejected", None):
                ann = {
                    "image": "x.png",
                    "annotation": {"type": "square", "cx": 1, "cy": 2, "size": 3},
                    "source": {"kind": "manual"},
                    "observation": obs,
                    "symptom": symptom_from_observation(obs, verdict),
                }
                assert validate_annotation(ann) is True


def test_validate_accepts_observation_field():
    """玩家原話要存得進 json——decoy 與 empty 在 bot 拒絕時都推成 no_target，
    推導不可逆，只有這個欄位留得住「像礦的地形」這種硬負樣本的身分。"""
    from miningbot.web_annotation import validate_annotation
    ann = {"image": "x.png", "source": {"kind": "manual"},
           "symptom": "no_target", "observation": "decoy"}
    assert validate_annotation(ann) is True
    ann["observation"] = 5
    assert validate_annotation(ann) is False
