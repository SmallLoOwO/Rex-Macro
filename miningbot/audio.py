import time
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
    r_norm = np.linalg.norm(r)
    if r_norm == 0 or np.linalg.norm(b) == 0:
        return 0.0
    # 主交叉相關（明確指定 FFT，此 array size 比 direct 快很多）
    corr = correlate(b, r, mode="valid", method="fft")
    # 正規化分母：每個 window 的能量，用 cumsum O(N) 取代 correlate（原做法佔了 ~70ms）
    cumsum_sq = np.cumsum(np.concatenate([[0.0], b**2]))
    window_sumsq = cumsum_sq[len(r):] - cumsum_sq[:-len(r)]
    denom = r_norm * np.sqrt(window_sumsq)
    denom[denom == 0] = 1e-9
    return float(np.max(np.abs(corr / denom)))

def detect(buffer: np.ndarray, reference: np.ndarray, threshold: float) -> bool:
    return match_score(buffer, reference) >= threshold


class ChillListener:
    """滾動緩衝 + 即時比對分數。由 LoopbackCapture 持續 feed 喇叭樣本。

    分數在 feed（音訊執行緒）時算好快取，latest_score 只回傳快取值，
    避免在主迴圈每幀重算交叉相關。

    match_score 很重（~110ms），但 chunk 每 ~85ms 到一個——若每 chunk 都算，
    音訊執行緒永遠跟不上、WASAPI 緩衝區持續積壓舊音訊（實測啟動後數秒即落後 6s）。
    解法：緩衝每 chunk 照常更新（只需 ~1ms），但 score 每 score_interval_s 才算一次。
    """
    def __init__(self, reference: np.ndarray, sample_rate: int, window_seconds: float,
                 score_interval_s: float = 0.3):
        self.reference = reference
        self.sample_rate = sample_rate
        self.window = int(sample_rate * window_seconds)
        self._buf = np.zeros(self.window, np.float32)
        self._score = 0.0
        self._rms = 0.0
        self._score_interval = score_interval_s
        self._last_score_time = 0.0

    def feed(self, chunk: np.ndarray) -> None:
        chunk = chunk.astype(np.float32)
        self._buf = np.concatenate([self._buf, chunk])[-self.window:]  # 滾動窗（~1ms）
        now = time.monotonic()
        if now - self._last_score_time >= self._score_interval:
            self._score = match_score(self._buf, self.reference)
            self._rms = float(np.sqrt(np.mean(self._buf**2)))
            self._last_score_time = now

    def latest_score(self) -> float:
        return self._score

    def latest_rms(self) -> float:
        """緩衝的原始 RMS（診斷用：RMS≈0 → loopback 死；RMS 高但 score≈0 → 參考 wav 不符）。"""
        return self._rms

    def save_buffer_wav(self, path: str) -> None:
        """把目前緩衝存成 WAV 檔（chill 觸發時呼叫，取樣供分析/重錄參考 wav 用）。"""
        from scipy.io import wavfile
        data = (self._buf * 32767).astype(np.int16)   # float32 → int16
        wavfile.write(path, self.sample_rate, data)


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
