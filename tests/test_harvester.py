from miningbot.harvester import (next_harvest_step, HarvestState, restore_actions,
                                 decide_harvest_result)
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
