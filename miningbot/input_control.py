import time
import pydirectinput

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

def click_at(x: int, y: int, button: str = "left"):
    """移到絕對座標再點一下（採集時 D3 點選追蹤框位置用）。"""
    pydirectinput.moveTo(x, y)
    time.sleep(0.05)
    pydirectinput.click(button=button)
    time.sleep(_STEP)

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
