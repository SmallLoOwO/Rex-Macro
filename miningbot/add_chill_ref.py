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
import re
from datetime import datetime

import numpy as np
from scipy.io import wavfile

from .audio import match_score, match_score_multi, save_wav
from .convert_audio import loudest_window
from .config import DEFAULT as cfg

CLIP_SECONDS = 1.0


def best_match_vs_refs(buffer, existing_refs, decimate: int = 1) -> float:
    """候選**完整實錄窗**對現有參考集的最高 match（0 = 無參考）。

    `buffer` 要傳整個實錄窗（audio_window_seconds，1.5s），不是抽出的 1.0s 裁片——
    這樣量到的分數就是 runtime 當下會算出的那個分數，「跟現有參考夠像」才真的等於
    「runtime 已經認得出來、不必再收」。

    **不可補零（2026-07-21 修）**：舊版把等長裁片兩側補零來製造滑動對齊空間，但
    `match_score` 是逐窗用該窗自身能量正規化的，補零區窗能量趨近 0 → 分母趨近 0 →
    正規化相關度虛高。實機 101 對 chill_091：補零 0.816（被判重複跳過）vs 原窗
    0.242（連 0.25 觸發門檻都不到＝整輪漏抓）——虛高 3.4 倍，害真正會漏的新家族
    永遠進不了參考集。原本要解的「等長無滑動空間」問題不存在：實錄窗 1.5s 比參考
    1.0s 長，本來就有 0.5s 真實滑動空間。
    """
    if not existing_refs:
        return 0.0
    return match_score_multi(buffer, existing_refs, decimate=decimate)


def is_distinct_chill(buffer, existing_refs, dup_threshold: float = 0.6,
                      decimate: int = 1) -> bool:
    """buffer 對現有參考的最高 match < dup_threshold → 視為新的 chill 音效（值得加入）。

    無現有參考 → 一律加入。同一種 chill 自己對自己 ~1.0、不同種 ~0.2-0.3，
    故 0.6 能乾淨分開「重複」與「新音效」。

    `buffer` 同 `best_match_vs_refs`：傳完整實錄窗，量到的才是 runtime 的分數。
    """
    if not existing_refs:
        return True
    return best_match_vs_refs(buffer, existing_refs, decimate) < dup_threshold


def would_false_trigger(clip, negatives, ceiling: float = None,
                        decimate: int = 1) -> bool:
    """這個候選參考會不會害已知的非 chill 音效跨過觸發門檻？

    **不是每個 confirmed 實錄都能當參考**：`loudest_window` 抽的是「最大聲的 1.0s」，
    chill 響的當下若有更大聲的非 chill 音效重疊，抽出來的就是那個雜音。2026-07-21
    實測 H040 的裁片把每 ~15 分鐘一次的週期性音效從 0.180 推到 0.507＝每 15 分鐘
    假觸發一次（白跑一輪採集＋誤發人工警報）。

    負樣本 = 沒有對應 confirmed chill 的 audiochg 錄音（見 collect_negatives）。
    """
    if not negatives:
        return False
    ceiling = ceiling if ceiling is not None else cfg.chill_ref_negative_ceiling
    return any(match_score(neg, clip, decimate) >= ceiling for neg in negatives)


def _stamp(name: str):
    m = re.search(r"(\d{8})_(\d{6})", name)
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S") if m else None


