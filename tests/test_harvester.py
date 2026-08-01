from miningbot import harvester
from miningbot.harvester import (next_harvest_step, HarvestState, restore_actions,
                                 decide_harvest_result, decide_verify_poll,
                                 d3_cooldown_remaining,
                                 pick_sweep_candidate, decide_sweep_failure,
                                 decide_post_success,
                                 format_rotation_hint,
                                 format_harvest_id,
                                 normalize_rotations, plan_return_rotations,
                                 plan_web_click_rotations,
                                 plan_giveup, GiveupPlan, GiveupCrop,
                                 giveup_send_groups,
                                 rotation_looks_eaten, restore_view)
from miningbot.config import DEFAULT

def test_no_marker_yet_waits():
    st = HarvestState(rotations=0, elapsed_s=0.5)
    step = next_harvest_step(marker=None, state=st, cfg=DEFAULT)
    assert step.action == "WAIT_SCAN"

def test_timeout_without_success_fails_to_human():
    st = HarvestState(rotations=0, elapsed_s=DEFAULT.harvest_verify_timeout_s + 1)
    step = next_harvest_step(marker=(960, 540), state=st, cfg=DEFAULT)
    assert step.action == "HUMAN"

def test_too_many_rotations_fails_to_human():
    st = HarvestState(rotations=DEFAULT.max_aim_rotations + 1, elapsed_s=1.0)
    step = next_harvest_step(marker=(100, 540), state=st, cfg=DEFAULT)
    assert step.action == "HUMAN"

def test_centered_marker_fires_d3():
    st = HarvestState(rotations=0, elapsed_s=1.0)
    step = next_harvest_step(marker=(965, 545), state=st, cfg=DEFAULT)
    assert step.action == "FIRE_D3"

def test_d3_cooldown_no_previous_fire_is_ready():
    assert d3_cooldown_remaining(now_s=100.0, last_fire_s=None,
                                 cooldown_s=10.0) == 0.0


def test_d3_cooldown_starts_when_shot_is_fired():
    assert d3_cooldown_remaining(now_s=100.0, last_fire_s=100.0,
                                 cooldown_s=10.0) == 10.0


def test_d3_cooldown_reports_remaining_time():
    assert d3_cooldown_remaining(now_s=104.25, last_fire_s=100.0,
                                 cooldown_s=10.0) == 5.75


def test_d3_cooldown_exact_boundary_and_later_are_ready():
    assert d3_cooldown_remaining(now_s=110.0, last_fire_s=100.0,
                                 cooldown_s=10.0) == 0.0
    assert d3_cooldown_remaining(now_s=112.0, last_fire_s=100.0,
                                 cooldown_s=10.0) == 0.0

def test_vertical_extreme_human():
    st = HarvestState(rotations=0, elapsed_s=1.0)
    step = next_harvest_step(marker=(960, 1000), state=st, cfg=DEFAULT)
    assert step.action == "HUMAN"

def test_restore_actions_undoes_net_right_rotation():
    # 淨右轉 3 次 → 要左轉 3 次轉回原角度
    assert restore_actions(3) == ["ROTATE_LEFT", "ROTATE_LEFT", "ROTATE_LEFT"]

def test_restore_actions_undoes_net_left_rotation():
    assert restore_actions(-2) == ["ROTATE_RIGHT", "ROTATE_RIGHT"]

def test_restore_actions_noop_when_balanced():
    assert restore_actions(0) == []


# --- normalize_rotations：淨轉動取「最短等價路徑」（純函式，主線程提速）---
# 8 方位＝360° 環：淨右轉 7 次 ≡ 左轉 1 次、淨 ±8 ≡ 不動。旋轉一次要 key_press +
# 0.35s settle，繞遠路一輪最多白花 ~2.4s（restore 淨 8 更是白轉整圈 ~2.8s）。
def test_normalize_rotations_seven_rights_is_one_left():
    assert normalize_rotations(7) == -1

def test_normalize_rotations_seven_lefts_is_one_right():
    assert normalize_rotations(-7) == 1

def test_normalize_rotations_full_circle_is_zero():
    assert normalize_rotations(8) == 0
    assert normalize_rotations(-8) == 0

def test_normalize_rotations_short_paths_unchanged():
    assert normalize_rotations(3) == 3
    assert normalize_rotations(-2) == -2
    assert normalize_rotations(0) == 0

def test_normalize_rotations_halfway_keeps_four():
    # 正好對面（4 格）：左右等距，取 +4（方向不影響步數）
    assert normalize_rotations(4) == 4

def test_restore_actions_takes_shortest_path():
    # 淨右轉 7 → 再右轉 1 次補滿 360° 即回原角（不必左轉 7 次）
    assert restore_actions(7) == ["ROTATE_RIGHT"]
    assert restore_actions(-7) == ["ROTATE_LEFT"]
    assert restore_actions(8) == []


# --- rotation_looks_eaten：驗證式旋轉的「按鍵被吃」判定（純函式，2026-07-05）---
# 視角回歸靠 net_rotations 計數反轉，前提是每個 ,/. 都真的生效——被吃一次就差 45°
# （挖礦視角是 90° 倍數對齊，差 45° 直接影響挖礦效率）。旋轉 45° 會讓中央場景劇變、
# 被吃則幾乎逐位元相同 → 前後幀「平均差 + 有感變化像素佔比」兩訊號都近零才判被吃。
# 誤判方向的取捨：實際轉了卻誤判被吃而重送＝直接製造 45° 偏移，比漏判（退回舊行為）
# 更糟 → 判「被吃」要保守（AND 兩訊號）、無從比較一律當已生效。

def test_rotation_eaten_when_scene_nearly_identical():
    # 被吃的按鍵：畫面只剩角色 idle 微幅變化，兩訊號都近零
    assert rotation_looks_eaten(0.3, 0.002, mean_thresh=2.0, frac_thresh=0.02) is True

def test_rotation_applied_when_scene_changed():
    assert rotation_looks_eaten(25.0, 0.6, mean_thresh=2.0, frac_thresh=0.02) is False

