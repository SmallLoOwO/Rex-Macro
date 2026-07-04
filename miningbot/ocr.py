import re
import os
import logging
import threading
import time
import numpy as np

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()

def contains_phrase(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)

def contains_any(text: str, phrases) -> bool:
    n = _normalize(text)
    return any(_normalize(p) in n for p in phrases)

def count_found(text: str, phrases) -> int:
    """計 phrases 在 text 中出現的總次數（正規化後比對）。

    給採集「差分確認」用：D3 前後各讀一次聊天框，只有數量「增加」才算新採到，
    避免舊的 "has found" 訊息賴在框裡偽造成功（stale-chat false positive）。
    """
    n = _normalize(text)
    return sum(n.count(_normalize(p)) for p in phrases)

def has_new_found(before: str, after: str, phrases) -> bool:
    """D3 後的 phrases 數量必須「多於」D3 前才算新事件。

    舊聊天訊息不再偽造成功；連續同一個稀有礦也能正確分辨（計數會 +1）。
    """
    return count_found(after, phrases) > count_found(before, phrases)

def has_new_found_last_line(before: str, after: str, phrases) -> bool:
    """chat 最後一行差分：after 底部出現了 before 底部沒有的 found 訊息，算新採集。

    count_found diff 在 chat 捲動（found_before 很高）時計數只減不增（假負）。
    新訊息永遠出現在 chat 底部 → 只看最後一行即可，捲動只影響頂部。
    """
    def last_line(text: str) -> str:
        stripped = text.strip()
        return stripped.split("\n")[-1].strip() if stripped else ""

    before_last = _normalize(last_line(before))
    after_last  = _normalize(last_line(after))
    if before_last == after_last:
        return False
    return any(_normalize(p) in after_last for p in phrases)


def _found_ore(line: str, found_keywords) -> str | None:
    """從一行聊天抽出「has found / found a」後面的礦名（正規化）；非 found 行回 None。

    例：「small_lo has found Lilaverine」→ "lilaverine"。
    """
    n = _normalize(line)
    for kw in found_keywords:
        k = _normalize(kw)
        i = n.find(k)
        if i >= 0:
            return n[i + len(k):].strip()
    return None

# 變體前綴：所有非 layer 礦都有 Ionized/Spectral 變體（wiki 證實 2026-07-03）。
# Rare/Master 的 Spectral 也會進 local chat →「has found Spectral Bandeau」若不剝前綴，
# "spectral bandeau" 不 startswith "bandeau" → 排除失效 → 被當稀有 → 假成功。
VARIANT_PREFIXES = ("spectral", "ionized")


# 變體行帶冠詞（H032 實錄 2026-07-04）：遊戲實際聊天是 "has found an ionized Diamantine"，
# 冠詞不剝掉的話 "an ionized diamantine" 剝不到變體前綴 → 不 startswith 任何排除清單
# → 被動低階變體被當稀有/special（假成功風險）。
_ARTICLES = ("an", "a")


def _strip_variant(ore: str) -> str:
    """剝掉礦名開頭的冠詞與變體前綴（已正規化小寫）："an ionized bandeau" → "bandeau"。"""
    for a in _ARTICLES:
        if ore.startswith(a + " "):
            ore = ore[len(a) + 1:]
            break
    for p in VARIANT_PREFIXES:
        if ore.startswith(p + " "):
            return ore[len(p) + 1:]
    return ore


def _is_rare_ore(ore: str | None, common_norm) -> bool:
    """礦名非空、且（剝變體前綴後）不屬於任何「低稀有度礦」（排除清單）→ 視為稀有礦。

    用 startswith 容忍 OCR 在一般礦名尾端多出的雜訊（如 "bandeau!"）→ 仍判為 common，
    偏保守（寧可把可疑的當 common 漏掉，也不要把一般礦誤當稀有礦造成假成功）。
    """
    if not ore:
        return False
    base = _strip_variant(ore)
    return not any(base.startswith(c) for c in common_norm)

def found_ore_name(line: str, found_keywords) -> str | None:
    """公開版 _found_ore：從一行聊天抽礦名（正規化小寫）；非 found 行回 None。

    給 main 的三態分類標注用（game_data.classify_found_ore 的輸入）。
    """
    return _found_ore(line, found_keywords)


def count_rare_found(text: str, common_names, found_keywords) -> int:
    """計聊天中「稀有礦」的 has-found 行數（反轉策略：排除低稀有度礦 common_names）。

    給 D3 採集確認用：聊天「<小名> has found X」混了普通鎬子挖的一般礦與 D3 稀有礦；
    X 屬於 common_names（低稀有度）→ 普通挖礦、忽略；不在 → 稀有礦 → 計一筆。
    上一輪留下的稀有礦會同名計多次，故回傳「次數」供差分（呼叫端比 before/after 是否增加）。
    """
    common = [_normalize(c) for c in common_names]
    total = 0
    for line in text.splitlines():
        if _is_rare_ore(_found_ore(line, found_keywords), common):
            total += 1
    return total

