"""一次性校準：擷取畫面，讓使用者用滑鼠框選關鍵區域，印出 Region 數值。"""
import cv2
from .capture import grab

REGIONS = ["chill_text_region", "chat_region", "boost_indicator_region"]

def main():
    frame = grab()
    for name in REGIONS:
        print(f"請框選 {name}，框好按 ENTER，取消按 c")
        r = cv2.selectROI(name, frame[:, :, ::-1], showCrosshair=True)
        cv2.destroyWindow(name)
        x, y, w, h = map(int, r)
        print(f"{name} = Region({x}, {y}, {w}, {h})")
    print("把上面數值貼進 miningbot/config.py 對應欄位。")
    print("槽位判定已改區域綠色主導（vision.slot_selected）：改框 d1_slot_region / d2_slot_region。")

if __name__ == "__main__":
    main()
