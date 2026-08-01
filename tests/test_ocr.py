import os
from miningbot.ocr import (contains_phrase, contains_any, count_found,
                           has_new_found, has_new_found_last_line,
                           count_rare_found, has_new_rare_found,
                           has_new_rare_found_last_line,
                           extract_new_found_lines,
                           parse_capacity_pct,
                           _tessdata_dir, _resolve_tessdata)

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

def test_count_rare_found_tolerates_trailing_ocr_truncation_on_common():
    # H072（harvest 162）：OCR 少讀尾碼（Weevil→Weevi），startswith 反向不成立
    # → 假稀有 → count 0→1 → 假成功。反向 prefix（common 名以 base 開頭）→ 截斷 → common。
    text = "small_lo has found Bandea"    # truncated "Bandeau"
    assert count_rare_found(text, COMMON, KW) == 0

def test_has_new_rare_found_false_when_common_ore_ocr_truncated():
    # H072 核心場景：before/after 是同一行，after 被 OCR 截斷一個尾碼。
    # 舊邏輯：before common(count 0) → after rare(count 1) → 假成功。
    before = "small_lo has found Bandeau"
    after  = "small_lo has found Bandea"  # 截斷，不是新行
    assert has_new_rare_found(before, after, COMMON, KW) is False

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


# ---- 模糊 found 行匹配（H020 假陰性對策，2026-07-03）----
# 根因：dark_mask pass 在亮粉背景「讀得到行、但關鍵字讀歪」——
# "small_lo has found Valytium" → "smeill_lo hee foumel velyiiuinm"，
# 精確子字串 "has found" 對不上 → 三 pass 全滅 → RESWEEP → 重掃全空 → 誤交人工。
# 對策：token≈"found"（比對比率門檻）＋ 礦名同時對「白名單稀有」與「排除清單」做
# 模糊比對，白名單分數須達門檻**且嚴格高於**排除清單分數（Surreal 誤讀
# "biemnentine"≈"Solemn Lamentine" 0.667 但同時 ≈"Diamantine" 0.667 → 平手判 common，
# 保守方向：寧可漏也不假成功）。
from miningbot.ocr import (count_fuzzy_rare_found, has_new_fuzzy_rare_found,
                           new_fuzzy_rare_lines, fuzzy_found_diagnostics)

F_COMMON = ("Diamantine", "Bandeau", "Jollycane")
F_RARES  = ("Valytium", "Solemn Lamentine", "Celinity")

# H020 實機 dark_mask pass 逐字輸出（tests/fixtures/chat/h020_after_pink_bg.png 重跑）
H020_DARKMASK = (
    "Only people iim sinniler egie Groups sinc Your tin\n"
    "ffrieingle cain elnsit warty youu\n"
    "Use fognel ior RE om Goraaltel, OF press ne [suTt\n"
    "KIT i@ennell_lo} Fes rSR Esl the event po Calin\n"
    "small hee founcl Biemnentine\n"
    "smeill_lo hee foumel velyiiuinm"
)


def test_fuzzy_rescues_mangled_valytium_line():
    # "hee foumel velyiiuinm"：foumel≈found、velyiiuinm≈Valytium(0.667) → 算 1 筆稀有
    assert count_fuzzy_rare_found("smeill_lo hee foumel velyiiuinm", F_COMMON, F_RARES) == 1


def test_fuzzy_rejects_misread_closer_or_equal_to_common():
    # "biemnentine"＝Surreal Diamantine 的誤讀：對 Solemn Lamentine 0.667 但對
    # Diamantine 也 0.667 → 未「嚴格高於」common → 判 common（防假成功）
    assert count_fuzzy_rare_found("small hee founcl Biemnentine", F_COMMON, F_RARES) == 0


def test_fuzzy_rejects_reroll_event_line_with_ore_name():
    # 事件行含礦名（Celinity）但無 found-ish token → 不可觸發
    line = "KIT (@small_lo) has rerolled the event to Celinity"
    assert count_fuzzy_rare_found(line, F_COMMON, F_RARES) == 0


def test_fuzzy_rejects_exact_common_found_line():
    assert count_fuzzy_rare_found("small_lo has found Bandeau", F_COMMON, F_RARES) == 0


def test_fuzzy_strips_variant_prefix_before_lookup():
    # Spectral + 排除清單礦 → 剝前綴後仍是 common → 不算
    assert count_fuzzy_rare_found("small_lo has found Spectral Bandeau", F_COMMON, F_RARES) == 0


def test_fuzzy_tolerates_trailing_junk_after_ore():
    # OCR 在礦名後黏了雜訊字 → 取前 1~2 token 比對仍要命中
    assert count_fuzzy_rare_found("smeill_lo hee foumel velyiiuinm game", F_COMMON, F_RARES) == 1


def test_fuzzy_full_h020_darkmask_counts_only_valytium():
    assert count_fuzzy_rare_found(H020_DARKMASK, F_COMMON, F_RARES) == 1


def test_has_new_fuzzy_rare_found_h020_scenario():
    assert has_new_fuzzy_rare_found("", H020_DARKMASK, F_COMMON, F_RARES) is True


def test_has_new_fuzzy_rare_ignores_stale_line_with_ocr_noise():
    # 上一輪殘留的稀有行在 before/after 被讀成略不同字樣 → 不可當「新增」
    before = "smeill_lo hee foumel velyiiuinm"
    after  = "smeill_lo hee foumel velyiiuinrn"
    assert has_new_fuzzy_rare_found(before, after, F_COMMON, F_RARES) is False


def test_any_new_rare_found_fuzzy_opt_in_via_rare_names():
    before = ["", "", ""]
    after = ["", "", H020_DARKMASK]
    # 不給 rare_names（預設）＝行為不變（三 pass 精確匹配全滅 → False）
    assert any_new_rare_found(before, after, F_COMMON, KW) is False
    # 給 rare_names → fuzzy 兜底救回
    assert any_new_rare_found(before, after, F_COMMON, KW, rare_names=F_RARES) is True


def test_new_fuzzy_rare_lines_reports_matched_ore():
    lines = new_fuzzy_rare_lines("", H020_DARKMASK, F_COMMON, F_RARES)
    assert len(lines) == 1
    line, ore, ratio = lines[0]
    assert "velyiiuinm" in line.lower()
    assert ore == "Valytium"
    assert ratio >= 0.6