def test_rotation_dark_cave_low_mean_but_wide_change_is_applied():
    # 近全黑礦坑旋轉：像素值低 → 平均差可能低於門檻，但變化像素佔比高 → 不可誤判被吃
    assert rotation_looks_eaten(1.2, 0.30, mean_thresh=2.0, frac_thresh=0.02) is False

def test_rotation_uncomparable_treated_as_applied():
    # 基準缺/尺寸不合＝無從比較 → 當作已生效（重送有過轉風險，寧信）
    assert rotation_looks_eaten(None, None, mean_thresh=2.0, frac_thresh=0.02) is False
    assert rotation_looks_eaten(0.1, None, mean_thresh=2.0, frac_thresh=0.02) is False
    assert rotation_looks_eaten(None, 0.001, mean_thresh=2.0, frac_thresh=0.02) is False


# --- restore_view 可注入 rotate callable（驗證式旋轉接入點）---
# main 傳 Bot._rotate_verified 讓回歸的每一步都驗證「真的轉了」；注入時不得碰
# input_control（測試用 fake 收集呼叫序列即可驗證方向與步數、含最短路徑 wrap）。

def test_restore_view_injected_rotate_left_for_net_right():
    calls = []
    restore_view(3, rotate=lambda d: calls.append(d) or True)
    assert calls == [-1, -1, -1]

def test_restore_view_injected_rotate_right_for_net_left():
    calls = []
    restore_view(-2, rotate=lambda d: calls.append(d) or True)
    assert calls == [1, 1]

def test_restore_view_injected_wraps_shortest_path():
    calls = []
    restore_view(7, rotate=lambda d: calls.append(d) or True)
    assert calls == [1]        # 淨右轉 7 → 右轉 1 次 wrap 360°，不左轉 7 次

def test_restore_view_injected_noop_for_full_circle():
    calls = []
    restore_view(8, rotate=lambda d: calls.append(d) or True)
    assert calls == []


# --- plan_return_rotations：sweep 完成後轉回最佳方位走最短方向（純函式）---
# sweep 結束站在 dir 7（rotate_right×7）；舊版一律往左轉 (7-best_dir) 次——
# best_dir=0 要左轉 7 次（~2.4s），其實右轉 1 次 wrap 360° 就到（0.35s）。
def test_plan_return_wraps_right_when_shorter():
    assert plan_return_rotations(7, 0) == 1     # 右轉 1 次 wrap，不左轉 7 次
    assert plan_return_rotations(7, 1) == 2

def test_plan_return_goes_left_when_shorter():
    assert plan_return_rotations(7, 6) == -1
    assert plan_return_rotations(7, 4) == -3

def test_plan_return_same_dir_is_noop():
    assert plan_return_rotations(7, 7) == 0

def test_plan_return_opposite_is_four_steps():
    assert abs(plan_return_rotations(7, 3)) == 4


# --- plan_web_click_rotations：web 點擊恆往左拆 sweep 的右轉（RR#44 根因）---
# sweep 做 8 次右轉，cur_dir%8 消去一圈但累積 ~4° 誤差。
# plan_return_rotations 在 mod 8 取最短路徑——dir1 回 0 步（殘留誤差）；
# 本函式一律往左拆，每步左轉抵消 sweep 的一次右轉 → 落點 = sweep 拍該方位的精確角度。
def test_web_click_dir1_is_full_undo_not_zero():
    """dir1：sweep 後 cur_dir%8=0 看似不用轉，但實際偏了 8ε。要左轉 8 步拆掉整圈。"""
    assert plan_web_click_rotations(cur_dir=8, tgt=0, sweep_start=0) == -8

def test_web_click_dir8_matches_old_behavior():
    """dir8：左轉 1 步（拆掉 sweep 的最後一次右轉）——與 plan_return_rotations 一致。"""
    assert plan_web_click_rotations(cur_dir=8, tgt=7, sweep_start=0) == -1

def test_web_click_all_directions_backward():
    """不論點哪個方位，步數恆 ≤ 0（左轉或零）——不往右疊。"""
    for tgt in range(8):
        result = plan_web_click_rotations(cur_dir=8, tgt=tgt, sweep_start=0)
        assert result <= 0, f"tgt={tgt}: expected <= 0 (LEFT/zero), got {result}"

def test_web_click_dir5_differs_from_shortest_path():
    """dir5：最短路徑 +4（右轉疊誤差），往左拆 -4（抵消精確）。"""
    assert plan_web_click_rotations(cur_dir=8, tgt=4, sweep_start=0) == -4
    assert plan_return_rotations(0, 4) == 4            # 舊法往右——正是要修掉的

def test_web_click_accounts_for_rot_missed():
    """sweep 有 1 次旋轉被吃 → cur_dir=7（只轉了 7 次），undo 步數跟著少 1。"""
    assert plan_web_click_rotations(cur_dir=7, tgt=0, sweep_start=0) == -7
    assert plan_web_click_rotations(cur_dir=7, tgt=6, sweep_start=0) == -1

def test_web_click_nonzero_sweep_start():
    """sweep_start 非 0（第二輪 sweep 等）也能正確算 undo。"""
    assert plan_web_click_rotations(cur_dir=16, tgt=0, sweep_start=8) == -8
    assert plan_web_click_rotations(cur_dir=16, tgt=7, sweep_start=8) == -1


# --- decide_harvest_result：成功判定（修「框消失≠我們採到」假成功）---
# 背景bug（2026-06-29 trace 20260629_022126）：真追蹤框疊在角色身上，D3 兩次都打不到，
# 但框被別人(small_lo)/掃描到期弄消失 → gone=True 被當成功。實際我方聊天無 "has found"。
# 修法：成功必須有我方 has found（confirmed）；gone 而未確認 = 礦被別人/到期拿走 → 重掃。

def test_decide_success_requires_confirmed_chat():
    # 我方 has found 出現 → 成功（不論框在不在）
    assert decide_harvest_result(gone=False, confirmed=True) == "SUCCESS"
    assert decide_harvest_result(gone=True, confirmed=True) == "SUCCESS"

