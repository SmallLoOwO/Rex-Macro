import re
import numpy as np

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()

def contains_phrase(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)

def contains_any(text: str, phrases) -> bool:
    n = _normalize(text)
    return any(_normalize(p) in n for p in phrases)

def read_text(image_bgr: np.ndarray, tesseract_path: str | None = None) -> str:
    """薄封裝：對已裁切的區域影像做 OCR。整合測試覆蓋。"""
    import pytesseract
    import cv2
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return pytesseract.image_to_string(gray)
