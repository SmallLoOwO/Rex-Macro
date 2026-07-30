import time
import logging
import pydirectinput
import ctypes

# W 鍵追蹤 logger（2026-07-25 使用者要求）：長按／放開各記一筆 DEBUG，事後比對「W 突然放開」
# 是 bot 主動 key_up 還是 Windows／遊戲側的狀態丟失。key_press（短按）不在此追蹤——
# 每秒都會跑、量太大且對挖礦前進無影響。logger 走 miningbot 命名空間，與 main 共用設定。
_log = logging.getLogger("miningbot.input_control")

# 之前輸入太快、遊戲來不及讀，導致 W 沒按下、Shift 沒置中等。整體放慢。
pydirectinput.PAUSE = 0.04                 # 每個 pydirectinput 動作後的間隔
_STEP = 0.06                               # 我們自己每個動作後再多等一下
# 放開「按住的挖礦左鍵」後，要等遊戲確實收到「放開」，否則接著的點擊會和殘留的按住衝突被吃掉。
RELEASE_SETTLE = 0.15

def settle(t: float = RELEASE_SETTLE):
    """放開按住的鍵/鍵後的沉澱等待，確保下一個動作不被殘留輸入吃掉。"""
    time.sleep(t)

def key_press(key: str, delay: float = 0.09):
    pydirectinput.press(key)
    time.sleep(delay)

def key_down(key: str):
    if key == "w":
        _log.info("key_down('w')")
    pydirectinput.keyDown(key)
    time.sleep(_STEP)

def key_up(key: str):
    if key == "w":
        _log.info("key_up('w')")
    pydirectinput.keyUp(key)
    time.sleep(_STEP)

def mouse_down():
    pydirectinput.mouseDown()
    time.sleep(_STEP)

def mouse_up():
    pydirectinput.mouseUp()
    time.sleep(_STEP)

def mouse_click(button: str = "left", hold: float = 0.0):
    """點一下。hold>0 時改成「按下→停 hold 秒→放開」的確實點擊，
    避免瞬間點擊在放置道具（boost/活動）時被遊戲吃掉。"""
    if hold > 0:
        pydirectinput.mouseDown(button=button)
        time.sleep(hold)
        pydirectinput.mouseUp(button=button)
    else:
        pydirectinput.click(button=button)
    time.sleep(_STEP)

_MOUSEEVENTF_WHEEL = 0x0800
_WHEEL_DELTA = 120           # Windows 滾輪一格的標準單位

def scroll(clicks: int):
    """滑鼠滾輪捲動：clicks 正值向上捲、負值向下捲（Windows WHEEL_DELTA=120/格）。

    本機安裝的 pydirectinput 版本沒有 scroll()（2026-07-08 確認：dir(pydirectinput)
    只有 moveTo/moveRel/click/keyDown/keyUp 等，無 scroll），改走 win32 mouse_event
    直接送 MOUSEEVENTF_WHEEL——與 main.py 既有用 ctypes.windll.user32 做視窗操作同模式。
    呼叫前應先用 move_to() 把游標移到要捲動的區域上方（Windows 滾輪事件作用於游標所在視窗/控制項）。
    """
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0, clicks * _WHEEL_DELTA, 0)
    time.sleep(_STEP)

def move_to(x: int, y: int):
    """移動滑鼠到絕對座標（不點擊）。給選單捲動/略過點擊的場景用。"""
    pydirectinput.moveTo(x, y)
    time.sleep(0.05)

# Roblox 全螢幕：游標停在畫面**頂端約 80px** 內會叫出可自動隱藏的視窗標題列
# （"Roblox" ＋ 還原/關閉鈕），那條蓋掉頂部事件橫幅——chill/**礦坑重置**橫幅 OCR 的
# 唯一來源，chill_text_region 讀到的會是字串 'Roblox'（2026-07-28 全螢幕實測）。
# 它是 hover-reveal：游標離開頂端就收起，但游標**停在**那裡就一直蓋著。
# 點在頂端的呼叫端（聊天圖示 y=42、回礦細格最上排、追蹤框在畫面頂端的 D3 開火）
# 點完不會自己移開游標 → 這裡統一收口：點完就把游標移回畫面中央。
# 純移動游標不會轉視角（要轉必須按住右鍵，見 aim_move），對任何流程都無副作用。
TOP_OVERLAY_STRIP_PX = 100      # 實測標題列高 ~80px，留 20px 餘裕