def has_new_rare_found(before: str, after: str, common_names, found_keywords) -> bool:
    """D3 後稀有礦 has-found 行數「多於」D3 前 → 採到新的稀有礦（排除低稀有度礦）。"""
    return (count_rare_found(after, common_names, found_keywords)
            > count_rare_found(before, common_names, found_keywords))

def has_new_rare_found_last_line(before: str, after: str, common_names, found_keywords) -> bool:
    """chat 最後一行差分：after 底部出現了 before 底部沒有的「稀有礦」行。

    **這是對抗捲動的主信號**：舊訊息從頂部刷掉會讓 count 只減不增（假負），但新訊息
    永遠出現在底部 → 只看最後一行，捲動只影響頂部。底部變動且該行是稀有礦才算
    （底部是一般礦則不算）。
    """
    def last_line(text: str) -> str:
        stripped = text.strip()
        return stripped.split("\n")[-1].strip() if stripped else ""

    before_last = last_line(before)
    after_last  = last_line(after)
    if _normalize(before_last) == _normalize(after_last):
        return False
    common = [_normalize(c) for c in common_names]
    return _is_rare_ore(_found_ore(after_last, found_keywords), common)


# ── 底部新增行對齊（2026-07-04 H032 假陰性對策）─────────────────────────────
# H032 實錄：D3 命中、聊天新增稀有行，但**同窗口又進來一行一般礦排在它後面**→底行信號滅；
# 同時頂部剛好刷掉一行舊稀有 → count 差分 3→3 也滅 → 假陰性誤交人工。
# 「新稀有行必在底部」的假設在多行同窗口抵達時不成立 → 改對齊 before 底行在 after 的
# 錨點位置，錨點之後**全部**都是新增行，任一行是稀有 found 行即確認。

def _chat_lines(text: str) -> list:
    return [l.strip() for l in text.splitlines() if l.strip()]


def _lines_alike(a: str, b: str) -> bool:
    """同一實體行的前後兩次 OCR 常略有出入 → 完全相等或相似度達噪音門檻即視為同行。"""
    return a == b or SequenceMatcher(None, a, b).ratio() >= FUZZY_STALE_LINE_RATIO


def _align_tail(before: str, after: str) -> tuple[bool, list]:
    """把 before 底行對齊到 after 中的錨點，回 (是否對到錨點, 錨點之後的新增行原文)。

    「對不到錨點」與「對到但沒有新增行」呼叫端待遇不同（ChatLedger 前者不推進錨點、
    後者要推進）→ 分開回報；new_chat_tail_lines 是不分辨的舊介面 wrapper。
    """
    b = [_normalize(l) for l in _chat_lines(before)]
    a_orig = _chat_lines(after)
    a = [_normalize(l) for l in a_orig]
    if not b or not a:
        return False, []
    best_j, best_run = -1, 0
    for j in range(len(a)):
        if not _lines_alike(a[j], b[-1]):
            continue
        run = 1
        while run < len(b) and j - run >= 0 and _lines_alike(a[j - run], b[-1 - run]):
            run += 1
        if run >= best_run:
            best_j, best_run = j, run
    if best_j < 0:
        return False, []
    return True, a_orig[best_j + 1:]


def new_chat_tail_lines(before: str, after: str) -> list:
    """after 相對 before 的底部新增行（原文，保序）。

    聊天是 append-only＋頂部刷掉：after ＝ before 的尾段＋新行。把 before 的底行對齊到
    after 中的位置當錨點（候選多個時取「向上連續吻合最長」者——before 底行可能是重複礦名、
    新行裡也有同名行，錨到新行會漏；同長取較晚位置，新行越少越保守）。
    對不到錨點（換場景/該 pass 的 OCR 噪音）→ 回空 list（保守：交回 count/底行信號，不假陽性）。
    """
    return _align_tail(before, after)[1]


def has_new_rare_found_tail(before: str, after: str, common_names, found_keywords) -> bool:
    """底部新增行（對齊錨點後）任一行是稀有 found 行 → True。

    比 has_new_rare_found_last_line 多涵蓋「新稀有行後面又跟了一般礦行」（H032）；
    錨點對不到時回 False，由 count/底行信號決定（不取代、只補洞）。
    """
    common = [_normalize(c) for c in common_names]
    return any(_is_rare_ore(_found_ore(l, found_keywords), common)
               for l in new_chat_tail_lines(before, after))


# ── 多前處理融合（H014 假陰性根因的對策）─────────────────────────────────
# 單一前處理必有背景盲區：min_channel 為暗背景紅字校準、在亮粉糖果礦區彩色行全滅
# （2026-07-03 H014：真正採到的底部新行 has found Diamorite 沒讀到→誤交人工）；
# dark_mask 靠「文字深色外框 vs 亮背景」、在近全黑礦坑反而分不開字與背景。
# 故 verify 對聊天框跑多種前處理，**各 pass 內部自洽比 before/after**（不同 pass 的
# OCR 噪音不同，交叉比會偽造 diff），任一 pass 有信號即 confirmed。
# 實測（tests/fixtures/chat 回歸集）：三種 pass 在暗棕混合背景各救回不同行、聯集嚴格更優。
CHAT_PREPROCESSES = ("min_channel", "gray", "dark_mask")

