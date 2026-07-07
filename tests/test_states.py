from miningbot.states import (State, Observation, decide_transition,
                              resolve_state_transition,
                              toggle_pause_action, is_blocked_from_mining)

def obs(**kw):
    base = dict(chill_audio=False, chill_text=False, harvest_done=False,
                harvest_failed=False, human_cleared=False)
    base.update(kw)
    return Observation(**base)

def test_mining_to_harvesting_requires_audio_and_text():
    assert decide_transition(State.MINING, obs(chill_audio=True, chill_text=True)) == State.HARVESTING

def test_mining_audio_only_stays_mining():
    # 只有音訊、OCR 未確認 → 不接管（防誤判）
    assert decide_transition(State.MINING, obs(chill_audio=True, chill_text=False)) == State.MINING

def test_harvesting_done_returns_to_mining():
    assert decide_transition(State.HARVESTING, obs(harvest_done=True)) == State.MINING

def test_harvesting_failed_goes_human():
    assert decide_transition(State.HARVESTING, obs(harvest_failed=True)) == State.NEEDS_HUMAN

def test_human_stays_until_cleared():
    assert decide_transition(State.NEEDS_HUMAN, obs()) == State.NEEDS_HUMAN
    assert decide_transition(State.NEEDS_HUMAN, obs(human_cleared=True)) == State.MINING

def test_mining_reset_goes_to_reset_wait():
    assert decide_transition(State.MINING, obs(mine_resetting=True)) == State.RESET_WAIT

def test_chill_takes_priority_over_reset():
    # 重置 + 同時 chill → 還是先去採集（稀有優先）
    assert decide_transition(State.MINING,
                             obs(mine_resetting=True, chill_audio=True, chill_text=True)) == State.HARVESTING

def test_reset_wait_yields_to_chill():
    # RESET_WAIT 期間意外出現稀有 → 強制採集
    assert decide_transition(State.RESET_WAIT,
                             obs(chill_audio=True, chill_text=True)) == State.HARVESTING

def test_reset_wait_resumes_on_clear():
    assert decide_transition(State.RESET_WAIT, obs()) == State.RESET_WAIT
    assert decide_transition(State.RESET_WAIT, obs(human_cleared=True)) == State.MINING


# --- resolve_state_transition：主迴圈 commit 邏輯（純函式）---
# 抽出來的原因：這層邏輯 inline 在 run() loop 時曾是 bug 溫床——一次 refactor 把
# 它寫成 `new_state = self.state`（讀 current 而非 decided），結果 chill 觸發的
# HARVESTING 被 commit 回 MINING，稀有礦完全不採。decide_transition 測試全綠但抓不到。
# 以下測試直接鎖定「decided 必須被採用」這個 invariant。

def test_resolve_commits_decided_when_no_override():
    # ★ 核心案例：decide_transition 回 HARVESTING，_on_enter 沒意見（None）
    # → commit 必須是 HARVESTING，不可被 current(MINING) 蓋回去。
    # （我之前的 bug 就是這裡被 inline 代碼寫成讀 current，導致採礦不啟動）
    assert resolve_state_transition(State.MINING, State.HARVESTING, None) == State.HARVESTING

def test_resolve_uses_override_when_on_enter_downgrades():
    # MINING 入口聚焦失敗 → _on_enter 回傳 NEEDS_HUMAN 降級
    assert resolve_state_transition(State.NEEDS_HUMAN, State.MINING, State.NEEDS_HUMAN) == State.NEEDS_HUMAN

def test_resolve_override_same_as_decided_is_noop():
    # _on_enter 回傳跟 decided 一樣 → 沒有降級，正常 commit
    assert resolve_state_transition(State.MINING, State.HARVESTING, State.HARVESTING) == State.HARVESTING

def test_resolve_no_transition_when_decided_equals_current():
    # decide_transition 回 current（沒變）→ commit current（_on_enter 不會被呼叫，傳 None）
    assert resolve_state_transition(State.MINING, State.MINING, None) == State.MINING

def test_resolve_override_to_same_as_current_unblocks_downgrade_loop():
    # 罕見：_on_enter 把「即將進入 X」降級回 current（表示拒絕轉換）→ 維持 current
    # （語意上與「沒降級、接受 decided」的差別在 entered != decided，但結果都是 current）
    assert resolve_state_transition(State.NEEDS_HUMAN, State.MINING, State.NEEDS_HUMAN) == State.NEEDS_HUMAN


# --- toggle_pause_action：Q 鍵 3 個分支的行為決策（純函式）---
def test_q_resumes_when_paused():
    # 暫停中按 Q → 解除暫停（即使同時處於 NEEDS_HUMAN，paused 優先）
    assert toggle_pause_action(paused=True, state=State.NEEDS_HUMAN) == "resume"
    assert toggle_pause_action(paused=True, state=State.MINING) == "resume"

def test_q_clears_human_when_in_needs_human_or_reset_wait():
    assert toggle_pause_action(paused=False, state=State.NEEDS_HUMAN) == "clear_human"
    assert toggle_pause_action(paused=False, state=State.RESET_WAIT) == "clear_human"

def test_q_pauses_when_running_normally():
    assert toggle_pause_action(paused=False, state=State.MINING) == "pause"
    assert toggle_pause_action(paused=False, state=State.HARVESTING) == "pause"


# --- is_blocked_from_mining：!resume 命令的阻塞判斷（純函式）---
def test_blocked_when_in_needs_human_or_reset_wait():
    assert is_blocked_from_mining(State.NEEDS_HUMAN, paused=False) is True
    assert is_blocked_from_mining(State.RESET_WAIT, paused=False) is True

def test_blocked_when_paused_even_in_mining():
    assert is_blocked_from_mining(State.MINING, paused=True) is True

def test_not_blocked_when_mining_and_not_paused():
    # MINING + 非暫停 = 已在挖，!resume 無效
    assert is_blocked_from_mining(State.MINING, paused=False) is False

def test_not_blocked_when_harvesting():
    # HARVESTING 中 !resume 不該介入（正在採集，別打擾）
    assert is_blocked_from_mining(State.HARVESTING, paused=False) is False
