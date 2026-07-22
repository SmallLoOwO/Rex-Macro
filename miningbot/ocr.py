import re
import os
import logging
import threading
import time
import numpy as np

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()

def _dehyphenate_if_unmatched(line_norm: str, keywords) -> str:
    """H041（2026-07-11）：RapidOCR 偶爾把整行空格讀成連字號
    （「small_lo has found X」→「small-lo-has-found-X」，整行變單一 token）。

    精確子字串比對全滅、且行內含 ``-`` 時，把 ``-`` 換空格再比一次。
    不改變既有可讀行的行為（已對到或無 ``-`` → 原樣回）。
    對稱應用於「行」側；「排除清單/白名單」側的對稱正規化在 _is_rare_ore 做。
    """
    if "-" not in line_norm:
        return line_norm
    if any(_normalize(k) in line_norm for k in keywords):
        return line_norm
    return line_norm.replace("-", " ")

def contains_phrase(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)

def contains_any(text: str, phrases) -> bool:
    n = _normalize(text)
    return any(_normalize(p) in n for p in phrases)

# ── Capacity 解析（2026-07-11 重置偵測第二信號）─────────────────────────────
# 頂部常駐「Capacity: NNN%」列：bot 挖礦累積、到 100% 觸發重置。OCR 尾端會帶 pill
# 分隔線雜訊（|/`[）。優先抓 Capacity label 後的數字；label 被讀歪時退而求整串第一個 NNN%。
# sanity range 0-150：超出（如把 Depth/$ 誤讀成 pct）回 None，防假觸發重置。
_CAPACITY_RE = re.compile(r"capacity.*?(-?\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
_PCT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")


def parse_capacity_pct(text: str) -> float | None:
    """從頂部列文字抽出 Capacity 百分比；找不到或超出 sanity range(0-150) 回 None。"""
    m = _CAPACITY_RE.search(text)
    if m is None:
        m = _PCT_RE.search(text)          # label 讀歪 → 退而求整串第一個 NNN%
    if m is None:
        return None
    v = float(m.group(1))
    if v < 0 or v > 150:
        return None
    return v

_DEPTH_SURFACE_RE = re.compile(r"depth\W*surface", re.IGNORECASE)
_DEPTH_METERS_RE = re.compile(r"depth\W*([\d,]+)\s*m", re.IGNORECASE)


def parse_depth_surface(text: str) -> bool | None:
    """從頂部列文字判斷人是否在地表（H046 開場狀態錨）。

    True＝讀到 "Depth: Surface"；False＝讀到 "Depth: NNNm"（礦內/墜落中）；
    None＝完全沒有 depth 資訊（OCR 失敗/區域被蓋）。尾端 "$..." 金額雜訊
    （實機裁圖固定拖尾）不影響前綴比對。
    """
    if not text:
        return None
    if _DEPTH_SURFACE_RE.search(text):
        return True
    if _DEPTH_METERS_RE.search(text):
        return False
    return None


def read_depth_is_surface(image_bgr, tesseract_path=None):
    """讀頂部 Depth 固定列（比照 read_capacity_pct）：回 True/False/None。"""
    text = read_text_line(
        image_bgr,
        tesseract_path,
        psm=7,
        validator=lambda value: parse_depth_surface(value) is not None,
    )
    return parse_depth_surface(text)


# 深度數值 sanity 上限：只擋 OCR 明顯讀歪（例如把尾端金額 "$108,537" 當成深度），
# **不擋合法的深層與墜落值**。最深層底是 9999m，但虛空墜落會一路累加（H043 實測
# 25790m，fixtures/reentry/h046_depth_25790m.png）→ 上限必須遠高於層表。
_DEPTH_METERS_MAX = 1_000_000


def parse_depth_meters(text: str) -> int | None:
    """從頂部列文字抽出 Depth 公尺數；地表／讀不到／超出 sanity 上限回 None。

    刻意**不**檢查數值是否落在任何層的區間內——那是 `game_data.layer_for_depth`
    的職責。本函式只忠實回報畫面上的數字，虛空墜落的 25790m 也照回，否則
    H043 那條「深度異常」的診斷線索會在這裡被吃掉。
    """
    if not text:
        return None
    if _DEPTH_SURFACE_RE.search(text):     # "Depth: Surface" 沒有數值
        return None
    m = _DEPTH_METERS_RE.search(text)
    if m is None:
        return None
    value = int(m.group(1).replace(",", ""))
    return value if 0 <= value <= _DEPTH_METERS_MAX else None


def read_depth_meters(image_bgr, tesseract_path=None):
    """讀頂部 Depth 固定列的公尺數（比照 read_depth_is_surface）：回 int 或 None。"""
    text = read_text_line(
        image_bgr,
        tesseract_path,
        psm=7,
        validator=lambda value: parse_depth_meters(value) is not None,
    )
    return parse_depth_meters(text)


def count_found(text: str, phrases) -> int:
    """計 phrases 在 text 中出現的總次數（正規化後比對）。

    給採集「差分確認」用：D3 前後各讀一次聊天框，只有數量「增加」才算新採到，
    避免舊的 "has found" 訊息賴在框裡偽造成功（stale-chat false positive）。
    """
    n = _normalize(text)
    n = _dehyphenate_if_unmatched(n, phrases)  # H041：RapidOCR 黏行（空格→連字號）fallback
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
    after_last  = _dehyphenate_if_unmatched(after_last, phrases)  # H041：黏行 fallback
    if before_last == after_last:
        return False
    return any(_normalize(p) in after_last for p in phrases)


def _found_ore(line: str, found_keywords) -> str | None:
    """從一行聊天抽出「has found / found a」後面的礦名（正規化）；非 found 行回 None。

    例：「small_lo has found Lilaverine」→ "lilaverine"。

    H041（2026-07-11）：RapidOCR 偶爾把整行空格讀成連字號（整行單一 token），
    精確子字串全滅 → fallback 把 - 換空格再比（harvest 071 Fortuitous 黏行事故）。
    """
    n = _normalize(line)
    n = _dehyphenate_if_unmatched(n, found_keywords)
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

    H041（2026-07-11）：連字號對稱正規化——白名單含 Anti-Shadow/X-Flare/Sub-Zero 等
    連字號礦名；比對前把 base 與清單項的 - 都換空格。安全方向：連字號差異絕不可造成
    「一般礦被誤判稀有」（OCR 把 "Sub-Zero" 讀成 "Sub Zero" 時仍須被排除清單擋下）。
    """
    if not ore:
        return False
    base = _strip_variant(ore).replace("-", " ")
    return not any(base.startswith(c.replace("-", " ")) for c in common_norm)

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
    before_lines, after_lines = _chat_lines(before), _chat_lines(after)
    # 基準沒有任何聊天行（整窗淡出，剝掉常駐面板後為空）→ 無從歸因給這一發：
    # 舊行重新淡入時底行必然「新出現」，採信就是憑空的假成功（H054 同型，091 實錄
    # 底行剛好是稀有礦 Starstride）。舊版靠 "NORMAL"=="NORMAL" 意外擋住，H055 剝殼後
    # 這道破口會露出來 → 明確棄權。方向同 ChatLedger「上次讀取為空→不計新增」。
    if not before_lines or not after_lines:
        return False
    if _normalize(before_lines[-1]) == _normalize(after_lines[-1]):
        return False
    common = [_normalize(c) for c in common_names]
    return _is_rare_ore(_found_ore(after_lines[-1], found_keywords), common)


# ── 底部新增行對齊（2026-07-04 H032 假陰性對策）─────────────────────────────
# H032 實錄：D3 命中、聊天新增稀有行，但**同窗口又進來一行一般礦排在它後面**→底行信號滅；
# 同時頂部剛好刷掉一行舊稀有 → count 差分 3→3 也滅 → 假陰性誤交人工。
# 「新稀有行必在底部」的假設在多行同窗口抵達時不成立 → 改對齊 before 底行在 after 的
# 錨點位置，錨點之後**全部**都是新增行，任一行是稀有 found 行即確認。

# ── 常駐 UI 殘留行過濾（H055 對策，2026-07-20）─────────────────────────────
# chat_region 下緣蓋到左上礦物面板標頭，"NORMAL"（091 另有右側圖層面板 "Shamrock"）
# **每次 OCR 都被讀成最後一行** → 底行信號兩側恆等、_align_tail 錨點恆落在尾端、
# tail 恆空 → 兩個抗捲動信號與 ChatLedger 錨點鏈全部結構性失效（實機 082 真成功實錄：
# 新增的 Weevil／ionized Starstride 兩行都插在 "NORMAL" 上面，只剩計數差還活著）。
#
# 為何不改 chat_region（實機量測否決）：面板是**疊在聊天上**、不在聊天下方——082 裁圖
# 面板上緣 y=227 橫穿最新 has-found 行的字身（y=225..234，量在無面板的 x>=250 帶），
# 094 最新（淡出中）聊天行更落在 "NORMAL" 白字帶（y≈240..258）內 → 任何「停在面板上方」
# 的裁法都會切掉真聊天行（config.py 對 chat_review_region 的警告即此）。
#
# 兩側夾（6 份實機 trace dump 全部行）：UI 殘留恰好 **1 token**（NORMAL ×11、Shamrock ×2）
# vs 真 found 行 **≥3 token**（"has found X" 的結構下限；實測最短 4）。
# 安全性可證、不只經驗：found_keywords 皆為雙詞片語 → 任何 found 行必 ≥3 token →
# **1 token 行永遠不可能是 found 行**，剝它不可能剝掉成功信號。1 token 的真聊天行只有
# 折行碎片（'Weevil'/'hasfound'/'Reminiscence!'），本來就 _found_ore()→None、無貢獻。
# 只剝**尾端**、遇第一個非殘留行即停：中段折行碎片留著，_align_tail 的向上連續比對不受擾。
UI_RESIDUE_MAX_TOKENS = 1


def _token_count(line: str) -> int:
    """去黏後的 token 數：H041 型整行連字號黏連會讓真聊天行看似單 token，必須先拆。"""
    return len([t for t in re.split(r"[\s\-=]+", _normalize(line)) if t])


def _is_ui_residue(line: str) -> bool:
    return _token_count(line) <= UI_RESIDUE_MAX_TOKENS


def _strip_ui_residue(lines: list) -> list:
    """剝掉尾端常駐 UI 殘留行；遇到第一個像聊天的行即停。"""
    end = len(lines)
    while end > 0 and _is_ui_residue(lines[end - 1]):
        end -= 1
    return lines[:end]


def _chat_lines(text: str) -> list:
    return _strip_ui_residue([l.strip() for l in text.splitlines() if l.strip()])


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

def baseline_saw_found_history(before_texts, found_keywords) -> bool:
    """episode 基準 OCR 是否真的看到了聊天的 has-found 歷史（H054 對策，2026-07-20）。

    計數差信號（has_new_rare_found / any_new_special_found）的**前提**是「基準與 after
    看的是同一個聊天視圖」——只有這樣，數量增加才能歸因到我方這一發。Roblox 聊天無新
    訊息 ~15s 會整窗淡出隱藏，episode 進場凍結的基準裁圖若剛好落在那段，基準讀到 0 條
    has-found（只剩常駐礦物面板文字）；之後任何新訊息會讓**舊行連同新行**整段重新顯示
    → 計數差把開火前早就在聊天裡的舊採集行全當本次新增 → 假成功。

    這正是 ChatLedger 既有規則（見 ChatLedger.update「上次讀取為空 → 只推進錨點、不計
    新增」）的同一條原則，只是計數差沒有錨點、無從自我保護 → 由呼叫端先問這個問題。

    判準用「有沒有任何 has-found 行」而非「有沒有任何文字」：裁圖含左上礦物面板等常駐
    UI，聊天全隱藏時仍讀得到那些字（實機 094/093 = "NORMAL"、091 = "NORMAL"+"Shamrock"），
    「有文字」分不出聊天死活。實機五場兩側夾：**基準 has-found 行 0 條**（081/091/093/094，
    四場皆為淡出隱藏）vs **10 條**（082，真成功、計數差正確確認 rare 1→2）。

    逐 pass 取聯集（任一 pass 看到即算），因為單一前處理本來就可能有背景盲區（H014）；
    「所有 pass 都沒看到」才是聊天層級的隱藏。
    """
    return any(
        _found_ore(line, found_keywords) is not None
        for text in before_texts
        for line in text.splitlines()
    )


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
    tokens = _normalize(line).replace("-", " ").split()  # H041：黏行去 - 再切 token
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
    # 底行同樣要剝常駐 UI 殘留（H055：否則兩側恆為 "NORMAL"、這條路徑也恆不觸發），
    # 並同樣在「基準無聊天行」時棄權（見 has_new_rare_found_last_line 的說明）。
    before_lines_raw, after_lines_raw = _chat_lines(before), _chat_lines(after)
    if before_lines_raw and after_lines_raw:
        b = _normalize(before_lines_raw[-1])
        a = _normalize(after_lines_raw[-1])
        if a != b and SequenceMatcher(None, b, a).ratio() < FUZZY_STALE_LINE_RATIO:
            d = _fuzzy_rare_line(a, common_pairs, rare_pairs)
            if d and d["accepted"]:
                return True
    before_lines = [_normalize(l) for l in before_lines_raw]
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
        ns = _dehyphenate_if_unmatched(_normalize(s), found_keywords)  # H041：黏行 fallback
        if any(_normalize(kw) in ns for kw in found_keywords):
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


_DEFAULT_TESSDATA_DIRS = (
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
)


def _tessdata_dir(tesseract_path: str | None) -> str | None:
    """由 tesseract.exe 路徑推得 tessdata（語言模型）目錄——tesserocr 需要它。"""
    if not tesseract_path:
        return None
    d = os.path.join(os.path.dirname(tesseract_path), "tessdata")
    return d if os.path.isdir(d) else None


def _resolve_tessdata(tesseract_path: str | None) -> str | None:
    """盡力找出可用的 tessdata 目錄：tesseract.exe 旁 → TESSDATA_PREFIX → 已知預設安裝路徑。

    關鍵（2026-07-07）：`PyTessBaseAPI()` 不帶 path 時預設用 `./`，TESSDATA_PREFIX 未設時
    必 init 失敗（"invalid tessdata path: ./"）。而 read_text 的 tesseract_path 預設是 None
    → 任何漏傳 path 的呼叫都會踩到 → 舊版還把它 latch 成「tesserocr 全程不可用」（見
    _get_tess_api）→ 整支退回 pytesseract、boost 被餓死。故這裡即使沒給 path 也主動找出
    系統 tessdata，讓漏傳 path 的呼叫仍能用 tesserocr。"""
    d = _tessdata_dir(tesseract_path)
    if d:
        return d
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        if os.path.isdir(env):
            return env
        cand = os.path.join(env, "tessdata")
        if os.path.isdir(cand):
            return cand
    for cand in _DEFAULT_TESSDATA_DIRS:
        if os.path.isdir(cand):
            return cand
    return None


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
    except Exception:
        _tesserocr_unavailable = True   # 真的沒裝 → 永久退回 pytesseract（正確；import 失敗才 latch）
        return None
    d = _resolve_tessdata(tesseract_path)
    try:
        api = tesserocr.PyTessBaseAPI(path=d) if d else tesserocr.PyTessBaseAPI()
    except Exception:
        # ★ 不再對「init 失敗」永久 latch（2026-07-07 對策）：init 失敗多半是「這次沒給對
        #   tessdata path」而非 tesserocr 壞掉——舊版一次 pathless 呼叫就把 tesserocr 全程停用、
        #   之後連帶正確 path 的呼叫也回 None（實測：available() 無參數→latch→available(path) 也 False）。
        #   只有「找到了合法 tessdata 卻仍 init 失敗」＝安裝真的壞了，才永久退回避免每次拋例外。
        if d is not None:
            _tesserocr_unavailable = True
        return None
    _tess_local.api = api
    return api


def tesserocr_available(tesseract_path: str | None = None) -> bool:
    """主動探測 tesserocr 是否真的可用（鏡射 rapidocr_available 的模式）。

    `_tesserocr_unavailable` 原本是 lazy 旗標——只有真的跑過一次 read_text 且走到
    tesserocr 分支失敗，才會翻成 True；啟動 preflight 在任何 OCR 呼叫之前取樣，
    永遠讀到樂觀初值 False，即使 tesserocr 根本沒裝也回報「可用」（H_preflight
    對策）。這裡呼叫與 read_text 相同的 `_get_tess_api`（同一個 init 路徑、同一顆
    thread-local 持久 API、同一面 `_tesserocr_unavailable` 旗標）做一次真實探測，
    冪等（已裝好只是回傳快取的 api、不重複 init；已判定不可用直接回 False，不重試）、
    絕不拋例外。不影響 read_text 既有的 fallback 行為。
    """
    try:
        return _get_tess_api(tesseract_path) is not None
    except Exception:
        return False


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


# ---------- RapidOCR 引擎（聊天全文＋固定 ROI 單行快速路徑） ----------
# 動機：Tesseract 是文件掃描引擎，對彩色遊戲背景上的抗鋸齒 UI 文字天生弱——H014（亮粉背景
# 彩色行全滅）、H020（has found 讀成 hee foumel）兩次「真採到卻誤交人工」都源於此，專案為它
# 堆了三前處理融合＋fuzzy 兜底＋final-check 多層補丁。RapidOCR（PaddleOCR 模型轉 ONNX，
# 深度學習偵測+辨識）對這類文字拼字精準（benchmark：H020 精確匹配直接過、Saerylium 全對），
# 從源頭消滅「關鍵字讀歪」假陰性；速度與三 pass 打平（滿版 ~3s、空圖 ~0.3s，實機 fixtures）。
# 聊天 verify 用完整偵測；固定 ROI 單行可略過 det/cls，失敗或驗證不通過時回退 tesseract。
PREFER_RAPIDOCR = True           # 強制退回 tesseract 融合（A/B 或除錯）時設 False
# Det.limit_type=max：偵測不把短邊放大到 736（460x280 聊天裁圖被放大 2.6x 是預設慢 3 倍的主因）
_RAPIDOCR_PARAMS = {"Det.limit_type": "max", "Det.limit_side_len": 960.0}
_rapid_lock = threading.Lock()
_rapid_infer_lock = threading.Lock()
_rapid_engine = None
_rapidocr_unavailable = False    # import/init 失敗一次即全程退回 tesseract 融合


def _get_rapid_engine():
    """回程序共用的 RapidOCR 引擎；不可用（未裝/init 失敗/被停用）時回 None → 退回 tesseract。

    首次呼叫載模型（實機 6~7s，常駐後免費；勿信 benchmark 機的 ~2.5s）——故 main 啟動時
    用背景執行緒預熱，別讓 init 落在第一次採集的基準 OCR 前。onnxruntime session
    模型單例常駐；RapidOCR 的呼叫參數會寫回引擎狀態，因此所有推論另以鎖序列化。
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
                log.info("RapidOCR 引擎初始化完成（init %.1fs，常駐）",
                         time.perf_counter() - t0)
            except Exception as e:
                _rapidocr_unavailable = True
                log.warning("RapidOCR 初始化失敗→OCR 退回 tesseract：%r", e)
                return None
    return _rapid_engine


def rapidocr_available() -> bool:
    return _get_rapid_engine() is not None


def _run_rapid(image_bgr: np.ndarray, *, use_det: bool):
    """以完整、明確的模式呼叫共用引擎，避免 recognition-only 狀態污染下一次推論。"""
    engine = _get_rapid_engine()
    if engine is None:
        raise RuntimeError("rapidocr 引擎不可用")
    with _rapid_infer_lock:
        return engine(
            image_bgr,
            use_det=use_det,
            use_cls=False,
            use_rec=True,
        )


_rapid_last_diag = None          # 最近一次 rapid 呼叫的逐行分數/耗時（pop 即清）


def _read_text_rapid(image_bgr: np.ndarray) -> str:
    """RapidOCR 讀整張裁圖，回傳按偵測順序以換行接起的全文（與聊天行差分邏輯相容）。

    順手把逐行信心分數與耗時存進 _rapid_last_diag（pop_rapid_diagnostics 取用）——
    裁決引擎好壞的素材：讀歪的行分數通常偏低，log 收集後可回頭調門檻/換模型。
    """
    global _rapid_last_diag
    t0 = time.perf_counter()
    out = _run_rapid(image_bgr, use_det=True)
    txts = list(out.txts) if out.txts else []
    scores = list(out.scores) if out.scores else [0.0] * len(txts)
    _rapid_last_diag = {"lines": list(zip(txts, scores)),
                        "elapse": time.perf_counter() - t0}
    return "\n".join(txts)


def _read_text_rapid_line(image_bgr: np.ndarray) -> str:
    """固定單行 ROI 的 recognition-only OCR；不做文字框偵測與方向分類。"""
    out = _run_rapid(image_bgr, use_det=False)
    txts = getattr(out, "txts", None) or []
    if isinstance(txts, str):
        txts = [txts]
    return " ".join(str(text).strip() for text in txts if str(text).strip())


def read_text_line(image_bgr: np.ndarray, tesseract_path: str | None = None,
                   preprocess: str = "gray", psm: int = 7,
                   validator=None, engine: str | None = None) -> str:
    """讀固定單行 ROI；自動模式優先 RapidOCR recognition-only，必要時安全回退。

    validator 接收辨識文字並回 bool。RapidOCR 空字串、推論例外或 validator 拒絕時，
    自動模式改走既有 tesseract 路徑。engine="rapidocr" 用於 fixture/benchmark，
    不會偷偷混入另一引擎；engine="tesseract" 則強制既有路徑。
    """
    if engine not in (None, "rapidocr", "tesseract"):
        raise ValueError(f"未知 OCR 引擎：{engine}")
    if engine == "tesseract":
        return read_text(image_bgr, tesseract_path, preprocess=preprocess, psm=psm)
    if engine == "rapidocr":
        return _read_text_rapid_line(image_bgr)

    if _get_rapid_engine() is not None:
        try:
            text = _read_text_rapid_line(image_bgr)
            if text.strip() and (validator is None or validator(text)):
                return text
        except Exception as exc:
            logging.getLogger("miningbot").debug(
                "RapidOCR 單行快速路徑失敗，退回 tesseract：%r", exc)
    return read_text(image_bgr, tesseract_path, preprocess=preprocess, psm=psm)


def read_capacity_pct(image_bgr: np.ndarray, tesseract_path: str | None = None):
    """讀 Capacity 固定列；RapidOCR 結果必須可解析，否則以 tesseract 複核。"""
    text = read_text_line(
        image_bgr,
        tesseract_path,
        psm=7,
        validator=lambda value: parse_capacity_pct(value) is not None,
    )
    return parse_capacity_pct(text)


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


def parse_rapid_boxes(boxes, txts, scores) -> list:
    """RapidOCR 輸出三陣列 → [{'text','score','center'}]（純函式，可單測）。

    center＝四點多邊形頂點平均（int）。給 reentry.pick_layer_button 挑層級按鈕用：
    文字框中心＝可直接點擊的螢幕座標（再加 region 偏移）。
    """
    boxes = list(boxes) if boxes is not None else []
    txts = list(txts) if txts else []
    scores = list(scores) if scores else [0.0] * len(txts)
    recs = []
    for b, t, s in zip(boxes, txts, scores):
        xs = [int(p[0]) for p in b]
        ys = [int(p[1]) for p in b]
        recs.append({"text": t, "score": float(s),
                     "center": (sum(xs) // len(xs), sum(ys) // len(ys))})
    return recs


def read_text_boxes(image_bgr: np.ndarray, region_offset=(0, 0)) -> list:
    """OCR 並回每行文字的框中心（螢幕座標＝crop 座標＋region_offset）。

    只有 rapidocr 路徑有框資訊；不可用回 []——呼叫端（reentry）據此走
    遮擋階梯/reroll，不做 tesseract 後備（無框＝無從點擊，硬湊必亂點）。
    """
    if _get_rapid_engine() is None:
        return []
    out = _run_rapid(image_bgr, use_det=True)
    recs = parse_rapid_boxes(out.boxes, out.txts, out.scores)
    ox, oy = region_offset
    for r in recs:
        r["center"] = (r["center"][0] + ox, r["center"][1] + oy)
    return recs
