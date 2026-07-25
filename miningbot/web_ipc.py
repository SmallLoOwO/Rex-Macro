"""race routing key、PendingReplies（先到先贏）、FallbackState（Task 6）。

spec §8 race 規則：bot 等玩家介入時，第一個進來的 reply（web 或 discord 任一）
鎖定，其他同 routing key 的 reply 立刻丟棄。「先到先贏，後到丟棄」。
"""
import threading
import time
from typing import Any, Callable


def routing_key(flow: str, episode_id: str) -> str:
    """flow + episode_id 組成 routing key。

    例：routing_key("harvest", "007") → "harvest:007"
        routing_key("reentry", "attempt_3") → "reentry:attempt_3"
    """
    return f"{flow}:{episode_id}"


def reply_matches(key_a: str, key_b: str) -> bool:
    """兩個 routing key 是否匹配（嚴格相等）。"""
    return key_a == key_b


class PendingReplies:
    """等待消費的 reply 佇列（先到先贏）。

    - push(key, reply)：同 key 第一個收下（回 True）；同 key 後續立刻丟棄（回 False）
    - pop(key)：取出該 key 的 reply（取出後 slot 清空，可 push 新 reply）；無則 None
    - pop_any_expired()：清掉所有過期 reply，回 [(key, reply), ...]

    時間透過 `_now` 注入（測試可替換）；production 用 time.monotonic。
    reply 結構由呼叫端決定（dict / dataclass 都行）。

    執行緒安全：本類別的 push/pop 由 WebIPC thread（單一 consumer 視角）呼叫，
    bot 主迴圈另一個 thread 只透過 pop(key) 讀取。為了 thread-safe，所有動作
    都在 instance lock 內做。WebIPC thread push、bot thread pop 是經典 SPSC，
    lock 仍加保守邊際。
    """

    def __init__(self):
        self._slots: dict[str, tuple[Any, float, float]] = {}  # key → (reply, push_time, ttl)
        self._lock = threading.Lock()
        self._now: Callable[[], float] = time.monotonic

    def push(self, key: str, reply: Any, ttl_s: float = 60.0) -> bool:
        """同 key 第一個收下；後到的立刻拒絕（spec §8「先到先贏，後到丟棄」）。

        回 True = 收下；False = 拒絕（已有人或 slot 未清）。
        """
        with self._lock:
            if key in self._slots:
                return False
            self._slots[key] = (reply, self._now(), ttl_s)
            return True

    def pop(self, key: str) -> Any | None:
        """取出該 key 的 reply（清空 slot）；無則 None。"""
        with self._lock:
            entry = self._slots.pop(key, None)
            return entry[0] if entry is not None else None

    def pop_any_expired(self) -> list[tuple[str, Any]]:
        """清掉所有過期 reply；回 [(key, reply), ...]。"""
        now = self._now()
        expired: list[tuple[str, Any]] = []
        with self._lock:
            for key in list(self._slots.keys()):
                reply, pushed_at, ttl = self._slots[key]
                if now - pushed_at >= ttl:
                    expired.append((key, reply))
                    del self._slots[key]
        return expired
