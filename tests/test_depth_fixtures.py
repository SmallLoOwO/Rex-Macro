"""Depth OCR 回歸測試：對「實機 Depth: ... 裁圖」跑真實引擎，鎖住地表/礦內判定。

H046 開場狀態錨：回礦開場成立與否看「人在不在地表」（Depth: Surface）而非
「點擊有沒有造成幀差」。本檔對 3 張實機裁圖（Region(890,92,210,45)；
2026-07-17 Surface 幀＋2026-07-14 488m/25790m 幀）跑 read_depth_is_surface，
斷言 True/False/False。尾端 "$..." 金額是裁圖右緣固定拖尾雜訊，parse 必須容忍。
比照 test_capacity_fixtures.py 慣例：引擎不可用時整檔 skip。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import ocr  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "reentry")


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


def test_depth_surface_frame_reads_true():
    # 2026-07-17 17:24:55 ep1 實機幀：人已在地表（H046(b) 誤鎖現場）
    assert ocr.read_depth_is_surface(_load("h046_depth_surface.png"),
                                     cfg.tesseract_path) is True


def test_depth_488m_frame_reads_false():
    # 2026-07-14 凍結舊幀：礦內深度 488m
    assert ocr.read_depth_is_surface(_load("h046_depth_488m.png"),
                                     cfg.tesseract_path) is False


def test_depth_25790m_frame_reads_false():
    # 2026-07-14 18:28:50 幀：已傳送下礦後的深度
    assert ocr.read_depth_is_surface(_load("h046_depth_25790m.png"),
                                     cfg.tesseract_path) is False


# ── 深度數值 → 層別（ledger ground truth；遊戲畫面不顯示在第幾層）────────
# 上面三張鎖「在不在地表」的布林；以下鎖同一批裁圖的**數值**路徑，以及
# 數值接上 game_data.layer_for_depth 之後的層別反推。

def test_depth_7100m_landing_frame_reads_meters():
    # 2026-07-22 13:48 ep20 回礦落地幀裁出（Region(890,92,210,45)）。
    # 該場次 10 張倖存 landing 幀真 OCR 全部讀到 7100m。
    assert ocr.read_depth_meters(_load("depth_7100m_shamrock_landing.png"),
                                 cfg.tesseract_path) == 7100


def test_depth_7100m_landing_frame_maps_to_shamrock():
    """端到端：實機裁圖 → 數值 → (Lucernia, 7100) → Shamrock。

    ledger 對這批 episode 有 5 筆把層標成 "Mantle Layer"，畫面層名牌實為
    Shamrock——這條鏈路就是拿來取代那個不可信宣告值的。
    """
    from miningbot import game_data
    depth = ocr.read_depth_meters(_load("depth_7100m_shamrock_landing.png"),
                                  cfg.tesseract_path)
    assert game_data.layer_for_depth("Lucernia", depth) == "Shamrock"


def test_depth_surface_frame_yields_no_meters():
    assert ocr.read_depth_meters(_load("h046_depth_surface.png"),
                                 cfg.tesseract_path) is None


def test_depth_488m_frame_reads_meters():
    assert ocr.read_depth_meters(_load("h046_depth_488m.png"),
                                 cfg.tesseract_path) == 488


def test_void_fall_depth_reads_value_but_maps_to_no_layer():
    """H043 虛空墜落 25790m：數值照讀（診斷線索要留），但層別必須回 None。

    這是「不可夾到最近的層」的實機側驗證——最深層底才 9999m。
    """
    from miningbot import game_data
    depth = ocr.read_depth_meters(_load("h046_depth_25790m.png"), cfg.tesseract_path)
    assert depth == 25790
    assert game_data.layer_for_depth("Lucernia", depth) is None
