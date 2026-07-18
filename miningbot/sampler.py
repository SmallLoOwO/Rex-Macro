"""手動取樣檔案助手：編號截圖＋俯仰 sidecar。

用途：使用者看到「值得當樣本的畫面」（傳送面板視角、漏抓的追蹤框、新背景的
聊天框）留檔，之後直接以編號指名「用 007 當模板」（calibrate_surface --import）。
sidecar json 記俯仰偏移量——這讓「合適的仰角」變成可重現的數字（寫回 config）。

2026-07-17 起 R 鍵取樣視窗（Tk 小窗：俯仰歸位/微調＋截圖鈕）退役：
截圖改走 Discord 遙控器 📷（同樣落編號檔到 manual_snapshot_dir）、
俯仰控制改走回礦 `仰角 歸位`/`仰角 上|下 [px]` 指令。本模組只剩檔案層助手。
"""
import json
import os
import re
import time

_NUM_RE = re.compile(r"^(\d{3})\.png$")


def next_manual_index(existing_names) -> int:
    nums = [int(m.group(1)) for n in existing_names for m in [_NUM_RE.match(n)] if m]
    return max(nums, default=0) + 1


def save_sample(frame_bgr, out_dir: str, pitch_offset_px: int) -> str:
    """存編號截圖＋sidecar。回傳編號字串（如 "007"）。"""
    import cv2
    os.makedirs(out_dir, exist_ok=True)
    stem = f"{next_manual_index(os.listdir(out_dir)):03d}"
    cv2.imwrite(os.path.join(out_dir, f"{stem}.png"), frame_bgr)
    with open(os.path.join(out_dir, f"{stem}.json"), "w", encoding="utf-8") as f:
        json.dump({"pitch_offset_px": pitch_offset_px,
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)
    return stem
