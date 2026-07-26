"""集中標記真實 fixture/OCR 測試，避免每個歷史檔案重複宣告。"""

_OCR_MODULES = {
    "test_capacity_fixtures.py",
    "test_ocr_fixtures.py",
    "test_player_list_fixtures.py",
}
# 2026-07-26 稽核移除 "test_chat_ui_fixtures.py"：2026-07-08 計畫規劃過這個檔（對聊天
# 輸入列的提示字做 OCR），但 H047 證明那條路徑會假陰性——聊天框開著久無訊息會整窗
# 自動隱藏，提示字跟著消失。判定已改看聊天圖示外觀（vision.chat_icon_state），回歸
# 測試在 tests/test_chat_icon.py、素材在 tests/fixtures/chat_icon/；相關 Config 欄位
# 也早已移除（test_chat_icon.py 有專測守著不得再被引用）。這筆是指向不存在模組的
# 死條目，留著會讓人以為那個檔案還在。


def pytest_collection_modifyitems(items):
    import pytest

    for item in items:
        filename = item.path.name
        if filename.endswith("_fixtures.py"):
            item.add_marker(pytest.mark.fixture)
        if filename in _OCR_MODULES:
            item.add_marker(pytest.mark.ocr)
