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
