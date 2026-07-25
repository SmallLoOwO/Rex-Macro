"""WebEventSink：把 EventLog 事件廣播給所有 WebSocket client。

跟 notify.py 的 DiscordSink 平行——同一份事件來源，兩個 sink 各自消化。
不影響 Discord 通知路徑。
"""
import logging
from typing import Callable

from miningbot.web_protocol import WebMessage


_log = logging.getLogger(__name__)


# 哪些事件要送 web client（同 Discord notify 的 _TEMPLATES 概念，但 web 不洗版，
# 可以更寬鬆。先放跟 Discord 一樣的「玩家該知道」集合）。
# flow 從事件 type 推導：harvest 系（NEEDS_HUMAN 在採集流程中觸發）/ reentry 系。
_RELEVANT_EVENTS = frozenset({
    "RARE_FOUND",
    "TRACKER_FOUND",
    "HARVEST_SUCCESS",
    "NEEDS_HUMAN",
    "SPAWN_CHILL",
    "MINE_RESET",
    "REENTRY_START",
    "REENTRY_SUCCESS",
})

_HARVEST_EVENTS = frozenset({
    "RARE_FOUND", "TRACKER_FOUND", "HARVEST_SUCCESS", "NEEDS_HUMAN", "SPAWN_CHILL",
})
_REENTRY_EVENTS = frozenset({"MINE_RESET", "REENTRY_START", "REENTRY_SUCCESS"})


def format_event_for_web(rec) -> WebMessage | None:
    """EventLog record → WebMessage；不需通知的事件回 None。

    flow 推導：HARVEST 系 → "harvest"；REENTRY 系 → "reentry"。
    NEEDS_HUMAN 預設 harvest（採集流程最常見）；reentry 的 NEEDS_HUMAN 未來可用
    meta["flow"] 覆寫（保留擴充點，目前不實作）。

    沿用 notify.py format_message 的精神：只挑玩家該知道的，避免洗 web client。
    """
    rtype = getattr(rec, "type", None)
    if rtype not in _RELEVANT_EVENTS:
        return None
    meta = getattr(rec, "meta", {}) or {}
    flow = "reentry" if rtype in _REENTRY_EVENTS else "harvest"
    payload = {"event": rtype, "flow": flow}
    payload.update(meta)
    return WebMessage(type="event", payload=payload)


class WebEventSink:
    """EventLog sink：把事件廣播給所有 WebSocket client。

    broadcast_callback 由 WebIPC thread 注入——實際廣播動作（iterate 連線、send）
    在 thread 內做，避免主迴圈接觸 WebSocket。

    廣播例外只 log 不丟——比照 notify.make_discord_sink 的「失敗只回報，不中斷」。
    """

    def __init__(self, broadcast_callback: Callable[[WebMessage], None]):
        self._broadcast = broadcast_callback

    def __call__(self, rec) -> None:
        msg = format_event_for_web(rec)
        if msg is None:
            return
        try:
            self._broadcast(msg)
        except Exception as e:
            # 廣播失敗（client 斷線、連線例外）只記 log，不傳染主迴圈
            _log.warning("WebEventSink broadcast 失敗: %s", e)