def any_new_rare_found(before_texts, after_texts, common_names, found_keywords,
                       rare_names=()) -> bool:
    """逐 pass 差分（count 增加或底部新稀有行），任一 pass 確認即 True。

    before_texts/after_texts 依 CHAT_PREPROCESSES 順序一一對應（read_text_multi 的輸出）。
    rare_names（白名單詞彙表）非空時加開模糊兜底（H020：關鍵字被 OCR 讀歪、精確
    匹配全滅時，靠「found-ish token＋礦名≈白名單」救回）；空＝行為不變。
    """
    return any(
        has_new_rare_found(b, a, common_names, found_keywords)
        or has_new_rare_found_last_line(b, a, common_names, found_keywords)
        or has_new_rare_found_tail(b, a, common_names, found_keywords)
        or (bool(rare_names)
            and has_new_fuzzy_rare_found(b, a, common_names, rare_names))
        for b, a in zip(before_texts, after_texts)
    )

def any_new_found(before_texts, after_texts, phrases) -> bool:
    """逐 pass 的 has_new_found（一般 phrase 差分用），任一 pass True 即 True。"""
    return any(has_new_found(b, a, phrases) for b, a in zip(before_texts, after_texts))


def count_special_found(text: str, common_names, found_keywords, variant_keywords) -> int:
    """計「found 行、含變體字樣（ionized/spectral）、且 base 礦名不在排除清單」的行數。

    舊版 special 判定只看 "spectral" 字樣出現次數（has_new_found）：被動挖到 Spectral
    Rare/Master（會進 local chat）或事件文字含該字 → 假成功。改綁 found 行 + 排除清單：
    Spectral Bandeau（低階）不算、Spectral Diamorite（高階目標）照算。
    """
    common = [_normalize(c) for c in common_names]
    total = 0
    for line in text.splitlines():
        ore = _found_ore(line, found_keywords)
        if not ore:
            continue
        if not any(_normalize(v) in ore for v in variant_keywords):
            continue
        if _is_rare_ore(ore, common):
            total += 1
    return total


# ── 模糊 found 行匹配（2026-07-03 H020 假陰性對策）──────────────────────────
# 根因：亮粉背景下三個前處理 pass 的「精確關鍵字」全滅——dark_mask 其實讀得到行，
# 但 "has found Valytium" 被讀成 "hee foumel velyiiuinm"，`has found` 子字串對不上
# → 整行作廢 → RESWEEP → 重掃全空（礦已採走）→ 誤交人工。
# 對策：行內找 token≈"found"（SequenceMatcher ≥ FUZZY_FOUND_TOKEN_RATIO），其後文字
# 同時對「稀有白名單」與「排除清單」模糊比對——白名單分數 ≥ FUZZY_ORE_RATIO **且
# 嚴格高於**排除清單分數才算稀有（"biemnentine"＝Surreal Diamantine 誤讀，對
# Solemn Lamentine 0.667 = 對 Diamantine 0.667 → 平手判 common；寧漏勿假成功）。
# 三重閘門（found-ish token ＋ 白名單命中 ＋ 贏過 common）讓寬鬆的 token 門檻安全。
from difflib import SequenceMatcher

# 門檻由 H020 實資料兩側夾出（真值 vs 誤收值都是實測）：
#   token：真誤讀 founcl=0.727、foumel=0.545；系統行 "friends"=0.500 曾誤收 → 0.52
#   ore：真誤讀 velyiiuinm→Valytium=0.667；"can chat"→Luckant=0.600 曾誤收 → 0.62
FUZZY_FOUND_TOKEN_RATIO = 0.52  # token vs "found"
FUZZY_FOUND_TOKEN_MIN_LEN = 4   # "un"(2字元)曾以 0.57 誤當 found-ish token
FUZZY_ORE_RATIO = 0.62          # 礦名 vs 白名單
FUZZY_STALE_LINE_RATIO = 0.85   # before/after 底行相似度 ≥ 此值 → 同一行的 OCR 噪音、非新行


def _best_match(cand: str, names_norm) -> tuple[float, str | None]:
    """cand 對 names_norm（(正規化, 原名) 對）取最高 SequenceMatcher 比率。"""
    best_r, best_n = 0.0, None
    sm = SequenceMatcher()
    sm.set_seq2(cand)                       # seq2 固定可重用內部索引
    for norm, orig in names_norm:
        sm.set_seq1(norm)
        if sm.real_quick_ratio() <= best_r or sm.quick_ratio() <= best_r:
            continue
        r = sm.ratio()
        if r > best_r:
            best_r, best_n = r, orig
    return best_r, best_n


