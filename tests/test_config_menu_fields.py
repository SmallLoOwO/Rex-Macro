"""選單前置切換／UI前置檢查／D5新顯示適配 的 config 欄位存在性與型別檢查。

這批欄位單獨開檔測試（而非散落在各功能測試裡斷言一次），因為 config.py 本身
不含邏輯，只有「有沒有定義、型別對不對」值得鎖——實際行為由消費這些欄位的
roblox_menu/vision/ocr 測試把關。
"""
from miningbot.config import DEFAULT as cfg
from miningbot.config import Region


def test_boost_indicator_region_excludes_permanent_counter_icon():
    # 2026-07-08 實機量測：永久計數圖示 bbox=(1740,1010,58,58)，右緣必須 <=1740 才不含它；
    # 下緣延到螢幕底 1080（原 1070 裁到圖示底）
    r = cfg.boost_indicator_region
    assert r.x + r.w <= 1740
    assert r.y + r.h == 1080


def test_movement_mode_options_are_three_known_values():
    assert cfg.movement_mode_options == (
        "Default (Keyboard)", "Keyboard + Mouse", "Click to Move")
    assert cfg.movement_mode_mining == "Default (Keyboard)"
    assert cfg.movement_mode_reentry == "Click to Move"
    assert cfg.movement_mode_mining in cfg.movement_mode_options
    assert cfg.movement_mode_reentry in cfg.movement_mode_options


def test_menu_panel_region_is_region():
    assert isinstance(cfg.menu_panel_region, Region)
    assert isinstance(cfg.menu_movement_label_region, Region)
    assert isinstance(cfg.menu_movement_value_region, Region)
    assert cfg.menu_movement_row_y > 0


def test_menu_numeric_fields_present_and_sane():
    assert cfg.menu_arrow_click_max >= 1
    assert cfg.menu_scroll_max_screens >= 1
    assert cfg.menu_retry_max >= 1
    assert 0.0 < cfg.menu_fuzzy_min_ratio <= 1.0
    assert cfg.menu_value_column_x_range[0] < cfg.menu_value_column_x_range[1]


def test_chat_icon_state_fields_present_and_sane():
    # H047：舊輸入列 placeholder OCR 信號已退役，改用聊天圖示狀態判定
    # （見 tests/test_chat_icon.py 的分類/邊界/動作規劃測試）。
    assert isinstance(cfg.chat_icon_state_region, Region)
    assert len(cfg.chat_icon_probe) == 4
    assert cfg.chat_icon_closed_max_gray < cfg.chat_icon_open_min_gray


def test_player_list_region_and_phrases():
    assert isinstance(cfg.player_list_region, Region)
    assert len(cfg.player_list_phrases) >= 1
