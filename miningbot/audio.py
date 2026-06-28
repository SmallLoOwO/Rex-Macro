import time
import numpy as np
from scipy.signal import correlate

def match_score(buffer: np.ndarray, reference: np.ndarray, decimate: int = 1) -> float:
    """參考樣本在緩衝中的最大正規化交叉相關 (0..1)。

    decimate>1：對 buffer 與 reference **同步**抽樣（stride）後再比對——同一個 stride 套在
    兩邊、aliasing 一致故相關度幾乎不變，但陣列縮小 k 倍 → match 快 ~k 倍。實測 k=4 分數
    與 full 完全一致、耗時 118ms→22ms。用於多參考比對時把每個參考的成本壓低，避免音訊積壓。
    """
    b = buffer.astype(np.float64)
    r = reference.astype(np.float64)
    if decimate > 1:
        b = b[::decimate]
        r = r[::decimate]
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


def match_score_multi(buffer: np.ndarray, references, decimate: int = 1) -> float:
    """對多個參考各算 match_score，回傳**最高分**。空參考集回 0.0。

    一種 chill 對單一參考飄 0.15-0.87（實測 5 個都是清楚的 chill 卻分數差很大，至少 3 種
    不同音效）→ 單參考必漏。改成「對任一已知 chill 命中即可」：每種 chill 至少完美命中自己
    的參考（~1.0）。配 decimate 把多參考成本壓在 0.3s 預算內。
    """
    best = 0.0
    for ref in references:
        s = match_score(buffer, ref, decimate=decimate)
        if s > best:
            best = s
    return best


class RisingEdgeDetector:
    """分數上升緣去抖動偵測：value 由低於門檻升到 ≥ 門檻時 update() 回 True 一次，
    維持高檔不重複觸發，回落到 release（預設 threshold/2）以下才 re-arm。

    用於「音訊明顯變動就記錄」：避免每幀都存檔，只在 score 一次次「升起」時記一筆。
    初始 armed=True——啟動即在門檻上方視為一次變動（會觸發）。純邏輯，有單元測試。
    """
    def __init__(self, threshold: float, release: float | None = None):
        self.threshold = threshold
        self.release = release if release is not None else threshold * 0.5
        self._armed = True

    def update(self, value: float) -> bool:
        if self._armed and value >= self.threshold:
            self._armed = False
            return True
        if not self._armed and value <= self.release:
            self._armed = True
        return False


def save_wav(path: str, samples: np.ndarray, sample_rate: int) -> None:
    """把樣本忠實存成 16-bit WAV。samples 已是 int16 值域的 float（loopback int16→float32），
    故**直接轉 int16，不可再乘 32767**（乘了會溢位繞回成雜訊——舊 save_buffer_wav 的 bug）。
    超出範圍先 clip 防環繞。
    """
    from scipy.io import wavfile
    data = np.clip(samples, -32768, 32767).astype(np.int16)
    wavfile.write(path, sample_rate, data)


class ChillListener:
    """滾動緩衝 + 即時比對分數。由 LoopbackCapture 持續 feed 喇叭樣本。

    分數在 feed（音訊執行緒）時算好快取，latest_score 只回傳快取值，
    避免在主迴圈每幀重算交叉相關。

    match_score 很重（~110ms），但 chunk 每 ~85ms 到一個——若每 chunk 都算，
    音訊執行緒永遠跟不上、WASAPI 緩衝區持續積壓舊音訊（實測啟動後數秒即落後 6s）。
    解法：緩衝每 chunk 照常更新（只需 ~1ms），但 score 每 score_interval_s 才算一次。
    """
    def __init__(self, reference, sample_rate: int, window_seconds: float,
                 score_interval_s: float = 0.3, event_threshold: float | None = None,
                 on_event=None, decimate: int = 1):
        # reference 可為單一 ndarray 或多個參考的 list（多種 chill 音效，取最高分）
        self.references = [reference] if isinstance(reference, np.ndarray) else list(reference)
        self.decimate = decimate
        self.sample_rate = sample_rate
        self.window = int(sample_rate * window_seconds)
        self._buf = np.zeros(self.window, np.float32)
        self._score = 0.0
        self._rms = 0.0
        self._score_interval = score_interval_s
        self._last_score_time = 0.0
        # 音訊變動記錄：score 升過 event_threshold（去抖動）就回呼 on_event(score, rms, buf_copy)。
        # 在音訊執行緒、score 算好的當下擷取 buffer，與分數同調——比 _on_enter 晚 3s 存準得多。
        self._edge = RisingEdgeDetector(event_threshold) if event_threshold else None
        self._on_event = on_event

    def feed(self, chunk: np.ndarray) -> None:
        chunk = chunk.astype(np.float32)
        self._buf = np.concatenate([self._buf, chunk])[-self.window:]  # 滾動窗（~1ms）
        now = time.monotonic()
        if now - self._last_score_time >= self._score_interval:
            self._score = match_score_multi(self._buf, self.references, decimate=self.decimate)
            self._rms = float(np.sqrt(np.mean(self._buf**2)))
            self._last_score_time = now
            if self._edge is not None and self._edge.update(self._score) and self._on_event:
                self._on_event(self._score, self._rms, self._buf.copy())

    def latest_score(self) -> float:
        return self._score

    def latest_rms(self) -> float:
        """緩衝的原始 RMS（診斷用：RMS≈0 → loopback 死；RMS 高但 score≈0 → 參考 wav 不符）。"""
        return self._rms

    def save_buffer_wav(self, path: str) -> None:
        """把目前緩衝存成 WAV 檔（chill 觸發時呼叫，取樣供分析/重錄參考 wav 用）。"""
        save_wav(path, self._buf, self.sample_rate)


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


def load_references(refs_dir: str, fallback_path: str) -> tuple[list, int]:
    """載入多參考集：refs_dir 內所有 *.wav（多種 chill 音效）；空則退回單一 fallback_path。

    回傳 (references, sample_rate)。各參考應同取樣率（都是同一台機器 loopback 擷取/裁出）。
    用 fallback 的 sr 當基準（視窗長度依它算）。
    """
    import glob, os
    paths = sorted(glob.glob(os.path.join(refs_dir, "*.wav"))) if refs_dir else []
    if not paths:
        data, sr = load_reference(fallback_path)
        return [data], sr
    refs = []
    sr = None
    for p in paths:
        d, s = load_reference(p)
        refs.append(d)
        sr = sr or s
    return refs, sr