def _name_pairs(names) -> list:
    return [(_normalize(n), n) for n in names]


def _fuzzy_rare_line(line: str, common_pairs, rare_pairs) -> dict | None:
    """單行模糊判定；回傳診斷 dict（accepted 註明收/拒），無 found-ish token 回 None。

    候選礦名取 found-token 之後的「全部 / 前 1 / 前 2 個 token」（容忍礦名後黏雜訊、
    也涵蓋多字礦名），各剝變體前綴後比對，取白名單分數最高的一組。
    """
    tokens = _normalize(line).split()
    best = None
    for i, t in enumerate(tokens[:-1]):     # found-token 之後至少要有礦名
        if i == 0:                          # 行首＝前面沒玩家名，不符 "<名> has found X" 結構
            continue                        # （系統行 "friends can chat..." 曾因此誤收）
        if len(t) < FUZZY_FOUND_TOKEN_MIN_LEN:
            continue
        if SequenceMatcher(None, t, "found").ratio() < FUZZY_FOUND_TOKEN_RATIO:
            continue
        rest = tokens[i + 1:]
        for cand in {" ".join(rest), rest[0], " ".join(rest[:2])}:
            cand = _strip_variant(cand)
            rare_r, rare_n = _best_match(cand, rare_pairs)
            if best is None or rare_r > best["best_rare"][1]:
                common_r, common_n = _best_match(cand, common_pairs)
                best = {"line": line.strip(), "token": t, "candidate": cand,
                        "best_rare": (rare_n, rare_r), "best_common": (common_n, common_r)}
    if best is None:
        return None
    best["accepted"] = (best["best_rare"][1] >= FUZZY_ORE_RATIO
                        and best["best_rare"][1] > best["best_common"][1])
    return best


def fuzzy_found_diagnostics(text: str, common_names, rare_names) -> list:
    """每個「含 found-ish token 的行」一筆診斷（含被拒者與分數）——詳細 log 用。"""
    common_pairs, rare_pairs = _name_pairs(common_names), _name_pairs(rare_names)
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        d = _fuzzy_rare_line(line, common_pairs, rare_pairs)
        if d is not None:
            out.append(d)
    return out


def count_fuzzy_rare_found(text: str, common_names, rare_names) -> int:
    """計「模糊 found 行且礦名最接近白名單稀有礦」的行數（差分用，語意同 count_rare_found）。"""
    return sum(1 for d in fuzzy_found_diagnostics(text, common_names, rare_names)
               if d["accepted"])


def has_new_fuzzy_rare_found(before: str, after: str, common_names, rare_names) -> bool:
    """模糊稀有行的前後差分：count 增加、底部出現新的模糊稀有行、或底部新增行
    （對齊錨點後，H032：新稀有行後面又跟了一般礦行）任一行是模糊稀有行。

    底行/新增行比對比精確版多一道「噪音守門」：同一實體行在前後兩次 OCR 常讀出略不同
    字樣（模糊路徑對此特別敏感），與 before 任一行相似度 ≥ FUZZY_STALE_LINE_RATIO
    視為同一行、不算新增。
    """
    common_pairs, rare_pairs = _name_pairs(common_names), _name_pairs(rare_names)
    if (count_fuzzy_rare_found(after, common_names, rare_names)
            > count_fuzzy_rare_found(before, common_names, rare_names)):
        return True
    def last_line(text: str) -> str:
        stripped = text.strip()
        return stripped.split("\n")[-1].strip() if stripped else ""
    b, a = _normalize(last_line(before)), _normalize(last_line(after))
    if a and a != b and SequenceMatcher(None, b, a).ratio() < FUZZY_STALE_LINE_RATIO:
        d = _fuzzy_rare_line(a, common_pairs, rare_pairs)
        if d and d["accepted"]:
            return True
    before_lines = [_normalize(l) for l in _chat_lines(before)]
    for line in new_chat_tail_lines(before, after):
        n = _normalize(line)
        if any(_lines_alike(bl, n) for bl in before_lines):
            continue                       # 噪音守門：before 已有的行（略讀歪）不算新增
        d = _fuzzy_rare_line(line, common_pairs, rare_pairs)
        if d and d["accepted"]:
            return True
    return False


def new_fuzzy_rare_lines(before: str, after: str, common_names, rare_names) -> list:
    """after 新增的模糊稀有行 [(原行, 匹配白名單礦名, 比率)]——通知標注用。

    「新增」＝與 before 任一行相似度 < FUZZY_STALE_LINE_RATIO（噪音守門，同
    has_new_fuzzy_rare_found 的底行邏輯，推廣到全部行）。
    """
    common_pairs, rare_pairs = _name_pairs(common_names), _name_pairs(rare_names)
    before_lines = [_normalize(l) for l in before.splitlines() if l.strip()]
    out = []
    for line in after.splitlines():
        if not line.strip():
            continue
        n = _normalize(line)
        if any(SequenceMatcher(None, b, n).ratio() >= FUZZY_STALE_LINE_RATIO
               for b in before_lines):
            continue
        d = _fuzzy_rare_line(line, common_pairs, rare_pairs)
        if d and d["accepted"]:
            out.append((line.strip(), d["best_rare"][0], d["best_rare"][1]))
    return out


