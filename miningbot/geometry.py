from dataclasses import dataclass

# 一次 `.`/`,` 轉 45°；在 1920 寬、~70° 水平視野下，約佔畫面 0.64 寬。
# 超過此門檻才用整段轉視角，否則用滑鼠微調。
ROTATE_THRESHOLD_PX = 480

@dataclass
class AimDecision:
    action: str          # FIRE | ROTATE_LEFT | ROTATE_RIGHT | MOUSE_AIM | HUMAN
    dx: int = 0
    dy: int = 0

def aim_decision(marker, center, tol_px, vertical_ratio, half_h) -> AimDecision:
    mx, my = marker
    cx, cy = center
    dx = mx - cx
    dy = my - cy

    # 垂直極端（頭頂/腳下）→ 人工
    if abs(dy) > half_h * vertical_ratio:
        return AimDecision("HUMAN")

    # 已對準
    if abs(dx) <= tol_px and abs(dy) <= tol_px:
        return AimDecision("FIRE")

    # 水平偏差大 → 整段轉視角 45°
    if dx <= -ROTATE_THRESHOLD_PX:
        return AimDecision("ROTATE_LEFT")
    if dx >= ROTATE_THRESHOLD_PX:
        return AimDecision("ROTATE_RIGHT")

    # 否則滑鼠微調
    return AimDecision("MOUSE_AIM", dx=dx, dy=dy)
