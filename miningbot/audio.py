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


class AdaptiveSpikeDetector:
    """安靜基準線上的「相對響度尖峰」偵測：不需事先知道目標音的絕對音量。

    每次 update() 餵一個 chunk 的 RMS：維護一條 EMA 基準線，當 rms/baseline 達
    spike_factor 時以上升緣語意回報一次（高檔不重複，回落到 release 才 re-arm）。
    專治「一段安靜之後一記清脆鈴聲」——重置完成音效正是這型。純邏輯，有單元測試。

    兩個必防的坑：
      1. 暖機：前 warmup_samples 次只建基準線、一律回 False（否則無基準會誤觸）。
      2. 基準線不被鈴聲自己拉高：ratio 處於高檔（>= release）時凍結 EMA 更新，
         回落才續更——否則鈴聲會把基準線推高、自我抑制或漏掉接連兩聲。
    min_floor 是絕對 RMS 下限，防純靜音時基準線趨近 0、除出假尖峰。
    """
    def __init__(self, spike_factor: float, baseline_alpha: float, min_floor: float,
                 warmup_samples: int, release_factor: float = 0.5):
        self.spike_factor = spike_factor
        self.baseline_alpha = baseline_alpha
        self.min_floor = min_floor
        self.warmup_samples = warmup_samples
        self.release_ratio = spike_factor * release_factor
        self.reset()

    def reset(self) -> None:
        self._baseline = 0.0
        self._count = 0
        self._armed = True

    @property
    def baseline(self) -> float:
        return self._baseline

    def _update_baseline(self, rms: float) -> None:
        if self._count == 1:
            self._baseline = rms                      # 第一個樣本直接當種子
        else:
            a = self.baseline_alpha
            self._baseline = a * self._baseline + (1.0 - a) * rms

    def update(self, rms: float) -> bool:
        self._count += 1
        if self._count <= self.warmup_samples:        # 暖機：只建基準線
            self._update_baseline(rms)
            return False
        ratio = rms / max(self._baseline, self.min_floor)
        if ratio < self.release_ratio:                # 只在低檔更新基準線（凍結防自我抑制）
            self._update_baseline(rms)
        fired = False
        if self._armed and ratio >= self.spike_factor:
            self._armed = False
            fired = True
        elif not self._armed and ratio < self.release_ratio:
            self._armed = True
        return fired


class ResetChimeRecorder:
    """RESET_WAIT 期間錄「重置完成鈴聲」候選片段（第一階段：只錄不比對）。

    維護 window_s 滾動緩衝；detector 觸發後不立即存，改設 post_roll 倒數、繼續收
    chunk，倒數歸零才把整條緩衝存檔——存下的片段是「觸發前一段 + 觸發後 post_roll」，
    鈴聲完整落在中段，方便裁 1s 參考。倒數期間再觸發則延長（不把一串鈴聲切兩半）。
    存檔在音訊執行緒 inline 跑（~5ms，比照 _on_audio_event）。
    """
    def __init__(self, sample_rate, window_s, post_roll_s, chunk_seconds, detector,
                 out_dir, max_clips, save_fn=None, log=None, diag=None):
        self.sample_rate = sample_rate
        self.window = int(sample_rate * window_s)
        self.post_roll_chunks = max(1, round(post_roll_s / chunk_seconds))
        self.detector = detector
        self.out_dir = out_dir
        self.max_clips = max_clips
        self._save = save_fn or save_wav
        self._log = log
        self._diag = diag
        self.reset()

    def reset(self):
        self._buf = np.zeros(self.window, np.float32)
        self._countdown = 0
        self._pending_rms = 0.0
        self._clips = 0
        self.detector.reset()

    def feed(self, chunk):
        chunk = np.asarray(chunk, np.float32)
        self._buf = np.concatenate([self._buf, chunk])[-self.window:]   # 滾動窗
        rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
        fired = self.detector.update(rms)
        if self._diag is not None:
            self._diag(rms, self.detector.baseline)
        if fired and self._clips < self.max_clips:
            self._countdown = self.post_roll_chunks    # (重)啟動 post-roll＝延長
            self._pending_rms = rms
        if self._countdown > 0:
            self._countdown -= 1
            if self._countdown == 0:
                self._flush()

    def _flush(self):
        import os, time
        os.makedirs(self.out_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.out_dir,
                            f"resetchime_{ts}_rms{int(round(self._pending_rms)):04d}.wav")
        self._save(path, self._buf.copy(), self.sample_rate)
        self._clips += 1
        if self._log is not None:
            self._log(path, self._pending_rms)