# ── Episode 級聊天帳本（2026-07-04，H032 延伸對策）─────────────────────────────
# 單一基準的點對點差分守不住兩個時間軸破口：
#  (a) 誤判失敗 → RESWEEP 作廢重取基準，晚到的成功行被吃進新基準 → 從此不算「新增」；
#  (b) 失敗路徑（D2 重掃/D5 守門 settle/8 方位重掃）沒人在看聊天，成功行抵達後又被
#      一般礦行往上推、捲出裁圖 → 之後任何 after 裡都不再出現，錨點對齊也救不了。
# 對策：基準在 HARVESTING 進場時取一次（episode 級、全程不作廢），之後每次 OCR 以
# 「上一次讀取」為錨點鏈式對齊（間隔短 → 錨點幾乎不會捲丟），新增行累積進帳本。
# 領域事實讓 episode 級語意成立：單人作業＋Exotic+ 被動出土 ≤1/1M → episode 內任何
# 時點出現的新稀有 found 行只可能來自自己的 D3 ＝成功，不論晚到多久、在哪個階段被看到。

class ChatLedger:
    """HARVESTING episode 的聊天新增行帳本（滾動錨點鏈、逐 pass 自洽）。

    baseline_texts＝read_text_multi 輸出（各前處理 pass 一份文字）；各 pass 各自維護
    錨點鏈（H014 原則：pass 間噪音不同、不可交叉比）。update() 是加法信號：帳本只補
    「對 episode 基準單次差分」的洞，count/底行等長程信號仍由呼叫端照跑、任一確認即可。
    """

    @staticmethod
    def _same_entity_line(prev_line: str, new_line: str, found_keywords) -> bool:
        """兩行是否為「同一實體行」（重讀噪音）。

        聊天行共享長前綴「<名> has found 」→ 整行相似度 0.85 連不同礦名的兩行都會過
        （saerylium vs essentlum 整行 ≈0.86）→ 真新增行被誤當重讀。都是 found 行時改比
        「礦名部分」（單人作業玩家名恆同，鑑別力全在礦名）；任一方不是 found 行
        （行讀歪到關鍵字都沒了）才退回整行比對。
        """
        po = _found_ore(prev_line, found_keywords)
        no = _found_ore(new_line, found_keywords)
        if po is not None and no is not None:
            return po == no or SequenceMatcher(None, po, no).ratio() >= FUZZY_STALE_LINE_RATIO
        return _lines_alike(_normalize(prev_line), _normalize(new_line))

    def __init__(self, baseline_texts):
        self._last = list(baseline_texts)      # 各 pass 的錨點鏈（最後一次成功對齊的讀取）
        self.new_lines: list = []              # 累積新增行（各 pass 聯集、保序去重）——診斷/通知用
        self.rare_lines: list = []             # 其中確認為稀有 found 的行

    @property
    def confirmed(self) -> bool:
        return bool(self.rare_lines)

    def update(self, after_texts, common_names, found_keywords, rare_names=()) -> list:
        """逐 pass 對齊上次讀取、把新增行累積進帳本；回傳本次新確認的稀有行。

        保守規則（寧漏勿假陽性，漏的交給長程信號兜底）：
        - 錨點對不到（大幅捲動/該 pass 整段讀歪）→ 該 pass 本次不追加、錨點不推進
          （留住上次好的錨點，下次讀取正常時仍可對齊）。
        - 上次讀取為空（聊天淡出/基準時無字）→ 新訊息會讓「舊行連同新行」重顯示，
          無從分辨 → 只推進錨點起鏈、不計新增（舊稀有行重顯示不可假陽性）。
        - 噪音守門：tail 行 ≈ 上次已有的行（FUZZY_STALE_LINE_RATIO）＝錨點誤差的重讀、
          非新增（一般礦重讀讀歪礦名會翻成稀有＝假陽性）。代價是同名稀有連續兩筆
          帳本不收——該情境 count 差分本來就抓得住（1→2），不漏。
        """
        common = [_normalize(c) for c in common_names]
        common_pairs = _name_pairs(common_names) if rare_names else None
        rare_pairs = _name_pairs(rare_names) if rare_names else None
        seen = {_normalize(l) for l in self.new_lines}
        rare_seen = {_normalize(l) for l in self.rare_lines}
        confirmed_now: list = []
        for i, after in enumerate(after_texts):
            if i >= len(self._last):
                break                          # 防禦：pass 數不該變（引擎切換只在 init 時）
            prev = self._last[i]
            if not _chat_lines(prev):
                if _chat_lines(after):
                    self._last[i] = after      # 起鏈：重顯示的舊行不計，之後的增量才算
                continue
            anchored, tail = _align_tail(prev, after)
            if not anchored:
                continue
            prev_lines = _chat_lines(prev)
            for line in tail:
                n = _normalize(line)
                if any(self._same_entity_line(p, line, found_keywords)
                       for p in prev_lines):
                    continue                   # 噪音守門（見 docstring）
                if n not in seen:
                    seen.add(n)
                    self.new_lines.append(line.strip())
                is_rare = _is_rare_ore(_found_ore(line, found_keywords), common)
                if not is_rare and rare_pairs:
                    # H020 模糊兜底：found-ish token＋礦名≈白名單且贏過排除清單
                    d = _fuzzy_rare_line(line, common_pairs, rare_pairs)
                    is_rare = bool(d and d["accepted"])
                if is_rare and n not in rare_seen:
                    rare_seen.add(n)
                    self.rare_lines.append(line.strip())
                    confirmed_now.append(line.strip())
            self._last[i] = after
        return confirmed_now


