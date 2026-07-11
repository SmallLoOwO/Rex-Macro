"""Capacity OCR 回歸測試：對「實機 Capacity: NNN% 裁圖」跑真實 tesseract，鎖住讀值。

重置偵測的第二信號（2026-07-11 設計）：頂部常駐「Capacity: NNN%」列，bot 挖礦累積
到 100% 觸發重置。本檔對 4 張實機裁圖（Region(715,92,200,45)）跑 read_text →
parse_capacity_pct，斷言 14/100/101/101。

fixtures 由 Claude 用真實引擎驗證讀值後裁好。尾端 | / [ 是 pill 分隔線雜訊，
parse_capacity_pct 必須容忍。比照 test_ocr_fixtures.py 慣例：引擎不可用時整檔 skip。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import ocr  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "capacity")


def _engine_ready() -> bool:
    try:
        ocr.read_text(np.zeros((20, 120, 3), dtype=np.uint8), cfg.tesseract_path)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _engine_ready(), reason="tesseract 引擎不可用")


def _load(name: str):
    # cv2.imread 在 Windows 吃不了非 ASCII 路徑（專案資料夾是中文名）→ fromfile+imdecode
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def test_capacity_14pct():
    text = ocr.read_text(_load("capacity_14pct.png"), cfg.tesseract_path)
    assert ocr.parse_capacity_pct(text) == 14.0


def test_capacity_100pct():
    text = ocr.read_text(_load("capacity_100pct.png"), cfg.tesseract_path)
    assert ocr.parse_capacity_pct(text) == 100.0


def test_capacity_101pct_a():
    text = ocr.read_text(_load("capacity_101pct_a.png"), cfg.tesseract_path)
    assert ocr.parse_capacity_pct(text) == 101.0


def test_capacity_101pct_b():
    text = ocr.read_text(_load("capacity_101pct_b.png"), cfg.tesseract_path)
    assert ocr.parse_capacity_pct(text) == 101.0
