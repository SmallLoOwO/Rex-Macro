"""低成本執行期延遲統計；只保存有界視窗，不引入額外依賴。"""
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LatencySummary:
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


def _percentile(values, fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


class LatencyTracker:
    """依名稱收集秒數，輸出毫秒 p50/p95/p99；每個名稱都受 max_samples 限制。"""

    def __init__(self, max_samples: int = 300):
        if max_samples < 1:
            raise ValueError("max_samples 必須 >= 1")
        self._max_samples = max_samples
        self._samples = defaultdict(lambda: deque(maxlen=self._max_samples))

    def observe(self, name: str, seconds: float) -> None:
        self._samples[name].append(max(0.0, float(seconds)))

    def snapshot(self, reset: bool = False):
        result = {}
        for name, samples in self._samples.items():
            if not samples:
                continue
            values_ms = [value * 1000.0 for value in samples]
            result[name] = LatencySummary(
                count=len(values_ms),
                p50_ms=_percentile(values_ms, 0.50),
                p95_ms=_percentile(values_ms, 0.95),
                p99_ms=_percentile(values_ms, 0.99),
                max_ms=max(values_ms),
            )
        if reset:
            self._samples.clear()
        return result
