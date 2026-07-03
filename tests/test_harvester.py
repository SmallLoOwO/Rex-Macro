from miningbot.harvester import (next_harvest_step, HarvestState, restore_actions,
                                 decide_harvest_result, decide_verify_poll,
                                 format_rotation_hint,
                                 format_harvest_id,
                                 plan_giveup, GiveupPlan, GiveupCrop,
                                 giveup_send_groups)
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
# 目的：log / 快照檔名 / Discord 共用同一個編號，事後說「H007 似乎誤判」即可一鍵搜查。
def test_format_harvest_id_zero_pads_to_three_digits():
    assert format_harvest_id(1) == "H001"
    assert format_harvest_id(7) == "H007"
    assert format_harvest_id(42) == "H042"

def test_format_harvest_id_beyond_three_digits_keeps_growing():
    # 單次執行採超過 999 顆才會到（極罕見），仍要正確不截斷
    assert format_harvest_id(1000) == "H1000"

def test_harvest_state_carries_harvest_id():
    st = HarvestState(rotations=0, elapsed_s=0.0, harvest_id="H001")
    assert st.harvest_id == "H001"

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
