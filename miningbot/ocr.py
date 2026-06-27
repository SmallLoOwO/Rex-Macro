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
