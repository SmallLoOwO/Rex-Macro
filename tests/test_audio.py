import numpy as np
from miningbot.audio import match_score, match_score_multi, detect, RisingEdgeDetector

def test_match_score_high_for_same_signal():
    ref = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    buf = np.concatenate([np.zeros(1000, np.float32), ref, np.zeros(1000, np.float32)])
    assert match_score(buf, ref) > 0.9

def test_match_score_low_for_noise():
    rng = np.random.default_rng(0)
    ref = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    buf = rng.standard_normal(6000).astype(np.float32)
    assert match_score(buf, ref) < 0.5

def test_detect_uses_threshold():
    # detect 就是 score >= threshold；用實際分數兩側的門檻驗證比較邏輯，
    # 不假設確切分數大小（乾淨嵌入訊號的分數本來就接近 1.0）。
    ref = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    buf = np.concatenate([np.zeros(500, np.float32), ref])
    score = match_score(buf, ref)
    assert detect(buf, ref, threshold=score - 0.01) is True
    assert detect(buf, ref, threshold=min(score + 0.01, 1.0 + 1e-6)) is False

def test_match_score_zero_when_buffer_shorter_than_reference():
    ref = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    buf = np.zeros(100, np.float32)               # 緩衝比參考短
    assert match_score(buf, ref) == 0.0


# --- decimate：抽樣加速比對（同 k 套在 buf+ref，分數幾乎不變）-------------------
def test_match_score_decimate_preserves_score():
    ref = np.sin(np.linspace(0, 80, 8000)).astype(np.float32)
    buf = np.concatenate([np.zeros(2000, np.float32), ref, np.zeros(2000, np.float32)])
    full = match_score(buf, ref)
    deci = match_score(buf, ref, decimate=4)
    assert abs(full - deci) < 0.02, f"decimate 不應改變分數：full={full:.3f} deci={deci:.3f}"


def test_match_score_decimate_zero_when_too_short():
    ref = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    buf = np.zeros(100, np.float32)
    assert match_score(buf, ref, decimate=4) == 0.0


# --- match_score_multi：對多個參考取最高分（多種 chill 音效用）------------------
def test_match_score_multi_takes_max():
    sig_a = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    sig_b = np.sin(np.linspace(0, 120, 4000)).astype(np.float32)   # 不同頻率 = 不同 chill
    # buffer 含 sig_b → 對 [a, b] 取 max 應接近 b 的高分、遠高於只比 a
    buf = np.concatenate([np.zeros(1000, np.float32), sig_b, np.zeros(1000, np.float32)])
    score_a = match_score(buf, sig_a)
    multi = match_score_multi(buf, [sig_a, sig_b])
    assert multi > 0.9, f"含 sig_b 應命中 b：multi={multi:.3f}"
    assert multi >= score_a


def test_match_score_multi_empty_returns_zero():
    buf = np.ones(4000, np.float32)
    assert match_score_multi(buf, []) == 0.0


def test_match_score_multi_passes_decimate():
    # 確認 decimate 有套用到每個參考（不報錯、分數合理）
    ref = np.sin(np.linspace(0, 80, 8000)).astype(np.float32)
    buf = np.concatenate([np.zeros(2000, np.float32), ref, np.zeros(2000, np.float32)])
    assert match_score_multi(buf, [ref], decimate=4) > 0.9

def test_loudest_window_picks_high_energy_region():
    from miningbot.convert_audio import loudest_window
    sr = 1000
    data = np.zeros(3000, np.float32)
    data[1500:2000] = 5.0                         # 強訊號在 1.5s 附近
    clip = loudest_window(data, sr, 0.5)          # 0.5s = 500 樣本
    assert len(clip) == 500
    assert clip.max() == 5.0                      # 選到的窗包含高能量

def test_loudest_window_short_input_returned_asis():
    from miningbot.convert_audio import loudest_window
    data = np.ones(100, np.float32)
    out = loudest_window(data, 1000, 1.0)         # 視窗 1000 > 100
    assert len(out) == 100


# --- RisingEdgeDetector：音訊明顯變動就記錄（上升緣去抖動）---------------------
# 用於「只要音訊變動就記錄」：score 由低升到 ≥ 門檻時觸發一次，維持高檔不重複，
# 回落到 release 以下才 re-arm。避免每幀都存檔洗版。

def test_rising_edge_fires_once_on_crossing():
    d = RisingEdgeDetector(threshold=0.15)
    assert d.update(0.01) is False                # 雜訊
    assert d.update(0.20) is True                 # 升過門檻 → 觸發一次
    assert d.update(0.30) is False                # 維持高檔 → 不重複觸發
    assert d.update(0.25) is False


def test_rising_edge_rearms_after_release():
    d = RisingEdgeDetector(threshold=0.20, release=0.10)
    assert d.update(0.25) is True                 # 觸發
    assert d.update(0.12) is False                # 還沒回到 release 以下
    assert d.update(0.05) is False                # 回落 ≤ release → re-arm（這幀不觸發）
    assert d.update(0.25) is True                 # 再次升過門檻 → 又觸發


def test_rising_edge_default_release_is_half_threshold():
    d = RisingEdgeDetector(threshold=0.20)        # 未指定 release → 預設 threshold/2 = 0.10
    assert d.update(0.25) is True
    assert d.update(0.11) is False                # > 0.10，仍 armed=False
    assert d.update(0.09) is False                # ≤ 0.10 → re-arm
    assert d.update(0.25) is True


