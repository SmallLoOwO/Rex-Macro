"""P2 Discord 訊息角色精簡：純函式 + StatusMessenger + 整合。

跟既有 tests/test_notify.py 共存——把 P2 新元件獨立成新檔，避免既有檔越長越亂。"""
import pytest


def test_config_has_status_edit_min_interval():
    from miningbot.config import Config
    cfg = Config()
    assert cfg.discord_status_edit_min_interval_s == 3.0


def test_ping_user_id_constant_present():
    import miningbot.notify as notify
    assert notify.PING_USER_ID == "373438562940747776"


def test_ping_user_id_is_str():
    """Discord mention format <@USER_ID> 要求 USER_ID 是字串；數字會崩。"""
    import miningbot.notify as notify
    assert isinstance(notify.PING_USER_ID, str)
    assert notify.PING_USER_ID.isdigit()
