import threading
import time
from miningbot.notify import format_message, make_async_sink, format_group_messages
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


def test_needs_human_appends_rotation_hint_when_present():
    """rotation_hint 出現時要接在 reason 後面（方便人工從 Discord 直接看出轉幾次）。"""
    m = format_message(rec("NEEDS_HUMAN", reason="D3 失敗",
                           rotation_hint="（面對追蹤框：按 . 3 次 ≈ 135°）"))
    assert m is not None
    assert "D3 失敗" in m
    assert "按 . 3 次" in m
    # 沒給 rotation_hint 時不能多出雜訊（既有 case 保持相容）
    m2 = format_message(rec("NEEDS_HUMAN", reason="X"))
    assert m2 is not None and m2.endswith("X")


def test_harvest_id_prefixes_message_when_present():
    """採集編號出現在 meta 時，訊息要前綴 [xxx]，讓 Discord 看到就能回報「哪個編號誤判」。"""
    m = format_message(rec("RARE_FOUND", harvest_id="001"))
    assert m is not None and m.startswith("[001]")


def test_harvest_success_keeps_id_and_mineral():
    m = format_message(rec("HARVEST_SUCCESS", harvest_id="007", mineral="Spectral 4FA208"))
    assert m is not None and m.startswith("[007]") and "Spectral 4FA208" in m


def test_needs_human_keeps_id_reason_and_hint():
    m = format_message(rec("NEEDS_HUMAN", harvest_id="003", reason="D3 失敗",
                           rotation_hint="（面對追蹤框：按 . 3 次 ≈ 135°）"))
    assert m is not None
    assert m.startswith("[003]") and "D3 失敗" in m and "按 . 3 次" in m


def test_no_harvest_id_means_no_prefix():
    # 非採集事件（或缺 id）不可多出 [H 前綴，保持既有相容
    m = format_message(rec("MINE_RESET"))
    assert m is not None and not m.startswith("[H")


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


# --- format_group_messages：人工介入截圖「先聊天框、再背包」分兩則發送（2026-07-02 需求）---
def test_format_group_messages_splits_into_one_message_per_group():
    groups = [("chat", ["cb.png", "ca.png"]), ("backpack", ["bb.png", "ba.png"])]
    msgs = format_group_messages("⚠️ 需要人工介入：X", groups)
    assert len(msgs) == 2
    assert msgs[0][1] == ["cb.png", "ca.png"]
    assert msgs[1][1] == ["bb.png", "ba.png"]

def test_format_group_messages_full_warning_only_on_first():
    # 第一則帶完整警告文字；第二則只帶群標題，不重複洗版整段警告
    groups = [("chat", ["a.png"]), ("backpack", ["b.png"])]
    msgs = format_group_messages("⚠️ 需要人工介入：X", groups)
    assert msgs[0][0].startswith("⚠️ 需要人工介入：X")
    assert "需要人工介入" not in msgs[1][0]

def test_format_group_messages_labels_chat_then_backpack():
    groups = [("chat", ["a.png"]), ("backpack", ["b.png"])]
    msgs = format_group_messages("X", groups)
    assert "聊天" in msgs[0][0] and "背包" in msgs[1][0]

def test_format_group_messages_empty_groups_yields_nothing():
    assert format_group_messages("X", []) == []


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

def test_format_group_messages_tracker_group_has_caption():
    # H015：D3 超時（有框）路徑改用分組發送＝追蹤框現況一則＋聊天/背包前後對比各一則，
    # tracker 群也要有人看得懂的標題（不能印裸 region 名）。
    msgs = format_group_messages("X", [("tracker", ["t.png"]), ("chat", ["a.png"])])
    assert "追蹤框" in msgs[0][0]