def chime_capacity_armed(capacity_pct, arm_pct: float) -> bool:
    """reset-chime 錄音窗開啟條件（純函式）：容量 OCR 讀到低值＝重置真的完成。

    H045 使用者裁決（2026-07-17）：時間錨（RESET_WAIT 滿 N 秒）是猜的——banner
    倒數到真重置完成的耗時不定（凍結可拖 1~2.5 分鐘），改用容量當錨，與開場
    容量閘同一訊號源。兩側夾：重置前／凍結舊幀 78~100%、真重置完成後 0%
    （2026-07-14 ep3 實機幀）。None＝OCR 沒讀到，不開窗（等下一輪讀值）。
    """
    return capacity_pct is not None and capacity_pct <= arm_pct


def capture_window_active(armed_since: float, now: float, max_s: float) -> bool:
    """reset-chime 錄音窗（純函式）：容量歸零觀測時刻起算，max_s 內收音。

    H045：舊邏輯「RESET_WAIT 滿 30s 開錄、離開 RESET_WAIT 即停錄」，但 banner
    倒數只有 26~28s＋沉澱 5s 就轉 REENTRY——實際錄音窗僅 1~3s，鈴聲永遠在窗外。
    改法：容量錨開窗（chime_capacity_armed）＋窗跨 RESET_WAIT/REENTRY；max_s
    收口防 REENTRY 等指令期間（可達數十分鐘）遊戲音效洗版 max_clips。
    armed_since<=0＝本輪尚未觀測到容量歸零，不收音。
    """
    if armed_since <= 0.0:
        return False
    return 0.0 <= now - armed_since <= max_s


def chill_muted_after_antiafk(pressed_at: float, now: float, mute_s: float) -> bool:
    """防掛機 Space 之後的 chill 靜音窗（純函式）——擋 bot 自製的假觸發。

    H060（2026-07-22 實機）：等待狀態每 antiafk_interval_s 按一次 Space 保活
    （main.run 的 NEEDS_HUMAN/RESET_WAIT/回礦等指令分支），角色原地跳的音效被
    loopback 收進 chill 偵測器。當日三次 REENTRY 的 spawn chill 通知**全部**發生在
    「防掛機：按 Space」之後 2 秒，分數 0.25/0.38/0.37 皆越過 0.25 門檻。

    這是唯一一種 bot 知道確切發生時刻的音源，故用時間窗直接排除，不必靠參考集
    品質——參考集校準再好也擋不住「自己製造的聲音剛好像 chill」這類迴圈。

    窗長由實機量測定：三次事件的分數分別維持到按鍵後 +4s/+5s/+4s（1.5s 滾動窗
    ＋落地音延遲），預設 6.0s 留邊際。相對 900s 保活週期只遮蔽 0.67%，且只在
    等待狀態發生（挖礦中不按 Space）。pressed_at<=0＝本行程尚未按過，不靜音；
    now 早於 pressed_at（時鐘回跳）也不靜音。
    """
    if pressed_at <= 0.0:
        return False
    return 0.0 <= now - pressed_at <= mute_s


def chill_edge_step(above: bool, score: float, threshold: float) -> tuple:
    """chill 上升緣狀態機的單步（純函式）→ (新的 above, "rise"|"fall"|"")。

    為什麼要數上升緣：`AudioListener.latest_score()` 是滾動比對，同一聲 chill 會連續
    多個 tick 都在門檻上（2026-07-22 01:43:31~33 三秒七行是同一聲）。「這個 episode
    響了幾聲」只能由「分數回落到門檻下再上來」的次數決定。

    ⚠ 呼叫端必須先套 `chill_muted_after_antiafk`（H060）再進來——防掛機跳躍音會被認成
    chill，混進來會直接污染上升緣分布。
    """
    now_above = score >= threshold
    if now_above == above:
        return now_above, ""
    return now_above, "rise" if now_above else "fall"


def chill_edges(samples, threshold: float) -> list:
    """[(時間戳, 分數)] → 上升緣 [(時間戳, 分數, 距上次回落秒數)]（純函式）。

    距上次回落秒數為 None＝序列開頭就在門檻上（沒有可比的回落）。這一欄是
    `count_chill_edges` 去抖動的唯一依據，也是實機分布要收的那份資料。
    """
    above, fell_at, out = False, None, []
    for ts, score in samples:
        above, edge = chill_edge_step(above, score, threshold)
        if edge == "rise":
            out.append((ts, score, None if fell_at is None else ts - fell_at))
        elif edge == "fall":
            fell_at = ts
    return out


def count_chill_edges(edges, release_s: float) -> int:
    """`chill_edges` 的輸出 → 去抖動後的上升緣數（純函式）。

    回落沒有維持滿 release_s 就又上來＝同一聲的抖動，不另計一聲。
    release_s=0 → 每個原始上升緣都算（＝完全不去抖動）。
    """
    return sum(1 for _ts, _score, since_fall in edges
               if since_fall is None or since_fall >= release_s)


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