def test_decide_gone_without_confirm_is_resweep_not_success():
    # ★ 核心bug：框消失但我方聊天無確認 → 礦被別人/掃描到期拿走，不是我們採到 → 重掃
    assert decide_harvest_result(gone=True, confirmed=False) == "RESWEEP"

def test_decide_still_there_and_unconfirmed_is_retry():
    # 框還在、未確認 → D3 沒打中，原地重試
    assert decide_harvest_result(gone=False, confirmed=False) == "RETRY"


# --- format_rotation_hint：採集放棄時給 Discord 看的旋轉提示（純函式）---
def test_rotation_hint_positive_means_dot_key():
    # 淨右轉 3 → 從原視角按 . 三次面對該角度
    h = format_rotation_hint(3)
    assert h != ""
    assert ". 3" in h and "135°" in h

def test_rotation_hint_negative_means_comma_key():
    h = format_rotation_hint(-2)
    assert h != ""
    assert ", 2" in h and "90°" in h

def test_rotation_hint_zero_is_empty_string():
    # 在原視角就不必提示（避免 Discord 訊息多出雜訊）
    assert format_rotation_hint(0) == ""


# --- format_harvest_id：每輪採集的可搜尋編號（純函式）---
# 目的：log / 快照檔名 / Discord 共用同一個編號，事後說「7 號似乎誤判」即可一鍵搜查。
# 純數字（不加 H 前綴）：避免與 docs/incidents.md 的事故編號 Hxxx 混淆（使用者回饋 2026-07-07）。
def test_format_harvest_id_zero_pads_to_three_digits():
    assert format_harvest_id(1) == "001"
    assert format_harvest_id(7) == "007"
    assert format_harvest_id(42) == "042"

def test_format_harvest_id_beyond_three_digits_keeps_growing():
    # 單次執行採超過 999 顆才會到（極罕見），仍要正確不截斷
    assert format_harvest_id(1000) == "1000"

def test_harvest_state_carries_harvest_id():
    st = HarvestState(rotations=0, elapsed_s=0.0, harvest_id="001")
    assert st.harvest_id == "001"

def test_harvest_state_harvest_id_defaults_empty():
    # 既有呼叫端（HarvestState(0, 0.0)）不傳 id 仍可建構，預設空字串
    st = HarvestState(rotations=0, elapsed_s=0.0)
    assert st.harvest_id == ""


# --- plan_giveup：放棄時視角處置 + 截圖方案（純函式，需求 A+C）---
def test_giveup_face_tracker_keeps_view_and_shows_tracker():
    # 有框採不到：不轉回、保持面對追蹤框，主圖給追蹤框裁圖
    plan = plan_giveup(face_tracker=True)
    assert plan.restore_view is False
    assert plan.tracker_view is True

def test_giveup_face_tracker_also_attaches_review_crops():
    # H015：D3 超時交人工時只送了追蹤框裁圖（而框已消失＝圖上空無一物），
    # 使用者無從判斷 → 有框路徑也要附聊天/背包前後對比（與無框路徑同一組）。
    plan = plan_giveup(face_tracker=True)
    assert len(plan.review_crops) == 4
    assert [(c.source, c.region) for c in plan.review_crops] == [
        ("before", "chat"), ("after", "chat"),
        ("before", "backpack"), ("after", "backpack"),
    ]

def test_giveup_no_tracker_restores_and_uses_four_review_crops():
    # 沒找到框：轉回原視角 + 4 張左側前後對比裁圖
    plan = plan_giveup(face_tracker=False)
    assert plan.restore_view is True
    assert plan.tracker_view is False
    assert len(plan.review_crops) == 4

def test_giveup_review_crops_order_is_chat_then_backpack_before_after():
    # Discord 2x2 縮圖：上排聊天(前/後)、下排背包(前/後)
    crops = plan_giveup(face_tracker=False).review_crops
    assert [(c.source, c.region) for c in crops] == [
        ("before", "chat"), ("after", "chat"),
        ("before", "backpack"), ("after", "backpack"),
    ]

def test_giveup_review_crop_labels_are_unique_and_descriptive():
    crops = plan_giveup(face_tracker=False).review_crops
    labels = [c.label for c in crops]
    assert labels == ["giveup_before_chat", "giveup_after_chat",
                      "giveup_before_backpack", "giveup_after_backpack"]
    assert len(set(labels)) == 4


# --- giveup_send_groups：放棄裁圖依 region 分組，供 Discord「先聊天框、再背包」分開發送 ---
def test_giveup_send_groups_order_is_chat_then_backpack():
    groups = giveup_send_groups(plan_giveup(face_tracker=False).review_crops)
    assert [region for region, _ in groups] == ["chat", "backpack"]

def test_giveup_send_groups_each_group_keeps_before_after_pattern():
    # 「保持一樣的模式」：每群仍是前/後對比兩張
    groups = giveup_send_groups(plan_giveup(face_tracker=False).review_crops)
    for _region, crops in groups:
        assert [c.source for c in crops] == ["before", "after"]

def test_giveup_send_groups_empty_when_no_review_crops():
    # 空 review_crops → 無分組（防呆；兩條路徑現在都有 crops，但函式仍須處理空輸入）
    assert giveup_send_groups(()) == []


# --- decide_verify_poll：D3 後輪詢驗證（H015 對策）---
# 舊流程 click 後固定等 0.5s 抓一幀就判生死：H015 第二槍實際命中，但框 2~10s 後才消失、
# 聊天成功行更晚到（且聊天淡出後看不見）→ gone=False + no-new → RETRY → 下一 tick 超時交人工。
# 改成在窗口內輪詢：confirmed 隨時早退成功；窗口未到一律續等（等晚到的行/慢消失的框）；
# 窗口到才用 decide_harvest_result 收尾。
def test_verify_poll_confirmed_is_immediate_success():
    assert decide_verify_poll(gone=False, confirmed=True, elapsed_s=0.1, window_s=8.0) == "SUCCESS"
    assert decide_verify_poll(gone=True, confirmed=True, elapsed_s=9.9, window_s=8.0) == "SUCCESS"

