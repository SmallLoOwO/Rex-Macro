import time
import pydirectinput
import ctypes

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
    pydirectinput.keyDown(key)
    time.sleep(_STEP)

def key_up(key: str):
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

def mouse_move_rel(dx: int, dy: int):
    pydirectinput.moveRel(dx, dy, relative=True)
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

def click_at(x: int, y: int, button: str = "left", hold: float = 0.0):
    """移到絕對座標再點一下。hold>0 時改成按住再放開（D3 採集需要 hold=0.4 才觸發）。"""
    pydirectinput.moveTo(x, y)
    time.sleep(0.05)
    mouse_click(button=button, hold=hold)

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

def _drag_vertical(total_px: int, chunk: int = 180):
    """右鍵按住的垂直拖曳，拆 chunk 段送（單次過大會被遊戲的滑鼠加速/取樣吃掉）。"""
    sign = 1 if total_px >= 0 else -1
    remaining = abs(total_px)
    pydirectinput.mouseDown(button="right")
    time.sleep(0.04)
    while remaining > 0:
        step = min(chunk, remaining)
        pydirectinput.moveRel(0, sign * step, relative=True)
        time.sleep(0.03)
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
    """俯仰微調一步（R 取樣視窗的上/下鈕用）。dy>0 向下拖。"""
    _drag_vertical(dy)
