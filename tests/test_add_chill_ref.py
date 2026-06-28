"""add_chill_ref 去重邏輯測試（TDD）。

自動把實錄 chill 升級成多參考集——核心是「這片是不是新的 chill 音效」判斷，
避免把同一種 chill 一直重複加入（拖慢比對、無增益）。
"""
import numpy as np
from miningbot.add_chill_ref import is_distinct_chill


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
