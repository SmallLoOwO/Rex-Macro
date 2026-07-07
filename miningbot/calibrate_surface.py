"""校準 CLI：把 R 鍵手動截圖變成 re-entry 需要的資產。

用法：
  python -m miningbot.calibrate_surface --import 007
      開 007.png，cv2.selectROI 框出面板 → 存 assets/surface/panel_007.png
  python -m miningbot.calibrate_surface --brightness 007
      印該圖 stuck_region 的平均亮度（收集「礦內 vs 地表」兩組樣本、
      人工取中間值填 config.reentry_mine_max_brightness）
"""
import argparse
import os

import cv2
import numpy as np

from .config import DEFAULT as cfg


def clamp_roi(roi, w, h):
    """selectROI 拖出框可能超出圖框，夾回合法範圍（純函式）。"""
    x, y, rw, rh = roi
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    rw = max(1, min(int(rw), w - x))
    rh = max(1, min(int(rh), h - y))
    return (x, y, rw, rh)


def _load(stem: str):
    path = os.path.join(cfg.manual_snapshot_dir, f"{stem}.png")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"找不到 {path}（先用 R 鍵截圖）")
    return img


def _import(stem: str):
    img = _load(stem)
    roi = cv2.selectROI("框出傳送面板（Enter 確認、c 取消）", img, showCrosshair=True)
    cv2.destroyAllWindows()
    if roi[2] == 0 or roi[3] == 0:
        raise SystemExit("已取消")
    x, y, w, h = clamp_roi(roi, img.shape[1], img.shape[0])
    os.makedirs(cfg.reentry_panel_dir, exist_ok=True)
    out = os.path.join(cfg.reentry_panel_dir, f"panel_{stem}.png")
    cv2.imwrite(out, img[y:y + h, x:x + w])
    print(f"模板已存 {out}（{w}x{h}）")


def _brightness(stem: str):
    img = _load(stem)
    r = cfg.stuck_region
    crop = img[r.y:r.y + r.h, r.x:r.x + r.w]
    print(f"{stem}: stuck_region 平均亮度 = {float(np.mean(crop)):.1f}"
          f"（礦內樣本應遠低於地表；中間值填 reentry_mine_max_brightness）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="imp", metavar="NNN")
    ap.add_argument("--brightness", metavar="NNN")
    a = ap.parse_args()
    if a.imp:
        _import(a.imp)
    elif a.brightness:
        _brightness(a.brightness)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