def collect_negatives(snapshots_dir: str, pair_window_s: float = 3.0) -> list:
    """撈「已知非 chill」錄音：沒有對應 confirmed chill 的 audiochg_*。

    audiochg 是 score 越過觀察門檻 0.15 但沒到觸發門檻的錄音，檔名的 `_miss`
    只代表「錄的當下沒觸發」，**不代表不是 chill**：實測 44 個裡有 15 個跟某個
    confirmed chill 同時刻（±3s）——那是同一次 chill 的上升緣，是**正樣本**。
    真正的負樣本是剩下 29 個，其中 28 個是每 ~15 分鐘規律出現的週期性遊戲音效。
    """
    confirmed = scan_sources(snapshots_dir)
    ctimes = [t for t in (_stamp(os.path.basename(p)) for p in confirmed) if t]
    out = []
    for p in sorted(glob.glob(os.path.join(snapshots_dir, "**", "*audiochg_*.wav"),
                              recursive=True)):
        t = _stamp(os.path.basename(p))
        if t is None:
            continue
        near = min((abs((t - c).total_seconds()) for c in ctimes), default=float("inf"))
        if near > pair_window_s:               # 配不到 confirmed → 不是 chill
            out.append(p)
    return out


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

    **檔名前綴（2026-07-21 修）**：confirmed 實錄現在帶 harvest_id 前綴
    （`087_chill_audio_*`、早期 `H014_chill_audio_*`），舊 glob `chill_audio_*.wav`
    少了前導 `*` → 實機檔案一個都不匹配，`--scan` 永遠「新增 0 個」。安全預設變成
    no-op、唯一掃得到東西的是 include_miss（已知會收雜訊）＝安全設計被整個反轉；
    參考集因此自 07-04 凍結在 8 個。兩個 pattern 都留前導 `*`，命名再變時不重演。
    """
    confirmed = sorted(glob.glob(os.path.join(snapshots_dir, "**", "*chill_audio_*.wav"),
                                 recursive=True))
    if not include_miss:
        return confirmed
    changes = sorted(glob.glob(os.path.join(snapshots_dir, "**", "*audiochg_*.wav"),
                               recursive=True))
    return confirmed + changes


def add_ref(src_wav: str, refs_dir: str = None, dup_threshold: float = 0.6,
            decimate: int = None, negatives=None) -> str | None:
    """從 src_wav 抽 loudest 1.0s，去重＋假觸發守門後存入 refs_dir。

    回傳新檔路徑（跳過則 None）。兩道關卡方向相反、缺一不可：
      1. 去重：比**完整實錄** `data`（runtime 同款量測）——夠像＝runtime 已認得，不必收
      2. 假觸發守門：比抽出的 `clip` 對 `negatives`——會把非 chill 推過門檻就拒收
    存下來的是 `clip`（參考要緊），量測用 `data`（要跟 runtime 一致），兩者刻意不同。
    """
    refs_dir = refs_dir or cfg.chill_refs_dir
    decimate = decimate if decimate is not None else cfg.audio_match_decimate
    os.makedirs(refs_dir, exist_ok=True)
    data, sr = _load_mono(src_wav)
    clip = loudest_window(data, sr, CLIP_SECONDS)
    existing = _existing_refs(refs_dir)
    best = best_match_vs_refs(data, existing, decimate)
    if best >= dup_threshold:
        print(f"跳過（與現有參考太像，max={best:.2f} >= {dup_threshold}）：{src_wav}")
        return None
    if would_false_trigger(clip, negatives, decimate=decimate):
        worst = max(match_score(neg, clip, decimate) for neg in negatives)
        print(f"拒收（會讓已知非 chill 音效衝到 {worst:.2f} "
              f">= {cfg.chill_ref_negative_ceiling}，等於製造假觸發）：{src_wav}")
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
    ap.add_argument("--snapshots-dir", default=None,
                    help="快照根目錄（預設 cfg.log_dir/snapshots）。⚠ pythonw(Store 版 Python) "
                         "跑的實機證據會被 MSIX 重導到 "
                         r"%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_*"
                         r"\LocalCache\Local\RexMacro\logs\snapshots，用 uv run 執行本工具時"
                         "要顯式指到那裡，否則掃不到任何實機錄音")
    ap.add_argument("--no-screen-negatives", action="store_true",
                    help="關掉假觸發守門（不建議：H040 那類被雜音污染的裁片會讓週期性"
                         "音效每 15 分鐘假觸發一次）")
    args = ap.parse_args()

    snapshots = args.snapshots_dir or os.path.join(cfg.log_dir, "snapshots")
    srcs = list(args.src)
    if args.scan:
        found = scan_sources(snapshots, include_miss=args.include_miss)
        if not found:
            print(f"⚠ {snapshots} 掃不到任何錄音——確認路徑（實機證據可能在 MSIX "
                  f"LocalCache，見 --snapshots-dir 說明）")
        srcs += found
    if not srcs:
        ap.error("請給來源 WAV 或用 --scan")

    negatives = None
    if not args.no_screen_negatives and os.path.isdir(snapshots):
        neg_paths = collect_negatives(snapshots)
        negatives = [_load_mono(p)[0] for p in neg_paths]
        print(f"假觸發守門：載入 {len(negatives)} 個已知非 chill 樣本"
              f"（ceiling={cfg.chill_ref_negative_ceiling}）\n")

    added = 0
    for s in srcs:
        # 逐一加入：每加一個就會被後續的去重看到（同種只會進一個）
        if add_ref(s, args.refs_dir, args.dup_threshold, negatives=negatives):
            added += 1
    print(f"\n完成：新增 {added} 個參考 -> {args.refs_dir}")


if __name__ == "__main__":
    main()
