import time
from dataclasses import dataclass
from .geometry import aim_decision
from . import input_control as ic
from .config import DEFAULT as cfg

@dataclass
class HarvestState:
    rotations: int          # 總轉動次數（給 max_aim_rotations 上限用）
    elapsed_s: float
    net_rotations: int = 0  # 淨轉動（右+1、左-1），用來挖完後轉回原角度
    d3_attempts: int = 0    # D3 連續未命中次數（達 3 次自動重掃）

@dataclass
class HarvestStep:
    action: str   # WAIT_SCAN | ROTATE_LEFT | ROTATE_RIGHT | MOUSE_AIM | FIRE_D3 | HUMAN
    dx: int = 0
    dy: int = 0

def next_harvest_step(marker, state: HarvestState, cfg) -> HarvestStep:
    if state.elapsed_s > cfg.harvest_verify_timeout_s:
        return HarvestStep("HUMAN")
    if state.rotations > cfg.max_aim_rotations:
        return HarvestStep("HUMAN")
    if marker is None:
        return HarvestStep("WAIT_SCAN")

    center = (cfg.screen_w // 2, cfg.screen_h // 2)
    d = aim_decision(marker, center, cfg.aim_center_tolerance_px,
                     cfg.vertical_extreme_ratio, cfg.screen_h // 2)
    mapping = {
        "HUMAN": "HUMAN", "FIRE": "FIRE_D3",
        "ROTATE_LEFT": "ROTATE_LEFT", "ROTATE_RIGHT": "ROTATE_RIGHT",
        "MOUSE_AIM": "MOUSE_AIM",
    }
    return HarvestStep(mapping[d.action], dx=d.dx, dy=d.dy)

def restore_actions(net_rotations: int) -> list:
    """挖完後要轉回原角度的動作序列（純函式）。

    淨右轉 N（net>0）→ 回傳 N 個 ROTATE_LEFT；淨左轉則相反。
    """
    if net_rotations > 0:
        return ["ROTATE_LEFT"] * net_rotations
    if net_rotations < 0:
        return ["ROTATE_RIGHT"] * (-net_rotations)
    return []

def prepare_scan():
    """停止移動、置中鏡頭——在這之後應立刻截圖當 reference，再呼叫 execute_scan。"""
    ic.key_up("w"); ic.mouse_up()
    ic.center_crosshair()                  # 置中後角色裝備位置才穩定
    time.sleep(0.15)                       # 等畫面更新再截 reference

def execute_scan():
    """置中後裝備 D2 + 點擊觸發掃描（與 prepare_scan 分開是為了讓呼叫端在中間截 reference）。"""
    ic.key_press("2")                      # D2 裝備掃描器
    time.sleep(0.3)                        # 等裝備動畫
    ic.click_at(cfg.screen_w // 2, cfg.screen_h // 2)  # 左鍵觸發掃描
    time.sleep(1.5)                        # 等追蹤框出現

def start_scan():
    prepare_scan()
    execute_scan()

def fire_d3():
    ic.key_press("3")

def restore_view(net_rotations: int):
    """實際送鍵把視角轉回原角度（挖完成功後呼叫）。"""
    for action in restore_actions(net_rotations):
        if action == "ROTATE_LEFT":
            ic.rotate_left()
        else:
            ic.rotate_right()
