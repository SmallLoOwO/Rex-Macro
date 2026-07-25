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

def d4_text_fresh(now: float, banner_at: float, last_press: float,
                  interval_s: float) -> bool:
    """D4 決策可否用背景 worker 的事件文字快取（不可用就同步重讀）。

    「夠新」之外還要求「晚於上次 D4 動作」——上次動作之前 OCR 的快取描述的是
    已被刷掉/確認過的舊事件，拿它決策會對剛骰出的新事件按錯鍵
    （2026-07-19 01:16 兩筆未知連刷、間隔僅 4s 的根因候選）。
    """
    return now - banner_at <= interval_s * 2 and banner_at > last_press

def plan_d4(kept: bool, matched: bool, unknown_confirmed: bool,
            resetting: bool = False) -> str:
    """D4 事件決策：keep（左鍵確認）/ reroll（右鍵刷新）/ hold（本輪不動作）/
    skip（重置中不碰、不進 hold 記帳）。

    重置倒數中事件列被重置公告蓋掉（與 reset 偵測共用 chill_text_region；
    07-19 01:32:24 實機「未知」白刷、2s 後即偵測到重置）→ skip：讀值無效
    且事件馬上被重置，按什麼都沒意義。
    認不得的文字第一次先 hold：單次誤讀（換場動畫、OCR 噪音）就右鍵會把
    keep 清單事件不可逆刷掉；等下一份新樣本仍認不得才刷新（雙樣本確認，
    比照 tracker 雙幀穩定／capacity streak 慣例）。
    """
    if resetting:
        return "skip"
    if kept:
        return "keep"
    if matched:
        return "reroll"
    return "reroll" if unknown_confirmed else "hold"

def init_mining_sequence(log=None, rotate=None):
    """初始化（只在啟動/失焦復原做一次）：放開→. , 視角→雙 Shift→（沒拿鎬子才按 D1）→挖礦。

    視角(., )與置中只做一次（之後視角不變）。D1 **只在槽位像素顯示沒拿鎬子時才按**，
    對照原巨集 IF PIXEL FOUND 2302755；已拿著又按一下反而會把十字鎬收起來。
    log：傳 callable 時每步驟記錄（採集後 W 不按住的 root cause 追蹤用）。
    rotate：可注入的驗證式單步旋轉 callable(direction)->bool（main 傳 Bot._rotate_verified）。
    ., 成對淨 0 的前提是兩鍵都生效——吃掉半對就歪 45°（挖礦視角 90° 倍數對齊）；
    注入時右轉沒轉成就不左轉（否則反歪 45°）、左轉被吃由 callable 自行重送。
    """
    if log: log("init_mining_sequence: 開始")
    ic.key_up("w"); ic.mouse_up()
    if log: log("init_mining_sequence: key_up('w')+mouse_up() done")
    if rotate is not None:
        if rotate(+1):                     # ., 設定視角（一次即可），成對淨 0
            rotate(-1)
    else:
        ic.rotate_right(); ic.rotate_left()
    if log: log("init_mining_sequence: rotate(.,) done")
    ic.center_crosshair()                  # 連按兩次 Shift：準心置中
    if log: log("init_mining_sequence: center_crosshair done")
    pressed = _ensure_pickaxe()            # 沒拿鎬子才按 D1
    if log: log("init_mining_sequence: _ensure_pickaxe pressed=%s" % pressed)
    ic.key_down("w"); ic.mouse_down()
    if log: log("init_mining_sequence: key_down('w')+mouse_down() done — complete")

def ensure_pickaxe() -> bool:
    """公開入口：條件式切回鎬子（槽位顯示沒拿鎬子才按 D1，安全不會 toggle 掉已裝備的）。

    採集成功後 pickup 動畫（1-2s）會吃掉 init 期的 D1，導致 D3 沒切回 → 按住 W 卻拿 D3
    無法前進。故動畫結束 settle 後需再呼叫本函式補確認一次（見 main 採集成功路徑）。
    """
    return _ensure_pickaxe()


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
        # 區域顏色判定（2026-07-10）：選中槽位底色轉綠 → slot_selected=True＝已裝備；
        # 未選中(灰底) → 沒拿鎬子 → 按 D1 切回（安全：已裝備時不會誤按而 toggle 收起）。
        if not vision.slot_selected(frame, cfg.d1_slot_region, cfg.d1_selected_greenness_min):
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

