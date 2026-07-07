"""reentry 純決策模組單元測試（TDD）。

設計：docs/superpowers/specs/2026-07-08-mine-reentry-design.md。
核心原則「寧漏勿誤」：低信心寧可 reroll 也不亂點（傳錯層貴、reroll 便宜）。
"""
from miningbot import reentry


class TestPickPanelDirection:
    def test_best_above_threshold(self):
        scores = [(0, 0.30, (100, 200)), (3, 0.62, (500, 300)), (5, 0.50, (700, 100))]
        assert reentry.pick_panel_direction(scores, 0.45) == (3, 0.62, (500, 300))

    def test_all_below_threshold_none(self):
        # 寧漏勿誤：低信心回 None（呼叫端 reroll），不取「矮子裡的高個」
        assert reentry.pick_panel_direction([(0, 0.44, (1, 1))], 0.45) is None

    def test_empty_none(self):
        assert reentry.pick_panel_direction([], 0.45) is None


class TestMovementStatus:
    def test_still_moving(self):
        assert reentry.movement_status([9.0, 8.0, 7.0], 2.0, 3) == "moving"

    def test_stopped_after_stable_ticks(self):
        assert reentry.movement_status([9.0, 1.0, 0.5, 0.8], 2.0, 3) == "stopped"

    def test_not_enough_history_is_moving(self):
        # 剛點完 click-to-move，樣本不足時不可誤判停下
        assert reentry.movement_status([0.5], 2.0, 3) == "moving"


class TestOcclusionLadder:
    def test_ladder_order(self):
        assert reentry.next_occlusion_action(()) == "orbit"
        assert reentry.next_occlusion_action(("orbit",)) == "renavigate"
        assert reentry.next_occlusion_action(("orbit", "renavigate")) == "reroll"


class TestGiveup:
    def test_below_max_continues(self):
        assert reentry.should_giveup(4, 5) is False

    def test_at_max_gives_up(self):
        assert reentry.should_giveup(5, 5) is True


class TestPickLayerButton:
    DECOYS = ("Back to pre-reset location", "Basalt Layer",
              "Diorite Layer", "Obsidian Layer", "Core Layer")

    def _rec(self, text, center=(0, 0)):
        return {"text": text, "score": 0.9, "center": center}

    def test_exact_hit(self):
        recs = [self._rec("Diorite Layer", (10, 10)),
                self._rec("Mantle Layer", (300, 240)),
                self._rec("Back to pre-reset location", (300, 120))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.75) == (300, 240)

    def test_ocr_noise_still_hits(self):
        # 遊戲字型 i/l 同形（H033）：Mantie 仍應命中，因對 target 分數嚴格高於任一 decoy
        recs = [self._rec("Mantie Layer", (300, 240))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.75) == (300, 240)

    def test_decoy_never_picked(self):
        recs = [self._rec("Core Layer", (300, 300))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.75) is None

    def test_ambiguous_returns_none(self):
        # 對 target 與 decoy 分數打平＝分不清 → 不點（寧漏勿誤）
        recs = [self._rec("Layer", (300, 300))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.10) is None

    def test_below_min_ratio_none(self):
        recs = [self._rec("xxxxx", (300, 300))]
        assert reentry.pick_layer_button(recs, "Mantle Layer", self.DECOYS, 0.75) is None