def test_verify_poll_keeps_polling_inside_window():
    # 窗口內未確認 → 續等（框在不在都一樣：晚到的聊天行才是成功的唯一證據）
    assert decide_verify_poll(gone=False, confirmed=False, elapsed_s=3.0, window_s=8.0) == "POLL"
    assert decide_verify_poll(gone=True, confirmed=False, elapsed_s=3.0, window_s=8.0) == "POLL"

def test_verify_poll_window_end_falls_back_to_harvest_result():
    # 窗口到、未確認 → 與既有 decide_harvest_result 同語意（gone→RESWEEP、框還在→RETRY）
    assert decide_verify_poll(gone=True, confirmed=False, elapsed_s=8.1, window_s=8.0) == "RESWEEP"
    assert decide_verify_poll(gone=False, confirmed=False, elapsed_s=8.1, window_s=8.0) == "RETRY"


# --- pick_sweep_candidate：sweep 多方位候選中選「最接近畫面中心」者（H019 對策）---
# H019：dir=3/4/5 三方位都看到同一顆框（x=1473/939/372），舊版取 candidates[0]（=最先看到的
# dir=3，x 離中心 533px）；轉回後 D5 到期 FOV 收縮把框往外推 ~390px → 撞進畫面邊緣 10%
# 排除帶（margin_frac）→ verify 整幀找不到 → 誤判「未找到」交人工。選最居中者（dir=4，
# 離中心 21px）天然留足邊緣餘裕，同樣位移後仍在偵測區內。
def test_pick_sweep_candidate_prefers_most_centered_x():
    cands = [(3, (1473, 493)), (4, (939, 512)), (5, (372, 489))]
    assert pick_sweep_candidate(cands, screen_w=1920) == (4, (939, 512))

def test_pick_sweep_candidate_single_candidate_returned_as_is():
    assert pick_sweep_candidate([(0, (1600, 400))], screen_w=1920) == (0, (1600, 400))

def test_pick_sweep_candidate_empty_returns_none():
    assert pick_sweep_candidate([], screen_w=1920) is None


# --- decide_sweep_failure：sweep 失敗依「掃描時是否看過穩定框」分流（H019 對策）---
# 「全 8 方位都沒看到」＝偵測已準、礦多半已被挖走 → 人工（2026-06-29 決策不變）。
# 「看到過穩定框、只是轉回後 verify 失敗」＝框確實存在（FOV 位移/邊緣裁切/短暫遮擋）
# → 重掃一次值得；上限 1 次防 verify 反覆失敗的無限重掃。
def test_sweep_failure_no_candidates_goes_human():
    assert decide_sweep_failure(had_candidates=False, resweeps_done=0) == "HUMAN"

def test_sweep_failure_with_candidates_resweeps_once():
    assert decide_sweep_failure(had_candidates=True, resweeps_done=0) == "RESWEEP"

def test_sweep_failure_resweep_budget_exhausted_goes_human():
    assert decide_sweep_failure(had_candidates=True, resweeps_done=1) == "HUMAN"


# --- scan_succeeded：D2 掃描成功確認（HANDOFF F）——OCR 左下 Local 標籤 ---
def test_scan_succeeded_exact_local():
    assert harvester.scan_succeeded(["Local"]) is True

def test_scan_succeeded_tolerates_ocr_noise():
    # 遊戲字型 i/l 同形（H033 教訓）＋常見誤讀
    assert harvester.scan_succeeded(["LocaI 12"]) is True
    assert harvester.scan_succeeded(["1ocal"]) is True

def test_scan_succeeded_rejects_empty_and_unrelated():
    assert harvester.scan_succeeded([]) is False
    assert harvester.scan_succeeded([""]) is False
    assert harvester.scan_succeeded(["Global"]) is False   # ratio("global","local")≈0.73 < 0.75


class TestPlanPitchLayers:
    """失敗路徑俯仰掃描的層規劃（2026-07-11 spec）：未校準/停用回空；啟用回上→下兩層。"""

    def test_disabled_returns_empty(self):
        assert harvester.plan_pitch_layers(False, 300, 400) == []

    def test_uncalibrated_step_returns_empty(self):
        assert harvester.plan_pitch_layers(True, 0, 400) == []

    def test_uncalibrated_center_back_returns_empty(self):
        assert harvester.plan_pitch_layers(True, 300, 0) == []

    def test_enabled_yields_up_then_down(self):
        layers = harvester.plan_pitch_layers(True, 300, 400)
        assert [l.name for l in layers] == ["up", "down"]
        assert [l.nudge_px for l in layers] == [-300, 300]


class TestDecideSweepFailurePitchLayers:
    """全空且尚有俯仰層 → NEXT_LAYER；其餘維持 H019 既有分流。"""

    def test_all_empty_with_layers_left(self):
        assert harvester.decide_sweep_failure(False, 0, pitch_layers_left=2) == "NEXT_LAYER"

    def test_all_empty_layers_exhausted(self):
        assert harvester.decide_sweep_failure(False, 0, pitch_layers_left=0) == "HUMAN"

    def test_resweep_takes_priority_over_layers(self):
        # 看過穩定框＝框在「這一層」，先在本層重掃（H019），不跳層
        assert harvester.decide_sweep_failure(True, 0, pitch_layers_left=2) == "RESWEEP"

    def test_had_candidates_resweeps_exhausted_goes_human(self):
        # spec：俯仰層只掛「全空」分支——verify 反覆失敗是 FOV 位移問題，跳層無益
        assert harvester.decide_sweep_failure(True, 1, pitch_layers_left=2) == "HUMAN"


class TestSweepSnapshotLabel:
    def test_mid_keeps_legacy_name(self):
        # 標準層維持舊檔名——logs/_diag_tracker.py 與文件的 `*sweep_empty*` glob 兩者都吃，
        # 但既有排錯習慣搜 sweep_empty_dirN，不無故改名
        assert harvester.sweep_snapshot_label("mid", 3) == "sweep_empty_dir3"

    def test_pitch_layer_tagged(self):
        assert harvester.sweep_snapshot_label("up", 0) == "sweep_empty_up_dir0"
        assert harvester.sweep_snapshot_label("down", 7) == "sweep_empty_down_dir7"