def test_rising_edge_starts_armed_below_threshold():
    # 一開始就在門檻上方不應觸發（沒有「上升」緣）——需先看到低於 release 才 arm...
    # 設計選擇：初始 armed=True，故第一次就 ≥ 門檻會觸發（視為一次變動）。
    d = RisingEdgeDetector(threshold=0.15)
    assert d.update(0.50) is True                 # 啟動即高 → 當作一次變動觸發


# --- AdaptiveSpikeDetector：安靜基準線 + 相對響度尖峰上升緣觸發 -----------------
from miningbot.audio import AdaptiveSpikeDetector


def _mk_detector(spike_factor=3.0, warmup_samples=2, min_floor=1.0, baseline_alpha=0.9):
    return AdaptiveSpikeDetector(spike_factor=spike_factor, baseline_alpha=baseline_alpha,
                                 min_floor=min_floor, warmup_samples=warmup_samples)


def test_spike_triggers_once_after_quiet_baseline():
    d = _mk_detector()
    # 暖機 2 次 + 幾次安靜，基準線 ~1
    for _ in range(5):
        assert d.update(1.0) is False
    # 一記尖峰
    assert d.update(10.0) is True


def test_spike_sustained_loud_triggers_only_once():
    d = _mk_detector()
    for _ in range(5):
        d.update(1.0)
    assert d.update(10.0) is True          # 第一次升起
    assert d.update(10.0) is False         # 持續高檔不重複
    assert d.update(10.0) is False


def test_spike_suppressed_during_warmup():
    d = _mk_detector(warmup_samples=3)
    assert d.update(10.0) is False         # 暖機期內尖峰不觸發
    assert d.update(10.0) is False
    assert d.update(10.0) is False


def test_spike_baseline_not_inflated_by_chime():
    # 鈴聲不得把基準線拉高到後續同樣尖峰被抑制：安靜→尖峰→回安靜(re-arm)→再尖峰 應再觸發
    d = _mk_detector()
    for _ in range(5):
        d.update(1.0)
    assert d.update(10.0) is True
    for _ in range(5):                     # 回落安靜，re-arm、基準線續更回 ~1
        d.update(1.0)
    assert d.update(10.0) is True          # 第二記仍觸發


def test_spike_min_floor_blocks_pure_silence_jitter():
    d = _mk_detector(spike_factor=3.0, min_floor=1.0)
    # 純靜音的微小抖動：rms 都遠小於 min_floor → ratio 恆小 → 不觸發
    for v in [0.01, 0.05, 0.02, 0.08, 0.03, 0.09]:
        assert d.update(v) is False


# --- ResetChimeRecorder：尖峰觸發後 pre/post-roll 存短片段 ----------------------
from miningbot.audio import ResetChimeRecorder


class _StubDetector:
    """在指定的第 N 次 feed（1-based）回報觸發，其餘 False。baseline 固定 0。"""
    def __init__(self, fire_on):
        self.fire_on = set(fire_on)
        self._n = 0
        self.baseline = 0.0
    def update(self, rms):
        self._n += 1
        return self._n in self.fire_on
    def reset(self):
        self._n = 0


def _mk_recorder(detector, saved, **kw):
    # sample_rate=10, window_s=1.0 → 10 樣本；chunk_seconds=0.1, post_roll_s=0.3 → 3 chunk
    def save_fn(path, samples, sr):
        saved.append(samples.copy())
    params = dict(sample_rate=10, window_s=1.0, post_roll_s=0.3, chunk_seconds=0.1,
                  detector=detector, out_dir="/unused", max_clips=20, save_fn=save_fn)
    params.update(kw)
    return ResetChimeRecorder(**params)


def test_recorder_saves_once_with_postroll_containing_spike():
    saved = []
    det = _StubDetector(fire_on=[4])          # 第 4 個 chunk 觸發
    rec = _mk_recorder(det, saved)
    seq = [0.0, 0.0, 0.0, 9.0, 0.0, 0.0, 0.0, 0.0]  # 尖峰在 index3(第4個)
    for v in seq:
        rec.feed(np.array([v], np.float32))
    assert len(saved) == 1                    # 恰存一次
    buf = saved[0]
    assert len(buf) == 10                     # window = sample_rate*window_s
    assert 9.0 in buf                         # 尖峰樣本落在片段內
    assert buf[-1] == 0.0                     # 尾端是 post-roll 的安靜（非切在尖峰當下）


def test_recorder_respects_max_clips():
    saved = []
    det = _StubDetector(fire_on=range(1, 100))   # 每個 chunk 都觸發
    rec = _mk_recorder(det, saved, post_roll_s=0.1, max_clips=2)  # post_roll=1 chunk
    for _ in range(50):
        rec.feed(np.array([5.0], np.float32))
    assert len(saved) == 2                    # 達上限即停


def test_recorder_reset_calls_detector_reset():
    saved = []
    det = _StubDetector(fire_on=[1])
    rec = _mk_recorder(det, saved)
    rec.feed(np.array([1.0], np.float32))
    rec.reset()
    assert det._n == 0                        # detector 已重置
