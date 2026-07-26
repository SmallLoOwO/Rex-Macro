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
    # H061（2026-07-26）：預設 False——web_server 的 fastapi/uvicorn heavy import 在
    # worker thread 啟動後會 process-level 卡死，實機三次啟動全部沒進主迴圈。真根因
    # 釐清前 bot 走回 web UI 之前的啟動路徑；欄位本身與整個 web 子系統都保留。
    assert cfg.web_server_enabled is False
    assert cfg.web_server_port == 8765
    assert cfg.web_fallback_grace_s == 30.0
