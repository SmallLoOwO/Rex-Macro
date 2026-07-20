"""Discord 文字命令的純解析邊界；不做網路、狀態修改或遊戲輸入。"""
from dataclasses import dataclass


COMMAND_NAMES = frozenset({
    "list", "keep", "unkeep", "clear", "pause", "resume", "status", "help", "shot",
    "ability", "回礦", "reenter", "校準", "calib", "轉", "rotate",
})

_ROTATE_WORDS = {"右": 1, "right": 1, "r": 1, "左": -1, "left": -1, "l": -1}


@dataclass(frozen=True)
class DiscordCommand:
    name: str
    args: tuple[str, ...]


def parse_command(content: str):
    """解析已知命令；支援可選的 `!` 前綴，普通聊天回 None。"""
    parts = content.split()
    if not parts:
        return None
    name = parts[0].lower().lstrip("!")
    if name not in COMMAND_NAMES:
        return None
    return DiscordCommand(name=name, args=tuple(parts[1:]))


def parse_rotate_direction(args):
    """`轉` 指令的方向解析（純函式）。回 +1＝右轉（`.`）、-1＝左轉（`,`）、None＝語法錯。

    無參數＝右轉，即使用者要求的「點一下 `.`」預設。看不懂的參數回 None 而非
    當成預設——寧可回提示也不要轉錯方向（手動校正時轉錯要多按 7 次才繞回來）。
    """
    if not args:
        return 1
    if len(args) != 1:
        return None
    return _ROTATE_WORDS.get(args[0].lower())
