"""聊天框開/關偵測回歸測試：鎖住「展開時 OCR 讀得到輸入列提示、收合時不會誤判」。

fixtures 取自 2026-07-08 實機截圖裁 cfg.chat_input_region：
- open.png：聊天框展開狀態（「To chat click here or press / key」輸入列）
- closed.png：預設收合狀態（該區域只剩背包面板一角，OCR 讀到雜訊，不得誤判為開啟）

需要本機 tesseract（同 production 引擎）；未裝時整檔 skip，不擋純邏輯 CI。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import ocr  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "chat_ui")


def _engine_ready() -> bool:
    try:
        ocr.read_text(np.zeros((20, 120, 3), dtype=np.uint8), cfg.tesseract_path)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _engine_ready(), reason="tesseract 引擎不可用")


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def test_open_chat_detected():
    text = ocr.read_text(_load("open.png"), cfg.tesseract_path)
    assert ocr.contains_any(text, cfg.chat_input_phrases) is True


def test_closed_chat_not_falsely_detected():
    text = ocr.read_text(_load("closed.png"), cfg.tesseract_path)
    assert ocr.contains_any(text, cfg.chat_input_phrases) is False
