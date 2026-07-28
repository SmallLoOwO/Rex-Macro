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


# --- D2（掃描器）slot 2：同 D1 的區域顏色判定，守 execute_scan 的 toggle 門（H065）。
# d2_slot_region 與 d1 同尺寸（54×58），故沿用原點對齊的 CROP_REGION 取整塊裁圖。
# slot2_equipped_green.png：121 mid 層（進場掃描成功、掃描器裝備中）。
# slot2_unequipped_gray.png：121 up 層（層轉換盲按 "2" 把掃描器 toggle 卸下）——toggle 鐵證。
def test_d2_equipped_slot_is_green_selected():
    scene = _load("slot2_equipped_green.png")
    assert vision.slot_selected(scene, CROP_REGION, cfg.d2_selected_greenness_min) is True


def test_d2_unequipped_slot_is_not_selected():
    scene = _load("slot2_unequipped_gray.png")
    assert vision.slot_selected(scene, CROP_REGION, cfg.d2_selected_greenness_min) is False


def test_d2_greenness_values_bracket_the_threshold():
    """兩側夾：slot2 裝備中 greenness 明顯 > 門檻 > 未裝備。

    slot2 未裝備基線（+1.48）比 slot1（-1.37）高——掃描器圖示本身帶一點綠，但仍是 UI
    固定屬性（up/d3/down 三個不同場景幀量出來分毫不差），不隨場景變，門檻 5.0 安全。
    """
    g_equipped = vision.region_greenness(_load("slot2_equipped_green.png"), CROP_REGION)
    g_unequipped = vision.region_greenness(_load("slot2_unequipped_gray.png"), CROP_REGION)
    assert g_equipped > 9.0        # 實測 ~+10.50
    assert g_unequipped < 3.0      # 實測 ~+1.48
    assert g_unequipped < cfg.d2_selected_greenness_min < g_equipped