def any_new_special_found(before_texts, after_texts, common_names,
                          found_keywords, variant_keywords) -> bool:
    """逐 pass 差分 special found 行數，任一 pass 增加 → True（特殊階採集確認）。"""
    return any(
        count_special_found(a, common_names, found_keywords, variant_keywords)
        > count_special_found(b, common_names, found_keywords, variant_keywords)
        for b, a in zip(before_texts, after_texts)
    )


def extract_new_found_lines_multi(before_texts, after_texts, found_keywords) -> list:
    """各 pass 抽新增 found 行後取聯集（正規化去重、保序）——給 Discord 通知看實際採到什麼。"""
    seen: set = set()
    out: list = []
    for b, a in zip(before_texts, after_texts):
        for line in extract_new_found_lines(b, a, found_keywords):
            key = _normalize(line)
            if key not in seen:
                seen.add(key)
                out.append(line)
    return out


def extract_new_found_lines(before: str, after: str, found_keywords) -> list:
    """D3 前後比對，回傳 after 多出來的「has found / found a」行（原文，未正規化）。

    給 Discord 通知「實際採到什麼」用：rare_before/after 只給數字，使用者看不出是哪顆；
    這裡直接抓出新增的整行聊天（含 礦名），方便人工確認採集結果。

    處理 chat 捲動：用集合差集（after 有、before 沒有的行）而非計數差——
    舊訊息從頂部刷掉不影響這裡（只看「after 才出現」的行）。
    只回 found 行（避免夾帶無關新聊天訊息），按 after 出現順序排列。
    """
    before_set = {_normalize(l) for l in before.splitlines() if l.strip()}
    new_lines = []
    for line in after.splitlines():
        s = line.strip()
        if not s or _normalize(s) in before_set:
            continue
        if any(_normalize(kw) in _normalize(s) for kw in found_keywords):
            new_lines.append(s)
    return new_lines


# ── OCR 引擎：tesserocr（持久 in-process API）優先，pytesseract 為後備 ──────────────
# pytesseract 每次 image_to_string 都 spawn 一個 tesseract.exe 子行程 + 重載語言模型：
# 實測連「20x120 空白圖」都要 ~2.5s（與圖無關的固定開銷）。這 OCR 在 MINING 每 2s 跑一次
# （_check_reset），會卡住主迴圈 ~2.5s → boost 偵測 2.5s 才跑一次 → 「boost 常常是空的」。
# tesserocr 是 Tesseract C++ API 的 Cython 綁定，引擎/模型持久留在行程內（免重複 spawn+載模型）：
# 同一顆 Tesseract → 準度不變（採集 has-found 讀取邏輯不受影響），實測 banner OCR 3062ms→446ms（7x）。
# PyTessBaseAPI 非執行緒安全 → 比照 capture 的 mss，用 threading.local 每執行緒各持一個持久 API。
PREFER_TESSEROCR = True          # 想強制退回 pytesseract（A/B 或除錯）時設 False
_tess_local = threading.local()
_tesserocr_unavailable = False   # import/init 失敗一次即全程退回 pytesseract（不再每次重試拋例外）


def _tessdata_dir(tesseract_path: str | None) -> str | None:
    """由 tesseract.exe 路徑推得 tessdata（語言模型）目錄——tesserocr 需要它。"""
    if not tesseract_path:
        return None
    d = os.path.join(os.path.dirname(tesseract_path), "tessdata")
    return d if os.path.isdir(d) else None


