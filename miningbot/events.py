import time
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class EventRecord:
    type: str
    timestamp: float
    meta: dict = field(default_factory=dict)

class EventLog:
    def __init__(self):
        self.records: list[EventRecord] = []
        self._sinks: list[Callable[[EventRecord], None]] = []

    def add_sink(self, sink: Callable[[EventRecord], None]) -> None:
        self._sinks.append(sink)

    def log(self, type_: str, **meta) -> EventRecord:
        rec = EventRecord(type=type_, timestamp=time.time(), meta=meta)
        self.records.append(rec)
        for sink in self._sinks:
            sink(rec)
        return rec


def make_file_sink(path: str) -> Callable[[EventRecord], None]:
    """回傳一個把事件以單行附加到檔案的 sink（給 EventLog.add_sink 用）。"""
    def sink(rec: EventRecord) -> None:
        line = f"{rec.timestamp:.3f}\t{rec.type}\t{rec.meta}\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    return sink
