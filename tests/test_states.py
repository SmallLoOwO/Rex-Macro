from miningbot.states import State, Observation, decide_transition

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
