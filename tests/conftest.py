"""集中標記真實 fixture/OCR 測試，避免每個歷史檔案重複宣告。"""

_OCR_MODULES = {
    "test_capacity_fixtures.py",
    "test_chat_ui_fixtures.py",
    "test_ocr_fixtures.py",
    "test_player_list_fixtures.py",
}


def pytest_collection_modifyitems(items):
    import pytest

    for item in items:
        filename = item.path.name
        if filename.endswith("_fixtures.py"):
            item.add_marker(pytest.mark.fixture)
        if filename in _OCR_MODULES:
            item.add_marker(pytest.mark.ocr)
