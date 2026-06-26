import time
from miningbot.notify import format_message
from miningbot.events import EventRecord


def rec(t, **meta):
    return EventRecord(type=t, timestamp=time.time(), meta=meta)


def test_rare_found_message():
    m = format_message(rec("RARE_FOUND"))
    assert m is not None and "稀有" in m


def test_harvest_success_includes_mineral():
    m = format_message(rec("HARVEST_SUCCESS", mineral="Spectral 4FA208"))
    assert m is not None and "Spectral 4FA208" in m


def test_harvest_success_without_mineral_still_sends():
    m = format_message(rec("HARVEST_SUCCESS"))
    assert m is not None and "成功" in m


def test_needs_human_includes_reason():
    m = format_message(rec("NEEDS_HUMAN", reason="稀有礦採集失敗"))
    assert m is not None and "稀有礦採集失敗" in m


def test_stuck_includes_reason():
    m = format_message(rec("STUCK", reason="60s 無進度"))
    assert m is not None and "60s 無進度" in m


def test_mine_reset_message():
    m = format_message(rec("MINE_RESET"))
    assert m is not None and "重置" in m


def test_noise_events_are_not_sent():
    # 狀態切換、暫停/恢復、心跳等不該洗版 Discord
    assert format_message(rec("STATE_CHANGE", from_="MINING", to="HARVESTING")) is None
    assert format_message(rec("PAUSED")) is None
    assert format_message(rec("RESUMED")) is None
