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


# --- reset-chime 錄音窗（H045）：舊時間錨（arm 30s > banner 倒數 26~28s）＝鈴聲
# 永遠在窗外；改容量錨（與開場容量閘同訊號源），窗跨 RESET_WAIT/REENTRY ----
from miningbot.audio import capture_window_active, chime_capacity_armed


def test_chime_arm_on_low_capacity():
    # 真重置完成幀 Capacity 0%（2026-07-14 ep3 dir7 實機幀）
    assert chime_capacity_armed(0.0, 10.0) is True
    assert chime_capacity_armed(10.0, 10.0) is True     # 邊界含


def test_chime_not_armed_on_stale_or_high_capacity():
    # 凍結舊幀 78%（ep3 dir0）／重置前 100%：都不開窗
    assert chime_capacity_armed(78.0, 10.0) is False
    assert chime_capacity_armed(100.0, 10.0) is False


def test_chime_not_armed_when_capacity_unreadable():
    assert chime_capacity_armed(None, 10.0) is False


def test_capture_window_active_within_max():
    assert capture_window_active(100.0, 100.5, 120.0) is True
    # 窗跨進 REENTRY（H045 前離開 RESET_WAIT 即停錄＝實際窗只有 1~3s）
    assert capture_window_active(100.0, 219.0, 120.0) is True


def test_capture_window_closes_after_max():
    # 上限收口：REENTRY 等 Discord 指令可長達數十分鐘，遊戲音效會洗版 max_clips
    assert capture_window_active(100.0, 221.0, 120.0) is False


def test_capture_window_inactive_when_not_armed():
    assert capture_window_active(0.0, 999.0, 120.0) is False


# --- H060：防掛機 Space 自製跳躍音的 chill 靜音窗 ---------------------------
from miningbot.audio import chill_muted_after_antiafk
from miningbot.config import DEFAULT as _cfg


def test_chill_muted_right_after_antiafk_press():
    # 實機三次都是「按鍵後 2 秒」才被主迴圈取樣到 → 窗必須涵蓋 +2s
    assert chill_muted_after_antiafk(100.0, 102.0, 6.0) is True
    assert chill_muted_after_antiafk(100.0, 100.0, 6.0) is True    # 按下當幀


def test_chill_muted_through_measured_tail():
    # 2026-07-22 三次事件分數分別維持到按鍵後 +4s / +5s / +4s（滾動窗＋落地音）
    assert chill_muted_after_antiafk(100.0, 105.0, 6.0) is True


def test_chill_not_muted_after_window_closes():
    assert chill_muted_after_antiafk(100.0, 106.01, 6.0) is False
    # 下一次按鍵前的 15 分鐘空檔＝完全不影響真 chill
    assert chill_muted_after_antiafk(100.0, 900.0, 6.0) is False


def test_chill_not_muted_before_any_press():
    assert chill_muted_after_antiafk(0.0, 999.0, 6.0) is False


def test_chill_not_muted_for_past_timestamps():
    # now 早於 pressed_at（時鐘回跳/測試樁）不可誤靜音
    assert chill_muted_after_antiafk(100.0, 99.0, 6.0) is False


def test_default_mute_window_covers_measured_tail():
    # 門檻取值有實機依據：最長一次的尾巴是 +5s，預設須留邊際
    assert _cfg.antiafk_chill_mute_s >= 5.0
    # 但不可長到吃掉 15 分鐘保活週期的可觀測時間（<1%）
    assert _cfg.antiafk_chill_mute_s < _cfg.antiafk_interval_s * 0.01


# ── chill 上升緣／回落（spec 2026-07-30-prechill-evidence-cache-design.md B 段）──
# 為什麼要數上升緣：latest_score() 是滾動比對，同一聲 chill 會連續多個 tick 都在門檻上
# （2026-07-22 01:43:31~33 三秒七行是同一聲）。「一場響幾聲」只能由回落再上來的次數決定。

def _edges(samples, threshold=0.25):
    from miningbot.audio import chill_edges
    return chill_edges(samples, threshold)


def test_chill_edge_step_reports_rise_and_fall_once():
    from miningbot.audio import chill_edge_step
    assert chill_edge_step(False, 0.30, 0.25) == (True, "rise")
    assert chill_edge_step(True, 0.30, 0.25) == (True, "")      # 續在門檻上＝同一聲
    assert chill_edge_step(True, 0.10, 0.25) == (False, "fall")
    assert chill_edge_step(False, 0.10, 0.25) == (False, "")


def test_multiple_ticks_above_threshold_count_as_one_edge():
    """連續多 tick 在門檻上只算一次上升緣（07-22 三秒七行是同一聲）。"""
    samples = [(0.0, 0.01), (0.3, 0.31), (0.6, 0.44), (0.9, 0.38), (1.2, 0.02)]
    assert len(_edges(samples)) == 1


def test_two_separate_chills_give_two_edges():
    """實錄間隔：07-29 14:43:58 → 14:44:14 共 16 秒。"""
    samples = [(0.0, 0.40), (1.0, 0.02), (16.0, 0.37), (17.0, 0.01)]
    edges = _edges(samples)
    assert [e[0] for e in edges] == [0.0, 16.0]
    assert edges[0][2] is None            # 序列開頭就在門檻上＝沒有可比的回落
    assert edges[1][2] == 15.0            # 距上次回落（1.0）15 秒


def test_no_edge_when_never_above_threshold():
    assert _edges([(0.0, 0.10), (1.0, 0.24), (2.0, 0.0)]) == []


def test_count_chill_edges_debounces_short_dips():
    """回落沒維持滿 release_s 就又上來＝同一聲的抖動，不另計。"""
    from miningbot.audio import count_chill_edges
    samples = [(0.0, 0.40), (0.3, 0.02), (0.6, 0.41), (1.0, 0.01),
               (20.0, 0.38), (21.0, 0.0)]
    edges = _edges(samples)
    assert len(edges) == 3                       # 原始上升緣三個
    assert count_chill_edges(edges, 0.0) == 3    # release=0 ＝完全不去抖動
    assert count_chill_edges(edges, 2.0) == 2    # 0.3s 的短回落被吃掉
    assert count_chill_edges(edges, 25.0) == 1   # 連 19s 的真間隔都吃掉（過大門檻＝漏判）


def test_antiafk_muted_scores_never_produce_edges():
    """H060：防掛機 Space 的原地跳音效必須在上升緣判定**之前**被靜音，否則污染分布。"""
    from miningbot.audio import chill_edge_step, chill_muted_after_antiafk
    pressed_at, above, rises = 100.0, False, 0
    for ts, raw in [(101.0, 0.38), (102.0, 0.37), (103.0, 0.25), (120.0, 0.40)]:
        score = 0.0 if chill_muted_after_antiafk(pressed_at, ts, 6.0) else raw
        above, edge = chill_edge_step(above, score, 0.25)
        rises += edge == "rise"
    assert rises == 1          # 只有窗外那次真 chill 算數
