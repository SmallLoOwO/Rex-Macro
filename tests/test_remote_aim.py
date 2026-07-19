import numpy as np
from miningbot import remote_aim
from miningbot.remote_aim import (AimCandidate, SweepShot, TargetObservation,
                                  build_aim_context, pick_recovery_observation,
                                  grid_cell_center, draw_overlay, parse_reply,
                                  plan_alignment, circled, format_candidate_summary,
                                  build_aim_groups, AIM_GROUP_HEADER,
                                  MANUAL_SURVEY_HELP)


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

    def test_accepted_and_fired_observations_rank_before_near_misses(self):
        shots = [_shot("mid", 1, [_rej(100, 200, 0.99)])]
        observations = [
            TargetObservation("up", 6, (600, 300), 0.10, "accepted",
                              "sweep_confirmed", "accepted.png"),
            TargetObservation("mid", 4, (400, 500), 0.05, "fired",
                              "d3_fire", "fired.png"),
        ]

        ctx = build_aim_context(shots, 0, "mid", "079", now=1.0,
                                observations=observations)

        assert [c.source for c in ctx.candidates] == [
            "sweep_confirmed", "d3_fire", "near_miss"]
        assert [c.status for c in ctx.candidates] == [
            "accepted", "fired", "rejected"]
        assert ctx.candidates[2].score == 0.99

    def test_observations_consume_cap_before_rejects(self):
        shots = [_shot("mid", 0, [_rej(10, 20, 0.99)])]
        observations = [
            TargetObservation("mid", 2, (200, 200), 0.20, "accepted",
                              "confirmed", "confirmed.png"),
            TargetObservation("down", 7, (700, 700), 0.10, "fired",
                              "fire", "fire.png"),
        ]

        ctx = build_aim_context(shots, 0, "mid", "079", now=1.0,
                                max_candidates=2, observations=observations)

        assert len(ctx.candidates) == 2
        assert {c.status for c in ctx.candidates} == {"accepted", "fired"}

    def test_observation_retains_absolute_direction_and_snapshot(self):
        observation = TargetObservation(
            "up", 7, (720, 360), 0.42, "fired", "d3_fire", "d3_fire.png")

        ctx = build_aim_context([_shot("up", 1, [])], 5, "up", "079",
                                now=1.0, observations=[observation])

        assert ctx.candidates[0].dir_idx == 7
        assert ctx.candidates[0].snapshot_path == "d3_fire.png"
        assert any((s.layer, s.dir_idx, s.snapshot_path) ==
                   ("up", 7, "d3_fire.png") for s in ctx.shots)

    def test_existing_call_and_candidate_constructor_keep_defaults(self):
        ctx = build_aim_context([_shot("mid", 3, [_rej(30, 40, 0.3)])],
                                0, "mid", "legacy", 2.0, 1)
        candidate = AimCandidate(1, "mid", 2, (640, 400), 0.3, "hard_rej")

        assert len(ctx.candidates) == 1
        assert ctx.candidates[0].snapshot_path == "snap_mid_3.png"
        assert candidate.source == "near_miss"
        assert candidate.status == "rejected"
        assert candidate.snapshot_path == ""


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


class TestGridCellOf:
    def test_roundtrip_all_cells(self):
        # grid_cell_center 的逆函式：24 格 roundtrip 全對
        for col in "ABCDEF":
            for row in "1234":
                cell = f"{col}{row}"
                assert remote_aim.grid_cell_of(grid_cell_center(cell)) == cell

    def test_boundary_pixels(self):
        # 格界：319/269 仍在 A1，320/270 進 B2（格寬 320、格高 270）
        assert remote_aim.grid_cell_of((0, 0)) == "A1"
        assert remote_aim.grid_cell_of((1919, 1079)) == "F4"
        assert remote_aim.grid_cell_of((319, 269)) == "A1"
        assert remote_aim.grid_cell_of((320, 270)) == "B2"

    def test_out_of_screen_returns_none(self):
        assert remote_aim.grid_cell_of((-1, 5)) is None
        assert remote_aim.grid_cell_of((1920, 0)) is None
        assert remote_aim.grid_cell_of((0, 1080)) is None


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


