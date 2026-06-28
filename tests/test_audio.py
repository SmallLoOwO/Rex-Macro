import numpy as np
from miningbot.audio import match_score, detect, RisingEdgeDetector

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
