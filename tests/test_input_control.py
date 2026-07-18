"""input_control 新增 I/O 薄封裝的單元測試：用 monkeypatch 換掉底層呼叫，
斷言傳入的參數/呼叫次數正確（不實際發送輸入）。"""
import ctypes
from miningbot import input_control as ic


def test_scroll_sends_wheel_delta_down(monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes.windll.user32, "mouse_event",
                        lambda flag, dx, dy, data, extra: calls.append((flag, dx, dy, data, extra)))
    ic.scroll(-2)
    assert len(calls) == 1
    flag, dx, dy, data, extra = calls[0]
    assert flag == ic._MOUSEEVENTF_WHEEL
    assert dx == 0 and dy == 0 and extra == 0
    assert data == -2 * ic._WHEEL_DELTA


def test_scroll_sends_wheel_delta_up(monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes.windll.user32, "mouse_event",
                        lambda flag, dx, dy, data, extra: calls.append((flag, dx, dy, data, extra)))
    ic.scroll(3)
    assert calls[0][3] == 3 * ic._WHEEL_DELTA


def test_move_to_calls_pydirectinput_moveto(monkeypatch):
    calls = []
    monkeypatch.setattr(ic.pydirectinput, "moveTo", lambda x, y: calls.append((x, y)))
    ic.move_to(500, 600)
    assert calls == [(500, 600)]


# ===== H048：俯仰右鍵拖曳人式分段（2026-07-18 實機兩側量測）=====
# 根因：合成右鍵拖曳時 Roblox 不一定鎖游標，指標加速（實測 ~2.0-2.3x）把實體游標
# 甩到螢幕邊緣——起手點落在 UI/工作列整段被吞、右鍵在標題列放開彈系統選單吃掉後續
# 輸入；且前段拖完 0.15~0.2s 內起手的下一段右鍵被吃（0.55s 以上生效）。
from miningbot.config import DEFAULT as cfg


class _DragRecorder:
    """攔截 pydirectinput/time.sleep，重建 hold 結構供斷言。"""

    def __init__(self, monkeypatch):
        self.events = []
        monkeypatch.setattr(ic.pydirectinput, "mouseDown",
                            lambda button=None: self.events.append(("down", button)))
        monkeypatch.setattr(ic.pydirectinput, "mouseUp",
                            lambda button=None: self.events.append(("up", button)))
        monkeypatch.setattr(ic.pydirectinput, "moveRel",
                            lambda dx, dy, relative=True: self.events.append(("rel", dx, dy)))
        monkeypatch.setattr(ic.pydirectinput, "moveTo",
                            lambda x, y: self.events.append(("to", x, y)))
        monkeypatch.setattr(ic.time, "sleep",
                            lambda t: self.events.append(("sleep", t)))
        monkeypatch.setattr(ic, "_screen_center", lambda: (960, 540))

    def holds(self):
        """[[hold 內各 moveRel 的 dy], ...]"""
        holds, cur = [], None
        for e in self.events:
            if e[0] == "down":
                cur = []
            elif e[0] == "rel" and cur is not None:
                cur.append(e[2])
            elif e[0] == "up":
                holds.append(cur)
                cur = None
        return holds


def test_drag_total_injected_preserved(monkeypatch):
    # 校準量以「注入 px 總和」計——分段不可改變總量
    rec = _DragRecorder(monkeypatch)
    ic._drag_vertical(1500)
    assert sum(sum(h) for h in rec.holds()) == 1500


def test_drag_hold_budget_respected(monkeypatch):
    # 單次 hold 注入 ≤ budget：加速 ~2.3x 後實走 <500px，游標甩不出遊戲視口
    rec = _DragRecorder(monkeypatch)
    ic._drag_vertical(1500)
    assert rec.holds()                            # 至少一次 hold
    for h in rec.holds():
        assert sum(abs(dy) for dy in h) <= cfg.pitch_drag_hold_budget_px


def test_drag_recenter_before_every_hold(monkeypatch):
    # 每次 hold 起手前游標必置中（起手點永遠蓋在 3D 視口上，不落 UI/工作列/標題列）
    rec = _DragRecorder(monkeypatch)
    ic._drag_vertical(400)
    non_sleep = [e for e in rec.events if e[0] != "sleep"]
    downs = [i for i, e in enumerate(non_sleep) if e[0] == "down"]
    assert downs
    for i in downs:
        assert non_sleep[i - 1] == ("to", 960, 540)


def test_drag_settle_between_holds(monkeypatch):
    # hold 間沉澱（含首段——覆蓋「點完 UI 按鈕立刻拖」的開場鏈時序）
    rec = _DragRecorder(monkeypatch)
    ic._drag_vertical(1500)
    settles = [e for e in rec.events
               if e[0] == "sleep" and e[1] == cfg.pitch_drag_hold_settle_s]
    assert len(settles) == len(rec.holds())


def test_drag_negative_direction(monkeypatch):
    rec = _DragRecorder(monkeypatch)
    ic._drag_vertical(-400)
    assert sum(sum(h) for h in rec.holds()) == -400
    for h in rec.holds():
        assert all(dy < 0 for dy in h)


def test_pitch_reset_saturate_then_back(monkeypatch):
    # 歸位語意不變：先下拉 clamp 飽和、再回拉 back（總注入量與舊版一致）
    rec = _DragRecorder(monkeypatch)
    ic.pitch_reset(1500, 400)
    totals = [sum(h) for h in rec.holds()]
    assert sum(t for t in totals if t > 0) == 1500
    assert sum(t for t in totals if t < 0) == -400
    last_down = max(i for i, t in enumerate(totals) if t > 0)
    first_back = min(i for i, t in enumerate(totals) if t < 0)
    assert last_down < first_back