def test_fuzzy_found_diagnostics_reports_rejected_near_miss():
    # 診斷要把「有 found-ish token 但被拒」的行連同分數一起回報（詳細 log 用）
    diags = fuzzy_found_diagnostics("small hee founcl Biemnentine", F_COMMON, F_RARES)
    assert len(diags) == 1
    d = diags[0]
    assert d["accepted"] is False
    assert d["best_rare"][0] == "Solemn Lamentine"
    assert d["best_common"][0] == "Diamantine"


# ---- 模糊匹配的假陽性防護（用聯集詞彙表重演 H020 時暴露的實際誤收）----
# 這些行在 H020 的 after 畫面真實存在（系統訊息/OCR 黏字），寬鬆閘門下曾被誤收：
# 危險方向是「假成功」——D3 其實沒打中卻判成功 → 直接續挖、稀有礦丟失。

def test_fuzzy_rejects_system_line_friends_can_chat():
    # "friends"≈found 恰好 0.5（門檻須 >0.5）且是行首（found 行前面必有玩家名）
    line = "friends can chat with you."
    assert count_fuzzy_rare_found(line, (), ("Luckant",)) == 0


def test_fuzzy_rejects_short_token_as_found():
    # OCR 黏字行："un"（2 字元）曾被當 found-ish token、"game"≈Amare 0.667 誤收
    line = "smal lBloassfoulmebVallyti Un game"
    assert count_fuzzy_rare_found(line, (), ("Amare",)) == 0


def test_fuzzy_rejects_found_token_at_line_start():
    # found-ish token 在行首＝前面沒有玩家名 → 結構不符 "<名> has found X"，拒收
    assert count_fuzzy_rare_found("founcl velyiiuinm", (), ("Valytium",)) == 0


# ---- pass_labels（log 標籤：rapid 單 pass vs tesseract 三 pass 融合）----

def test_pass_labels_tesseract_fusion_uses_preprocess_names():
    from miningbot.ocr import pass_labels, CHAT_PREPROCESSES
    assert pass_labels(["a", "b", "c"]) == list(CHAT_PREPROCESSES)

def test_pass_labels_single_pass_is_rapidocr():
    # RapidOCR 路徑回單元素 list——log 若標成 min_channel 會誤導事後排錯
    from miningbot.ocr import pass_labels
    assert pass_labels(["text"]) == ["rapidocr"]


# ---- RapidOCR 裁決輸出：低信心 found 行偵測（純邏輯）----
# 之後裁決引擎好壞的素材：found 行信心分數低於門檻 → main 記 WARNING，grep 即收集疑似讀歪樣本

def test_low_confidence_found_lines_flags_weak_found_line():
    from miningbot.ocr import low_confidence_found_lines
    lines = [("small_lo has found Valytium", 0.62), ("The mine is resetting...", 0.55)]
    flagged = low_confidence_found_lines(lines, ("has found", "found a"))
    assert flagged == [("small_lo has found Valytium", 0.62)]  # 非 found 行不收

def test_low_confidence_found_lines_ignores_confident_lines():
    from miningbot.ocr import low_confidence_found_lines
    lines = [("small_lo has found Valytium", 0.97)]
    assert low_confidence_found_lines(lines, ("has found",)) == []

def test_low_confidence_found_lines_threshold_is_tunable():
    from miningbot.ocr import low_confidence_found_lines
    lines = [("x has found Y", 0.9)]
    assert low_confidence_found_lines(lines, ("has found",), threshold=0.95) == lines


# ---- H032（2026-07-04）假陰性：新稀有行「不是底行」＋ 頂部捲動剛好補償 count ----
# 實錄：D3 第一發命中、聊天新增 "has found Essentlum"（Essentium），但同窗口又進來一行
# 一般礦 "has found Halcylite (Lucky Cave)" 排在它後面 → 底行信號滅；同時頂部剛好刷掉
# 一行舊稀有（Saerylium）→ count 3→3 不增 → confirmed=False → RESWEEP 全空 → 誤交人工。
# 對策：new_chat_tail_lines 用「before 底行在 after 的對齊錨點」找出 after 的全部新增行，
# 任一新增行是稀有 found 行即確認（不再假設新稀有行必在底部）。
from miningbot.ocr import new_chat_tail_lines, has_new_rare_found_tail

H032_COMMON = ("Diamantine", "Dulcinette", "Loveletter", "Halcylite")

H032_BEFORE = (
    "small_lo has found Saerylium\n"
    "small_lo has found Diamantine\n"
    "small_lo has found Diamantine\n"
    "KIT (@small_lo) has boosted the event's length\n"
    "small_lo has found Diamantine\n"
    "small_lo has found Diamantine\n"
    "small_lo has found Dulcinette\n"
    "small_lo has found an ionized Diamantine\n"
    "small_lo has found Diamantine\n"
    "small_lo has found Loveletter\n"
    "small_lo has found Valytium"
)
H032_AFTER = (
    "small_lo has found Diamantine\n"
    "KIT (@small_lo) has boosted the event's length\n"
    "small_lo has found Diamantine\n"
    "small_lo has found Diamantine\n"
    "small_lo has found Dulcinette\n"
    "small_lo has found an ionized Diamantine\n"
    "small_lo has found Diamantine\n"
    "small_lo has found Loveletter\n"
    "small_lo has found Valytium\n"
    "small_lo has found Essentlum\n"
    "small_lo has found Halcylite (Lucky Cave)"
)


def test_h032_confirms_new_rare_when_not_at_bottom_and_count_compensated():
    # 實錄回歸：count 差分與底行信號雙滅，tail 對齊要救回
    assert any_new_rare_found([H032_BEFORE], [H032_AFTER], H032_COMMON, KW) is True


def test_new_chat_tail_lines_h032_alignment():
    tail = new_chat_tail_lines(H032_BEFORE, H032_AFTER)
    assert tail == ["small_lo has found Essentlum",
                    "small_lo has found Halcylite (Lucky Cave)"]


def test_new_chat_tail_lines_anchors_on_longest_run_with_duplicate_bottom_line():
    # before 底行（Diamantine）在 after 出現多次（新行裡也有一筆）→
    # 要取「向上連續吻合最長」的錨點，不可錨到新進來的那筆重複行
    before = "has found Loveletter\nhas found Diamantine"
    after  = ("has found Loveletter\nhas found Diamantine\n"
              "has found Essentium\nhas found Diamantine")
    assert new_chat_tail_lines(before, after) == ["has found Essentium",
                                                  "has found Diamantine"]


