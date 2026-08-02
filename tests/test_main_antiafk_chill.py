"""H060：防掛機 Space（原地跳）自製的 chill 假觸發 —— observe() 接線層回歸。

純函式 `audio.chill_muted_after_antiafk` 在 test_audio.py 驗；這裡只鎖「主迴圈真的
有用它」。分開測的理由見 `states.resolve_state_transition` 的教訓：決策函式本身正確、
測試全綠，但接線層讀錯變數照樣整條路壞掉。

實機（2026-07-22）：REENTRY 等指令期間每 15 分鐘按一次 Space 保活，三次 spawn chill
誤報全部發生在「防掛機：按 Space」之後 2 秒，分數 0.25 / 0.38 / 0.37。
"""
from miningbot import main
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


class _StubListener:
    def __init__(self, score):
        self._score = score

    def latest_score(self):
        return self._score


def _observing_bot(score, pressed_at):
    """只裝 observe() 會碰到的欄位——不建整個 Bot runtime。"""
    bot = Bot.__new__(Bot)
    bot.listener = _StubListener(score)
    bot._peak_audio_since_hb = 0.0
    bot.logger = _LogRecorder()
    bot._antiafk_pressed_at = pressed_at
    bot._antiafk_mute_logged = False
    # chill 上升緣純記錄（spec 2026-07-30 B 段）：靜音必須在上升緣判定**之前**生效，
    # 否則 bot 自製的跳躍音會污染那份要拿來定 debounce 門檻的實機分布。
    bot._chill_above = False
    bot._chill_fell_at = None
    bot._chill_edges = []
    bot.log_harvest = _LogRecorder()
    bot._manual_reentry = False
    bot.human_cleared = False
    bot._reentry_done = False
    bot._reentry_failed = False
    bot._check_reset = lambda frame: False
    bot._update_reset_complete = lambda: False
    bot._reentry_active = lambda: False
    # observe() 在 08-02 為 double-chill banner 偵測加了 `if self.state is State.MINING`
    # 通往 _sample_banner_color(frame)。本檔只測 antiafk 靜音窗，banner 與之無關——
    # 設 MINING 並 stub 掉取樣，免得 frame=None 炸掉（banner 偵測另由實機驗證）。
    bot.state = main.State.MINING
    bot._sample_banner_color = lambda frame: None
    return bot


def test_observe_suppresses_chill_inside_antiafk_mute_window(monkeypatch):
    # 實機最高的一次誤報分數 0.38，落在按鍵後 2s
    monkeypatch.setattr(main.time, "time", lambda: 102.0)
    bot = _observing_bot(score=0.38, pressed_at=100.0)

    obs = bot.observe(frame=None)

    assert obs.chill_audio is False, "防掛機按鍵後的跳躍音不可被當成 chill"
    assert obs.chill_text is False
    assert any("chill 靜音" in r for r in bot.logger.records), "靜音要留一筆可診斷的 log"
    assert not any("chill 觸發" in r for r in bot.logger.records)


def test_observe_accepts_chill_after_antiafk_mute_window(monkeypatch):
    # 同一個分數、只差時間落在窗外 → 必須照常觸發（靜音窗不可吃掉真 chill）
    monkeypatch.setattr(main.time, "time",
                        lambda: 100.0 + main.cfg.antiafk_chill_mute_s + 0.5)
    bot = _observing_bot(score=0.38, pressed_at=100.0)

    obs = bot.observe(frame=None)

    assert obs.chill_audio is True
    assert obs.chill_text is True          # chill_require_ocr=False：只靠音訊
    assert any("chill 觸發" in r for r in bot.logger.records)


def test_observe_accepts_chill_when_antiafk_never_pressed(monkeypatch):
    # 挖礦中不按 Space（防掛機只在等待狀態跑）→ 錨點為 0，完全不影響
    monkeypatch.setattr(main.time, "time", lambda: 100.0)
    bot = _observing_bot(score=0.38, pressed_at=0.0)

    assert bot.observe(frame=None).chill_audio is True


def test_observe_logs_antiafk_mute_once_per_press(monkeypatch):
    # 實機一次誤報會連續取樣到 ~12 幀；靜音 log 每次按鍵只能留一筆
    monkeypatch.setattr(main.time, "time", lambda: 102.0)
    bot = _observing_bot(score=0.38, pressed_at=100.0)

    for _ in range(5):
        bot.observe(frame=None)

    assert sum("chill 靜音" in r for r in bot.logger.records) == 1


def test_antiafk_press_arms_mute_window(monkeypatch):
    """`_antiafk_tick` 真的按下 Space 時要把靜音窗錨點設到**按下當刻**。

    錨點不可用進函式時的 now：`_focus_roblox` 失焦時會先花 ~1.3s，用舊時間會少遮
    一段尾巴。
    """
    presses = []
    clock = [500.0]
    monkeypatch.setattr(main.time, "time", lambda: clock[0])
    monkeypatch.setattr(main.ic, "key_press", lambda key: presses.append(key))

    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._antiafk_last = 500.0 - main.cfg.antiafk_interval_s      # 剛好到期
    bot._antiafk_pressed_at = 0.0
    bot._antiafk_mute_logged = True
    # 失焦分支：不開 Roblox，聚焦動作以樁攔下（並模擬它花掉的時間）
    bot._focus_roblox = lambda: clock.__setitem__(0, clock[0] + 1.3)

    bot._antiafk_tick("測試")

    assert presses == ["space"]
    assert bot._antiafk_pressed_at == clock[0], "錨點要是按下當刻，不是進函式時的 now"
    assert bot._antiafk_mute_logged is False, "新一次按鍵要重新武裝靜音 log"


def test_muted_score_never_becomes_a_chill_edge(monkeypatch):
    """靜音要在**上升緣判定之前**套用（spec 2026-07-30 B 段）。

    上升緣分布是之後用來定 `chill_edge_release_s` 的唯一依據；讓 bot 自己的跳躍音
    進去，等於用假資料訂門檻，再用那個門檻去製造新的人工次數。
    """
    monkeypatch.setattr(main.time, "time", lambda: 102.0)
    bot = _observing_bot(score=0.38, pressed_at=100.0)      # 窗內

    bot.observe(frame=None)

    assert bot._chill_edges == [], "防掛機靜音期間不得產生上升緣"
    assert bot._chill_above is False


def test_real_chill_outside_mute_window_records_an_edge(monkeypatch):
    """兩側夾：窗外的真 chill 必須留下上升緣，否則整份記錄形同關閉。"""
    monkeypatch.setattr(main.time, "time", lambda: 200.0)
    bot = _observing_bot(score=0.38, pressed_at=100.0)      # 窗外

    bot.observe(frame=None)

    assert len(bot._chill_edges) == 1
    ts, score, since_fall = bot._chill_edges[0]
    assert (ts, score, since_fall) == (200.0, 0.38, None)
