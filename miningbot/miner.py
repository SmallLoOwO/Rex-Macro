from dataclasses import dataclass
from . import input_control as ic

@dataclass
class EventFlags:
    boost_expired: bool
    activity_event: bool
    scan_event: bool
    cave_event: bool
    window_unfocused: bool

def dispatch_event(f: EventFlags):
    """回傳該幀要執行的動作標籤，優先序固定。"""
    if f.window_unfocused:
        return "REFOCUS"
    if f.cave_event:
        return "CAVE"
    if f.scan_event:
        return "SCAN"
    if f.boost_expired:
        return "USE_D5"
    if f.activity_event:
        return "USE_D4"
    return None

def cooldown_ready(icon_present: bool, since_last_press: float, grace_s: float) -> bool:
    """工具是否就緒可用：右下角冷卻圖示「不在」= 冷卻好了。

    冷卻圖示還在 → 還在冷卻，不能用。
    圖示不在但剛按過（寬限期內）→ 先等冷卻圖示出現，避免在它出現前重複按。
    （D4 用此取代定時，避免「能用卻沒用」。）
    """
    if icon_present:
        return False
    return since_last_press > grace_s

def init_mining_sequence(log=None):
    """初始化（只在啟動/失焦復原做一次）：放開→. , 視角→雙 Shift→（沒拿鎬子才按 D1）→挖礦。

    視角(., )與置中只做一次（之後視角不變）。D1 **只在槽位像素顯示沒拿鎬子時才按**，
    對照原巨集 IF PIXEL FOUND 2302755；已拿著又按一下反而會把十字鎬收起來。
    log：傳 callable 時每步驟記錄（採集後 W 不按住的 root cause 追蹤用）。
    """
    if log: log("init_mining_sequence: 開始")
    ic.key_up("w"); ic.mouse_up()
    if log: log("init_mining_sequence: key_up('w')+mouse_up() done")
    ic.rotate_right(); ic.rotate_left()    # ., 設定視角（一次即可）
    if log: log("init_mining_sequence: rotate(.,) done")
    ic.center_crosshair()                  # 連按兩次 Shift：準心置中
    if log: log("init_mining_sequence: center_crosshair done")
    pressed = _ensure_pickaxe()            # 沒拿鎬子才按 D1
    if log: log("init_mining_sequence: _ensure_pickaxe pressed=%s" % pressed)
    ic.key_down("w"); ic.mouse_down()
    if log: log("init_mining_sequence: key_down('w')+mouse_down() done — complete")

def _ensure_pickaxe() -> bool:
    """槽位像素顯示「沒拿鎬子」時才按 D1（對照原巨集；避免已拿著又按反而收起）。

    按 D1 後等 0.4s 讓裝備動畫完成——太早接著按 W 會被動畫吃掉，bot 就不會走
    （對照 D3 fire 的 0.6s 等待；採集成功後切回鎬子才暴露出這問題）。
    回傳是否按了 D1（ True=有切換裝備）。
    """
    from . import capture, vision
    from .config import DEFAULT as cfg
    try:
        frame = capture.grab()
        if vision.pixel_matches(frame, cfg.slot_pixel, cfg.slot_color, tol=12):
            ic.key_press("1")
            ic.settle(0.4)    # 等鎬子裝備動畫（太早按 W 會被吃掉，bot 不會走）
            return True
    except Exception:
        pass
    return False

def use_boost():           # 對照原巨集：放左鍵 → D5 → 點擊 → D1(切回鎬子) → 按住左鍵（W 全程不放）
    ic.mouse_up(); ic.settle()
    ic.key_press("5"); ic.mouse_click(hold=0.08)
    ic.key_press("1"); ic.mouse_down()

def use_activity():        # 對照原巨集：放左鍵 → D4 → 點擊 → D1 → 按住左鍵
    ic.mouse_up(); ic.settle()
    ic.key_press("4"); ic.mouse_click(button="right", hold=0.08)  # 右鍵=刷新事件（使用者確認；加強事件之後再做）
    ic.key_press("1"); ic.mouse_down()

def use_activity_keep():  # D4 保留當前事件：左鍵確認（對照 use_activity 的右鍵刷新）
    ic.mouse_up(); ic.settle()
    ic.key_press("4"); ic.mouse_click(button="left", hold=0.08)   # 左鍵=確認/保留事件
    ic.key_press("1"); ic.mouse_down()

def use_scan():            # SCAN 變體：D2→點擊→Z→D5→點擊→D1→續挖（對照 boost+scan .mcr）
    ic.mouse_up(); ic.key_press("2"); ic.mouse_click(); ic.key_press("z")
    ic.key_press("5"); ic.mouse_click(); ic.key_press("1"); ic.mouse_down()

def handle_cave():         # CAVE 變體：F 進入→等待→旋轉視角+X 退出（對照 boost+cave .mcr）
    import time
    ic.key_press("f"); time.sleep(3.0)
    ic.rotate_right(); ic.rotate_right(); ic.key_press("x"); time.sleep(1.0)
    ic.rotate_left(); ic.rotate_left()
    ic.key_down("w"); ic.mouse_down()
