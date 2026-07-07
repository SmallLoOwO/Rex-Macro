"""把實錄的 chill 片段升級成多參考集 assets/chill_refs/（自動去重）。

**為什麼存在**：實測同樣是清楚的 chill，對單一參考檔分數飄 0.15-0.87（至少 3 種不同
chill 音效），單一參考必漏。改用多參考取最高分後，每種 chill 至少完美命中自己的參考。
這支工具讓「把漏抓的 chill 升級成參考」變一行——錄音器（audio_event_record）已在
logs/snapshots/ 留下 audiochg_*.wav，挑漏抓（_miss）且清楚的丟進來即可。

**自動去重**：抽 loudest 1.0s 後，對現有參考取最高分；太像（≥ dup_threshold）就跳過，
只加「新音效」，避免參考集塞滿同種 chill 拖慢比對。

用法：
    # 加單一片段（通常是 logs/snapshots 裡漏抓的 audiochg_*_miss.wav）
    python -m miningbot.add_chill_ref logs/snapshots/audiochg_20260628_205006_s22_miss.wav

    # 遞迴掃 logs/snapshots（含 audio/ 子夾）的 chill_audio_*（confirmed，安全種子）與
    # audiochg_*（含 _miss），自動挑 distinct 的加入
    python -m miningbot.add_chill_ref --scan
"""
import argparse
import glob
import os

import numpy as np
from scipy.io import wavfile

from .audio import match_score_multi, save_wav
from .convert_audio import loudest_window
from .config import DEFAULT as cfg

CLIP_SECONDS = 1.0


def best_match_vs_refs(clip, existing_refs, decimate: int = 1) -> float:
    """候選 clip 對現有參考集的最高 match（0 = 無參考）。

    **要點：兩段等長 clip 直接比沒有滑動空間對齊 → 同一種 chill 只要時間平移就誤判成
    「不同」**。故比對前把候選 clip 兩側補零給參考滑動對齊（時間平移仍能命中）。
    """
    if not existing_refs:
        return 0.0
    pad = len(clip) // 2                       # 兩側各補半長 → 參考可滑動對齊平移版本
    padded = np.concatenate([np.zeros(pad, clip.dtype), clip, np.zeros(pad, clip.dtype)])
    return match_score_multi(padded, existing_refs, decimate=decimate)


def is_distinct_chill(clip, existing_refs, dup_threshold: float = 0.6,
                      decimate: int = 1) -> bool:
    """clip 對現有參考的最高 match < dup_threshold → 視為新的 chill 音效（值得加入）。

    無現有參考 → 一律加入。同一種 chill 自己對自己 ~1.0、不同種 ~0.2-0.3，
    故 0.6 能乾淨分開「重複」與「新音效」。
    """
    if not existing_refs:
        return True
    return best_match_vs_refs(clip, existing_refs, decimate) < dup_threshold


def _load_mono(path: str) -> tuple[np.ndarray, int]:
    sr, d = wavfile.read(path)
    if d.ndim > 1:
        d = d.mean(axis=1)
    return d.astype(np.float32), sr


def _existing_refs(refs_dir: str) -> list:
    refs = []
    for p in sorted(glob.glob(os.path.join(refs_dir, "*.wav"))):
        d, _ = _load_mono(p)
        refs.append(d)
    return refs


def scan_sources(snapshots_dir: str, include_miss: bool = False) -> list:
    """收集 snapshots 夾下的 chill 取樣（**遞迴**，含 2026-06-29 分類後的 audio/ 子夾）。

    舊版只 glob 扁平的 logs/snapshots/audiochg_*.wav，分類後檔案改放 audio/ 子夾 → 掃不到。
    這裡用 recursive glob 同時涵蓋舊扁平位置與新子夾。

    **預設只收 confirmed（chill_audio_*，確定觸發過的安全來源）**——2026-07-04 實測教訓：
    盲掃 audiochg 把 6 個 _miss 升級成參考，對照實驗證實它們對 25 個 confirmed 真 chill
    分數零貢獻（原參考已全覆蓋）、對任何 confirmed 錄音最高只像 0.16-0.48＝非 chill 雜訊，
    純假觸發風險（假觸發＝白跑一輪採集＋誤發人工警報）。「與現有參考不像」無法區分
    「新 chill 家族」和「雜訊」，去重種子順序擋不住這洞。audiochg 來源須顯式
    include_miss=True（CLI --include-miss）且建議人工聽過再收；confirmed 在前當去重種子。
    """
    confirmed = sorted(glob.glob(os.path.join(snapshots_dir, "**", "chill_audio_*.wav"),
                                 recursive=True))
    if not include_miss:
        return confirmed
    changes = sorted(glob.glob(os.path.join(snapshots_dir, "**", "audiochg_*.wav"),
                               recursive=True))
    return confirmed + changes


def add_ref(src_wav: str, refs_dir: str = None, dup_threshold: float = 0.6,
            decimate: int = None) -> str | None:
    """從 src_wav 抽 loudest 1.0s，去重後存入 refs_dir。回傳新檔路徑（跳過則 None）。"""
    refs_dir = refs_dir or cfg.chill_refs_dir
    decimate = decimate if decimate is not None else cfg.audio_match_decimate
    os.makedirs(refs_dir, exist_ok=True)
    data, sr = _load_mono(src_wav)
    clip = loudest_window(data, sr, CLIP_SECONDS)
    existing = _existing_refs(refs_dir)
    best = best_match_vs_refs(clip, existing, decimate)
    if best >= dup_threshold:
        print(f"跳過（與現有參考太像，max={best:.2f} >= {dup_threshold}）：{src_wav}")
        return None
    base = "chill_" + os.path.splitext(os.path.basename(src_wav))[0].replace("audiochg_", "")
    out = os.path.join(refs_dir, base + ".wav")
    save_wav(out, clip, sr)
    print(f"加入參考：{out}")
    return out


def main():
    ap = argparse.ArgumentParser(description="把實錄 chill 升級成多參考集（自動去重）")
    ap.add_argument("src", nargs="*", help="來源 WAV（通常是 logs/snapshots/audiochg_*.wav）")
    ap.add_argument("--scan", action="store_true",
                    help="掃 logs/snapshots 的 confirmed chill（chill_audio_*）自動挑 distinct 加入")
    ap.add_argument("--include-miss", action="store_true",
                    help="--scan 連 audiochg_*（含 _miss）一起掃——可能是非 chill 雜訊，"
                         "會害假觸發採集，建議人工聽過再用")
    ap.add_argument("--refs-dir", default=cfg.chill_refs_dir)
    ap.add_argument("--dup-threshold", type=float, default=0.6)
    args = ap.parse_args()

    srcs = list(args.src)
    if args.scan:
        srcs += scan_sources(os.path.join(cfg.log_dir, "snapshots"),
                             include_miss=args.include_miss)
    if not srcs:
        ap.error("請給來源 WAV 或用 --scan")

    added = 0
    for s in srcs:
        # 逐一加入：每加一個就會被後續的去重看到（同種只會進一個）
        if add_ref(s, args.refs_dir, args.dup_threshold):
            added += 1
    print(f"\n完成：新增 {added} 個參考 -> {args.refs_dir}")


if __name__ == "__main__":
    main()
