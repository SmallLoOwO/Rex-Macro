"""R 鍵手動取樣：編號接續（純函式）與熱鍵邊緣觸發（TDD）。"""
from miningbot.sampler import next_manual_index, sync_action
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


class TestHotkeyF8:
    # F8（VK 0x77）＝跳過啟動環境檢查；邊緣觸發，樣式同 R（spec 2026-07-10 第 1 節）。
    def _mk(self, down):
        calls = []
        hk = _HotkeyController(down, on_stop=lambda: None, on_toggle=lambda: None,
                               on_quit=lambda: None, on_skip=lambda: calls.append(1))
        return hk, calls

    def test_f8_edge_triggers_once(self):
        pressed = {0x77}
        hk, calls = self._mk(lambda vk: vk in pressed)
        hk.tick(); hk.tick()          # 按住兩 tick 只觸發一次（邊緣觸發）
        assert calls == [1]
        pressed.clear(); hk.tick()
        pressed.add(0x77); hk.tick()  # 放開再按 → 再觸發
        assert calls == [1, 1]

    def test_no_callback_no_crash(self):
        hk = _HotkeyController(lambda vk: vk == 0x77, lambda: None,
                               lambda: None, lambda: None)
        hk.tick()   # on_skip 未掛也不能炸（既有呼叫端不傳此參數）


class TestSyncAction:
    # sync_action：HUD _poll 用來把「R 熱鍵請求」對齊「取樣視窗實際狀態」的純決策。
    # 對應 2026-07-10 修復：背景執行緒建第二個 tk.Tk() 會靜默失敗（OS 層無窗），
    # 改由 HUD Tk 主執行緒輪詢此決策建/銷 Toplevel。
    def test_want_and_dead_opens(self):
        assert sync_action(True, False) == "open"

    def test_unwant_and_alive_closes(self):
        assert sync_action(False, True) == "close"

    def test_steady_states_none(self):
        assert sync_action(True, True) is None
        assert sync_action(False, False) is None
