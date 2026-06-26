from miningbot.miner import dispatch_event, EventFlags, cooldown_ready

def flags(**kw):
    base = dict(boost_expired=False, activity_event=False, scan_event=False,
                cave_event=False, window_unfocused=False)
    base.update(kw)
    return EventFlags(**base)

def test_window_unfocused_has_top_priority():
    assert dispatch_event(flags(window_unfocused=True, boost_expired=True)) == "REFOCUS"

def test_boost_expired_uses_d5():
    assert dispatch_event(flags(boost_expired=True)) == "USE_D5"

def test_activity_event_uses_d4():
    assert dispatch_event(flags(activity_event=True)) == "USE_D4"

def test_no_event_returns_none():
    assert dispatch_event(flags()) is None

def test_priority_order_refocus_over_d4():
    assert dispatch_event(flags(window_unfocused=True, activity_event=True)) == "REFOCUS"


# --- cooldown_ready：冷卻圖示不在 = 工具就緒（D4 改用冷卻偵測而非定時）-----------
def test_cooldown_icon_present_means_not_ready():
    # 冷卻圖示還在 → 還在冷卻，不能用（不管過了多久）
    assert cooldown_ready(icon_present=True, since_last_press=99.0, grace_s=3.0) is False


def test_cooldown_clear_after_grace_means_ready():
    # 圖示不在且已過寬限 → 就緒可用
    assert cooldown_ready(icon_present=False, since_last_press=5.0, grace_s=3.0) is True


def test_cooldown_clear_within_grace_waits():
    # 圖示不在但剛按過（寬限內）→ 先等冷卻圖示出現，避免重複按
    assert cooldown_ready(icon_present=False, since_last_press=1.0, grace_s=3.0) is False
