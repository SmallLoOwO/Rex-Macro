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