def use_boost_harvest():   # 採集中補 D5（H026 FOV 守門）：喝完不切回鎬子、不按住左鍵——採集不挖礦，
    ic.mouse_up(); ic.settle()  # D3 序列自己按 2→3 處理裝備、回 D1 交給採集收尾的 init_mining_sequence
    ic.key_press("5"); ic.mouse_click(hold=0.08)

def use_activity():        # 對照原巨集：放左鍵 → D4 → 點擊 → D1 → 按住左鍵
    ic.mouse_up(); ic.settle()
    ic.key_press("4"); ic.mouse_click(button="right", hold=0.08)  # 右鍵=刷新事件（使用者確認；加強事件之後再做）
    ic.key_press("1"); ic.mouse_down()

def use_activity_keep():  # D4 保留當前事件：左鍵＝**加強**事件（對照 use_activity 的右鍵刷新）
    ic.mouse_up(); ic.settle()
    # 左鍵是「加強事件」，**不會**把事件洗掉（2026-07-25 使用者更正；舊註解寫「確認/保留」
    # 容易讓人以為是唯讀確認）。想留住的事件按左鍵只會變強，故 keep 路徑用它是安全的；
    # 會不可逆換掉事件的是右鍵（use_activity）。
    ic.key_press("4"); ic.mouse_click(button="left", hold=0.08)
    ic.key_press("1"); ic.mouse_down()

def use_scan():            # SCAN 變體：D2→點擊→Z→D5→點擊→D1→續挖（對照 boost+scan .mcr）
    ic.mouse_up(); ic.key_press("2"); ic.mouse_click(); ic.key_press("z")
    ic.key_press("5"); ic.mouse_click(); ic.key_press("1"); ic.mouse_down()

# 以下兩個是「連續使用」用的單一能力版本（對照 use_boost 的形狀：放左鍵→換道具→用→
# 回 D1→續挖）。與 use_scan 的差別是**只觸發一個能力**，兩者冷卻各自獨立，才能像
# D4/D5 那樣各自到期各自重按。
# ⚠ 數字鍵是 toggle：雷達已在手上時再按 `2` 會收起來。這裡安全是因為挖礦中手上是
#   D1 鎬子，按 `2` 屬於「換槽」而非「同槽切換」——與 use_boost 按 `5` 同理。

def use_radar_scan():      # D2 左鍵 Cyberscan：範圍自動採礦＋Surreal+ 掛追蹤框
    ic.mouse_up(); ic.settle()
    ic.key_press("2"); ic.mouse_click(hold=0.08)
    ic.key_press("1"); ic.mouse_down()

def use_cave_skim():       # D2 Z Cave Skim：削掉特殊洞穴的洞穴方塊（Crystallized Stone/Ice）
    ic.mouse_up(); ic.settle()
    ic.key_press("2"); ic.key_press("z")
    ic.key_press("1"); ic.mouse_down()

def handle_cave(rotate=None):  # CAVE 變體：F 進入→等待→旋轉視角+X 退出（對照 boost+cave .mcr）
    import time
    ic.key_press("f"); time.sleep(3.0)
    if rotate is not None:     # 驗證式：只回轉「確認轉成」的次數，成對淨 0 不歪 45°
        done = sum(1 for _ in range(2) if rotate(+1))
        ic.key_press("x"); time.sleep(1.0)
        for _ in range(done):
            rotate(-1)
    else:
        ic.rotate_right(); ic.rotate_right(); ic.key_press("x"); time.sleep(1.0)
        ic.rotate_left(); ic.rotate_left()
    ic.key_down("w"); ic.mouse_down()
