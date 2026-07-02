from miningbot.ocr import (contains_phrase, contains_any, count_found,
                           has_new_found, has_new_found_last_line,
                           count_rare_found, has_new_rare_found,
                           has_new_rare_found_last_line,
                           extract_new_found_lines)

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


# --- 稀有礦判定：排除低稀有度（反轉策略，D3 採集確認）---
# 背景：聊天「小名 has found X」混了普通鎬子挖的一般礦與 D3 稀有礦；名字過濾無解（同名）。
# 高稀有度礦太多列不完 → 改列舉「低稀有度礦」(COMMON)當排除清單：has found X 的 X 不在
# COMMON → 視為稀有礦。COMMON = 低稀有度（普通鎬子會挖到）。
COMMON = ("Lovelocket", "Bandeau", "Peppermint Core", "Sub-Zero", "Compact Snow")
# KW（"has found"/"found a"）已於檔案上方定義

def test_count_rare_found_excludes_common_counts_rare():
    text = ("small_lo has found Bandeau\n"          # common → 排除
            "small_lo has found Lilaverine\n"        # 不在 common → 稀有
            "small_lo has found Lovelocket")         # common → 排除
    assert count_rare_found(text, COMMON, KW) == 1

def test_count_rare_found_counts_duplicates():
    # 上一輪留下的稀有礦也會出現 → 同名計多次（使用者點名的 2-3 個情境）
    text = "small_lo has found Rosarium\nsmall_lo has found Rosarium"
    assert count_rare_found(text, COMMON, KW) == 2

def test_count_rare_found_ignores_non_found_lines():
    # 沒有 "has found / found a" 的行不算（避免亂數雜訊誤計）
    text = "the console absolutely solidified\nmanzana rerolled the event"
    assert count_rare_found(text, COMMON, KW) == 0

def test_count_rare_found_multiword_common_excluded():
    # 多字一般礦（Compact Snow）整串比對才排除
    text = "small_lo has found Compact Snow"
    assert count_rare_found(text, COMMON, KW) == 0

def test_count_rare_found_tolerates_trailing_ocr_noise_on_common():
    # OCR 在一般礦名尾端多了雜訊（startswith 容忍）→ 仍判為 common、不誤當稀有
    text = "small_lo has found Bandeau!"
    assert count_rare_found(text, COMMON, KW) == 0

def test_has_new_rare_found_true_when_rare_count_increases():
    before = "small_lo has found Rosarium"
    after  = "small_lo has found Rosarium\nsmall_lo has found Lilaverine"
    assert has_new_rare_found(before, after, COMMON, KW) is True

def test_has_new_rare_found_false_when_only_common_mined():
    # 視窗內只多了一般礦（低稀有度）→ 不算採集成功（防普通挖礦偽造）
    before = "small_lo has found Rosarium"
    after  = "small_lo has found Rosarium\nsmall_lo has found Bandeau"
    assert has_new_rare_found(before, after, COMMON, KW) is False

def test_has_new_rare_found_false_when_no_change():
    msg = "small_lo has found Rosarium"
    assert has_new_rare_found(msg, msg, COMMON, KW) is False

# --- 捲動造成計數遞減（2→1）的假負：靠底部新行為主信號 ---
def test_has_new_rare_found_last_line_true_when_rare_at_bottom_despite_scroll():
    # 舊稀有礦從頂部刷掉 → 稀有計數 2→可能不增（甚至減），但底部新出現稀有礦 → 仍確認
    before = "has found Rosarium\nhas found Bandeau\nhas found Abyssium"
    after  = "has found Bandeau\nhas found Abyssium\nhas found Lilaverine"
    assert has_new_rare_found_last_line(before, after, COMMON, KW) is True

def test_has_new_rare_found_last_line_false_when_common_at_bottom():
    before = "has found Rosarium"
    after  = "has found Rosarium\nhas found Bandeau"   # 底部是一般礦
    assert has_new_rare_found_last_line(before, after, COMMON, KW) is False

