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

def init_mining_sequence():
    """移植原巨集初始化：放開狀態→調視角→雙 Shift→挖礦。"""
    ic.key_up("w"); ic.mouse_up()
    ic.rotate_right(); ic.rotate_left()
    ic.key_press("shift"); ic.key_press("shift")
    ic.key_down("w"); ic.mouse_down()

def use_boost():           # D5：放開左鍵→D5→點擊→D1→續挖
    ic.mouse_up(); ic.key_press("5"); ic.mouse_click(); ic.key_press("1"); ic.mouse_down()

def use_activity():        # D4：放開左鍵→D4→點擊→D1→續挖
    ic.mouse_up(); ic.key_press("4"); ic.mouse_click(); ic.key_press("1"); ic.mouse_down()

def use_scan():            # SCAN 變體：D2→點擊→Z→D5→點擊→D1→續挖（對照 boost+scan .mcr）
    ic.mouse_up(); ic.key_press("2"); ic.mouse_click(); ic.key_press("z")
    ic.key_press("5"); ic.mouse_click(); ic.key_press("1"); ic.mouse_down()

def handle_cave():         # CAVE 變體：F 進入→等待→旋轉視角+X 退出（對照 boost+cave .mcr）
    import time
    ic.key_press("f"); time.sleep(3.0)
    ic.rotate_right(); ic.rotate_right(); ic.key_press("x"); time.sleep(1.0)
    ic.rotate_left(); ic.rotate_left()
    ic.key_down("w"); ic.mouse_down()
