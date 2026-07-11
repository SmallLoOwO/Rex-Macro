import numpy as np
from miningbot import remote_aim
from miningbot.remote_aim import (AimCandidate, SweepShot, build_aim_context,
                                  grid_cell_center, draw_overlay)


def _shot(layer, d, rejects):
    return SweepShot(layer=layer, dir_idx=d, snapshot_path=f"snap_{layer}_{d}.png",
                     rejects=rejects)

def _rej(x, y, edge, reason="hard_rej", colored=0.8):
    return {"pos": (x, y), "colored": colored, "edge": edge, "reason": reason}


class TestBuildAimContext:
    def test_numbers_by_score_desc_across_shots(self):
        # 編號＝全域流水、依分數（edge 優先、無 edge 用 colored）降冪——最像框的排最前
        shots = [_shot("mid", 2, [_rej(100, 200, 0.30)]),
                 _shot("up", 5, [_rej(500, 400, 0.38), _rej(900, 300, None, "margin", 0.9)])]
        ctx = build_aim_context(shots, 0, "mid", "071", now=123.0)
        assert [c.number for c in ctx.candidates] == [1, 2, 3]
        assert ctx.candidates[0].pos == (500, 400)      # edge 0.38 最高
        assert ctx.candidates[0].layer == "up" and ctx.candidates[0].dir_idx == 5
        assert ctx.candidates[2].pos == (900, 300)      # 無 edge（margin）排 edge 之後
        assert ctx.pose_net_rotations == 0 and ctx.harvest_id == "071"

    def test_cap_max_candidates(self):
        shots = [_shot("mid", 0, [_rej(10 * i, 20, 0.2 + i * 0.01) for i in range(1, 15)])]
        ctx = build_aim_context(shots, 0, "mid", "072", now=0.0, max_candidates=9)
        assert len(ctx.candidates) == 9

    def test_empty_shots_gives_empty_candidates(self):
        ctx = build_aim_context([], 3, "up", "073", now=0.0)
        assert ctx.candidates == [] and ctx.pose_net_rotations == 3
        assert ctx.pose_pitch_layer == "up"


class TestGridCellCenter:
    def test_c3_center(self):
        # 6×4 網格、1920×1080：格寬 320、高 270。C=第3欄(idx2)、3=第3列(idx2)
        assert grid_cell_center("C3") == (2 * 320 + 160, 2 * 270 + 135)

    def test_a1_and_f4_corners(self):
        assert grid_cell_center("A1") == (160, 135)
        assert grid_cell_center("F4") == (5 * 320 + 160, 3 * 270 + 135)

    def test_case_insensitive(self):
        assert grid_cell_center("c3") == grid_cell_center("C3")

    def test_invalid_cells(self):
        for bad in ("G1", "A5", "AA", "3C", "", "C"):
            assert grid_cell_center(bad) is None


class TestDrawOverlay:
    def test_marks_candidate_and_keeps_input_intact(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cands = [AimCandidate(1, "mid", 2, (640, 400), 0.3, "hard_rej")]
        out = draw_overlay(frame, cands, grid=True)
        assert out.shape == frame.shape
        assert frame.sum() == 0                      # 輸入不被改
        assert out[400, 640 - 40:640 + 40].sum() > 0  # 候選框附近有畫東西
        assert out.sum() > 0

    def test_no_candidates_grid_only(self):
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        out = draw_overlay(frame, [], grid=True)
        assert out.sum() > 0                          # 網格線有畫