def test_has_new_rare_found_last_line_false_when_bottom_unchanged():
    msg = "has found Rosarium\nhas found Lilaverine"
    assert has_new_rare_found_last_line(msg, msg, COMMON, KW) is False


# --- extract_new_found_lines：抽 after 才出現的 found 行（原文，給 Discord 通知）---
def test_extract_new_found_lines_returns_new_found_lines_only():
    before = "small_lo has found Rosarium"
    after  = "small_lo has found Rosarium\nImGoc52 has found Lilaverine"
    lines = extract_new_found_lines(before, after, KW)
    assert lines == ["ImGoc52 has found Lilaverine"]

def test_extract_new_found_lines_handles_chat_scroll_loss():
    # 舊訊息從頂部刷掉（before 有但 after 沒有）→ 不影響抽 after 的新行
    before = "has found Abyssium\nhas found Rosarium"
    after  = "has found Rosarium\nhas found Lilaverine"   # Abyssium 被捲掉、Lilaverine 新增
    lines = extract_new_found_lines(before, after, KW)
    assert lines == ["has found Lilaverine"]

def test_extract_new_found_lines_ignores_non_found_chat_lines():
    # 新聊天是閒聊/系統訊息（非 found keyword）→ 不抽取
    before = "has found Rosarium"
    after  = "has found Rosarium\nsomeone: hello world"
    assert extract_new_found_lines(before, after, KW) == []

def test_extract_new_found_lines_empty_when_no_change():
    msg = "small_lo has found Rosarium"
    assert extract_new_found_lines(msg, msg, KW) == []


# --- 多前處理融合（H014 根因：min_channel 在亮粉背景漏讀彩色行，單一前處理必有盲區）---
# 每種前處理各自「內部自洽」比 before/after（同 pass 才可比），任一 pass 有信號即 confirmed。
# 對應實機證據 2026-07-03 H014：dark_mask 讀得到底部新行 has found Diamorite、min_channel 讀不到。
from miningbot.ocr import (any_new_rare_found, any_new_found,
                           extract_new_found_lines_multi, _preprocess)
import numpy as np


def test_any_new_rare_found_true_when_only_one_pass_sees_bottom_rare():
    # pass0（min_channel）什麼都沒讀到；pass1（dark_mask）讀到底部新稀有行 → True
    before = ["", "has found Rosarium"]
    after  = ["", "has found Rosarium\nhas found Lilaverine"]
    assert any_new_rare_found(before, after, COMMON, KW) is True


def test_any_new_rare_found_true_when_one_pass_count_increases():
    before = ["has found Rosarium", ""]
    after  = ["has found Lilaverine\nhas found Rosarium", ""]  # 底部沒變新（插頂部），靠 count
    assert any_new_rare_found(before, after, COMMON, KW) is True


def test_any_new_rare_found_false_when_all_passes_negative():
    before = ["has found Rosarium", ""]
    after  = ["has found Rosarium\nhas found Bandeau", ""]   # 底部是一般礦、count 沒增
    assert any_new_rare_found(before, after, COMMON, KW) is False


def test_any_new_rare_found_passes_are_independent():
    # 不同 pass 之間不可交叉比（噪音不同會偽造 diff）：before pass0 的行跑到 after pass1
    # 不算新增——只有同 pass 自己 before/after 差分才算。
    before = ["has found Lilaverine", ""]
    after  = ["has found Lilaverine", ""]
    assert any_new_rare_found(before, after, COMMON, KW) is False


def test_any_new_found_true_when_any_pass_sees_special_keyword():
    special = ("ionized",)
    assert any_new_found(["", ""], ["", "obtained IONIZED ore"], special) is True
    assert any_new_found(["", ""], ["", ""], special) is False