def test_new_chat_tail_lines_empty_when_no_anchor():
    # before 的行完全對不到 after（換場景/OCR 噪音）→ 保守回空、不假陽性
    assert new_chat_tail_lines("completely different", "has found Essentium") == []


def test_new_chat_tail_lines_empty_when_bottom_unchanged():
    msg = "has found Loveletter\nhas found Valytium"
    assert new_chat_tail_lines(msg, msg) == []


def test_has_new_rare_found_tail_false_when_new_lines_all_common():
    before = "has found Valytium"
    after  = "has found Valytium\nhas found Bandeau\nhas found Lovelocket"
    assert has_new_rare_found_tail(before, after, COMMON, KW) is False


def test_has_new_rare_found_tail_tolerates_ocr_noise_in_anchor():
    # 錨點行前後兩次 OCR 略有出入（模糊比對 ≥ FUZZY_STALE_LINE_RATIO 仍可對齊）
    before = "has found Loveletter\nhas found Valytium"
    after  = "has found Loveletter\nhas found Va1ytium\nhas found Essentium"
    assert has_new_rare_found_tail(before, after, COMMON, KW) is True


def test_fuzzy_tail_rescues_mangled_rare_not_at_bottom():
    # 模糊路徑同樣不可假設新稀有行在底部：讀歪的稀有行後面跟了一行一般礦
    before = "small_lo has found Diamantine"
    after  = ("small_lo has found Diamantine\n"
              "small_lo hee foumel velyiiuinm\n"      # ≈ has found Valytium
              "small_lo has found Diamantine")
    assert has_new_fuzzy_rare_found(before, after, F_COMMON, F_RARES) is True


# ---- 變體行帶冠詞「an/a」（H032 實錄同批發現）----
# 遊戲實際聊天行是 "has found an ionized Diamantine"（帶冠詞），舊 _strip_variant 只剝
# 行首的 ionized/spectral → "an ionized diamantine" 剝不掉 → 不 startswith 任何排除清單
# → 被動挖到的低階變體被當稀有/special → 假成功風險（H032 裡它讓 rare count 虛胖成 3）。
def test_count_rare_found_strips_article_before_variant_prefix():
    text = "small_lo has found an ionized Diamantine"
    assert count_rare_found(text, H032_COMMON, KW) == 0


def test_count_special_found_strips_article_for_common_base():
    text = "small_lo has found an ionized Diamantine"
    assert count_special_found(text, H032_COMMON, KW, SPECIAL) == 0


def test_count_special_found_article_variant_rare_base_still_special():
    text = "small_lo has found an ionized Zynulvinite"
    assert count_special_found(text, H032_COMMON, KW, SPECIAL) == 1


# ---- Episode 級聊天帳本 ChatLedger（2026-07-04，H032 延伸對策）----
# 情境：D3 其實命中但驗證誤判失敗 → RESWEEP 期間（D2 重掃/D5 守門 settle）晚到的成功行
# 抵達、又被一般礦行往上推；等下次 OCR 時「episode 基準的底行」已捲出裁圖 → 錨點對不到，
# count 又被頂部捲掉的舊稀有行補償 → 對單一基準的全部差分信號同時滅（假陰性誤交人工）。
# 對策：基準提升到 HARVESTING episode 級、每次 OCR 以「上一次讀取」為錨點鏈式對齊
# （間隔短 → 錨點幾乎不會捲丟），新增行累積進帳本；episode 內累積出任一稀有 found 行
# 即確認（單人作業＋Exotic+ 被動出土 ≤1/1M → episode 內新稀有行只可能來自自己的 D3）。
from miningbot.ocr import ChatLedger

LG_COMMON = ("Diamantine", "Dulcinette", "Loveletter", "Halcylite")

LG_BASE = ("small_lo has found Saerylium\n"       # 舊 episode 殘留稀有行（將捲出、補償 count）
           "small_lo has found Diamantine\n"
           "small_lo has found Loveletter\n"
           "small_lo has found Dulcinette")
LG_STEP1 = ("small_lo has found Diamantine\n"     # 頂部捲掉 Saerylium
            "small_lo has found Loveletter\n"
            "small_lo has found Dulcinette\n"
            "small_lo has found Halcylite")
LG_STEP2 = ("small_lo has found Halcylite\n"      # 基準的行已全數捲出裁圖
            "small_lo has found Essentlum\n"      # 晚到的成功行（非底行）
            "small_lo has found Halcylite (Lucky Cave)")


def test_ledger_confirms_late_rare_after_baseline_scrolled_out():
    led = ChatLedger([LG_BASE])
    assert led.update([LG_STEP1], LG_COMMON, KW) == []
    assert led.confirmed is False
    got = led.update([LG_STEP2], LG_COMMON, KW)
    assert got == ["small_lo has found Essentlum"]
    assert led.confirmed is True
    # 對照組：同一情境下「對 episode 基準的單次差分」全滅（count 被捲動補償、底行是
    # 一般礦、基準底行已捲出對不到錨點）——這正是帳本存在的理由
    assert any_new_rare_found([LG_BASE], [LG_STEP2], LG_COMMON, KW) is False


def test_ledger_skips_unanchored_read_and_recovers_on_next():
    led = ChatLedger([LG_BASE])
    # 整段讀歪（錨點對不到）→ 保守：不追加、錨點不推進
    assert led.update(["complete garbage text"], LG_COMMON, KW) == []
    assert led.confirmed is False
    # 下一次讀取正常：以「上次好的錨點」（基準底行）仍可對齊、收下新增行
    after = LG_BASE + "\nsmall_lo has found Essentlum"
    assert led.update([after], LG_COMMON, KW) == ["small_lo has found Essentlum"]


def test_ledger_passes_are_self_consistent():
    # pass 間噪音不同不可交叉比（H014 原則）→ 各 pass 各自鏈錨點；
    # 只有 pass2 讀到成功行 → 仍確認
    base1 = "small_lo has found Loveletter"
    base2 = "small_lo has found Love1etter"        # pass2 對同一行的讀法略異
    led = ChatLedger([base1, base2])
    up1 = base1                                     # pass1 沒讀到新行
    up2 = base2 + "\nsmall_lo has found Essentlum"  # pass2 讀到成功行
    assert led.update([up1, up2], LG_COMMON, KW) == ["small_lo has found Essentlum"]
    assert led.confirmed is True


