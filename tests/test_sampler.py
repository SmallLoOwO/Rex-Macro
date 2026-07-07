"""R 鍵手動取樣：編號接續（純函式）與熱鍵邊緣觸發（TDD）。"""
from miningbot.sampler import next_manual_index
from miningbot.main import _HotkeyController


class TestNextManualIndex:
    def test_empty_starts_at_1(self):
        assert next_manual_index([]) == 1

    def test_continues_from_max(self):
        assert next_manual_index(["001.png", "002.png", "007.png"]) == 8

    def test_ignores_non_matching(self):
        # sidecar json 與雜檔不干擾編號
        assert next_manual_index(["001.png", "001.json", "readme.txt"]) == 2


class TestHotkeyR:
    def _mk(self, down):
        calls = []
        hk = _HotkeyController(down, on_stop=lambda: None, on_toggle=lambda: None,
                               on_quit=lambda: None, on_sample=lambda: calls.append(1))
        return hk, calls

    def test_r_edge_triggers_once(self):
        pressed = {0x52}
        hk, calls = self._mk(lambda vk: vk in pressed)
        hk.tick(); hk.tick()          # 按住兩 tick 只觸發一次（邊緣觸發）
        assert calls == [1]
        pressed.clear(); hk.tick()
        pressed.add(0x52); hk.tick()  # 放開再按 → 再觸發
        assert calls == [1, 1]

    def test_no_callback_no_crash(self):
        hk = _HotkeyController(lambda vk: vk == 0x52, lambda: None,
                               lambda: None, lambda: None)
        hk.tick()   # on_sample 未掛也不能炸（既有呼叫端不傳此參數）
