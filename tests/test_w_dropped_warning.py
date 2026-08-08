"""W 鍵 OS 層落差警報（H082 續，2026-08-08）。

`input_control.key_down/key_up('w')` 只記 bot 自己送出指令當下的意圖——遊戲或
Windows 把這個持續按住的鍵吃掉，pydirectinput 收不到任何回報。這條直接問
`GetAsyncKeyState`：bot 認為 W 該按著，但 OS 層已經沒按著，就是「W 被外力放掉」
的直接證據，而非 bot 主動 `key_up`（H082 已用實機 log 排除後者：bot 自己呼叫
key_up 到下次 key_down 全部 ≤12s）。
"""
from miningbot.main import Bot
from miningbot.states import State


class _Recorder:
    def __init__(self):
        self.records = []

    def warning(self, msg, *args):
        self.records.append(("WARNING", msg % args if args else msg))

    def info(self, msg, *args):
        self.records.append(("INFO", msg % args if args else msg))


def _bot(should_be_down=True, actually_down=False):
    bot = Bot.__new__(Bot)
    bot.logger = _Recorder()
    bot.paused = False
    bot.state = State.MINING
    bot._w_drop_notified = False
    bot._ic_should = should_be_down
    bot._ic_actual = actually_down
    return bot


def _patch_ic(monkeypatch, bot):
    from miningbot import main
    monkeypatch.setattr(main.ic, "w_should_be_down", lambda: bot._ic_should)
    monkeypatch.setattr(main.ic, "w_actually_down", lambda: bot._ic_actual)


def test_warns_when_bot_thinks_down_but_os_says_up(monkeypatch):
    bot = _bot(should_be_down=True, actually_down=False)
    _patch_ic(monkeypatch, bot)
    bot._check_w_os_state()
    warnings = [r for r in bot.logger.records if r[0] == "WARNING"]
    assert len(warnings) == 1
    assert "w-dropped" in warnings[0][1]
    assert bot._w_drop_notified is True


def test_no_warning_when_os_agrees_key_is_down(monkeypatch):
    bot = _bot(should_be_down=True, actually_down=True)
    _patch_ic(monkeypatch, bot)
    bot._check_w_os_state()
    assert bot.logger.records == []
    assert bot._w_drop_notified is False


def test_no_warning_when_bot_never_pressed_w(monkeypatch):
    """bot 根本不認為 W 該按著（例如剛開機）——OS 沒按著是正常狀態，不可誤報。"""
    bot = _bot(should_be_down=False, actually_down=False)
    _patch_ic(monkeypatch, bot)
    bot._check_w_os_state()
    assert bot.logger.records == []


def test_does_not_check_when_paused(monkeypatch):
    bot = _bot(should_be_down=True, actually_down=False)
    bot.paused = True
    _patch_ic(monkeypatch, bot)
    bot._check_w_os_state()
    assert bot.logger.records == []
    assert bot._w_drop_notified is False


def test_does_not_check_when_not_mining(monkeypatch):
    for state in (State.HARVESTING, State.RESET_WAIT, State.REENTRY,
                  State.NEEDS_HUMAN):
        bot = _bot(should_be_down=True, actually_down=False)
        bot.state = state
        _patch_ic(monkeypatch, bot)
        bot._check_w_os_state()
        assert bot.logger.records == [], f"state={state} 不該警報"
        assert bot._w_drop_notified is False


def test_warns_once_until_key_recovers(monkeypatch):
    """警報後鎖住；OS 再次回報按著才解鎖——避免每個 tick 洗頻道。"""
    bot = _bot(should_be_down=True, actually_down=False)
    _patch_ic(monkeypatch, bot)

    bot._check_w_os_state()
    assert len([r for r in bot.logger.records if r[0] == "WARNING"]) == 1
    assert bot._w_drop_notified is True

    bot._check_w_os_state()            # 仍然沒按著 -> 不重複警報
    assert len([r for r in bot.logger.records if r[0] == "WARNING"]) == 1

    bot._ic_actual = True              # 鍵又按著了（人工介入或 REFOCUS 重壓）
    bot._check_w_os_state()
    assert bot._w_drop_notified is False

    bot._ic_actual = False             # 之後若又掉了 -> 可再警報
    bot._check_w_os_state()
    assert len([r for r in bot.logger.records if r[0] == "WARNING"]) == 2