def test_ledger_empty_baseline_does_not_count_redisplayed_lines():
    # 聊天在基準時淡出（讀到空）→ 新訊息讓「舊行連同新行」一起重顯示。H064 起首次
    # 非空讀取只認**最底行**（讓聊天重現的那則新訊息），其上全是重顯示的舊歷史：
    # 這裡底行是一般礦 → 不確認，而中段那條舊稀有行（Saerylium）絕不可被計入。
    led = ChatLedger([""])
    redisplay = "small_lo has found Saerylium\nsmall_lo has found Loveletter"
    assert led.update([redisplay], LG_COMMON, KW) == []
    assert led.confirmed is False
    assert not any("Saerylium" in l for l in led.new_lines)
    assert led.update([redisplay + "\nsmall_lo has found Essentlum"],
                      LG_COMMON, KW) == ["small_lo has found Essentlum"]


def test_ledger_ignores_common_and_article_variant_lines():
    led = ChatLedger([LG_BASE])
    after = (LG_BASE + "\nsmall_lo has found an ionized Diamantine"
                       "\nsmall_lo has found Halcylite (Lucky Cave)")
    assert led.update([after], LG_COMMON, KW) == []
    assert led.confirmed is False
    # 新增行仍留檔（診斷/通知用），只是不算稀有
    assert led.new_lines == ["small_lo has found an ionized Diamantine",
                             "small_lo has found Halcylite (Lucky Cave)"]


def test_ledger_fuzzy_rescues_mangled_found_line():
    # H020 語意的模糊兜底也要在帳本上生效（rare_names 非空才開）
    led = ChatLedger([LG_BASE])
    after = LG_BASE + "\nsmall_lo hee foumel velyiiuinm"   # ≈ has found Valytium
    got = led.update([after], LG_COMMON, KW,
                     rare_names=("Valytium", "Solemn Lamentine"))
    assert got == ["small_lo hee foumel velyiiuinm"]
    assert led.confirmed is True


def test_ledger_duplicate_rare_line_is_guarded_but_count_diff_backstops():
    # 噪音守門：≈上次已有行一律當「錨點誤差的重讀」跳過（一般礦重讀讀歪礦名會翻成
    # 稀有＝假陽性，寧漏勿假成功）。代價是「同名稀有連續兩筆」帳本不收——但這種
    # 情境 episode 基準的 count 差分本來就抓得住（1→2）＝兜底不漏。
    base = "small_lo has found Loveletter\nsmall_lo has found Saerylium"
    led = ChatLedger([base])
    after = base + "\nsmall_lo has found Saerylium"
    assert led.update([after], LG_COMMON, KW) == []
    assert led.new_lines == []
    assert any_new_rare_found([base], [after], LG_COMMON, KW) is True


# --- tessdata 路徑解析（2026-07-07：pathless init 會 latch 全程停用 tesserocr 的對策）---
# 關鍵前提：PyTessBaseAPI() 不帶 path 時預設 './' 必 init 失敗（TESSDATA_PREFIX 未設時），
# read_text 的 tesseract_path 預設又是 None → 漏傳 path 的呼叫會踩到。_resolve_tessdata 即使
# 沒 path 也主動找系統 tessdata，讓漏傳 path 的呼叫仍能用 tesserocr（不誤退 pytesseract）。
def test_tessdata_dir_finds_sibling_tessdata(tmp_path):
    (tmp_path / "tessdata").mkdir()
    exe = tmp_path / "tesseract.exe"
    exe.write_text("")
    assert _tessdata_dir(str(exe)) == os.path.join(str(tmp_path), "tessdata")

def test_tessdata_dir_none_when_missing_or_no_path(tmp_path):
    assert _tessdata_dir(None) is None
    assert _tessdata_dir(str(tmp_path / "tesseract.exe")) is None   # 無 sibling tessdata

def test_resolve_tessdata_prefers_path_derived_over_defaults(tmp_path):
    # 給了合法 tesseract_path（旁有 tessdata）→ 一律優先用它，不落到 env/預設安裝路徑
    (tmp_path / "tessdata").mkdir()
    exe = tmp_path / "tesseract.exe"
    exe.write_text("")
    assert _resolve_tessdata(str(exe)) == os.path.join(str(tmp_path), "tessdata")


# --- read_text_boxes：RapidOCR 文字框中心（reentry 層級按鈕點擊用）---
from miningbot import ocr


class TestParseRapidBoxes:
    def test_basic(self):
        boxes = [[(100, 200), (200, 200), (200, 240), (100, 240)]]
        recs = ocr.parse_rapid_boxes(boxes, ["Mantle Layer"], [0.95])
        assert recs == [{"text": "Mantle Layer", "score": 0.95,
                         "center": (150, 220)}]

    def test_none_inputs_empty(self):
        # rapid 對空圖可能回 None 欄位（與 _read_text_rapid 同款防禦）
        assert ocr.parse_rapid_boxes(None, None, None) == []

    def test_missing_scores_default_zero(self):
        boxes = [[(0, 0), (10, 0), (10, 10), (0, 10)]]
        recs = ocr.parse_rapid_boxes(boxes, ["x"], None)
        assert recs[0]["score"] == 0.0


# ---- H041（2026-07-11）：RapidOCR 黏行（空格→連字號）導致 found 行解析全滅 ----
# 實錄 harvest 071：D3 採到稀有礦 Fortuitous，聊天新增行的真實文字是
# "small_lo has found Fortuitous"，但 RapidOCR 穩定讀成 "small-lo-has-found-Fortuitous"
# （整行單一 token、conf 0.98）或 "rsmall_lo-has-found-Fortuitous"（行首多 r、conf 0.97）。
# 空格全變連字號 → 精確 "has found" 子字串找不到 → _found_ore/fuzzy 兩路全滅
# → RESWEEP → 礦已採走重掃必空 → 誤交人工。對策：含 - 的行精確比對失敗時
# fallback 把 - 換空格再比（不改變既有可讀行的行為）。
from miningbot.ocr import _found_ore

H041_COMMON = ("Siogyne", "Cleavelite", "Toppatrick", "Riches")
H041_RARES = ("Fortuitous",)


def test_h041_found_ore_dehyphenates_single_token_line():
    # RapidOCR 把 "small_lo has found Fortuitous" 讀成單一連字號 token
    assert _found_ore("small-lo-has-found-Fortuitous", KW) == "fortuitous"


def test_h041_found_ore_dehyphenates_leading_noise_char():
    # 行首多一個 r（conf 0.97 的變體讀法）也要救回
    assert _found_ore("rsmall_lo-has-found-Fortuitous", KW) == "fortuitous"


def test_h041_found_ore_normal_line_unchanged():
    # 一般可讀行（無 -）行為不變
    assert _found_ore("small_lo has found Fortuitous", KW) == "fortuitous"


