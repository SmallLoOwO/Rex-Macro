"""D1（鎬子）槽位「是否已裝備」的區域顏色偵測回歸（2026-07-10）。

背景：原本用單點 `pixel_matches(slot_pixel=(1011,845), 0x232323)` 判斷槽位是否「沒拿鎬子」。
使用者把工作列調回顯示後，遊戲視窗底部整條 UI 上移約 50px（實測 boost 瓶子 1039→989），
那顆寫死的單點落到角色/場景上（實測讀到 ~[164,167,217] 紅色）→ 判定全錯。

對策（使用者要求）：改「根據區域顏色」判定——hotbar 選中的槽位底色會轉綠。
量 slot 1 內部區域的『綠色主導』程度 greenness = 平均G - 平均(R+B)/2：
- 裝備中（選中，綠底）：實測 +9.8 ~ +11.5
- 未裝備（未選中，灰底）：實測 -1.4 ~ 0.0
→ 門檻 5.0 兩側夾（遠離兩端）。

fixtures 是實機裁圖（cfg.d1_slot_region 那塊 54x58）：
- slot1_equipped_green.png：按 D1 選中鎬子後（綠底）→ slot_selected 應為 True
- slot1_unequipped_gray.png：再按 D1 卸下（灰底）→ slot_selected 應為 False
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import vision  # noqa: E402
from miningbot.config import DEFAULT as cfg, Region  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "slot")
# fixture 已裁成 d1_slot_region 大小 → 用原點對齊的 region 取整塊
CROP_REGION = Region(0, 0, cfg.d1_slot_region.w, cfg.d1_slot_region.h)


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def test_equipped_slot_is_green_selected():
    scene = _load("slot1_equipped_green.png")
    assert vision.slot_selected(scene, CROP_REGION, cfg.d1_selected_greenness_min) is True


def test_unequipped_slot_is_not_selected():
    scene = _load("slot1_unequipped_gray.png")
    assert vision.slot_selected(scene, CROP_REGION, cfg.d1_selected_greenness_min) is False


def test_greenness_values_bracket_the_threshold():
    """兩側夾：裝備中 greenness 明顯 > 門檻 > 未裝備，且門檻落在 gap 中央附近。"""
    g_equipped = vision.region_greenness(_load("slot1_equipped_green.png"), CROP_REGION)
    g_unequipped = vision.region_greenness(_load("slot1_unequipped_gray.png"), CROP_REGION)
    assert g_equipped > 9.0        # 實測 ~10.78
    assert g_unequipped < 1.0      # 實測 ~-1.37
    assert g_unequipped < cfg.d1_selected_greenness_min < g_equipped