def _get_tess_api(tesseract_path: str | None):
    """回本執行緒的持久 tesserocr API；不可用（未裝/初始化失敗/被停用）時回 None → 退回 pytesseract。"""
    global _tesserocr_unavailable
    if not PREFER_TESSEROCR or _tesserocr_unavailable:
        return None
    api = getattr(_tess_local, "api", None)
    if api is not None:
        return api
    try:
        import tesserocr
        kw = {}
        d = _tessdata_dir(tesseract_path)
        if d:
            kw["path"] = d          # 指向系統 tessdata（wheel 自帶 libtesseract，但用系統語言模型）
        api = tesserocr.PyTessBaseAPI(**kw)
    except Exception:
        _tesserocr_unavailable = True   # 一次失敗即全程退回，行為與舊版 pytesseract 完全一致
        return None
    _tess_local.api = api
    return api


_DARK_MASK_V_THRESHOLD = 120   # HSV V 低於此視為「文字深色外框」；背景亮（如粉紅礦壁）時分得開


def _preprocess(image_bgr: np.ndarray, preprocess: str) -> np.ndarray:
    """OCR 前處理：BGR → 單通道灰階圖。各模式適用背景見 read_text docstring。"""
    import cv2
    if preprocess == "min_channel":
        return np.min(image_bgr, axis=2).astype(np.uint8)
    if preprocess == "dark_mask":
        v = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)[:, :, 2]
        return np.where(v < _DARK_MASK_V_THRESHOLD, 0, 255).astype(np.uint8)
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)


def read_text(image_bgr: np.ndarray, tesseract_path: str | None = None,
              preprocess: str = "gray", psm: int = 6) -> str:
    """薄封裝：對已裁切的區域影像做 OCR（tesserocr 優先，pytesseract 後備；兩者同引擎、同準度）。

    preprocess='gray'        ：標準灰階（適合白字/灰字）
    preprocess='min_channel' ：最小通道（適合紅色/彩色文字，如遊戲聊天框）
                               紅字 min(R,G,B) 低→深色；白底 min=255→亮色，對比好。
    preprocess='dark_mask'   ：暗色遮罩（適合**亮背景**上的任意色文字，如亮粉糖果礦壁）
                               聊天字不論填色都有深色外框→V<門檻視為字；近全黑背景會失效
                               （整片都「暗」分不開）→ 不可單用，走 read_text_multi 融合。
    psm：Tesseract page segmentation mode。預設 6（假設單一均勻文字區塊）——本函式只
         收「裁切過的 UI 區域」（聊天框/事件列/重置訊息），都是單欄文字塊，psm 6 最準；
         舊版用隱含預設 psm 3（全頁自動版面分析）會把多行聊天拆錯→「has found」被黏成
         「hasifoumd」→ count_rare_found=0 → 採集 verify 永遠 no-new → 假性 NEEDS_HUMAN
         （H005@23:10 根因；psm 6 實測可正確讀出 has found 礦名）。
    """
    processed = _preprocess(image_bgr, preprocess)
    api = _get_tess_api(tesseract_path)
    if api is not None:
        try:
            from PIL import Image
            api.SetPageSegMode(psm)                 # 接受原始 int（實測 OK）
            api.SetImage(Image.fromarray(processed))
            return api.GetUTF8Text()
        except Exception:
            pass                                    # 執行期失敗 → 這次退回 pytesseract（不停用，可能只是暫時）
    import pytesseract
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    return pytesseract.image_to_string(processed, config=f"--psm {psm}")


# ---------- RapidOCR 聊天引擎（2026-07-04 起首選；tesseract 三 pass 融合為後備） ----------
# 動機：Tesseract 是文件掃描引擎，對彩色遊戲背景上的抗鋸齒 UI 文字天生弱——H014（亮粉背景
# 彩色行全滅）、H020（has found 讀成 hee foumel）兩次「真採到卻誤交人工」都源於此，專案為它
# 堆了三前處理融合＋fuzzy 兜底＋final-check 多層補丁。RapidOCR（PaddleOCR 模型轉 ONNX，
# 深度學習偵測+辨識）對這類文字拼字精準（benchmark：H020 精確匹配直接過、Saerylium 全對），
# 從源頭消滅「關鍵字讀歪」假陰性；速度與三 pass 打平（滿版 ~3s、空圖 ~0.3s，實機 fixtures）。
# 只用於聊天 verify（read_text_multi）；banner/事件列等小圖仍走 tesserocr（夠快夠準、不動）。
PREFER_RAPIDOCR = True           # 強制退回 tesseract 融合（A/B 或除錯）時設 False
# Det.limit_type=max：偵測不把短邊放大到 736（460x280 聊天裁圖被放大 2.6x 是預設慢 3 倍的主因）
_RAPIDOCR_PARAMS = {"Det.limit_type": "max", "Det.limit_side_len": 960.0}
_rapid_lock = threading.Lock()
_rapid_engine = None
_rapidocr_unavailable = False    # import/init 失敗一次即全程退回 tesseract 融合