def test_h041_count_rare_found_counts_fortuitous_in_glued_line():
    text = "small-lo-has-found-Fortuitous"
    assert count_rare_found(text, H041_COMMON, KW) == 1


def test_h041_count_rare_found_excludes_common_after_dehyphenation():
    # ★ 安全方向：一般礦被黏行 → de-hyphen 後仍須被排除清單擋下（不可誤判稀有）
    text = "small-lo-has-found-Siogyne"
    assert count_rare_found(text, H041_COMMON, KW) == 0


def test_h041_count_rare_found_hyphenated_common_ore_name_excluded():
    # 排除清單含連字號礦名（如 Sub-Zero）：de-hyphen 對稱正規化後仍須排除。
    # OCR 把 "Sub-Zero" 讀成 "Sub Zero"（- 變空格）時也不可逃過排除清單。
    text = "small_lo has found Sub Zero"
    assert count_rare_found(text, ("Sub-Zero",), KW) == 0


def test_h041_count_found_dehyphenates_glued_line():
    # count_found（raw substring 路徑）也要處理黏行
    assert count_found("small-lo-has-found-Fortuitous", KW) == 1


def test_h041_has_new_found_last_line_dehyphenates_glued_line():
    before = "some chat"
    after = "some chat\nsmall-lo-has-found-Fortuitous"
    assert has_new_found_last_line(before, after, KW) is True


def test_h041_any_new_rare_found_full_071_transcript():
    # harvest 071 實錄 13 行全文：底部黏行 rsmall_lo-has-found-Fortuitous 是真成功
    before = "NORMAL\nShamrock [2/3"
    after = (
        "small_lo has tound Siogyne\n"
        "small_lo has found Cleavelite\n"
        "small_lo has found Toppatrick\n"
        "small_lo has found Siogyne\n"
        "small_lo has found Siogyne\n"
        "small_lo has found Siogyne\n"
        "The mine is resetting...\n"
        "The mine has regenerated!\n"
        "KIT (@small_lo) has rerolled the event to Verd\n"
        "small_lo has found Riches\n"
        "rsmall_lo-has-found-Fortuitous\n"
        "NORMAL\n"
        "Shamrock [2/3"
    )
    assert any_new_rare_found([before], [after], H041_COMMON, KW,
                              rare_names=H041_RARES) is True


# ── parse_capacity_pct：頂部「Capacity: NNN%」解析（2026-07-11 重置偵測第二信號）──
# OCR 實測 4 張快照的讀值（Claude 真實引擎驗證，直接寫進測試）：
#   'Capacity: 14% |'  → 14
#   'Capacity: 100% |' → 100
#   'Capacity: 101% [' → 101
#   'Capacity: 101% |' → 101
# 尾端 | / [ 是 pill 分隔線雜訊，解析必須容忍。

def test_parse_capacity_pct_real_fixture_strings():
    assert parse_capacity_pct("Capacity: 14% |") == 14.0
    assert parse_capacity_pct("Capacity: 100% |") == 100.0
    assert parse_capacity_pct("Capacity: 101% [") == 101.0
    assert parse_capacity_pct("Capacity: 101% |") == 101.0

def test_parse_capacity_pct_case_insensitive():
    assert parse_capacity_pct("CAPACITY: 99%") == 99.0
    assert parse_capacity_pct("capacity: 42%") == 42.0

def test_parse_capacity_pct_decimal():
    assert parse_capacity_pct("Capacity: 99.5%") == 99.5

def test_parse_capacity_pct_tolerates_trailing_noise():
    assert parse_capacity_pct("Capacity: 87%|Depth: 100m") == 87.0

def test_parse_capacity_pct_empty_returns_none():
    assert parse_capacity_pct("") is None

def test_parse_capacity_pct_no_percent_returns_none():
    assert parse_capacity_pct("Capacity: 100") is None

def test_parse_capacity_pct_depth_not_misread_as_pct():
    # sanity range 守門：Depth 的數字不可被當成 pct（防 OCR 把整行讀歪時誤觸發重置）
    assert parse_capacity_pct("Depth: 8109m") is None

def test_parse_capacity_pct_out_of_range_returns_none():
    # >150 → None（防把 $ 金額誤讀成 pct）
    assert parse_capacity_pct("Capacity: 800%") is None

def test_parse_capacity_pct_falls_back_to_first_pct_when_label_missing():
    # OCR 可能把 label 讀歪但數字在 → 退而求整串第一個 NNN%
    assert parse_capacity_pct("Capucity 98%") == 98.0

def test_parse_capacity_pct_negative_returns_none():
    assert parse_capacity_pct("Capacity: -5%") is None


# ── fixed-ROI single-line RapidOCR fast path ──

def test_read_text_line_rapid_disables_detection_and_classification(monkeypatch):
    from miningbot import ocr as ocr_module

    calls = []

    class Output:
        txts = ("Capacity: 100%",)
        scores = (0.99,)

    def fake_engine(image, **kwargs):
        calls.append(kwargs)
        return Output()

    monkeypatch.setattr(ocr_module, "_get_rapid_engine", lambda: fake_engine)
    image = np.zeros((45, 200, 3), dtype=np.uint8)

    assert ocr_module.read_text_line(image, engine="rapidocr") == "Capacity: 100%"
    assert calls == [{"use_det": False, "use_cls": False, "use_rec": True}]


def test_read_text_line_does_not_poison_next_full_detection(monkeypatch):
    from miningbot import ocr as ocr_module

    calls = []

    class Output:
        scores = (0.99,)

        def __init__(self, text):
            self.txts = (text,)

    class StatefulEngine:
        use_det = True

        def __call__(self, image, **kwargs):
            self.use_det = kwargs["use_det"]
            calls.append(dict(kwargs))
            return Output("full chat" if self.use_det else "Capacity: 100%")

    engine = StatefulEngine()
    monkeypatch.setattr(ocr_module, "_get_rapid_engine", lambda: engine)
    image = np.zeros((45, 200, 3), dtype=np.uint8)

    assert ocr_module.read_text_line(image, engine="rapidocr") == "Capacity: 100%"
    assert ocr_module._read_text_rapid(image) == "full chat"
    assert [call["use_det"] for call in calls] == [False, True]