def test_harvest_state_pitch_defaults():
    st = harvester.HarvestState(rotations=0, elapsed_s=0.0)
    assert st.pitch_layer == "mid"
    assert st.pitch_layers_left == []
    assert st.pitch_touched is False


def test_harvest_state_extra_targets_defaults_zero():
    # episode 進場時 HarvestState 全新建構 → extra_targets=0（incident 072 續採計數起點）
    st = HarvestState(rotations=0, elapsed_s=0.0)
    assert st.extra_targets == 0


# --- decide_post_success：採集成功後續採決策（純函式，incident 072 對策）---
# 同一 chill episode 可能同畫面有兩顆不同階礦的追蹤框；採到第一顆後畫面仍清晰存在
# 第二顆 → 舊版無條件回 MINING 直接漏採。寧漏勿誤：距離閘擋「剛採掉、2~10s 才淡出」
# 的原地殘影（漂移 ≤8px），真第二顆距上一發開火座標 551px（072 實錄）遠超 100px 閘。
def test_post_success_no_tracker_exits():
    assert decide_post_success(None, (607, 223), 0, 2, 100) == "EXIT"

def test_post_success_extra_budget_exhausted_exits():
    # 已續採到上限（2,2）→ 即使畫面還有框也不續採（迴圈保險）
    assert decide_post_success((1097, 475), (607, 223), 2, 2, 100) == "EXIT"

def test_post_success_no_fired_pos_exits():
    # 晚到確認路徑：上一發座標已被 RESWEEP 清掉，無法距離閘 → 不續採
    assert decide_post_success((1097, 475), None, 0, 2, 100) == "EXIT"

def test_post_success_too_close_to_fired_pos_exits():
    # 剛採掉的框擊中後 2~10s 才淡出，原地殘影漂移 ≤8px → 距離閘擋下
    assert decide_post_success((609, 215), (607, 223), 0, 2, 100) == "EXIT"

def test_post_success_072_real_values_continues():
    # 072 實錄：第二顆 (1097,475) 距上一發 (607,223)＝551px，遠超 100px 閘 → 續採
    assert decide_post_success((1097, 475), (607, 223), 0, 2, 100) == "CONTINUE"


# --- decide_sweep_failure：extra_mode（續採途中 bonus 框淡掉≠失敗，incident 072）---
def test_sweep_failure_extra_mode_no_candidates_exits_success():
    # 續採途中 sweep 全空＝bonus 框已淡出，episode 已有成功入帳 → 正常收尾，不交人工/換層
    assert decide_sweep_failure(had_candidates=False, resweeps_done=0,
                                extra_mode=True) == "EXIT_SUCCESS"

def test_sweep_failure_extra_mode_resweep_budget_exhausted_exits_success():
    assert decide_sweep_failure(had_candidates=True, resweeps_done=1,
                                extra_mode=True) == "EXIT_SUCCESS"

def test_sweep_failure_extra_mode_all_empty_with_layers_exits_success():
    # 續採途中不 escalate 到換俯仰層——bonus 框淡掉即收尾
    assert decide_sweep_failure(had_candidates=False, resweeps_done=0,
                                pitch_layers_left=2, extra_mode=True) == "EXIT_SUCCESS"

def test_sweep_failure_extra_mode_with_candidates_still_resweeps():
    # RESWEEP 條件成立時仍 RESWEEP（框還在、值得重定位）
    assert decide_sweep_failure(had_candidates=True, resweeps_done=0,
                                extra_mode=True) == "RESWEEP"

def test_sweep_failure_default_behavior_unchanged_without_extra_mode():
    # 既有行為：extra_mode 未傳（預設 False）→ 原 RESWEEP/NEXT_LAYER/HUMAN 分流不變
    assert decide_sweep_failure(had_candidates=False, resweeps_done=0) == "HUMAN"
    assert decide_sweep_failure(had_candidates=True, resweeps_done=0) == "RESWEEP"
    assert decide_sweep_failure(had_candidates=True, resweeps_done=1) == "HUMAN"
    assert decide_sweep_failure(had_candidates=False, resweeps_done=0,
                                pitch_layers_left=2) == "NEXT_LAYER"

def test_mining_pitch_home_enabled_requires_calibration():
    # <=0＝未校準＝停用（與 plan_pitch_layers 同慣例）；>0＝已校準
    assert harvester.mining_pitch_home_enabled(0) is False
    assert harvester.mining_pitch_home_enabled(-40) is False
    assert harvester.mining_pitch_home_enabled(300) is True


# ===== 啟動仰角顯示（2026-07-18 使用者要求：啟動時 log＋Discord 顯示目前仰角）=====
def test_format_startup_pitch_status_homed():
    from miningbot.harvester import format_startup_pitch_status
    s = format_startup_pitch_status(300, homed=True, offset_px=300)
    assert "夾限上 300px" in s and "標準角" in s


def test_format_startup_pitch_status_eaten():
    from miningbot.harvester import format_startup_pitch_status
    s = format_startup_pitch_status(300, homed=False, offset_px=0)
    assert "被吃" in s or "不受控" in s


def test_format_startup_pitch_status_uncalibrated():
    from miningbot.harvester import format_startup_pitch_status
    s = format_startup_pitch_status(0, homed=False, offset_px=0)
    assert "未校準" in s and "角度不明" in s


def test_plan_boost_pair_due():
    """FOV 前後幀對節流（2026-07-19）：計數前進 N 才存、None 不存、首次必存。"""
    from miningbot.harvester import plan_boost_pair_due
    assert plan_boost_pair_due(42, None, 10) is True       # session 首次＝基準點
    assert plan_boost_pair_due(45, 42, 10) is False        # 未滿 N
    assert plan_boost_pair_due(52, 42, 10) is True         # 滿 N
    assert plan_boost_pair_due(None, 42, 10) is False      # 讀不出＝無 x 軸標籤，不存
    assert plan_boost_pair_due(42, None, 0) is False       # 功能關閉


