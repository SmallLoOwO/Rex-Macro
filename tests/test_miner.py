from miningbot.miner import dispatch_event, EventFlags

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
