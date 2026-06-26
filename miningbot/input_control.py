import time
import pydirectinput

# 之前輸入太快、遊戲來不及讀，導致 W 沒按下、Shift 沒置中等。整體放慢。
pydirectinput.PAUSE = 0.04                 # 每個 pydirectinput 動作後的間隔
_STEP = 0.06                               # 我們自己每個動作後再多等一下

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

def mouse_click(button: str = "left"):
    pydirectinput.click(button=button)
    time.sleep(_STEP)

def mouse_move_rel(dx: int, dy: int):
    pydirectinput.moveRel(dx, dy, relative=True)
    time.sleep(_STEP)

# 連按兩次 Shift = 把滑鼠準心對準畫面中心點（瞄準前必做，偏移計算才正確）
def center_crosshair():
    key_press("shift", delay=0.12); key_press("shift", delay=0.12)

# 視角轉動：'.' 向右 45°、',' 向左 45°（對應原巨集 KeyCode190/188）
def rotate_right():
    key_press(".")

def rotate_left():
    key_press(",")
