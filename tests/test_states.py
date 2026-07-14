from miningbot.states import (State, Observation, decide_transition,
                              resolve_state_transition,
                              toggle_pause_action, is_blocked_from_mining,
                              can_consume_ability, can_accept_manual_reentry,
                              should_notify_spawn_chill,
                              update_capacity_streak)

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

def test_q_skips_env_check_during_startup():
    # 啟動環境檢查期間按 Q → 跳過剩餘檢查直接開挖（使用者「暫停重新繼續」直覺；
    # 原 F8 方案與 Roblox 內建功能衝突而廢棄，2026-07-10）。startup_phase 最優先。
    assert toggle_pause_action(paused=False, state=State.MINING,
                               startup_phase=True) == "skip_env"
    assert toggle_pause_action(paused=True, state=State.MINING,
                               startup_phase=True) == "skip_env"

def test_q_startup_phase_default_false_keeps_old_behavior():
    # 未傳 startup_phase＝既有三分支不變（回歸保護）
    assert toggle_pause_action(paused=False, state=State.MINING) == "pause"


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


# --- REENTRY：重置後自動回礦（docs/superpowers/specs/2026-07-08-mine-reentry-design.md）---

class TestReentryTransitions:
    def test_reset_wait_auto_reenter_off_stays(self):
        # auto_reenter 關 ＝ 今日行為：RESET_WAIT 等人工，reset_complete 也不自動走
        o = obs(reset_complete=True, auto_reenter=False)
        assert decide_transition(State.RESET_WAIT, o) is State.RESET_WAIT

    def test_reset_wait_enters_reentry_when_reset_complete(self):
        o = obs(reset_complete=True, auto_reenter=True)
        assert decide_transition(State.RESET_WAIT, o) is State.REENTRY

    def test_reset_wait_human_q_wins_over_auto(self):
        # 使用者按 Q＝明確接手，優先於自動路徑
        o = obs(reset_complete=True, auto_reenter=True, human_cleared=True)
        assert decide_transition(State.RESET_WAIT, o) is State.MINING

    def test_reset_wait_not_complete_waits(self):
        o = obs(auto_reenter=True)
        assert decide_transition(State.RESET_WAIT, o) is State.RESET_WAIT

    def test_reentry_done_to_mining(self):
        assert decide_transition(State.REENTRY, obs(reentry_done=True)) is State.MINING

    def test_reentry_failed_to_needs_human(self):
        assert decide_transition(State.REENTRY, obs(reentry_failed=True)) is State.NEEDS_HUMAN

    def test_reentry_failed_wins_over_done(self):
        o = obs(reentry_done=True, reentry_failed=True)
        assert decide_transition(State.REENTRY, o) is State.NEEDS_HUMAN

    def test_reentry_otherwise_stays(self):
        assert decide_transition(State.REENTRY, obs()) is State.REENTRY


# --- should_notify_spawn_chill：spawn chill 通知決策（純函式）---
# spawn chill = 礦坑刷新時稀有礦生在預設方塊。bot 處於挖不到的狀態（NEEDS_HUMAN/
# REENTRY）時 chill 響 → 只通知主人，不嘗試採集。RESET_WAIT 不算（它會直接強採）。

class TestSpawnChillNotify:
    def test_needs_human_with_chill_notifies(self):
        assert should_notify_spawn_chill(State.NEEDS_HUMAN, True, True, False) is True

    def test_reentry_with_chill_notifies(self):
        assert should_notify_spawn_chill(State.REENTRY, True, True, False) is True

    def test_mining_with_chill_does_not_notify(self):
        # MINING chill 走正常採集流程，不需 spawn chill 通知
        assert should_notify_spawn_chill(State.MINING, True, True, False) is False

    def test_reset_wait_with_chill_does_not_notify(self):
        # RESET_WAIT chill 直接轉 HARVESTING 強採，不是 spawn chill
        assert should_notify_spawn_chill(State.RESET_WAIT, True, True, False) is False

    def test_harvesting_does_not_notify(self):
        assert should_notify_spawn_chill(State.HARVESTING, True, True, False) is False

    def test_audio_only_without_text_does_not_notify(self):
        # 只有音訊、OCR 沒確認 → 防誤判，不通知
        assert should_notify_spawn_chill(State.NEEDS_HUMAN, True, False, False) is False

    def test_no_chill_does_not_notify(self):
        assert should_notify_spawn_chill(State.NEEDS_HUMAN, False, False, False) is False

    def test_already_notified_does_not_notify_again(self):
        # 去抖動：同一波 chill 已通知過 → 不重複
        assert should_notify_spawn_chill(State.NEEDS_HUMAN, True, True, True) is False
        assert should_notify_spawn_chill(State.REENTRY, True, True, True) is False


# ── update_capacity_streak：Capacity 連續飽和計數（輔助信號，2026-07-11；2026-07-12
#    起降級為「記一次飽和 INFO＋跳過後續 capacity OCR」，不再觸發 RESET_WAIT）──
# 語意：pct None（讀失敗）→ streak 原樣不推進不歸零；≥threshold → +1、達 2 觸發；
#       <threshold → 歸零。單次讀失敗不重計（防單次 OCR 抖動造成假歸零）。純函式本身不變。
TH = 100.0

