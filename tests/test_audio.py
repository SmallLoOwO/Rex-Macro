import numpy as np
from miningbot.audio import match_score, detect

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
