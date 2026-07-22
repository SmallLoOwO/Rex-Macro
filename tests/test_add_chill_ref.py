"""add_chill_ref 去重邏輯測試（TDD）。

自動把實錄 chill 升級成多參考集——核心是「這片是不是新的 chill 音效」判斷，
避免把同一種 chill 一直重複加入（拖慢比對、無增益）。
"""
import os

import numpy as np
from scipy.io import wavfile

from miningbot.add_chill_ref import (
    CLIP_SECONDS,
    best_match_vs_refs,
    is_distinct_chill,
    scan_sources,
    would_false_trigger,
)
from miningbot.audio import match_score
from miningbot.config import DEFAULT as cfg
from miningbot.convert_audio import loudest_window

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "chill")


def _load_mono(name):
    sr, d = wavfile.read(os.path.join(FIXTURES, name))
    if d.ndim > 1:
        d = d.mean(axis=1)
    return d.astype(np.float32)


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


def test_dedupe_uses_runtime_measure_not_padded_clip():
    """去重必須用 **runtime 同款量測**（完整 1.5s 實錄窗對參考），不可補零。

    實機 101（2026-07-21）：這是一個既有參考蓋不到的新 chill 家族，runtime 對整個
    參考集只有 0.242——**低於觸發門檻 0.25，整輪會被漏掉**。但舊去重法把抽出的
    1.0s 裁片兩側補零再比，同一對組合卻算出 0.816 → 判定「與現有參考太像」而跳過，
    於是這個會漏抓的家族永遠進不了參考集。

    成因：`match_score` 逐窗用該窗自身能量正規化；補零區窗能量趨近 0 → 分母趨近 0
    → 正規化相關度虛高。補零的原意（給等長裁片滑動對齊空間）本身合理，但完整實錄
    窗(1.5s) 比參考(1.0s) 長，本來就有 0.5s 的真實滑動空間，不需要補零。

    兩側夾（101 對 chill_091，decimate=8）：
        補零(舊)     0.816  → 被判重複
        原窗(runtime) 0.242  → 實際上連觸發門檻都不到
    """
    cand = _load_mono("h101_new_family_recording.wav")
    ref = _load_mono("ref_091_existing_family.wav")
    k = cfg.audio_match_decimate

    runtime_score = best_match_vs_refs(cand, [ref], decimate=k)
    assert runtime_score < cfg.audio_match_threshold, (
        f"101 對既有參考的 runtime 分數應低於觸發門檻（實測 0.242），得到 {runtime_score:.3f}")

    # 因為 runtime 根本認不出來 → 必須判定為新家族並收進參考
    assert is_distinct_chill(cand, [ref], dup_threshold=0.6, decimate=k) is True


def test_reference_that_would_false_trigger_is_rejected():
    """會讓已知非 chill 音效跨過觸發門檻的候選，**不可以**收成參考。

    2026-07-21 實測：不是每個 confirmed 實錄都能當參考。`loudest_window` 抽的是
    「最大聲的 1.0s」，若 chill 響的當下剛好有更大聲的非 chill 音效重疊，抽出來的
    就是那個雜音。H040 的裁片正是如此——把每 ~15 分鐘出現一次的週期性音效（s18 族）
    從 0.180 一路推到 0.507，等於每 15 分鐘假觸發一次（假觸發＝白跑一輪採集＋
    誤發人工警報）。

    兩側夾（decimate=8）：
        安全參考集下，s18 負樣本最高            0.180
        收了 H040 之後，同一個負樣本            0.507   → 遠超觸發門檻 0.25
    """
    cand_full = _load_mono("h040_contaminated_candidate.wav")
    negative = _load_mono("neg_s18_periodic.wav")
    k = cfg.audio_match_decimate

    clip = loudest_window(cand_full, cfg.audio_sample_rate, CLIP_SECONDS)
    lifted = match_score(negative, clip, k)
    assert lifted >= cfg.audio_match_threshold, (
        f"H040 裁片本來就會把負樣本推過門檻（實測 0.507），得到 {lifted:.3f}")

    assert would_false_trigger(clip, [negative], decimate=k) is True, (
        "會害假觸發的候選必須被守門擋下")


def test_safe_reference_passes_negative_screen():
    """反向：正常的 chill 參考不會碰到負樣本，守門不可誤擋。"""
    ref = _load_mono("ref_091_existing_family.wav")
    negative = _load_mono("neg_s18_periodic.wav")
    k = cfg.audio_match_decimate
    assert match_score(negative, ref, k) < cfg.chill_ref_negative_ceiling
    assert would_false_trigger(ref, [negative], decimate=k) is False


# --- H060：「週期性非 chill 音效」的真身＝bot 自己的防掛機 Space（原地跳）-----
# neg_s18_periodic 那族一直被當成不明的遊戲音效，2026-07-22 對上 miningbot.log
# 才發現每一筆都緊跟在「防掛機：按 Space」之後——是 bot 自己按出來的跳躍音。
# 07-22 這場的跳躍音變體分數比 s18 高一截（0.18 → 0.37），故另立負樣本。


def test_antiafk_jump_is_a_negative_not_a_chill():
    """防掛機跳躍音在安全參考下必須遠低於觸發門檻（兩側夾的負樣本側）。"""
    ref = _load_mono("ref_091_existing_family.wav")
    negative = _load_mono("neg_antiafk_jump_s37.wav")
    k = cfg.audio_match_decimate
    assert match_score(negative, ref, k) < cfg.chill_ref_negative_ceiling
    assert would_false_trigger(ref, [negative], decimate=k) is False


