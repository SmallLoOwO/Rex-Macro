"""輕量恢復（2026-07-20）：MINING 暫停恢復不再跑 zoom_normalize＋init_mining_sequence。

角度／遠近只在稀有礦重追、回礦、啟動時才會被動到（那些路徑各自歸位）；單純暫停
期間相機未動，舊版每次恢復都跑 I×30+O×4 歸位＋rotate(.,)/center_crosshair 是白
做工。測試鎖定 _resume 在 MINING 狀態只做：聚焦＋確認鎬子＋重新握住 W+左鍵，
且不再觸發 _zoom_normalize 與 miner.init_mining_sequence。
"""
from miningbot import main
from miningbot.main import Bot
from miningbot.states import State


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)

    def log(self, message):
        self.records.append(message)


def _resume_bot(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot.log = bot.logger                  # _resume 用 self.log.log("RESUMED")
    bot.paused = True
    bot.state = State.MINING
    bot._calib_session = None
    bot._antiafk_last = 999.0             # 驗證會被重置為 0.0
    bot._rotate_verified = lambda direction: True
    calls = {"focus": 0, "zoom_normalize": 0, "init_mining": 0,
             "ensure_pickaxe": 0, "key_down": [], "mouse_down": 0}
    bot._focus_roblox = lambda: calls.__setitem__("focus", calls["focus"] + 1)
    bot._zoom_normalize = lambda label: calls.__setitem__(
        "zoom_normalize", calls["zoom_normalize"] + 1)
    bot._rr_skip_on_pause_resume = lambda source: None
    monkeypatch.setattr(main.miner, "init_mining_sequence",
                        lambda **kw: calls.__setitem__(
                            "init_mining", calls["init_mining"] + 1))
    monkeypatch.setattr(main.miner, "ensure_pickaxe",
                        lambda: calls.__setitem__(
                            "ensure_pickaxe", calls["ensure_pickaxe"] + 1))
    monkeypatch.setattr(main.ic, "key_down",
                        lambda k: calls["key_down"].append(k))
    monkeypatch.setattr(main.ic, "key_up", lambda k: None)
    monkeypatch.setattr(main.ic, "mouse_down",
                        lambda: calls.__setitem__("mouse_down", calls["mouse_down"] + 1))
    monkeypatch.setattr(main.ic, "mouse_up", lambda: None)
    return bot, calls


def test_resume_mining_is_lightweight(monkeypatch):
    """MINING 暫停恢復：不跑 zoom_normalize／init，只聚焦＋確認鎬子＋握住 W+左鍵。"""
    bot, calls = _resume_bot(monkeypatch)
    bot._resume()
    assert bot.paused is False
    assert bot._antiafk_last == 0.0
    assert calls["focus"] == 1                 # 仍重新聚焦（焦點可能飄走）
    assert calls["zoom_normalize"] == 0        # 不再跑 I×30+O×4 歸位
    assert calls["init_mining"] == 0           # 不再跑 rotate(.,)/center_crosshair
    assert calls["ensure_pickaxe"] == 1        # 仍確認鎬子（便宜安全網）
    assert calls["key_down"] == ["w"]          # 重新握住 W
    assert calls["mouse_down"] == 1            # 重新握住左鍵


def test_resume_non_mining_skips_keybus(monkeypatch):
    """非 MINING 狀態恢復：不碰鍵鼠／相機，交給 decide_transition→_on_enter。"""
    bot, calls = _resume_bot(monkeypatch)
    bot.state = State.NEEDS_HUMAN
    bot._resume()
    assert bot.paused is False
    assert calls["zoom_normalize"] == 0
    assert calls["init_mining"] == 0
    assert calls["ensure_pickaxe"] == 0        # 非 MINING 不碰鍵鼠
    assert calls["key_down"] == []
    assert calls["mouse_down"] == 0