# ── chill 前證據快取取用（spec 2026-07-30-prechill-evidence-cache-design.md A 段）──

def _entry(ts):
    return (ts, f"chat@{ts}", f"panel@{ts}")


def test_pick_prechill_ref_takes_newest_old_enough():
    from miningbot.harvester import pick_prechill_ref
    entries = [_entry(100.0), _entry(101.0), _entry(102.0), _entry(103.0)]
    # before_ts=105、min_age=3 → 上界 102 → 取 102（≤ 上界的最新一筆）
    assert pick_prechill_ref(entries, 105.0, 3.0, 6.0)[0] == 102.0


def test_pick_prechill_ref_empty_buffer():
    from miningbot.harvester import pick_prechill_ref
    assert pick_prechill_ref([], 105.0, 3.0, 6.0) is None


def test_pick_prechill_ref_all_too_new():
    """全部都比 chill 晚不到 min_age_s → None（太新的參考可能已含那次挖掘）。"""
    from miningbot.harvester import pick_prechill_ref
    entries = [_entry(104.0), _entry(104.5)]
    assert pick_prechill_ref(entries, 105.0, 3.0, 6.0) is None


def test_pick_prechill_ref_boundary_is_inclusive():
    from miningbot.harvester import pick_prechill_ref
    assert pick_prechill_ref([_entry(102.0)], 105.0, 3.0, 6.0)[0] == 102.0
    assert pick_prechill_ref([_entry(102.01)], 105.0, 3.0, 6.0) is None


def test_pick_prechill_ref_rejects_stale_previous_episode_frame():
    """上界：快取進 HARVESTING 不清空，回 MINING 沒幾秒又 chill 時緩衝裡還留著
    **上一場之前**的幀。拿它當基準會把上一場採到的礦算成這一場的新增＝假救援
    ＝靜默放生一顆真稀有礦。過期一律回 None（救援整個跳過＝回到今日行為）。"""
    from miningbot.harvester import pick_prechill_ref
    # 上一場 episode 跑了三分鐘：緩衝裡只有 chill 前 180 秒的殘幀
    assert pick_prechill_ref([_entry(925.0)], 1105.0, 3.0, 6.0) is None
    # 剛好落在上界內就仍然可用（兩側夾）
    assert pick_prechill_ref([_entry(1099.0)], 1105.0, 3.0, 6.0)[0] == 1099.0


def test_pick_prechill_ref_stale_entry_never_rescued_by_older_one():
    """最新的合格候選過期時不得往回找更舊的——更舊只會更糟。"""
    from miningbot.harvester import pick_prechill_ref
    assert pick_prechill_ref([_entry(900.0), _entry(925.0)], 1105.0, 3.0, 6.0) is None


# ── NORMAL 面板名字欄剖析（spec 2026-07-30-giveup-rescue-already-mined-design.md）──
# 幾何依 2026-07-30 全螢幕實機量測：名字框中心 x 72~103、標頭 y≈14、篩選框 y≈45、
# 第一列 y≈78；右側 craft 面板自 x≈185 起。

_GATES = dict(max_x=DEFAULT.panel_name_col_max_x, min_y=DEFAULT.panel_row_min_y)


def _box(text, x, y):
    return {"text": text, "score": 0.99, "center": (x, y)}


def test_parse_panel_splits_name_from_stuck_count():
    """黏框切在第一個數字或逗號之前（RapidOCR 實測 125 的最後兩列）。"""
    from miningbot.harvester import parse_panel_ore_names
    boxes = [_box("Cloverstone 1,6", 101, 258), _box("Imbollyx. 8", 103, 320)]
    assert parse_panel_ore_names(boxes, **_GATES) == ["cloverstone", "imbollyx"]


def test_parse_panel_passes_clean_names_through():
    from miningbot.harvester import parse_panel_ore_names
    boxes = [_box("Leprechaun", 82, 78), _box("Faedrine", 83, 113)]
    assert parse_panel_ore_names(boxes, **_GATES) == ["leprechaun", "faedrine"]


def test_parse_panel_drops_header_and_filter_box():
    """NORMAL 標頭與 www 篩選框在 y 閘之上——擋掉才不會被當礦名。"""
    from miningbot.harvester import parse_panel_ore_names
    boxes = [_box("NORMAL", 115, 14), _box("www", 118, 45), _box("Faedrine", 83, 113)]
    assert parse_panel_ore_names(boxes, **_GATES) == ["faedrine"]


def test_parse_panel_drops_craft_panel_column():
    """右側 Shamrock craft 面板（x≈185 起）整欄不得進名字集合。"""
    from miningbot.harvester import parse_panel_ore_names
    boxes = [_box("Materials", 204, 200), _box("310", 210, 169), _box("Siogyne", 80, 186)]
    assert parse_panel_ore_names(boxes, **_GATES) == ["siogyne"]


def test_parse_panel_drops_short_ocr_noise():
    """craft 面板數字被讀歪出來的 1-2 字雜訊（實測 '\u2022P11/'、'.73'）不得變成假礦名。"""
    from miningbot.harvester import parse_panel_ore_names
    assert parse_panel_ore_names(
        [_box("\u2022P11/", 100, 209), _box(".73", 100, 268), _box("4/", 100, 248)],
        **_GATES) == []


def test_parse_panel_dedupes_preserving_order():
    from miningbot.harvester import parse_panel_ore_names
    boxes = [_box("Faedrine", 83, 113), _box("faedrine", 83, 150)]
    assert parse_panel_ore_names(boxes, **_GATES) == ["faedrine"]


# ── 面板白名單存在性檢查（spec 2026-07-31）─────────────────────────────────

def test_rare_panel_ores_reports_whitelist_names():
    from miningbot.harvester import rare_panel_ores
    assert rare_panel_ores(["leprechaun", "faedrine"]) == ["leprechaun", "faedrine"]


def test_rare_panel_ores_filters_common():
    """common（Surreal/Mythic）不在白名單上 → 濾掉。"""
    from miningbot.harvester import rare_panel_ores
    assert rare_panel_ores(["weevil", "siogyne", "faedrine"]) == ["faedrine"]