def test_extract_new_found_lines_multi_unions_and_dedupes_across_passes():
    # 兩個 pass 各讀到不同新行 → 聯集；同一行兩個 pass 都讀到 → 去重（正規化比對）
    before = ["", ""]
    after  = ["small_lo has found Diamorite",
              "small_lo HAS FOUND Diamorite\nsmall_lo has found Lilaverine"]
    lines = extract_new_found_lines_multi(before, after, KW)
    assert len(lines) == 2
    assert any("Diamorite" in l for l in lines)
    assert any("Lilaverine" in l for l in lines)


# --- dark_mask 前處理（純像素邏輯，不需 tesseract）---
def test_preprocess_dark_mask_separates_dark_text_from_bright_bg():
    # 亮粉背景 + 深色文字外框（H014 場景）：文字→0（黑）、背景→255（白）
    img = np.full((40, 100, 3), (200, 100, 220), dtype=np.uint8)   # 亮粉 BGR
    img[10:20, 10:60] = (10, 10, 10)                               # 深色筆畫
    out = _preprocess(img, "dark_mask")
    assert out[15, 30] == 0 and out[5, 5] == 255


def test_preprocess_known_modes_unchanged():
    # 既有模式行為不變：gray 是灰階、min_channel 是最小通道
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    img[:, :] = (10, 200, 30)
    assert _preprocess(img, "min_channel").max() == 10
    assert _preprocess(img, "gray").shape == (4, 4)


# --- Spectral/Ionized 變體前綴（2026-07-03 wiki 證實的假成功漏洞）---
# Rare/Master 的 Spectral 變體也會進 local chat：聊天行「has found Spectral Bandeau」。
# 舊邏輯兩處都會誤判成功：(1) "spectral bandeau" 不 startswith "bandeau" → 排除失效、
# 被 count_rare_found 當稀有；(2) special_keywords 只看 "spectral" 字樣出現 → special=True。
# 修法：剝變體前綴後查排除清單；special 改「found 行含變體字樣且 base 不在排除清單」。
from miningbot.ocr import count_special_found, any_new_special_found

SPECIAL = ("ionized", "spectral")


def test_spectral_common_ore_is_excluded_after_prefix_strip():
    # 被動挖到 Spectral 低階礦 → 剝前綴後 base 在排除清單 → 不算稀有
    text = "small_lo has found Spectral Bandeau"
    assert count_rare_found(text, COMMON, KW) == 0


def test_ionized_common_ore_is_excluded_after_prefix_strip():
    text = "small_lo has found Ionized Lovelocket"
    assert count_rare_found(text, COMMON, KW) == 0


def test_spectral_rare_ore_still_counts_as_rare():
    # 高階礦的變體（D3 目標）不受影響：base 不在排除清單 → 稀有
    text = "small_lo has found Spectral Lilaverine"
    assert count_rare_found(text, COMMON, KW) == 1


def test_spectral_common_at_bottom_not_new_rare_last_line():
    before = "some chat"
    after  = "some chat\nsmall_lo has found Spectral Bandeau"
    assert has_new_rare_found_last_line(before, after, COMMON, KW) is False


def test_count_special_found_ignores_spectral_common():
    # special 判定：found 行含變體字樣，但 base 是排除清單低階 → 不算 special
    text = "small_lo has found Spectral Bandeau"
    assert count_special_found(text, COMMON, KW, SPECIAL) == 0


def test_count_special_found_counts_spectral_noncommon():
    text = "small_lo has found Spectral Zynulvinite"
    assert count_special_found(text, COMMON, KW, SPECIAL) == 1


def test_count_special_found_ignores_variant_word_outside_found_line():
    # 非 found 行出現 spectral 字樣（系統訊息/事件）→ 不算（舊 has_new_found 會誤算）
    text = "a spectral cyclone ravages the mine"
    assert count_special_found(text, COMMON, KW, SPECIAL) == 0


def test_any_new_special_found_diffs_per_pass():
    before = ["", ""]
    after  = ["", "small_lo has found Ionized Zynulvinite"]
    assert any_new_special_found(before, after, COMMON, KW, SPECIAL) is True
    assert any_new_special_found(after, after, COMMON, KW, SPECIAL) is False
