"""熱鍵控制器單元測試（TDD）。

_HotkeyController 封裝邊緣觸發邏輯，down_fn 由外部注入，方便測試。
"""
from miningbot.main import _HotkeyController


def _make(down_fn=None, on_stop=None, on_toggle=None, on_quit=None):
    calls = []
    def _stop():  calls.append("stop")
    def _toggle(): calls.append("toggle")
    def _quit():  calls.append("quit")
    ctrl = _HotkeyController(
        down_fn  or (lambda vk: False),
        on_stop  or _stop,
        on_toggle or _toggle,
        on_quit  or _quit,
    )
    return ctrl, calls


def test_ctrlq_triggers_stop_on_first_press():
    ctrl, calls = _make(lambda vk: vk in (0x11, 0x51))
    ctrl.tick()
    assert calls == ["stop"]


def test_ctrlq_held_does_not_repeat():
    ctrl, calls = _make(lambda vk: vk in (0x11, 0x51))
    ctrl.tick(); ctrl.tick(); ctrl.tick()
    assert calls == ["stop"]


def test_q_alone_toggles_once():
    ctrl, calls = _make(lambda vk: vk == 0x51)
    ctrl.tick(); ctrl.tick()
    assert calls == ["toggle"]


def test_q_release_and_repress_toggles_twice():
    ctrl, calls = _make()
    ctrl._down = lambda vk: vk == 0x51
    ctrl.tick()                          # 按下 → toggle
    ctrl._down = lambda vk: False
    ctrl.tick()                          # 放開
    ctrl._down = lambda vk: vk == 0x51
    ctrl.tick()                          # 再按 → toggle
    assert calls == ["toggle", "toggle"]


def test_ctrlq_does_not_also_fire_q_toggle():
    # Ctrl+Q 不應額外觸發單獨 Q 的 toggle
    ctrl, calls = _make(lambda vk: vk in (0x11, 0x51))
    ctrl.tick()
    assert "toggle" not in calls


def test_f12_triggers_quit():
    ctrl, calls = _make(lambda vk: vk == 0x7B)
    ctrl.tick()
    assert "quit" in calls


def test_no_keys_no_action():
    ctrl, calls = _make(lambda vk: False)
    ctrl.tick(); ctrl.tick()
    assert calls == []


# --- 接線契約：Ctrl+Q = 只暫停（永不繼續）、Q = 開關（暫停↔繼續）-----------------
# 動機：強制停止已與暫停無異，故移除「強制停止」那層，避免暫停時誤按 Ctrl+Q 觸發更重的動作。
# 用一個忠實模型化 Bot 暫停語意的 target 驗證 on_stop / on_toggle 的接線意圖。

class _PauseModel:
    def __init__(self):
        self.paused = False
        self.resumes = 0
    def pause_only(self):          # Ctrl+Q → on_stop：只暫停，idempotent，永不繼續
        self.paused = True
    def toggle(self):              # Q → on_toggle：開關
        if self.paused:
            self.paused = False
            self.resumes += 1
        else:
            self.paused = True


def _wire(model):
    ctrl = _HotkeyController(lambda vk: False, model.pause_only, model.toggle, lambda: None)
    return ctrl


def test_ctrlq_pauses_but_never_resumes():
    m = _PauseModel()
    ctrl = _wire(m)
    ctrl._down = lambda vk: vk in (0x11, 0x51)   # Ctrl+Q 按下
    ctrl.tick()
    assert m.paused is True
    ctrl._down = lambda vk: False                # 放開
    ctrl.tick()
    ctrl._down = lambda vk: vk in (0x11, 0x51)   # 暫停中再按 Ctrl+Q
    ctrl.tick()
    assert m.paused is True, "Ctrl+Q 只暫停，暫停中再按應維持暫停"
    assert m.resumes == 0, "Ctrl+Q 永遠不該觸發繼續"


def test_q_toggles_pause_and_resume():
    m = _PauseModel()
    ctrl = _wire(m)
    ctrl._down = lambda vk: vk == 0x51           # Q 按下 → 暫停
    ctrl.tick()
    assert m.paused is True
    ctrl._down = lambda vk: False
    ctrl.tick()
    ctrl._down = lambda vk: vk == 0x51           # 再按 Q → 繼續
    ctrl.tick()
    assert m.paused is False and m.resumes == 1, "Q 應在暫停↔繼續間開關"


def test_q_resumes_after_ctrlq_pause():
    # 用 Ctrl+Q 暫停後，Q 應能繼續（兩條暫停路徑一致，Q 統一負責繼續）
    m = _PauseModel()
    ctrl = _wire(m)
    ctrl._down = lambda vk: vk in (0x11, 0x51)
    ctrl.tick()
    assert m.paused is True
    ctrl._down = lambda vk: False
    ctrl.tick()
    ctrl._down = lambda vk: vk == 0x51           # 單獨 Q → 繼續
    ctrl.tick()
    assert m.paused is False and m.resumes == 1