def test_read_text_line_auto_falls_back_when_validator_rejects(monkeypatch):
    from miningbot import ocr as ocr_module

    class Output:
        txts = ("unrelated text",)
        scores = (0.91,)

    monkeypatch.setattr(ocr_module, "_get_rapid_engine", lambda: lambda image, **kwargs: Output())
    monkeypatch.setattr(ocr_module, "read_text", lambda *args, **kwargs: "Capacity: 14%")
    image = np.zeros((45, 200, 3), dtype=np.uint8)

    text = ocr_module.read_text_line(
        image,
        validator=lambda value: ocr_module.parse_capacity_pct(value) is not None,
    )

    assert text == "Capacity: 14%"


def test_read_text_line_auto_falls_back_when_rapidocr_raises(monkeypatch):
    from miningbot import ocr as ocr_module

    def broken_engine(image, **kwargs):
        raise RuntimeError("temporary inference failure")

    monkeypatch.setattr(ocr_module, "_get_rapid_engine", lambda: broken_engine)
    monkeypatch.setattr(ocr_module, "read_text", lambda *args, **kwargs: "fallback")
    image = np.zeros((45, 200, 3), dtype=np.uint8)

    assert ocr_module.read_text_line(image) == "fallback"


# ---- H054（2026-07-20，harvest 094；使用者發現「把過去的挖礦紀錄當成功依據」）----
# 根因：episode 進場凍結的聊天裁圖落在 Roblox 聊天淡出時段（無新訊息 ~15s 整窗隱藏），
# 基準 OCR 只讀到常駐 UI（礦物面板 "NORMAL"）、**0 條 has-found 行**。sweep 那 ~25s 間
# 事件訊息抵達使聊天整段重新淡入 → 計數差把「開火前早就在聊天裡的舊採集行」全當本次
# 新增 → rare 0→2 + special → 假成功。實機鐵證：094 框未消失（gone=False）、且開火前
# (12:44:47) 與開火後 (12:44:56) 的聊天裁圖 MD5 完全相同＝這一發根本沒產生任何新行。
# 錨點信號（last_line/tail）與 ChatLedger 都正確拒絕了（ocr.py:522 早有「上次讀取為空
# → 不計新增」規則），只有**計數差**沒有這道保護 → confirmed 是三者 OR、帳本無法否決。
# 對策：基準沒讀到任何 has-found 歷史時，計數差不可採信（方向：寧漏勿假成功——
# 漏判走 RETRY/RESWEEP 再射一次，假成功＝礦沒挖到卻收尾走人）。
H054_COMMON = ("Siogyne", "Riches", "Toppatrick", "Weevil", "Syrooze",
               "Cleavelite", "Coinstorm", "Imbollyx")

# harvest 094 實機原文（logs/snapshots/trace/20260720_124456_094_chat_ocr_success.txt）
H054_BASELINE_HIDDEN = "NORMAL"
H054_AFTER_094 = (
    "nil (@small_io) nasreroliea ne event lo\n"
    "Reminiscence!\n"
    "KIT (@small_lo) has rerolled the event to Cobb\n"
    "small_lo has found Clovara\n"
    "small_lo has found an ionized Imbollyx\n"
    "small_lo has found Riches\n"
    "small_lo has found Siogyne\n"
    "small_lo has found Toppatrick\n"
    "small_lo has found Syrooze (Candied Cave)\n"
    "NORMAL"
)

# harvest 082 實機原文（20260719_012711_082_chat_ocr_success.txt）＝**真成功**對照組：
# 基準讀得到 10 條 has-found 歷史，新增行只有底部兩條 → 計數差在此必須照常生效。
H054_BASELINE_VISIBLE_082 = (
    "small_io nas louna uelisoi (sortsnow Cave)\n"
    "small_lo has found Siogyne\n"
    "small_lo has found Cleavelite\n"
    "small_lo has found Riches\n"
    "KIT (@small_lo) has activated the Wintburg ev\n"
    "KIT (@small_lo) has rerolled the event to Polar\n"
    "KIT (@small_lo) has rerolled the event to Cobb\n"
    "small_lo has found Siogyne\n"
    "KIT (@small_lo) has rerolled the event to Everg\n"
    "small_lo has found a spectral Auriclase\n"
    "NORMAL"
)
H054_AFTER_082 = (
    "small_io nas rouna Siogyne\n"
    "small_lo has found Cleavelite\n"
    "small_lo has found Riches\n"
    "KIT (@small_lo) has activated the Wintburg ev\n"
    "KIT (@small_lo) has rerolled the event to Polar\n"
    "KIT (@small_lo) has rerolled the event to Cobb\n"
    "small_lo has found Siogyne\n"
    "KIT (@small_lo) has rerolled the event to Everg\n"
    "small_lo has found a spectral Auriclase\n"
    "small_lo has found Weevil\n"
    "small-lo-has-found-an ionized Starstride\n"
    "NORMAL"
)

from miningbot.ocr import baseline_saw_found_history


def test_h054_hidden_chat_baseline_is_not_usable():
    # 094/093/091/081 五場實機基準都是這一種：整窗淡出、只剩常駐面板文字
    assert baseline_saw_found_history([H054_BASELINE_HIDDEN], KW) is False


def test_h054_visible_chat_baseline_is_usable():
    # 082 真成功：基準確實看到了聊天歷史 → 計數差有意義
    assert baseline_saw_found_history([H054_BASELINE_VISIBLE_082], KW) is True


def test_h054_baseline_usable_when_any_pass_saw_history():
    # 逐 pass 盲區（H014）：某個前處理讀不到不代表聊天是隱藏的——任一 pass 看到即可用
    assert baseline_saw_found_history(["", H054_BASELINE_VISIBLE_082], KW) is True


def test_h054_empty_baseline_is_not_usable():
    assert baseline_saw_found_history(["", ""], KW) is False


def test_h054_count_diff_alone_would_have_faked_success_on_094():
    # 事故本體：計數差信號在 094 確實回 True（0→2）——這就是假成功的來源。
    # 這條測試釘住「為什麼需要基準閘」：不是計數差壞了，是它的前提不成立。
    assert has_new_rare_found(H054_BASELINE_HIDDEN, H054_AFTER_094,
                              H054_COMMON, KW) is True
    assert baseline_saw_found_history([H054_BASELINE_HIDDEN], KW) is False


def test_h054_real_success_082_still_confirmed_by_count_diff():
    # 兩側夾的另一側：真成功不可被閘擋掉
    assert has_new_rare_found(H054_BASELINE_VISIBLE_082, H054_AFTER_082,
                              H054_COMMON, KW) is True
    assert baseline_saw_found_history([H054_BASELINE_VISIBLE_082], KW) is True