def test_rare_panel_ores_filters_unknown():
    """H069：unknown（低階礦兩張表都沒有）不算進帳。"""
    from miningbot.harvester import rare_panel_ores
    from miningbot import game_data
    game_data.set_world("Lucernia")
    try:
        assert game_data.classify_found_ore("cloverstone")[0] == "unknown"
        assert rare_panel_ores(["faedrine", "cloverstone"]) == ["faedrine"]
    finally:
        game_data.clear_world()


def test_rare_panel_ores_empty_is_empty():
    from miningbot.harvester import rare_panel_ores
    assert rare_panel_ores([]) == []
    assert rare_panel_ores(None) == []


def test_rare_panel_ores_rejects_fuzzy_match():
    """spec 02：面板只認 exact，不收 rare_fuzzy。

    `essence of luck`（低階、底色 H=0）被模糊配到 Lovessence（Transcendent、Aesteria）
    ratio 0.824 → 假陽性。238 幀 1909 列量測：320 列真陽性全是 exact（ratio None），
    rare_fuzzy 在面板上的唯一貢獻就是這類假命中。聊天路徑不動（那邊真的需要模糊）。
    """
    from miningbot.harvester import rare_panel_ores
    from miningbot import game_data
    assert game_data.classify_found_ore("essence of luck")[0] == "rare_fuzzy"
    assert rare_panel_ores(["essence of luck"]) == []
    # exact 仍然收
    assert rare_panel_ores(["faedrine", "essence of luck"]) == ["faedrine"]


def test_rare_panel_ores_h069_live_panel_names():
    """H069 實錄（2026-07-31 harvest 145）：整排全是鎬子挖到的低階礦 → 回空。

    `egguinox` 是第二顆地雷：Lucernia 白名單真的有一顆叫 `Eg`，裸 startswith 讓它被判成
    Transcendent。`_prefix_hit` 修復後 egguinox 落 unknown。
    """
    from miningbot.harvester import rare_panel_ores
    from miningbot import game_data
    game_data.set_world("Lucernia")
    try:
        names = ["duskgravite", "siogyne", "sugarmuck", "egguinox", "cloverstone",
                 "imbollyx", "bonnite", "fortunatum"]
        assert rare_panel_ores(names) == []
    finally:
        game_data.clear_world()


# ── 面板標頭與歸零驗證（spec 2026-07-31 面板歸零救援）──────────────────────

_PANEL_HEADERS = ("NORMAL", "IONIZED", "SPECTRAL")


def test_panel_header_finds_normal():
    from miningbot.harvester import panel_header
    boxes = [_box("NORMAL", 118, 14), _box("faedrine", 80, 78)]
    assert panel_header(boxes, DEFAULT.panel_row_min_y, _PANEL_HEADERS) == "NORMAL"


def test_panel_header_finds_spectral():
    from miningbot.harvester import panel_header
    boxes = [_box("SPECTRAL", 118, 14)]
    assert panel_header(boxes, DEFAULT.panel_row_min_y, _PANEL_HEADERS) == "SPECTRAL"


def test_panel_header_none_when_below_row_min_y():
    """標頭框落在 row_min_y 以下（ 礦名列區）→ 不算標頭。"""
    from miningbot.harvester import panel_header
    boxes = [_box("NORMAL", 118, 78)]
    assert panel_header(boxes, DEFAULT.panel_row_min_y, _PANEL_HEADERS) is None


def test_panel_header_none_when_empty():
    from miningbot.harvester import panel_header
    assert panel_header([], DEFAULT.panel_row_min_y, _PANEL_HEADERS) is None


def test_panel_header_ignores_non_header_text():
    """www 篩選框 y≈45 < row_min_y=60，但文字不在標頭集合 → 不算標頭。"""
    from miningbot.harvester import panel_header
    boxes = [_box("wwww", 119, 45), _box("Faedrine", 80, 78)]
    assert panel_header(boxes, DEFAULT.panel_row_min_y, _PANEL_HEADERS) is None


def test_panel_is_zeroed_true_for_normal_empty():
    from miningbot.harvester import panel_is_zeroed
    assert panel_is_zeroed("NORMAL", [], "NORMAL") is True


def test_panel_is_zeroed_false_for_wrong_page():
    from miningbot.harvester import panel_is_zeroed
    assert panel_is_zeroed("SPECTRAL", [], "NORMAL") is False


def test_panel_is_zeroed_false_when_whitelist_ore_present():
    from miningbot.harvester import panel_is_zeroed
    assert panel_is_zeroed("NORMAL", ["faedrine"], "NORMAL") is False


def test_panel_is_zeroed_true_when_only_low_tier_rows():
    """低階礦回填不算破壞零點（2026-07-31 使用者）。

    清空之後那一下「點畫面中央還焦點」是真的挖礦點擊，實測馬上挖到一顆 shamrock
    回填面板（17:37:04 讀到 1 列 shamrock）。路 B 只問「有沒有白名單礦」，所以要驗
    的不變式是「此刻面板上沒有白名單礦」，不是「面板全空」——後者實機上永遠達不到。
    """
    from miningbot.harvester import panel_is_zeroed
    assert panel_is_zeroed("NORMAL", ["shamrock"], "NORMAL") is True
    assert panel_is_zeroed("NORMAL", ["shamrock", "loinnire"], "NORMAL") is True


def test_panel_is_zeroed_false_when_low_tier_and_whitelist_mixed():
    """混著也不行：白名單礦在場就是零點不成立。"""
    from miningbot.harvester import panel_is_zeroed
    assert panel_is_zeroed("NORMAL", ["shamrock", "faedrine"], "NORMAL") is False


# ── 列底色 → tier（D11 量測：每階一色、零重疊）────────────────────────────

def test_whitelist_hue_hits_catches_the_three_high_tiers():
    """Exotic 46／Exquisite 128／Transcendent 210 都要認得。"""
    from miningbot.harvester import whitelist_hue_hits
    hues = list(DEFAULT.panel_whitelist_hues)
    assert whitelist_hue_hits(hues, DEFAULT.panel_whitelist_hues,
                              DEFAULT.panel_hue_tol_deg) == hues


