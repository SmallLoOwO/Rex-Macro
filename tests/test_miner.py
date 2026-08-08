from miningbot.miner import dispatch_event, EventFlags, cooldown_ready, counts_as_progress
from miningbot.config import DEFAULT

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


# --- boost 不空轉：高頻偵測 config-lock（需求 #4 方案 A）---
def test_boost_detection_is_high_frequency_and_single_scale():
    # 不空轉＝到期即補＝越快偵測瓶子消失越好；瓶子是固定尺寸 UI → 單尺度即可
    assert DEFAULT.boost_check_interval_s <= 0.3
    assert DEFAULT.boost_buff_scales == (1.0,)

def test_boost_checks_more_often_than_d4():
    # D4 不在意空轉 → 維持較疏節流；boost 要比 D4 更頻繁
    assert DEFAULT.boost_check_interval_s < DEFAULT.activity_check_interval_s


# --- D4 決策文字的快取有效性（2026-07-19 01:16 未知連刷對策）------------------
# 快取必須「夠新」且「晚於上次 D4 動作」——上次動作之前 OCR 的快取描述的是
# 已被刷掉/確認過的舊事件，用它決策等於對錯的事件按鍵。
from miningbot.miner import d4_text_fresh, plan_d4


def test_d4_cache_fresh_and_after_last_press_usable():
    assert d4_text_fresh(now=100.0, banner_at=99.0, last_press=90.0,
                         interval_s=2.0) is True


def test_d4_cache_from_before_last_press_rejected():
    # 01:16:42 按了 D4 → 01:16:46 再判時快取仍是動作前 OCR 的 → 必須同步重讀
    assert d4_text_fresh(now=100.0, banner_at=97.0, last_press=98.0,
                         interval_s=2.0) is False


def test_d4_cache_too_old_rejected():
    assert d4_text_fresh(now=100.0, banner_at=95.0, last_press=0.0,
                         interval_s=2.0) is False


def test_d4_cache_usable_at_boot():
    # 開機 _last_activity=0.0：第一份快取即可用
    assert d4_text_fresh(now=10.0, banner_at=9.0, last_press=0.0,
                         interval_s=2.0) is True


# --- plan_d4：未知文字雙樣本確認才刷新（單次誤讀就右鍵＝keep 事件被不可逆刷掉）---
def test_plan_d4_keep_listed_event_keeps():
    assert plan_d4(kept=True, matched=True, unknown_confirmed=False) == "keep"


def test_plan_d4_known_non_keep_rerolls():
    assert plan_d4(kept=False, matched=True, unknown_confirmed=False) == "reroll"


def test_plan_d4_first_unknown_holds():
    # 第一次認不得：hold 等背景 worker 的下一份新樣本（比照 tracker 雙幀穩定慣例）
    assert plan_d4(kept=False, matched=False, unknown_confirmed=False) == "hold"


def test_plan_d4_unknown_confirmed_by_second_sample_rerolls():
    # 新樣本仍認不得 → 維持舊巨集語意刷新（未知事件通常是無事件/低價值）
    assert plan_d4(kept=False, matched=False, unknown_confirmed=True) == "reroll"


def test_plan_d4_resetting_skips_regardless():
    # 重置倒數：事件列被重置公告蓋掉（07-19 01:32:24 未知白刷）→ 一律 skip，
    # 連 keep/matched 都不信——讀到的字根本不是事件文字
    assert plan_d4(kept=True, matched=True, unknown_confirmed=False,
                   resetting=True) == "skip"
    assert plan_d4(kept=False, matched=False, unknown_confirmed=True,
                   resetting=True) == "skip"


# --- counts_as_progress：卡住偵測不該被冷卻計時動作洗掉（2026-08-08）---------
# 實機 2026-08-01 01:16-01:53：D5 冷卻到期照常觸發，但同段時間 STUCK（60s 無進度）
# 連跳 8 次——D4/D5/D2 是計時到了就按，跟 W 有沒有讓角色前進無關；只有 REFOCUS
# 會重新按住 W，才是移動真的恢復。
def test_use_d5_does_not_count_as_progress():
    assert counts_as_progress("USE_D5") is False


def test_use_d4_does_not_count_as_progress():
    assert counts_as_progress("USE_D4") is False


def test_scan_and_cave_do_not_count_as_progress():
    assert counts_as_progress("SCAN") is False
    assert counts_as_progress("CAVE") is False


def test_no_action_does_not_count_as_progress():
    assert counts_as_progress(None) is False


def test_refocus_counts_as_progress():
    # REFOCUS 會跑 init_mining_sequence 重新按住 W，移動真的重新開始
    assert counts_as_progress("REFOCUS") is True