# ---- H055（2026-07-20，harvest 082；H054 調查副產物，使用者裁決當時不在該輪範圍）----
# 左上礦物面板標頭 "NORMAL" 落在 config.chat_region = Region(0,110,460,280) 的下緣，
# **每次聊天 OCR 都被讀成最後一行** → 兩個抗捲動信號結構性失效（不是調參問題、是恆成立）：
#   has_new_rare_found_last_line：before_last == after_last == "NORMAL" → 永遠 False
#   has_new_rare_found_tail：_align_tail 的錨點恆對到 after 尾端的 "NORMAL"、tail 恆為空
#   ChatLedger：同一個 _align_tail，錨點鏈一併被綁死
# 實機鐵證＝082（真成功）：新增行 "small_lo has found Weevil" 與
# "small-lo-has-found-an ionized Starstride" 都插在 "NORMAL" **上面**，兩信號全滅，
# 整套 verify 退化成只剩計數差——而計數差正是 H054 假成功的來源。
#
# 為何不縮短 chat_region（route b，實機量測否決）：面板不是「在聊天下方」而是**疊在聊天上**。
#   082_d3_chat_after.png：面板白色圓角上緣在裁圖 y=227，最新 has-found 行的字身
#     量在無面板的 x>=250 帶＝y=225..234 → 邊框橫穿字身（這也是 OCR 讀成
#     "small-lo-has-found-an" 連字號的來源，H041 同型）。
#   094_d3_chat_after.png：最新（淡出中）聊天行落在 y≈240..255，正是 "NORMAL" 字身帶
#     （白字 y=240..258）→ 任何「停在面板上方」的裁法都會切掉真聊天行。
#   故 config.py:73「勿縮短高度否則漏掉最新 has-found」是實機事實，不是保守估計。
#
# 對策（route a，純加法）：比對進入點剝掉尾端常駐 UI 殘留行，讓錨點自然落回真聊天行。
# 兩側夾（6 份實機 trace dump 全部行）：
#   UI 殘留＝**恰好 1 token**（NORMAL ×11、Shamrock ×2，共 13 筆）
#   真 found 行＝**≥3 token**（"has found X" 的下限；實測最短 "small_lo has found W" ＝4）
# 安全性不只經驗：found_keywords = ("has found","found a") 都是雙詞片語 → 任何 found 行
# 必 ≥3 token → **1 token 行永遠不可能是 found 行**，剝掉它不可能剝掉成功信號。
# 1 token 的真聊天行只有折行碎片（'Weevil'/'hasfound'/'Reminiscence!'/'30%!'），
# 它們本來就 _found_ore() → None、對信號無貢獻。
from miningbot.ocr import (has_new_rare_found_tail, new_chat_tail_lines,
                           ChatLedger as _H055Ledger)

H055_COMMON = H054_COMMON

# harvest 091 實機原文（20260719_183935_091_chat_ocr_success.txt）：
# 面板殘留**兩行**（左 NORMAL + 右側圖層面板 Shamrock），且基準整窗淡出。
H055_BASELINE_FADED_091 = "NORMAL\nShamrock"
H055_AFTER_091 = (
    "small_io nas rouna Faearne\n"
    "KIT (@small_lo) has boosted the event's length\n"
    "small_lo has found Siogyne\n"
    "small_lo has found Siogyne\n"
    "small_lo has found Polkegg (Eggshell Cave)\n"
    "small_lo has found an ionized Imbollyx\n"
    "small_lo has found Eleggtricity (Eggshell Cave\n"
    "KIT (@small_lo) has rerolled the event to Antle\n"
    "KIT (@small_lo) has rerolled the event to Antle\n"
    "small_lo has found Riches\n"
    "small-lo-has-found-Starstride\n"
    "NORMAL\n"
    "Shamrock"
)


def test_h055_082_last_line_signal_sees_the_new_rare_line():
    # 事故本體①：082 是真成功，底行信號本應 True，卻因 "NORMAL" 恆為兩側最後一行而回 False
    assert has_new_rare_found_last_line(H054_BASELINE_VISIBLE_082, H054_AFTER_082,
                                        H055_COMMON, KW) is True


def test_h055_082_tail_signal_sees_the_new_rare_line():
    # 事故本體②：錨點恆對到尾端 "NORMAL" → tail 恆空 → H032 的補洞信號一併失效
    assert has_new_rare_found_tail(H054_BASELINE_VISIBLE_082, H054_AFTER_082,
                                   H055_COMMON, KW) is True


def test_h055_082_tail_lines_are_exactly_the_two_new_chat_lines():
    # 錨點應落在 before 的真底行（a spectral Auriclase），其後兩行才是新增
    assert new_chat_tail_lines(H054_BASELINE_VISIBLE_082, H054_AFTER_082) == [
        "small_lo has found Weevil",
        "small-lo-has-found-an ionized Starstride",
    ]


def test_h055_082_ledger_anchor_chain_confirms():
    # 事故本體③：ChatLedger 走同一個 _align_tail，錨點鏈被同一原因綁死
    ledger = _H055Ledger([H054_BASELINE_VISIBLE_082])
    ledger.update([H054_AFTER_082], H055_COMMON, KW)
    assert ledger.confirmed is True
    assert any("Starstride" in l for l in ledger.rare_lines)


def test_h055_strips_both_ui_residue_lines_091():
    # 091 是雙面板場景：NORMAL + Shamrock 都要剝，錨點才落得回真聊天行
    tail = new_chat_tail_lines("small_lo has found Riches\nNORMAL\nShamrock",
                               H055_AFTER_091)
    assert tail == ["small-lo-has-found-Starstride"]


def test_h055_does_not_eat_hyphen_welded_real_chat_line():
    # 使用者硬性要求：不可誤殺被 OCR 讀歪的真聊天行。
    # H041 型整行黏連字號（"small-lo-has-found-an ionized Starstride"）去黏後 7 token，
    # 遠高於 1 → 必須留下，否則正是它撐起 082 的成功判定。
    welded = "small-lo-has-found-an ionized Starstride"
    assert new_chat_tail_lines("small_lo has found Riches\nNORMAL",
                               f"small_lo has found Riches\n{welded}\nNORMAL") == [welded]


def test_h055_keeps_short_but_multi_token_chat_fragments():
    # 兩側夾的下側：3 token 的折行碎片（093 實機 "chance by 15%!"）不可被當面板剝掉
    assert new_chat_tail_lines("small_lo has found Riches\nNORMAL",
                               "small_lo has found Riches\nchance by 15%!\nNORMAL") == [
        "chance by 15%!"]


