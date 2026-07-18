"""Discord 文字命令的純解析邊界；不做網路、狀態修改或遊戲輸入。"""
from dataclasses import dataclass


COMMAND_NAMES = frozenset({
    "list", "keep", "unkeep", "clear", "pause", "resume", "status", "help", "shot",
    "ability", "回礦", "reenter", "校準", "calib",
})


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
