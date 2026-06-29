import re
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

def _is_rare_ore(ore: str | None, common_norm) -> bool:
    """礦名非空、且不屬於任何「低稀有度礦」（排除清單）→ 視為稀有礦。

    用 startswith 容忍 OCR 在一般礦名尾端多出的雜訊（如 "bandeau!"）→ 仍判為 common，
    偏保守（寧可把可疑的當 common 漏掉，也不要把一般礦誤當稀有礦造成假成功）。
    """
    if not ore:
        return False
    return not any(ore.startswith(c) for c in common_norm)

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


def read_text(image_bgr: np.ndarray, tesseract_path: str | None = None,
              preprocess: str = "gray") -> str:
    """薄封裝：對已裁切的區域影像做 OCR。

    preprocess='gray'        ：標準灰階（適合白字/灰字）
    preprocess='min_channel' ：最小通道（適合紅色/彩色文字，如遊戲聊天框）
                               紅字 min(R,G,B) 低→深色；白底 min=255→亮色，對比好。
    """
    import pytesseract
    import cv2
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    if preprocess == "min_channel":
        processed = np.min(image_bgr, axis=2).astype(np.uint8)
    else:
        processed = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return pytesseract.image_to_string(processed)
