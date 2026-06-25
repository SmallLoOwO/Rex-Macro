import numpy as np
from scipy.signal import correlate

def match_score(buffer: np.ndarray, reference: np.ndarray) -> float:
    """參考樣本在緩衝中的最大正規化交叉相關 (0..1)。"""
    b = buffer.astype(np.float64)
    r = reference.astype(np.float64)
    if len(b) < len(r):                 # 緩衝比參考短 → 無法比對（參考應比偵測窗短）
        return 0.0
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
    """滾動緩衝 + 即時比對分數。由 LoopbackCapture 持續 feed 喇叭樣本。

    分數在 feed（音訊執行緒）時算好快取，latest_score 只回傳快取值，
    避免在主迴圈每幀重算交叉相關。
    """
    def __init__(self, reference: np.ndarray, sample_rate: int, window_seconds: float):
        self.reference = reference
        self.sample_rate = sample_rate
        self.window = int(sample_rate * window_seconds)
        self._buf = np.zeros(self.window, np.float32)
        self._score = 0.0

    def feed(self, chunk: np.ndarray) -> None:
        chunk = chunk.astype(np.float32)
        self._buf = np.concatenate([self._buf, chunk])[-self.window:]
        self._score = match_score(self._buf, self.reference)

    def latest_score(self) -> float:
        return self._score


class LoopbackCapture:
    """背景擷取系統喇叭輸出（WASAPI loopback），把單聲道樣本餵給 on_chunk。"""
    def __init__(self, on_chunk, chunk_frames: int = 4096):
        self.on_chunk = on_chunk
        self.chunk_frames = chunk_frames
        self.sample_rate = None
        self._running = False
        self._thread = None

    def start(self):
        import threading
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        import pyaudiowpatch as pa
        p = pa.PyAudio()
        stream = None
        try:
            wi = p.get_host_api_info_by_type(pa.paWASAPI)
            dev = p.get_device_info_by_index(wi["defaultOutputDevice"])
            if not dev.get("isLoopbackDevice"):
                for d in p.get_loopback_device_info_generator():
                    if dev["name"] in d["name"]:
                        dev = d
                        break
            ch = int(dev["maxInputChannels"])
            self.sample_rate = int(dev["defaultSampleRate"])
            stream = p.open(format=pa.paInt16, channels=ch, rate=self.sample_rate,
                            frames_per_buffer=self.chunk_frames, input=True,
                            input_device_index=dev["index"])
            while self._running:
                data = stream.read(self.chunk_frames, exception_on_overflow=False)
                arr = np.frombuffer(data, np.int16).astype(np.float32)
                if ch > 1:
                    arr = arr.reshape(-1, ch).mean(axis=1)
                self.on_chunk(arr)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream(); stream.close()
                except Exception:
                    pass
            p.terminate()


def load_reference(path: str) -> tuple[np.ndarray, int]:
    from scipy.io import wavfile
    sr, data = wavfile.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data.astype(np.float32), sr
