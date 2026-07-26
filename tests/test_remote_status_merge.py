"""遙控器卡合併狀態顯示（spec §7 A「遙控器卡（合併狀態顯示，1 則常駐）」）。

2026-07-26：P2 Task 7 原本 post 一則**獨立**的 StatusMessenger 純文字狀態訊息，
跟遙控器 embed 本來就有的 `**狀態**` 欄重複＝同一份狀態散在兩則訊息。本次併回
遙控器卡，並依使用者裁決收緊刷新條件：

- 觸發 edit：只有 (paused, state) 變動
- 不觸發：last_action 字串、音訊分數、容量、運行時間（顯示最新值，但自己不觸發）
- 降頻上限：discord_status_edit_min_interval_s
"""
from miningbot import notify
from miningbot.main import Bot
from miningbot.states import State


class _Listener:
    def __init__(self, score):
        self._score = score

    def latest_score(self):
        return self._score


def _metrics_bot(*, score=0.42, capacity=None, started_delta=7355.0):
    import time
    bot = Bot.__new__(Bot)
    bot.listener = _Listener(score)
    bot._capacity_pct = capacity
    bot._started = time.time() - started_delta
    return bot


# ===== A. 狀態欄第二行：音訊／容量／運行時間 =====

def test_metrics_line_contains_audio_and_uptime():
    line = _metrics_bot()._build_remote_metrics_line()
    assert "音訊 0.42" in line
    assert "運行 2h02m" in line          # 7355s = 2h 2m 35s，秒不顯示


def test_metrics_line_omits_capacity_when_unknown():
    assert "容量" not in _metrics_bot(capacity=None)._build_remote_metrics_line()


def test_metrics_line_shows_capacity_when_known():
    assert "容量 45%" in _metrics_bot(capacity=45.0)._build_remote_metrics_line()


def test_metrics_line_survives_listener_failure():
    """音訊讀取炸掉不能讓遙控器整張卡組不出來（沿用 notify「失敗不中斷」慣例）。"""
    class _Boom:
        def latest_score(self):
            raise RuntimeError("audio down")

    bot = _metrics_bot()
    bot.listener = _Boom()
    assert "音訊 0.00" in bot._build_remote_metrics_line()


def test_remote_embed_embeds_metrics_line():
    """metrics 行要真的出現在遙控器 embed 裡（合併，不是另發一則）。"""
    bot = _metrics_bot(score=0.11, capacity=80.0)
    bot.state = State.MINING
    bot.paused = False
    bot.last_action = "掃描 dir3"
    embed = bot._build_remote_embed()
    desc = embed["description"]
    assert "**狀態**" in desc
    assert "音訊 0.11" in desc and "容量 80%" in desc
    assert "掃描 dir3" in desc


# ===== B. 刷新條件：只有狀態轉換觸發 =====

def test_action_string_change_alone_does_not_trigger_edit():
    """last_action 變了但 (paused, state) 沒變 → 不 PATCH。

    這是使用者 2026-07-26 的裁決：last_action 幾乎每 tick 都在動，納入觸發條件
    等於每 3s PATCH 一次到天荒地老。
    """
    bot = Bot.__new__(Bot)
    bot.paused = False
    bot.state = State.MINING
    bot._remote_message_id = "mid"
    bot._remote_last_shown = (False, State.MINING.value)

    bot.last_action = "掃描 dir3"
    before = (bot.paused, bot.state.value)
    bot.last_action = "掃描 dir4"
    assert (bot.paused, bot.state.value) == before   # 觸發鍵不含 last_action


def test_state_transition_changes_trigger_key():
    bot = Bot.__new__(Bot)
    bot.paused = False
    bot.state = State.MINING
    bot._remote_last_shown = (False, State.MINING.value)
    bot.state = State.HARVESTING
    assert bot._remote_last_shown != (bot.paused, bot.state.value)


def test_pause_toggle_changes_trigger_key():
    bot = Bot.__new__(Bot)
    bot.paused = False
    bot.state = State.MINING
    bot._remote_last_shown = (False, State.MINING.value)
    bot.paused = True
    assert bot._remote_last_shown != (bot.paused, bot.state.value)


# ===== C. 降頻：狀態機快速擺盪不逐次 PATCH =====

def test_throttle_blocks_rapid_flapping():
    t = notify.EditThrottle(min_interval_s=3.0)
    assert t.allow_edit(100.0) is True      # MINING → HARVESTING
    assert t.allow_edit(100.5) is False     # HARVESTING → MINING（0.5s 後）
    assert t.allow_edit(102.9) is False
    assert t.allow_edit(103.0) is True      # 滿 3s 才放行


def test_blocked_edit_does_not_advance_baseline():
    """被降頻擋下時 _remote_last_shown 不可前進，否則狀態會永遠停在舊值。

    _edit_remote_control 才更新 baseline；throttle 擋下時根本不呼叫它，
    所以下一輪輪詢（1s）條件仍成立 → 自動補上。這裡驗的是這個契約。
    """
    bot = Bot.__new__(Bot)
    bot.paused = False
    bot.state = State.HARVESTING
    bot._remote_message_id = "mid"
    bot._remote_last_shown = (False, State.MINING.value)
    bot._remote_edit_throttle = notify.EditThrottle(min_interval_s=3.0)

    edits = []
    bot._edit_remote_control = lambda: edits.append(1)

    def _sync_once(now):
        if (bot._remote_message_id
                and bot._remote_last_shown != (bot.paused, bot.state.value)):
            if bot._remote_edit_throttle.allow_edit(now):
                bot._edit_remote_control()

    _sync_once(100.0)
    assert len(edits) == 1
    bot._remote_last_shown = (False, State.HARVESTING.value)   # 模擬 edit 成功
    bot.state = State.MINING                                   # 立刻又擺盪回去
    _sync_once(100.5)
    assert len(edits) == 1                                     # 被擋
    assert bot._remote_last_shown == (False, State.HARVESTING.value)  # baseline 沒動
    _sync_once(103.0)
    assert len(edits) == 2                                     # 冷卻後自動補上


# ===== D. 不再有獨立狀態訊息 =====

def test_no_separate_status_messenger_on_bot():
    """Bot 不該再持有 _status_messenger／_update_status_messenger。

    留著就代表狀態又被拆回兩則訊息（違反 spec §7 A 的「1 則常駐」）。
    """
    assert not hasattr(Bot, "_update_status_messenger")
    src = Bot.run.__doc__ or ""
    assert "StatusMessenger" not in src
