from miningbot.ocr import (contains_phrase, contains_any, count_found,
                           has_new_found, has_new_found_last_line)

def test_contains_phrase_case_insensitive_and_fuzzy():
    text = "A CHILL goes  down your spine..."
    assert contains_phrase(text, "a chill goes down your spine")

def test_contains_phrase_rejects_other_text():
    text = "manzana rerolled the event to The Firewall!"
    assert not contains_phrase(text, "a chill goes down your spine")

def test_contains_any_matches_found_keywords():
    text = "ImGoc52 has found Equalizosity"
    assert contains_any(text, ("has found", "found a"))


# --- 採集差分確認（has_new_found）---
# 背景bug：_verify_success 舊版用 contains_any（存在性），聊天框累積的舊 "has found"
# 會偽造 HARVEST_SUCCESS。改用 count_found 前後差分：只有「數量增加」才算新採到。
KW = ("has found", "found a")

def test_count_found_zero_when_no_keyword():
    assert count_found("manzana rerolled the event", KW) == 0

def test_count_found_one_match():
    assert count_found("small_lo has found Bandeau", KW) == 1

def test_count_found_two_matches_consecutive_same_mineral():
    # 連續採到同一個稀有礦 → 聊天累積兩條相同訊息（使用者點名的 edge case）
    text = "small_lo has found Bandeau\nsmall_lo has found Bandeau"
    assert count_found(text, KW) == 2

def test_count_found_case_and_whitespace_insensitive():
    assert count_found("Small_LO  HAS FOUND  Bandeau", KW) == 1

def test_has_new_found_true_when_new_message():
    # D3 前無訊息、D3 後出現一條 → 新採集成功
    assert has_new_found("", "small_lo has found Bandeau", KW) is True

def test_has_new_found_false_when_stale_message():
    # ★ 核心bug：D3 前就有舊訊息、D3 後數量沒增加 → 不算成功（舊訊息不再偽造）
    before = "small_lo has found Bandeau"
    after = "small_lo has found Bandeau"
    assert has_new_found(before, after, KW) is False

def test_has_new_found_true_when_count_increases_consecutive_same_mineral():
    # 連續同一礦：D3 前一條、D3 後兩條 → 新的一次確實成功（diff 抓得住）
    before = "small_lo has found Bandeau"
    after = "small_lo has found Bandeau\nsmall_lo has found Bandeau"
    assert has_new_found(before, after, KW) is True

def test_has_new_found_false_when_both_empty():
    assert has_new_found("", "", KW) is False


# --- has_new_found_last_line：最後一行差分（解決 chat 捲動問題）---
# 背景：count_found diff 在 found_before 很高時會因 chat 捲動而回傳假負（5→2）。
# has_new_found_last_line 只看最後一行：新訊息永遠出現在 chat 底部，
# 捲動只影響頂部，不影響底部的判定。

def test_last_line_new_found_when_fresh_message_at_bottom():
    # D3 前 chat 沒有 "has found"，D3 後底部多一行 → True
    before = "Roblox system message...\nsome event"
    after  = "Roblox system message...\nsome event\nsmall_lo has found Lilaverine"
    assert has_new_found_last_line(before, after, KW) is True


def test_last_line_no_new_when_last_line_unchanged():
    # D3 後底部沒變 → False
    msg = "small_lo has found Lilaverine"
    assert has_new_found_last_line(msg, msg, KW) is False


def test_last_line_no_new_when_no_found_in_after_tail():
    # D3 後底部出現的是非採集訊息 → False
    before = "some chat"
    after  = "some chat\nrerolled the event to Myth"
    assert has_new_found_last_line(before, after, KW) is False


def test_last_line_true_when_scroll_and_new_found_at_bottom():
    # 03:51 情境：chat 從 before_last="has found Msg3" 捲到 after_last="has found NewOre"（不同礦）
    before = "has found Msg1\nhas found Msg2\nhas found Msg3"
    after  = "has found Msg2\nhas found Msg3\nhas found NewOre"
    assert has_new_found_last_line(before, after, KW) is True


def test_last_line_false_when_same_ore_at_bottom_no_new():
    # chat 內容完全沒變（D3 未命中）→ False
    before = "has found Msg2\nhas found Msg3\nhas found Msg4"
    after  = "has found Msg2\nhas found Msg3\nhas found Msg4"
    assert has_new_found_last_line(before, after, KW) is False
