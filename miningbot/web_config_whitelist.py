"""玩家可在網頁改的 Config 欄位白名單 + 值型別驗證。

spec §6：玩家只動 4 個「遊戲 play style」欄位，門檻 / ROI / 偵測參數完全不暴露。
AI agent 改這些是直接 edit config.py（Claude session 內），跟網頁無關。
"""
from typing import Any


WEB_CONFIGURABLE_FIELDS: frozenset[str] = frozenset({
    "reentry_mode",
    "reentry_target_layer",
    "reentry_yaw_sample_sweep",
    "sweep_pitch_enabled",
})

_REENTRY_MODE_VALUES = frozenset({"off", "remote", "auto"})


def is_web_configurable(field: str) -> bool:
    """欄位是否在玩家可改白名單內。"""
    return field in WEB_CONFIGURABLE_FIELDS


def validate_value(field: str, value: Any) -> bool:
    """欄位+值組合是否合法。

    非白名單欄位一律 False（即使值看起來對）。
    白名單欄位的值驗證規則：
    - reentry_mode：只能是 "off"/"remote"/"auto"
    - reentry_target_layer：任意字串（含空字串 fallback）
    - 兩個 toggle：嚴格 bool（不收 0/1/"true"）
    """
    if not is_web_configurable(field):
        return False
    if field == "reentry_mode":
        return value in _REENTRY_MODE_VALUES
    if field == "reentry_target_layer":
        return isinstance(value, str)
    # 兩個 bool toggle
    # 注意：isinstance(True, int) 是 True，所以反過來要先檢查 bool
    return isinstance(value, bool)
