"""把 chill 音檔（mp3 等）轉成比對用的 assets/chill_reference.wav。

- 轉單聲道、48kHz
- 自動裁出能量最強的 1 秒（boom 主體），確保比偵測窗（audio_window_seconds=1.5）短

用法：
    python -m miningbot.convert_audio "C:\\Users\\you\\Downloads\\chill.mp3"
需要 imageio-ffmpeg（已在 requirements）。
"""
import argparse
import os
import subprocess
import tempfile

import numpy as np
from scipy.io import wavfile

TARGET_SR = 48000
CLIP_SECONDS = 1.0


def _ffmpeg_decode(src: str, dst_wav: str, sr: int):
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([exe, "-y", "-i", src, "-ac", "1", "-ar", str(sr), dst_wav],
                   check=True, capture_output=True)


def loudest_window(data: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    """回傳能量最強的 `seconds` 秒片段；若音檔本來就比較短，原樣回傳。"""
    win = int(sr * seconds)
    if len(data) <= win:
        return data
    sq = data.astype(np.float64) ** 2
    csum = np.concatenate([[0.0], np.cumsum(sq)])
    sums = csum[win:] - csum[:-win]               # 每個起點的窗能量
    start = int(np.argmax(sums))
    return data[start:start + win]


def convert(src: str, dst: str = "assets/chill_reference.wav",
            sr: int = TARGET_SR, seconds: float = CLIP_SECONDS) -> str:
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_wav = os.path.join(tmp, "full.wav")
        _ffmpeg_decode(src, tmp_wav, sr)
        fsr, data = wavfile.read(tmp_wav)
    if data.ndim > 1:
        data = data.mean(axis=1).astype(data.dtype)
    clip = loudest_window(data, fsr, seconds)
    wavfile.write(dst, fsr, clip)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="來源音檔（mp3 等）")
    ap.add_argument("--dst", default="assets/chill_reference.wav")
    ap.add_argument("--seconds", type=float, default=CLIP_SECONDS)
    args = ap.parse_args()
    out = convert(args.src, args.dst, seconds=args.seconds)
    sr, data = wavfile.read(out)
    print(f"OK -> {out}  ({len(data)} samples @ {sr}Hz = {len(data)/sr:.2f}s)")


if __name__ == "__main__":
    main()