def test_rising_edge_clip_that_lifts_antiafk_jump_is_rejected():
    """上升緣錄音抽出的裁片會把防掛機跳躍音推過門檻 → 守門必須擋下。

    2026-07-21 校準（ae3bd16）把 7 個 `audiochg_*`（chill 的**上升緣**錄音）收成
    參考。`loudest_window` 抽「最大聲的 1.0s」，但上升緣窗裡 chill 還沒到，抽到的
    是背景音——與 H040 同一種污染，只是來源是上升緣而非重疊雜音。

    後果（H060，2026-07-22 實機）：防掛機每 15 分鐘按一次 Space 保活，跳躍音被
    這個參考認成 chill。當日 22 筆相位鎖定的跳躍音有 19 筆越過 0.25 門檻，
    REENTRY 中三次全部在按鍵後 2 秒發出 spawn chill 誤報。

    兩側夾（decimate=8）：
        安全參考集下，防掛機跳躍音           0.180
        收了這個上升緣裁片之後，同一個負樣本   0.375   → 遠超觸發門檻 0.25
    """
    clip = _load_mono("contaminated_rising_edge_101.wav")     # 已是抽出的 1.0s 裁片
    negative = _load_mono("neg_antiafk_jump_s37.wav")
    k = cfg.audio_match_decimate

    lifted = match_score(negative, clip, k)
    assert lifted >= cfg.audio_match_threshold, (
        f"這個裁片本來就會把防掛機跳躍音推過門檻（實測 0.375），得到 {lifted:.3f}")

    assert would_false_trigger(clip, [negative], decimate=k) is True, (
        "上升緣污染裁片必須被假觸發守門擋下，否則 --scan 會再把它收回參考集")


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


def test_scan_sources_recurses_into_audio_subdir(tmp_path):
    """--scan 必須找到 audio/ 子夾裡的取樣（2026-06-29 分類後新位置），
    不能只看舊的扁平 logs/snapshots/。"""
    snap = tmp_path / "snapshots"
    _touch(str(snap / "audio" / "audiochg_20260629_205139_s18_miss.wav"))
    _touch(str(snap / "audiochg_20260629_013442_s15_miss.wav"))   # 舊扁平位置也要找到
    found = scan_sources(str(snap), include_miss=True)
    names = {os.path.basename(p) for p in found}
    assert "audiochg_20260629_205139_s18_miss.wav" in names
    assert "audiochg_20260629_013442_s15_miss.wav" in names


def test_scan_sources_includes_confirmed_chills_first(tmp_path):
    """confirmed chill（chill_audio_*）是最安全的參考來源，應一併納入並排在
    audiochg_*（含可能是雜訊的 _miss）之前，當作去重的種子。"""
    snap = tmp_path / "snapshots"
    _touch(str(snap / "audio" / "chill_audio_20260629_021105.wav"))
    _touch(str(snap / "audio" / "audiochg_20260629_205139_s18_miss.wav"))
    found = scan_sources(str(snap), include_miss=True)
    names = [os.path.basename(p) for p in found]
    assert "chill_audio_20260629_021105.wav" in names
    assert "audiochg_20260629_205139_s18_miss.wav" in names
    assert names.index("chill_audio_20260629_021105.wav") < names.index(
        "audiochg_20260629_205139_s18_miss.wav")


def test_scan_sources_finds_harvest_id_prefixed_confirmed(tmp_path):
    """confirmed 實錄檔名帶 harvest_id 前綴（`087_chill_audio_*`，079 快照修復後的
    現行命名）也必須掃得到。

    舊 glob `chill_audio_*.wav` 少了前綴萬用字元 → 對實機檔名一個都不匹配，
    `--scan` 永遠回報「新增 0 個」。安全預設變成 no-op，而唯一掃得到東西的模式
    是 `--include-miss`（2026-07-04 實測證實會收進雜訊、害假觸發）——安全設計被
    整個反轉。參考集因此自 07-04 凍結在 8 個，新 chill 家族從未進參考，觸發分數
    貼著門檻 0.25（實機 091/101 只有 0.270/0.271，差一點就整輪漏抓）。
    """
    snap = tmp_path / "snapshots"
    _touch(str(snap / "audio" / "087_chill_audio_20260719_150719.wav"))
    _touch(str(snap / "audio" / "H014_chill_audio_20260703_014321.wav"))
    names = {os.path.basename(p) for p in scan_sources(str(snap))}
    assert "087_chill_audio_20260719_150719.wav" in names
    assert "H014_chill_audio_20260703_014321.wav" in names


def test_scan_sources_excludes_miss_by_default(tmp_path):
    """--scan 預設**只收 confirmed**（2026-07-04 實測教訓）：盲掃把 6 個 audiochg
    _miss 升級成參考，對照實驗證實它們對 25 個 confirmed 真 chill 分數零貢獻、
    對任何 confirmed 錄音最高只像 0.16-0.48＝非 chill 雜訊，只帶假觸發風險。
    audiochg 來源須顯式 --include-miss 且人工聽過再收。"""
    snap = tmp_path / "snapshots"
    _touch(str(snap / "audio" / "chill_audio_20260629_021105.wav"))
    _touch(str(snap / "audio" / "audiochg_20260629_205139_s18_miss.wav"))
    names = {os.path.basename(p) for p in scan_sources(str(snap))}
    assert "chill_audio_20260629_021105.wav" in names
    assert "audiochg_20260629_205139_s18_miss.wav" not in names