class TestParseReply:
    def test_candidate_number(self):
        r = parse_reply("2", 3)
        assert r.kind == "candidate" and r.number == 2

    def test_candidate_out_of_range(self):
        assert parse_reply("4", 3) is None
        assert parse_reply("0", 3) is None

    def test_grid_default_layer(self):
        r = parse_reply("5 C3", 0)
        assert (r.kind, r.dir_idx, r.layer, r.cell) == ("grid", 5, "mid", "C3")

    def test_grid_pitch_layers(self):
        r = parse_reply("5U c3", 0, layers_available=("mid", "up", "down"))
        assert (r.kind, r.dir_idx, r.layer, r.cell) == ("grid", 5, "up", "C3")
        r = parse_reply("0d A1", 0, layers_available=("mid", "up", "down"))
        assert (r.kind, r.dir_idx, r.layer) == ("grid", 0, "down")

    def test_grid_layer_unavailable(self):
        # 俯仰掃描未啟用（layers 只有 mid）→ U/D 不合法
        assert parse_reply("5U C3", 0, layers_available=("mid",)) is None

    def test_grid_invalid(self):
        assert parse_reply("8 C3", 0) is None       # 方位只有 0-7
        assert parse_reply("5 G1", 0) is None       # 格子不合法
        assert parse_reply("5", 0) is None           # 單數字但零候選

    def test_skip(self):
        assert parse_reply("跳過", 3).kind == "skip"
        assert parse_reply("SKIP", 3).kind == "skip"

    def test_manual_keywords_and_all_alias(self):
        # `全部`/`all` 為舊別名（統一走手動最後手段：重掃＋全方位圖）
        for word in ("手動", "manual", "全部", "all", "MANUAL"):
            assert parse_reply(word, 3).kind == "manual"

    def test_fullwidth_space_and_noise(self):
        r = parse_reply("　5　C3　", 0)               # 全形空白
        assert r is not None and r.kind == "grid"
        assert parse_reply("哈哈這是聊天", 3) is None
        assert parse_reply("", 3) is None


class TestPlanAlignment:
    def test_restored_pose_to_dir5(self):
        # giveup 已歸位（net=0, mid）→ 目標方位 5：最短路徑左轉 3（5-0=5 → -3）
        assert plan_alignment(0, "mid", 5, "mid") == (-3, None)

    def test_face_tracker_pose_same_dir(self):
        # face_tracker giveup 停在 dir3（net=3）→ 目標同方位：不轉
        assert plan_alignment(3, "mid", 3, "mid") == (0, None)

    def test_wrapped_net_rotations(self):
        # net=9（sweep 轉了超過一圈）≡ dir1 → 目標 0：左轉 1
        assert plan_alignment(9, "mid", 0, "mid") == (-1, None)

    def test_layer_change(self):
        steps, pitch = plan_alignment(0, "mid", 2, "up")
        assert steps == 2 and pitch == "up"

    def test_back_to_mid_from_up(self):
        # 目前在 up 層、目標 mid 層 → pitch_change="mid"（純歸位）
        assert plan_alignment(0, "up", 0, "mid") == (0, "mid")

    def test_same_layer_no_pitch(self):
        assert plan_alignment(0, "up", 0, "up") == (0, None)


def _cand(number, dir_idx, pos, score, reason,
          status="rejected", source="near_miss"):
    return AimCandidate(number=number, layer="mid", dir_idx=dir_idx, pos=pos,
                        score=score, reason=reason, source=source, status=status)


class TestCircled:
    def test_1_to_9(self):
        assert [circled(n) for n in (1, 5, 9)] == ["①", "⑤", "⑨"]

    def test_out_of_range_fallback(self):
        assert circled(10) == "(10)"