def _get_rapid_engine():
    """回程序共用的 RapidOCR 引擎；不可用（未裝/init 失敗/被停用）時回 None → 退回 tesseract。

    首次呼叫載模型（實機 6~7s，常駐後免費；勿信 benchmark 機的 ~2.5s）——故 main 啟動時
    用背景執行緒預熱，別讓 init 落在第一次採集的基準 OCR 前。onnxruntime session
    執行緒安全，單例即可（聊天 OCR 只在主迴圈 verify 路徑呼叫）。
    """
    global _rapid_engine, _rapidocr_unavailable
    if not PREFER_RAPIDOCR or _rapidocr_unavailable:
        return None
    if _rapid_engine is not None:
        return _rapid_engine
    with _rapid_lock:
        if _rapid_engine is None and not _rapidocr_unavailable:
            # init 成敗記主敘事 log（miningbot.log）——裁決時第一個問題是「這場用的是哪個引擎」
            log = logging.getLogger("miningbot")
            try:
                t0 = time.perf_counter()
                from rapidocr import RapidOCR
                _rapid_engine = RapidOCR(params=dict(_RAPIDOCR_PARAMS))
                log.info("聊天 OCR 引擎＝RapidOCR（init %.1fs，常駐）",
                         time.perf_counter() - t0)
            except Exception as e:
                _rapidocr_unavailable = True
                log.warning("RapidOCR 初始化失敗→聊天 OCR 退回 tesseract 三前處理融合：%r", e)
                return None
    return _rapid_engine


def rapidocr_available() -> bool:
    return _get_rapid_engine() is not None


_rapid_last_diag = None          # 最近一次 rapid 呼叫的逐行分數/耗時（pop 即清）


def _read_text_rapid(image_bgr: np.ndarray) -> str:
    """RapidOCR 讀整張裁圖，回傳按偵測順序以換行接起的全文（與聊天行差分邏輯相容）。

    順手把逐行信心分數與耗時存進 _rapid_last_diag（pop_rapid_diagnostics 取用）——
    裁決引擎好壞的素材：讀歪的行分數通常偏低，log 收集後可回頭調門檻/換模型。
    """
    global _rapid_last_diag
    t0 = time.perf_counter()
    out = _get_rapid_engine()(image_bgr, use_cls=False)   # use_cls=False：遊戲字不旋轉
    txts = list(out.txts) if out.txts else []
    scores = list(out.scores) if out.scores else [0.0] * len(txts)
    _rapid_last_diag = {"lines": list(zip(txts, scores)),
                        "elapse": time.perf_counter() - t0}
    return "\n".join(txts)


def pop_rapid_diagnostics():
    """取回最近一次 rapid 呼叫的 {'lines': [(text, score)...], 'elapse': s}，取後即清。

    None＝上次聊天 OCR 不是走 rapid（tesseract 後備路徑不產生診斷、也不殘留舊的）。
    """
    global _rapid_last_diag
    d, _rapid_last_diag = _rapid_last_diag, None
    return d


RAPID_LOW_CONF_THRESHOLD = 0.80   # found 行低於此信心→WARNING（初始經驗值；乾淨文字實測 >0.9）


def low_confidence_found_lines(lines, found_keywords,
                               threshold: float = RAPID_LOW_CONF_THRESHOLD) -> list:
    """從 (text, score) 行列表挑出「是 found 行且信心低於門檻」者——疑似讀歪的裁決素材。"""
    return [(t, s) for t, s in lines
            if s < threshold and contains_any(t, found_keywords)]


def pass_labels(texts) -> list:
    """log 標籤：read_text_multi 輸出對應的引擎/前處理名（rapid 單 pass vs tess 三 pass）。"""
    if len(texts) == len(CHAT_PREPROCESSES):
        return list(CHAT_PREPROCESSES)
    return ["rapidocr"] * len(texts)


def read_text_multi(image_bgr: np.ndarray, tesseract_path: str | None = None,
                    preprocesses=CHAT_PREPROCESSES, psm: int = 6,
                    engine: str | None = None) -> list:
    """聊天框 OCR：回傳文字 list，搭配 any_new_rare_found / extract_new_found_lines_multi
    做逐 pass 自洽差分（差分邏輯對 list 長度無假設，1 或 3 個 pass 都能跑）。

    engine=None       ：自動——rapidocr 可用走它（單元素 list），否則 tesseract 三 pass 融合
    engine="rapidocr" ：強制 RapidOCR（不可用時 RuntimeError；測試用）
    engine="tesseract"：強制三前處理融合（後備路徑回歸測試用）
    注意：同一輪 verify 的 before/after 必須同引擎（差分逐 pass 對應）——引擎在首次
    init 後即固定，執行期不會中途切換；rapid 單次呼叫失敗直接拋出（不靜默混用引擎）。
    """
    if engine == "rapidocr":
        if _get_rapid_engine() is None:
            raise RuntimeError("rapidocr 引擎不可用")
        return [_read_text_rapid(image_bgr)]
    if engine is None and _get_rapid_engine() is not None:
        return [_read_text_rapid(image_bgr)]
    return [read_text(image_bgr, tesseract_path, preprocess=p, psm=psm)
            for p in preprocesses]
