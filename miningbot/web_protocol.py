"""WebSocket 訊息協議：dataclass、序列化、座標還原（純函式）。

訊息分兩種 type：
- "event"（bot → web）：NEEDS_HUMAN / HARVEST_SUCCESS / REENTRY_START / 狀態變動 等
- "command"（web → bot）：fire_at / reentry_click / config_set / pause / request_frame 等

座標系：所有 (x,y) 都是**遊戲原生解析度**（1920×1080）；client 端用 CSS scale 顯示，
點擊座標 server 端用 client_to_native_coords 還原（Task 3）。
"""
import json
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class WebMessage:
    """WebSocket 訊息。type 必為 "event" 或 "command"；payload 是 dict。

    frozen=True：訊息不可變，避免 consumer 改到 producer 還在用的實例。
    """
    type: str
    payload: dict


def serialize_message(msg: WebMessage) -> str:
    """WebMessage → JSON 字串（ WebSocket text frame 傳輸用）。"""
    return json.dumps(asdict(msg), ensure_ascii=False)


def parse_message(text: str) -> WebMessage | None:
    """JSON 字串 → WebMessage；不合法回 None（不丟例外，避免網路層吃壞資料炸掉）。

    缺 type / 缺 payload / type 不是字串 / payload 不是 dict 一律 None。
    """
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    t = d.get("type")
    p = d.get("payload")
    if not isinstance(t, str) or not isinstance(p, dict):
        return None
    return WebMessage(type=t, payload=p)