class TestFormatCandidateSummary:
    def test_observation_first_line_quick_reharvest(self):
        # ① 是觀測證據（掃到未採）→ 最優提示行；② 一般近失行
        cands = [_cand(1, 5, (800, 675), 0.42, "sweep_stable",
                       status="accepted", source="sweep_stable"),
                 _cand(2, 2, (1100, 400), 0.38, "hard_rej")]
        lines = format_candidate_summary(cands).splitlines()
        assert lines[0] == "①（最優）DIR5・約C3・曾鎖定——回 1 快速重採"
        assert lines[1] == "② DIR2・約D2・分數0.38・形狀分不足"

    def test_number_one_near_miss_is_plain_line(self):
        # ① 不是觀測證據 → 不加（最優）提示（規則綁狀態、不綁編號）
        text = format_candidate_summary([_cand(1, 0, (10, 10), 0.44, "soft")])
        assert text == "① DIR0・約A1・分數0.44・形狀弱訊號"

    def test_hsv_only_candidate_shows_colored_not_negative(self):
        # 無 edge 候選排序鍵＝colored−1.0（負數）→ 顯示「色0.55」不出現負號
        text = format_candidate_summary([_cand(1, 7, (330, 700), -0.45, "margin")])
        assert text == "① DIR7・約B3・色0.55・太靠邊"
        assert "-" not in text

    def test_fired_and_seen_once_labels(self):
        cands = [_cand(1, 4, (400, 500), 0.05, "d3_fire",
                       status="fired", source="d3_fire"),
                 _cand(2, 6, (600, 300), 0.10, "double_frame_unstable",
                       status="seen_once", source="double_frame_unstable")]
        lines = format_candidate_summary(cands).splitlines()
        assert lines[0] == "①（最優）DIR4・約B2・射過未確認——回 1 快速重採"
        assert "單幀目擊" in lines[1]

    def test_unknown_reason_falls_through_as_is(self):
        assert "weird_code" in format_candidate_summary(
            [_cand(1, 0, (10, 10), 0.5, "weird_code")])

    def test_empty_candidates(self):
        assert format_candidate_summary([]) == ""


class TestBuildAimGroups:
    def test_sorted_by_min_number_and_batched_by_four(self):
        # 依各圖最小候選編號升冪 → ① 的圖必在首組首張（最優快速重採入口）
        rendered = [((5, 6), 3, "mid", "d3.png"),
                    ((1,), 5, "mid", "d5.png"),
                    ((2, 3), 0, "mid", "d0.png"),
                    ((4,), 7, "up", "d7.png"),
                    ((7,), 2, "mid", "d2.png")]
        groups = build_aim_groups(rendered, "總表內容")
        assert len(groups) == 2
        cap0, paths0 = groups[0]
        assert paths0 == ["d5.png", "d0.png", "d7.png", "d3.png"]
        assert cap0 == f"{AIM_GROUP_HEADER}\n總表內容"
        cap1, paths1 = groups[1]
        assert paths1 == ["d2.png"]
        assert cap1.startswith("🎯 近失候選（續）")
        assert "⑦" in cap1 and "DIR2" in cap1

    def test_single_group_header_and_summary(self):
        groups = build_aim_groups([((1,), 0, "mid", "a.png")], "line")
        assert groups == [(f"{AIM_GROUP_HEADER}\nline", ["a.png"])]

    def test_empty_summary_header_only(self):
        groups = build_aim_groups([((1,), 0, "mid", "a.png")], "")
        assert groups == [(AIM_GROUP_HEADER, ["a.png"])]

    def test_empty_rendered(self):
        assert build_aim_groups([], "x") == []

    def test_header_offers_number_skip_manual_but_not_grid(self):
        # 指令降級（spec §1/§5）：格子語法不在群標題，只在手動模式 caption
        assert "手動" in AIM_GROUP_HEADER and "跳過" in AIM_GROUP_HEADER
        assert "C3" not in AIM_GROUP_HEADER
        assert "C3" in MANUAL_SURVEY_HELP and "5U C3" in MANUAL_SURVEY_HELP


def test_recovery_prefers_latest_fired_then_accepted_then_seen_once():
    observations = [
        TargetObservation("mid", 1, (100, 100), 0.9, "seen_once", "s1", "1.png"),
        TargetObservation("mid", 2, (200, 200), 0.8, "fired", "f1", "2.png"),
        TargetObservation("mid", 3, (300, 300), 0.7, "accepted", "a1", "3.png"),
        TargetObservation("mid", 4, (400, 400), 0.1, "fired", "f2", "4.png"),
    ]
    assert pick_recovery_observation(observations) is observations[3]
    assert pick_recovery_observation([]) is None
