import re
import os
import threading
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


def _strip_variant(ore: str) -> str:
    """剝掉礦名開頭的變體前綴（已正規化小寫）："spectral bandeau" → "bandeau"。"""
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


# ── 多前處理融合（H014 假陰性根因的對策）─────────────────────────────────
# 單一前處理必有背景盲區：min_channel 為暗背景紅字校準、在亮粉糖果礦區彩色行全滅
# （2026-07-03 H014：真正採到的底部新行 has found Diamorite 沒讀到→誤交人工）；
# dark_mask 靠「文字深色外框 vs 亮背景」、在近全黑礦坑反而分不開字與背景。
# 故 verify 對聊天框跑多種前處理，**各 pass 內部自洽比 before/after**（不同 pass 的
# OCR 噪音不同，交叉比會偽造 diff），任一 pass 有信號即 confirmed。
# 實測（tests/fixtures/chat 回歸集）：三種 pass 在暗棕混合背景各救回不同行、聯集嚴格更優。
CHAT_PREPROCESSES = ("min_channel", "gray", "dark_mask")

def any_new_rare_found(before_texts, after_texts, common_names, found_keywords) -> bool:
    """逐 pass 差分（count 增加或底部新稀有行），任一 pass 確認即 True。

    before_texts/after_texts 依 CHAT_PREPROCESSES 順序一一對應（read_text_multi 的輸出）。
    """
    return any(
        has_new_rare_found(b, a, common_names, found_keywords)
        or has_new_rare_found_last_line(b, a, common_names, found_keywords)
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


def read_text_multi(image_bgr: np.ndarray, tesseract_path: str | None = None,
                    preprocesses=CHAT_PREPROCESSES, psm: int = 6) -> list:
    """同一張圖跑多種前處理各 OCR 一次，回傳文字 list（與 preprocesses 順序對應）。

    聊天框 verify 專用：搭配 any_new_rare_found / extract_new_found_lines_multi 做
    逐 pass 自洽差分。tesserocr 下每 pass ~0.4s，只在 D3 前後各跑一次、非每幀。
    """
    return [read_text(image_bgr, tesseract_path, preprocess=p, psm=psm)
            for p in preprocesses]
