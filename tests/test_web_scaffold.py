"""web 子系統 scaffolding：依賴可裝、模組可 import、Config 欄位就位。"""
import pytest


def test_fastapi_importable():
    import fastapi
    import uvicorn
    assert fastapi.__version__  # 確保安裝
    assert uvicorn.__version__


@pytest.mark.parametrize("module_name", [
    "miningbot.web_protocol",
    "miningbot.web_config_whitelist",
    "miningbot.web_ipc",
    "miningbot.web_sink",
    "miningbot.web_server",
])
def test_module_importable(module_name):
    __import__(module_name)


def test_config_has_web_fields():
    from miningbot.config import Config
    cfg = Config()
    assert cfg.web_server_enabled is True
    assert cfg.web_server_port == 8765
    assert cfg.web_fallback_grace_s == 30.0
