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
    # 聊天在基準時淡出（讀到空）→ 之後新訊息會讓「舊行連同新行」一起重顯示，
    # 無從分辨舊行重顯示 vs 真新增 → 首次非空讀取只起鏈、不計新增（舊稀有行
    # 重顯示不可假陽性）；起鏈之後的增量照常計
    led = ChatLedger([""])
    redisplay = "small_lo has found Saerylium\nsmall_lo has found Loveletter"
    assert led.update([redisplay], LG_COMMON, KW) == []
    assert led.confirmed is False
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
