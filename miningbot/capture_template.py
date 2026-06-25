"""擷取事件模板：觸發某個道具/事件後，框選畫面上出現的效果，存成 assets/<name>.png。

把你說的「短時間內截圖」交給程式：倒數時你切回遊戲並確保焦點在遊戲，
時間到程式自動按道具鍵＋點畫面，稍候再截圖，最後你用滑鼠框選效果範圍存檔。

用法（請先讓 Roblox 全螢幕、焦點在遊戲）：
    python -m miningbot.capture_template boost      # D5 加成（效果在右下角）
    python -m miningbot.capture_template activity   # D4 控制活動（頂部）
    python -m miningbot.capture_template scan        # D2 掃描
    python -m miningbot.capture_template cave        # 洞穴入口（場景事件，不自動觸發，直接截現況）
    python -m miningbot.capture_template boost --manual   # 不自動按鍵，你自己觸發，只負責截圖+框選

框選後會印出該區域座標 (x,y,w,h)，可直接拿去校正 config 的偵測範圍。
"""
import argparse
import time

import cv2
import pydirectinput

from . import input_control as ic
from .capture import grab

CENTER = (960, 540)


def _click_center():
    pydirectinput.moveTo(*CENTER)
    pydirectinput.click()


# event -> (輸出檔名, 觸發函式 or None)
TRIGGERS = {
    "boost":    ("boost_expired",   lambda: (ic.key_press("5"), _click_center())),
    "activity": ("activity_event",  lambda: (ic.key_press("4"), _click_center())),
    "scan":     ("scan_event",      lambda: (ic.key_press("2"), _click_center())),
    "cave":     ("cave_event",      None),   # 洞穴是場景事件，無法用按鍵觸發
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("event", choices=list(TRIGGERS))
    ap.add_argument("--countdown", type=int, default=4, help="倒數秒數（切回遊戲用）")
    ap.add_argument("--delay", type=float, default=0.6, help="觸發後等多久再截圖")
    ap.add_argument("--manual", action="store_true", help="不自動按鍵，自己觸發")
    args = ap.parse_args()

    name, trigger = TRIGGERS[args.event]
    print(f"=== 擷取 {args.event} -> assets/{name}.png ===")
    print(f"{args.countdown} 秒內請切回遊戲、把滑鼠移到遊戲畫面上（確保焦點在遊戲）")
    for i in range(args.countdown, 0, -1):
        print(i, end=" ", flush=True)
        time.sleep(1)
    print()

    if trigger and not args.manual:
        print("觸發中…（按道具鍵 + 點畫面）")
        trigger()
    time.sleep(args.delay)

    frame = grab()
    print("已截圖。請用滑鼠框選『效果』範圍 → 按 ENTER 確認、按 c 取消。")
    r = cv2.selectROI(name, frame, showCrosshair=True)
    cv2.destroyAllWindows()
    x, y, w, h = map(int, r)
    if w == 0 or h == 0:
        print("未框選，取消，未存檔。")
        return
    out = f"assets/{name}.png"
    cv2.imwrite(out, frame[y:y + h, x:x + w])
    print(f"已存 {out}  ({w}x{h})")
    print(f"偵測區域座標：Region({x}, {y}, {w}, {h})  ← 可貼進 config 對應欄位")


if __name__ == "__main__":
    main()
