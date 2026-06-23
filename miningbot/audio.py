import numpy as np
from scipy.signal import correlate

def match_score(buffer: np.ndarray, reference: np.ndarray) -> float:
    """參考樣本在緩衝中的最大正規化交叉相關 (0..1)。"""
    b = buffer.astype(np.float64)
    r = reference.astype(np.float64)
    b -= b.mean()
    r -= r.mean()
    if np.linalg.norm(b) == 0 or np.linalg.norm(r) == 0:
        return 0.0
    corr = correlate(b, r, mode="valid")
    denom = np.linalg.norm(r) * np.sqrt(
        correlate(b**2, np.ones_like(r), mode="valid")
    )
    denom[denom == 0] = 1e-9
    return float(np.max(np.abs(corr / denom)))

def detect(buffer: np.ndarray, reference: np.ndarray, threshold: float) -> bool:
    return match_score(buffer, reference) >= threshold


class ChillListener:
    """薄封裝：背景擷取喇叭 loopback，提供 latest_score()。整合測試/校準覆蓋。"""
    def __init__(self, reference: np.ndarray, sample_rate: int, window_seconds: float):
        self.reference = reference
        self.sample_rate = sample_rate
        self.window = int(sample_rate * window_seconds)
        self._buf = np.zeros(self.window, np.float32)

    def feed(self, chunk: np.ndarray) -> None:
        chunk = chunk.astype(np.float32)
        self._buf = np.concatenate([self._buf, chunk])[-self.window:]

    def latest_score(self) -> float:
        return match_score(self._buf, self.reference)


def load_reference(path: str) -> tuple[np.ndarray, int]:
    from scipy.io import wavfile
    sr, data = wavfile.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data.astype(np.float32), sr
