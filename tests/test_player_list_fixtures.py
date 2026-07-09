"""右上角玩家列表開/關偵測回歸測試：鎖住「開啟時 OCR 讀得到 Players/Blocks Mined、關閉時不會誤判」。

Tab 是 toggle，沒開時按 Tab 反而打開 → 只有確實偵測到列表才可以按 Tab。
故偵測引擎必須可靠：實測 RapidOCR（read_text_boxes）三張 fixture 全部正確，
tesseract（read_text）漏 open.png／2x 放大漏 open2.png（單一前處理必有背景盲區，
見 CLAUDE.md H014 精神）→ 本測試只用 RapidOCR。

fixtures 取自 2026-07-09 實機 client-area 截圖（1920×1051）裁 x 1490..1915、y 100..235：
- open.png / open2.png：列表開啟（兩種不同背景：亮粉礦壁、綠色礦壁），標題列 Players/Blocks Mined
- closed.png：列表未開啟（同區域只有礦壁雜訊），OCR 讀空

需要 RapidOCR（同 production 引擎）；未裝時整檔 skip，不擋純邏輯 CI。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import ocr  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "player_list")

pytestmark = pytest.mark.skipif(not ocr.rapidocr_available(), reason="rapidocr 引擎不可用")


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def test_open_player_list_detected():
    recs = ocr.read_text_boxes(_load("open.png"))
    joined = " ".join(r["text"] for r in recs)
    assert ocr.contains_any(joined, cfg.player_list_phrases) is True


def test_open2_player_list_detected():
    recs = ocr.read_text_boxes(_load("open2.png"))
    joined = " ".join(r["text"] for r in recs)
    assert ocr.contains_any(joined, cfg.player_list_phrases) is True


def test_closed_player_list_not_falsely_detected():
    recs = ocr.read_text_boxes(_load("closed.png"))
    joined = " ".join(r["text"] for r in recs)
    assert ocr.contains_any(joined, cfg.player_list_phrases) is False
