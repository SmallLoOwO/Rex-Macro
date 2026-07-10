"""HUD 文字防線：astral-plane 字元（>U+FFFF）不可進 Tk。

這台 Tcl/Tk 8.6 遇到非 BMP 字元（如 📸 U+1F4F8）會讓整個 Tk 事件迴圈
無聲卡死（無例外、無崩潰；實機二分驗證 2026-07-10，見 docs/manual-sampling.md）。
HUD label 吃 bot.last_action 自由文字 → 在 config 前一律過 _bmp_safe。
"""
from miningbot.status_hud import _bmp_safe


class TestBmpSafe:
    def test_strips_astral_emoji(self):
        assert _bmp_safe("\U0001F4F8 手動截圖 #007") == " 手動截圖 #007"

    def test_keeps_bmp_text(self):
        # 中文、BMP 符號（●、⚠、▲）都要原樣保留
        s = "● 挖礦中 ⚠ ▲偏移 40px"
        assert _bmp_safe(s) == s

    def test_empty(self):
        assert _bmp_safe("") == ""
