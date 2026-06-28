import threading
import time
from miningbot.notify import format_message, make_async_sink
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


# --- make_async_sink：把阻塞的 Discord 上傳移出主迴圈 ---------------------------
# 根因：send_image_message 在 EventLog.log→_on_enter 同步跑（multipart 上傳，
# timeout 最長 15s），阻塞主迴圈 → chill 偵測後延遲、HARVESTING 期間卡頓。

def test_async_sink_returns_immediately_even_if_inner_blocks():
    """呼叫端（主迴圈）丟事件後必須立即返回，不等網路上傳。"""
    started = threading.Event()
    def slow_inner(_rec):
        started.set()
        time.sleep(1.0)                      # 模擬慢速網路上傳
    sink = make_async_sink(slow_inner)
    t0 = time.monotonic()
    sink(rec("RARE_FOUND"))
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, f"async sink 不該阻塞主迴圈，實際耗時 {elapsed:.3f}s"
    assert started.wait(2.0), "背景 worker 應已開始處理事件"


def test_async_sink_eventually_calls_inner():
    """事件最終要在背景被處理（不是丟掉）。"""
    got = []
    done = threading.Event()
    def inner(r):
        got.append(r.type)
        done.set()
    sink = make_async_sink(inner)
    sink(rec("HARVEST_SUCCESS"))
    assert done.wait(2.0), "事件應在背景被處理"
    assert got == ["HARVEST_SUCCESS"]


def test_async_sink_inner_error_does_not_kill_worker():
    """某事件處理拋例外不該讓 worker 死掉，後續事件仍要被處理。"""
    seen = []
    second = threading.Event()
    def inner(r):
        seen.append(r.type)
        if r.type == "BOOM":
            raise RuntimeError("模擬上傳失敗")
        if r.type == "OK":
            second.set()
    sink = make_async_sink(inner)
    sink(rec("BOOM"))
    sink(rec("OK"))
    assert second.wait(2.0), "worker 應在前一事件出錯後仍處理後續事件"
    assert "OK" in seen
