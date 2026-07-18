"""手動取樣檔案助手：編號接續（純函式）。

R 鍵取樣視窗（Tk 小窗＋熱鍵）已於 2026-07-17 退役：截圖改走 Discord 遙控器 📷
（同樣以 sampler.save_sample 落編號檔）、俯仰控制改走回礦 `仰角` 指令。
本檔只剩編號邏輯——calibrate_surface --import NNN 仍靠它。
"""
from miningbot.sampler import next_manual_index


class TestNextManualIndex:
    def test_empty_starts_at_1(self):
        assert next_manual_index([]) == 1

    def test_continues_from_max(self):
        assert next_manual_index(["001.png", "002.png", "007.png"]) == 8

    def test_ignores_non_matching(self):
        # sidecar json 與雜檔不干擾編號
        assert next_manual_index(["001.png", "001.json", "readme.txt"]) == 2
