import time
import pydirectinput

pydirectinput.PAUSE = 0.01

def key_press(key: str, delay: float = 0.05):
    pydirectinput.press(key)
    time.sleep(delay)

def key_down(key: str):
    pydirectinput.keyDown(key)

def key_up(key: str):
    pydirectinput.keyUp(key)

def mouse_down():
    pydirectinput.mouseDown()

def mouse_up():
    pydirectinput.mouseUp()

def mouse_click(button: str = "left"):
    pydirectinput.click(button=button)

def mouse_move_rel(dx: int, dy: int):
    pydirectinput.moveRel(dx, dy, relative=True)

# 視角轉動：'.' 向右 45°、',' 向左 45°（對應原巨集 KeyCode190/188）
def rotate_right():
    key_press(".")

def rotate_left():
    key_press(",")
