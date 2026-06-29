"""add_chill_ref 去重邏輯測試（TDD）。

自動把實錄 chill 升級成多參考集——核心是「這片是不是新的 chill 音效」判斷，
避免把同一種 chill 一直重複加入（拖慢比對、無增益）。
"""
import os

import numpy as np
from miningbot.add_chill_ref import is_distinct_chill, scan_sources


def test_distinct_when_no_existing_refs():
    clip = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    assert is_distinct_chill(clip, [], dup_threshold=0.6) is True


def test_not_distinct_when_matches_existing():
    sig = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    # 同一種音效（自己對自己 ~1.0）→ 不該重複加入
    assert is_distinct_chill(sig, [sig], dup_threshold=0.6) is False


def test_distinct_when_different_sound():
    a = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    b = np.sin(np.linspace(0, 200, 4000)).astype(np.float32)   # 不同頻率 = 不同 chill
    # b 對既有 [a] 的最高分低於門檻 → 視為新音效，值得加入
    assert is_distinct_chill(b, [a], dup_threshold=0.6) is True


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


def test_scan_sources_recurses_into_audio_subdir(tmp_path):
    """--scan 必須找到 audio/ 子夾裡的取樣（2026-06-29 分類後新位置），
    不能只看舊的扁平 logs/snapshots/。"""
    snap = tmp_path / "snapshots"
    _touch(str(snap / "audio" / "audiochg_20260629_205139_s18_miss.wav"))
    _touch(str(snap / "audiochg_20260629_013442_s15_miss.wav"))   # 舊扁平位置也要找到
    found = scan_sources(str(snap))
    names = {os.path.basename(p) for p in found}
    assert "audiochg_20260629_205139_s18_miss.wav" in names
    assert "audiochg_20260629_013442_s15_miss.wav" in names


def test_scan_sources_includes_confirmed_chills_first(tmp_path):
    """confirmed chill（chill_audio_*）是最安全的參考來源，應一併納入並排在
    audiochg_*（含可能是雜訊的 _miss）之前，當作去重的種子。"""
    snap = tmp_path / "snapshots"
    _touch(str(snap / "audio" / "chill_audio_20260629_021105.wav"))
    _touch(str(snap / "audio" / "audiochg_20260629_205139_s18_miss.wav"))
    found = scan_sources(str(snap))
    names = [os.path.basename(p) for p in found]
    assert "chill_audio_20260629_021105.wav" in names
    assert "audiochg_20260629_205139_s18_miss.wav" in names
    assert names.index("chill_audio_20260629_021105.wav") < names.index(
        "audiochg_20260629_205139_s18_miss.wav")