def test_h055_faded_baseline_must_not_confirm_via_last_line():
    # ★ 剝殼暴露的既有破口：091 基準整窗淡出（剝完為空），after 底行剛好是稀有礦
    # （Starstride）。舊行為靠 "NORMAL"=="NORMAL" 意外擋住；剝掉後若不補「基準為空即棄權」，
    # 會憑空生出假成功。方向同 ChatLedger「上次讀取為空→不計新增」與 H054 基準閘。
    assert has_new_rare_found_last_line(H055_BASELINE_FADED_091, H055_AFTER_091,
                                        H055_COMMON, KW) is False


def test_h055_faded_baseline_must_not_confirm_via_tail():
    assert has_new_rare_found_tail(H055_BASELINE_FADED_091, H055_AFTER_091,
                                   H055_COMMON, KW) is False


def test_h055_does_not_resurrect_h054_false_success_on_094():
    # H054 回歸釘樁：剝殼後 094 的基準變成「真的空」，兩個錨點信號仍須拒絕
    assert has_new_rare_found_last_line(H054_BASELINE_HIDDEN, H054_AFTER_094,
                                        H054_COMMON, KW) is False
    assert has_new_rare_found_tail(H054_BASELINE_HIDDEN, H054_AFTER_094,
                                   H054_COMMON, KW) is False


# ---- H064（2026-07-28，harvest 110~119；使用者發現「幾乎每輪都要人工」）----
# 根因：HARVESTING 一進場就 prepare_scan 停止移動 → 被動採礦停 → 聊天無新訊息 ~15s
# 整窗淡出 → episode 基準（進場凍結的裁圖）恆讀到 0 條 has-found → H054 基準閘擋掉
# 計數差、last_line/tail/ledger 三個錨點信號各自棄權 → **礦確實採到了也永遠 no-new**
# → RESWEEP → 重掃全空（礦已被自己採走）→ 誤交人工。不是機率性漏判，是結構性全滅。
# 對策：ChatLedger 的「上次讀取為空 → 不計新增」改成「只認最底行」——Roblox 聊天整窗
# 只在有新訊息抵達時重新顯示，新訊息恆在最底下 → 底行＝讓聊天重現的那則新訊息。
# 原文取自實機 trace dump（110/111/112 在 logs/snapshots/trace/，119 同）。
H064_COMMON = ("Siogyne", "Riches", "Toppatrick", "Weevil", "Syrooze",
               "Cleavelite", "Imbollyx", "Clovara")   # 注意：Coinstorm 在此世界是稀有

# harvest 119（20260728_165414_119_chat_ocr_resweep.txt）：基準整窗淡出＝空字串
H064_AFTER_119 = (
    "2070:\n"
    "KIT (@small_lo) has boosted the event's length\n"
    "30%！\n"
    "small_lo has found Siogyne\n"
    "small_lo has found an ionized Plentium\n"
    "KIT (@small_lo) has boosted the event's length\n"
    "30%!\n"
    "small_lo has found Siogyne\n"
    "small_lo has found Cleavelite\n"
    "KIT (@small_lo) has boosted the event ore's sp\n"
    "chance by 15%!\n"
    "small_lo has found Coinstorm"
)

# harvest 112（20260726_021734_112_chat_ocr_resweep.txt）：底行是 H041 型連字號黏連
H064_AFTER_112 = (
    "small_lo has tound Cleavelite\n"
    "The mine is resetting...\n"
    "The mine has regenerated!\n"
    "KIT (@small_lo) has boosted the event ore's sp\n"
    "chance by 15%!\n"
    "small_lo has foundan ionized Plentium\n"
    "KIT (@small_lo) hasrerolled the event to Ornas\n"
    "small_lo has found Siogyne\n"
    "small_lo has foundSiogyne\n"
    "small_lo has found Riches\n"
    "rsmall-lo-has-found-Starstride\n"
    "NORMAL"
)


def test_h064_reappeared_chat_confirms_via_bottom_line_119():
    # 事故本體：119 真的採到 Coinstorm，舊規則整輪棄權 → 誤交人工
    led = ChatLedger([""])
    assert led.update([H064_AFTER_119], H064_COMMON, KW) == [
        "small_lo has found Coinstorm"]
    assert led.confirmed is True


def test_h064_reappeared_chat_confirms_hyphen_welded_bottom_line_112():
    # 112 底行被 OCR 黏成連字號（H041 型）——剝殼/去黏仍須認得出它是 found 行
    led = ChatLedger(["NORMAL"])
    assert led.update([H064_AFTER_112], H064_COMMON, KW) == [
        "rsmall-lo-has-found-Starstride"]


def test_h064_only_the_bottom_line_is_attributed_not_the_redisplayed_history():
    # 安全方向：重顯示的整段舊歷史不可入帳（119 中段另有 ionized Plentium 等稀有行）
    led = ChatLedger([""])
    led.update([H064_AFTER_119], H064_COMMON, KW)
    assert led.new_lines == ["small_lo has found Coinstorm"]


def test_h064_does_not_resurrect_h054_false_success_on_094():
    # 兩側夾的另一側（最關鍵的一條）：094 假成功的底行是排除清單內的一般礦
    # （Syrooze）→ 重顯示規則放寬後仍須拒絕，H054 不得復活
    led = ChatLedger([H054_BASELINE_HIDDEN])
    assert led.update([H054_AFTER_094], H054_COMMON, KW) == []
    assert led.confirmed is False


def test_h064_still_abstains_while_chat_stays_hidden_110():
    # 110 實錄：前後兩次讀取都只有面板殘留（聊天全程沒重現）→ 無證據可用，
    # 行為不變（不確認），且錨點不可被空讀取推進
    led = ChatLedger(["NORMAL"])
    assert led.update(["NORMAL"], H064_COMMON, KW) == []
    assert led.confirmed is False
    # 之後聊天終於重現時仍走重顯示規則（錨點沒被 "NORMAL" 汙染）
    assert led.update([H064_AFTER_119], H064_COMMON, KW) == [
        "small_lo has found Coinstorm"]


def test_h064_bottom_line_ores_are_rare_in_every_world():
    # 釘住 fixture 的前提：Coinstorm/Starstride 不在任何世界的排除清單裡＝真稀有
    from miningbot import game_data
    common = {c.lower() for c in game_data.common_ore_names()}
    assert "coinstorm" not in common and "starstride" not in common