def test_whitelist_hue_hits_rejects_every_measured_low_tier_band():
    """實機量到的非白名單色帶（Mythic 304／Surreal 166／低階 0、30、280）一個都不能中。

    最近的一對是 Exotic 46 vs 低階 30（相隔 16°），tol=6 兩側各留 10° 餘裕。
    """
    from miningbot.harvester import whitelist_hue_hits
    assert whitelist_hue_hits([0.0, 30.0, 166.0, 280.0, 304.0],
                              DEFAULT.panel_whitelist_hues,
                              DEFAULT.panel_hue_tol_deg) == []


def test_whitelist_hue_hits_is_circular_and_skips_none():
    """色相是環狀的（358 與 2 相差 4°）；讀不到的列（None）直接略過不當命中。"""
    from miningbot.harvester import whitelist_hue_hits
    assert whitelist_hue_hits([358.0], (2.0,), 6.0) == [358.0]
    assert whitelist_hue_hits([None, 30.0], DEFAULT.panel_whitelist_hues,
                              DEFAULT.panel_hue_tol_deg) == []


def test_panel_row_hues_reads_the_row_background():
    """合成一張兩列不同底色的面板裁圖，色相要讀回那兩個值。"""
    import cv2
    import numpy as np

    from miningbot.vision import panel_row_hues
    crop = np.zeros((200, 226, 3), dtype=np.uint8)
    # OpenCV HSV：H 是 0..179（度數的一半）。Exotic 46° → 23；Surreal 166° → 83
    for y0, y1, h in ((40, 80, 23), (100, 140, 83)):
        band = np.zeros((y1 - y0, 226, 3), dtype=np.uint8)
        band[:, :] = (h, 200, 200)
        crop[y0:y1] = cv2.cvtColor(band, cv2.COLOR_HSV2BGR)
    got = panel_row_hues(crop, [60, 120], *DEFAULT.panel_hue_sample_x)
    assert [round(v) for v in got] == [46, 166]


def test_panel_rows_keeps_row_y_for_hue_sampling():
    """`parse_panel_rows` 要回 (name, cy)，名字版本是它的投影（只有一份實作）。"""
    from miningbot.harvester import parse_panel_ore_names, parse_panel_rows
    boxes = [{"text": "Faedrine 17", "center": (80, 78)},
             {"text": "Weevil 229", "center": (80, 114)}]
    rows = parse_panel_rows(boxes, DEFAULT.panel_name_col_max_x,
                            DEFAULT.panel_row_min_y, DEFAULT.panel_name_min_letters)
    assert rows == [("faedrine", 78), ("weevil", 114)]
    assert parse_panel_ore_names(boxes, DEFAULT.panel_name_col_max_x,
                                 DEFAULT.panel_row_min_y,
                                 DEFAULT.panel_name_min_letters) == ["faedrine", "weevil"]


# ── 反向色相閘（spec 01：未知色相當高階，擋零點成立）─────────────────────

def test_non_low_tier_hues_blocks_known_whitelist_bands():
    """三個已量到的高階色帶（46/128/210）都要回來——它們不是低階。"""
    from miningbot.harvester import non_low_tier_hues
    got = non_low_tier_hues([46.0, 128.0, 210.0],
                            DEFAULT.panel_low_tier_hues, DEFAULT.panel_hue_tol_deg)
    assert got == [46.0, 128.0, 210.0]


def test_non_low_tier_hues_rejects_every_measured_low_tier_band():
    """五個已量到的低階色帶（0/30/166/280/304）一個都不能中。"""
    from miningbot.harvester import non_low_tier_hues
    assert non_low_tier_hues([0.0, 30.0, 166.0, 280.0, 304.0],
                             DEFAULT.panel_low_tier_hues,
                             DEFAULT.panel_hue_tol_deg) == []


def test_non_low_tier_hues_treats_unknown_hue_as_high_tier():
    """未量到的色相（例如 90）→ 當成高階、擋零點成立（spec 01 核心決定）。"""
    from miningbot.harvester import non_low_tier_hues
    assert non_low_tier_hues([90.0], DEFAULT.panel_low_tier_hues,
                             DEFAULT.panel_hue_tol_deg) == [90.0]


def test_non_low_tier_hues_skips_none_and_is_circular():
    """None 略過；環狀（358 與 0 相差 2°）要算落在低階帶。"""
    from miningbot.harvester import non_low_tier_hues
    assert non_low_tier_hues([None, 30.0], DEFAULT.panel_low_tier_hues,
                             DEFAULT.panel_hue_tol_deg) == []
    assert non_low_tier_hues([358.0], (0.0,), 6.0) == []   # 358 距 0 是 2°


def test_panel_is_zeroed_false_when_header_missing():
    from miningbot.harvester import panel_is_zeroed
    assert panel_is_zeroed(None, [], "NORMAL") is False


# ── 雙 chill 對帳判定（spec 2026-07-30-double-chill-reconciliation-design.md）──

def test_chill_reconcile_single_edge_always_balanced():
    from miningbot.harvester import chill_reconcile_unbalanced
    assert chill_reconcile_unbalanced(0, 0) is False
    assert chill_reconcile_unbalanced(1, 0) is False     # 單聲 chill 不進對帳
    assert chill_reconcile_unbalanced(1, 1) is False


def test_chill_reconcile_two_edges_one_gain_is_unbalanced():
    from miningbot.harvester import chill_reconcile_unbalanced
    assert chill_reconcile_unbalanced(2, 1) is True
    assert chill_reconcile_unbalanced(2, 0) is True
    assert chill_reconcile_unbalanced(3, 2) is True


def test_chill_reconcile_balanced_when_gains_match():
    from miningbot.harvester import chill_reconcile_unbalanced
    assert chill_reconcile_unbalanced(2, 2) is False
    assert chill_reconcile_unbalanced(2, 3) is False     # 進帳更多（續採）也算平