def test_capacity_streak_none_keeps_streak_no_trigger():
    assert update_capacity_streak(0, None, TH) == (0, False)
    assert update_capacity_streak(1, None, TH) == (1, False)

def test_capacity_streak_single_at_threshold_no_trigger():
    assert update_capacity_streak(0, 100.0, TH) == (1, False)

def test_capacity_streak_two_consecutive_at_threshold_triggers():
    s1, t1 = update_capacity_streak(0, 100.0, TH)
    assert (s1, t1) == (1, False)
    s2, t2 = update_capacity_streak(s1, 100.0, TH)
    assert (s2, t2) == (2, True)

def test_capacity_streak_below_threshold_resets_to_zero():
    s1, _ = update_capacity_streak(0, 100.0, TH)
    s2, t2 = update_capacity_streak(s1, 95.0, TH)
    assert (s2, t2) == (0, False)

def test_capacity_streak_100_95_100_does_not_trigger():
    # 中間歸零後再 100 只是 streak=1，不觸發（防抖：連續必須不打斷）
    s1, _ = update_capacity_streak(0, 100.0, TH)
    s2, _ = update_capacity_streak(s1, 95.0, TH)
    s3, t3 = update_capacity_streak(s2, 100.0, TH)
    assert (s3, t3) == (1, False)

def test_capacity_streak_continues_true_after_first_trigger():
    # 觸發後持續 ≥門檻仍回 True（消費者用 _capacity_full_logged 去抖，只記一次 INFO）
    s2, t2 = update_capacity_streak(1, 100.0, TH)
    assert (s2, t2) == (2, True)
    s3, t3 = update_capacity_streak(s2, 101.0, TH)
    assert (s3, t3) == (3, True)

def test_capacity_streak_above_101_triggers_at_two():
    s1, t1 = update_capacity_streak(0, 101.0, TH)
    assert (s1, t1) == (1, False)
    s2, t2 = update_capacity_streak(s1, 101.0, TH)
    assert (s2, t2) == (2, True)


# --- Discord `ability` 指令：主迴圈消費狀態閘（純函式 can_consume_ability）---------
# 對應 2026-07-12 spec：遠端按一次 X。輪詢執行緒只寫旗標、主迴圈消費。
# 消費閘：HARVESTING/REENTRY 進行中插按鍵會干擾 sweep/開火/導航時序 → 不消費（旗標留著，
# 回到可消費狀態自然執行）。MINING/NEEDS_HUMAN/RESET_WAIT 可安全按 X。

def test_can_consume_ability_mining_yes():
    assert can_consume_ability(State.MINING) is True

def test_can_consume_ability_needs_human_yes():
    assert can_consume_ability(State.NEEDS_HUMAN) is True

def test_can_consume_ability_reset_wait_yes():
    assert can_consume_ability(State.RESET_WAIT) is True

def test_can_consume_ability_harvesting_no():
    # sweep/開火中插按鍵會干擾時序——旗標留著，回 MINING 自然執行
    assert can_consume_ability(State.HARVESTING) is False

def test_can_consume_ability_reentry_no():
    # 自動回礦導航中——同上，不消費
    assert can_consume_ability(State.REENTRY) is False


# ===== H044 spec 第 3 節：手動回礦觸發 =====
def _obs_manual(**kw):
    base = dict(chill_audio=False, chill_text=False, harvest_done=False,
                harvest_failed=False, human_cleared=False,
                manual_reentry=True, auto_reenter=True)
    base.update(kw)
    return Observation(**base)


def test_manual_reentry_from_mining():
    assert decide_transition(State.MINING, _obs_manual()) is State.REENTRY


def test_manual_reentry_from_needs_human_beats_human_cleared():
    o = _obs_manual(human_cleared=True)
    assert decide_transition(State.NEEDS_HUMAN, o) is State.REENTRY


def test_manual_reentry_from_reset_wait_bypasses_reset_complete():
    o = _obs_manual(mine_resetting=True, reset_complete=False)
    assert decide_transition(State.RESET_WAIT, o) is State.REENTRY


def test_manual_reentry_ignored_without_auto_reenter():
    o = _obs_manual(auto_reenter=False)
    assert decide_transition(State.MINING, o) is State.MINING


def test_manual_reentry_mining_loses_to_chill_and_reset():
    o = _obs_manual(chill_audio=True, chill_text=True)
    assert decide_transition(State.MINING, o) is State.HARVESTING
    o = _obs_manual(mine_resetting=True)
    assert decide_transition(State.MINING, o) is State.RESET_WAIT


def test_manual_reentry_does_not_touch_harvesting():
    assert decide_transition(State.HARVESTING, _obs_manual()) is State.HARVESTING


def test_can_accept_manual_reentry_matrix():
    ok, _ = can_accept_manual_reentry(State.MINING, True)
    assert ok
    ok, _ = can_accept_manual_reentry(State.RESET_WAIT, True)
    assert ok
    ok, reason = can_accept_manual_reentry(State.HARVESTING, True)
    assert not ok and "採集" in reason
    ok, reason = can_accept_manual_reentry(State.REENTRY, True)
    assert not ok and "回礦" in reason
    ok, reason = can_accept_manual_reentry(State.MINING, False)
    assert not ok and "未啟用" in reason
