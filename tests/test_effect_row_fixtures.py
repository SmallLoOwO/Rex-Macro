"""效果列徽章格定位＋D2 掃描確認的實機 fixture 回歸（2026-07-25 校準）。

fixture 是 6 個真實遊戲畫面的 `cfg.scan_confirm_region` 裁圖（右下角效果列整條）：
    local_only              D2 左鍵後，只有 Local 徽章（x=1676）  → 掃描成功
    local_and_caveskim      左鍵＋Z，Local 1676、Cave Skim 1612    → 掃描成功
    local_displaced_3slots  Z→D5→左鍵，Local 被推到 1548          → 掃描成功
    caveskim_only           只按了 Z（同樣是雷達徽章）             → **不可**判成成功
    d4_used_only            只有 D4 的 Used 徽章                   → 不成功
    no_effects              效果列全空                             → 不成功

背景：舊的 scan_confirm_region 是左下估值，離線重放 22 幀 TP=0（讀到左側礦物面板文字）。
改成整條效果列後，因為徽章疊加會位移，必須逐格 OCR——固定單格與整條一次 OCR 都已實測失敗。
"""
import os

import cv2
import numpy as np
import pytest

from miningbot import harvester, ocr, vision
from miningbot.config import DEFAULT as cfg

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "effect_row")


def _engine_ready():
    try:
        return ocr.tesserocr_available(cfg.tesseract_path)
    except Exception:
        return False


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, f"{name}.png"), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


# --- 徽章格定位：純視覺，不需 OCR 引擎，永遠會跑 ---

@pytest.mark.parametrize("name,expected", [
    ("local_only", 1),
    ("local_and_caveskim", 2),
    ("local_displaced_3slots", 3),
    ("caveskim_only", 1),
    ("d4_used_only", 1),
    ("no_effects", 0),
])
def test_find_effect_slots_counts(name, expected):
    assert len(vision.find_effect_slots(_load(name))) == expected


def test_local_found_when_displaced_from_anchor():
    """回歸本體：Local 不在最右格時仍要找得到。

    fixture 是實機依序按 Z → D5 → 左鍵疊出來的三格（Cave Skim 佔最右 1676、
    boost 佔 1612、Local 被推到 1548）。舊的固定格作法會讀到最右格的 Cave Skim
    並判定掃描失敗——這正是這次修的東西。
    """
    band = _load("local_displaced_3slots")
    slots = vision.find_effect_slots(band)
    assert len(slots) == 3
    xs = [x for (x, _, _, _) in slots]
    assert xs == sorted(xs)
    # 格距 64：1548 / 1612 / 1676（band 從 x=1150 起算 → 398 / 462 / 526）
    assert xs[1] - xs[0] == pytest.approx(64, abs=6)
    assert xs[2] - xs[1] == pytest.approx(64, abs=6)
    # Local 落最左格，離最右格 128px——固定單格必漏
    assert xs[2] - xs[0] == pytest.approx(128, abs=10)


def test_slots_are_square_and_in_row():
    """每格都該是 ~58x58 的方形、落在同一列（y 對齊）。"""
    for (x, y, w, h) in vision.find_effect_slots(_load("local_and_caveskim")):
        assert 40 <= w <= 90 and 40 <= h <= 90
        assert abs(w - h) <= 18
        assert 10 <= y <= 40          # band y=940 起算，徽章列在 ~960


def test_stacking_shifts_position_not_identity():
    """疊加時新徽章插在左邊、既有的不位移——這正是不能釘死單格的原因。"""
    one = vision.find_effect_slots(_load("local_only"))
    two = vision.find_effect_slots(_load("local_and_caveskim"))
    assert len(one) == 1 and len(two) == 2
    assert two[1][0] == one[0][0]                 # 最右格位置不變
    assert two[0][0] < two[1][0]                  # 新的在左邊
    assert two[1][0] - two[0][0] == pytest.approx(64, abs=6)   # 實測格距 64


def test_permanent_count_icon_not_counted_as_slot():
    """band 右緣停在 x=1740，常駐計數圖示（永久 UI）不可被當成一格 buff。"""
    assert cfg.scan_confirm_region.x + cfg.scan_confirm_region.w == 1740
    for (x, _, w, _) in vision.find_effect_slots(_load("local_only")):
        assert x + w <= cfg.scan_confirm_region.w


# --- 逐格 OCR → scan_succeeded：需要 tesseract 引擎 ---

pytestmark_ocr = pytest.mark.skipif(not _engine_ready(), reason="tesseract 引擎不可用")


def _scan_ok(name):
    band = _load(name)
    texts = [ocr.read_text(band[y:y + h, x:x + w], cfg.tesseract_path)
             for (x, y, w, h) in vision.find_effect_slots(band)]
    return harvester.scan_succeeded(texts)


@pytestmark_ocr
@pytest.mark.parametrize("name", ["local_only", "local_and_caveskim",
                                  "local_displaced_3slots"])
def test_scan_confirm_positive(name):
    assert _scan_ok(name) is True


@pytestmark_ocr
@pytest.mark.parametrize("name", ["caveskim_only", "d4_used_only", "no_effects"])
def test_scan_confirm_negative(name):
    """Cave Skim 是最關鍵的負樣本：同樣是 D2 的雷達徽章，只按 Z 不等於掃描成功。"""
    assert _scan_ok(name) is False
