"""偵測 Roblox 視窗是否「跑位」：失焦或位置/大小不在預期的全螢幕基準。

純邏輯 `displacement_reason()` 可單元測試；`query_window()` 是 Win32 薄封裝
（讀視窗狀態，不做動作），由整合/實機驗證。

為什麼用 Win32 而非取樣像素：遊戲背景隨區域變色（見 docs/game-mechanics.md），
取樣固定點的顏色會誤判。問作業系統「Roblox 視窗在不在前景、在哪、多大」才可靠。
"""
from dataclasses import dataclass


@dataclass
class WindowState:
    found: bool          # 有沒有找到 Roblox 視窗
    foreground: bool     # 是不是目前的前景（有焦點）視窗
    x: int               # 視窗左上角螢幕座標
    y: int
    w: int               # 視窗寬高
    h: int


def displacement_reason(current: WindowState, baseline: WindowState,
                        pos_tol: int, size_tol: int):
    """相對「啟動時量到的正確基準」判斷視窗是否跑位；正常回 None。

    用基準相對比較而非寫死 1920x1080，因 DPI 縮放會讓 GetWindowRect 回報縮放後座標。
    優先序：視窗不存在 > 失焦 > 位移 > 大小不符。
    """
    if not current.found:
        return "window_missing"
    if not current.foreground:
        return "not_foreground"
    if abs(current.x - baseline.x) > pos_tol or abs(current.y - baseline.y) > pos_tol:
        return "moved"
    if abs(current.w - baseline.w) > size_tol or abs(current.h - baseline.h) > size_tol:
        return "resized"
    return None


def window_displaced(current: WindowState, baseline: WindowState,
                     pos_tol: int, size_tol: int) -> bool:
    return displacement_reason(current, baseline, pos_tol, size_tol) is not None


def query_window(title: str) -> WindowState:
    """薄封裝：用 Win32 讀 Roblox 視窗目前狀態（前景與位置/大小）。整合測試覆蓋。"""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, title)
    if not hwnd:
        return WindowState(found=False, foreground=False, x=0, y=0, w=0, h=0)
    rect = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(rect))
    return WindowState(
        found=True,
        foreground=bool(u.GetForegroundWindow() == hwnd),
        x=int(rect.left),
        y=int(rect.top),
        w=int(rect.right - rect.left),
        h=int(rect.bottom - rect.top),
    )