def click_at(x: int, y: int, button: str = "left", hold: float = 0.0):
    """移到絕對座標再點一下。hold>0 時改成按住再放開（D3 採集需要 hold=0.4 才觸發）。

    點在畫面頂端時，點完把游標移回中央（見 TOP_OVERLAY_STRIP_PX）。
    """
    pydirectinput.moveTo(x, y)
    time.sleep(0.05)
    mouse_click(button=button, hold=hold)
    if y < TOP_OVERLAY_STRIP_PX:
        move_to(*_screen_center())

def aim_move(dx: int, dy: int):
    """細部瞄準：**按住右鍵**拖曳滑鼠來轉視角（REX 用右鍵按著調整方位），移完放開。

    單純 moveRel 不會轉視角（實測無效），一定要右鍵按著。
    """
    pydirectinput.mouseDown(button="right")
    time.sleep(0.04)
    pydirectinput.moveRel(dx, dy, relative=True)
    time.sleep(0.04)
    pydirectinput.mouseUp(button="right")
    time.sleep(_STEP)

# 連按兩次 Shift = 把滑鼠準心對準畫面中心點（瞄準前必做，偏移計算才正確）
def center_crosshair():
    key_press("shift", delay=0.12); key_press("shift", delay=0.12)

# 視角轉動：'.' 向右 45°、',' 向左 45°（對應原巨集 KeyCode190/188）
def rotate_right():
    key_press(".")

def rotate_left():
    key_press(",")

def _screen_center() -> tuple:
    u = ctypes.windll.user32
    return u.GetSystemMetrics(0) // 2, u.GetSystemMetrics(1) // 2

def _drag_vertical(total_px: int, chunk: int = 75):
    """右鍵垂直拖曳（H048 重寫）：拆成多次短 hold，每次 hold 前游標重新置中＋沉澱。

    H048 實機兩側量測（2026-07-18）：合成右鍵拖曳時 Roblox 不一定鎖游標，實體游標
    被 Windows 指標加速（實測 ~2.0-2.3x）甩到螢幕邊緣——起手點落在 UI 按鈕/工作列上
    整段被吞、右鍵在標題列放開會彈出視窗系統選單吃掉後續輸入；且前一段拖曳結束後
    0.15~0.2s 內起手的下一段右鍵也會被吃（0.55s 以上生效）。因此：
    - 每次 hold 注入量 ≤ pitch_drag_hold_budget_px（加速後仍甩不到邊緣）；
    - 每次 hold 從畫面中央起手（永遠蓋在遊戲 3D 視口上）；
    - hold 之間沉澱 pitch_drag_hold_settle_s（含第一段——覆蓋「點完 UI 立刻拖」的
      開場鏈時序）。校準量以「注入 px 總和」計，與舊版一致。
    """
    from .config import DEFAULT as cfg
    cx, cy = _screen_center()
    sign = 1 if total_px >= 0 else -1
    remaining = abs(total_px)
    while remaining > 0:
        move_to(cx, cy)
        time.sleep(cfg.pitch_drag_hold_settle_s)
        hold_budget = min(cfg.pitch_drag_hold_budget_px, remaining)
        pydirectinput.mouseDown(button="right")
        time.sleep(0.04)
        while hold_budget > 0:
            step = min(chunk, hold_budget)
            pydirectinput.moveRel(0, sign * step, relative=True)
            time.sleep(0.03)
            hold_budget -= step
            remaining -= step
        pydirectinput.mouseUp(button="right")
        time.sleep(_STEP)

def pitch_reset(down_px: int, back_px: int):
    """俯仰歸位：先向下拖到夾限（飽和，量多無妨）、再回拉固定量。

    俯仰角沒有絕對讀數（挖礦中途人工抬頭後回不去），但夾限是硬邊界——
    飽和之後「回拉多少」就是可重現的絕對角度。down/back 方向若與遊戲相反
    （拖下=抬頭），校準時把兩個參數對調正負驗證，勿改此函式。
    """
    _drag_vertical(down_px)
    settle()
    _drag_vertical(-back_px)
    settle()

def pitch_nudge(dy: int):
    """俯仰微調一步（回礦 `仰角 上/下` 指令用；原 R 取樣視窗上/下鈕）。dy>0 向下拖。"""
    _drag_vertical(dy)
