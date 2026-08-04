"""fake bot harness：不啟動整台 bot，只組出跑得動 main.py 整合路徑的最小 Bot。

**為什麼需要這個**（2026-07-26 補）：P1~P5 每一階段都把「main.py 整合測試」往下推，
理由都是「具體 fake bot 結構依 main.py，留下階段補」——結果 8 個 `pytest.skip` 從
P1 一路留到現在，所有 web 測試都只驗 standalone `WebIPCThread` + mock，從來沒有一個
測試跑過 `Bot` 上真正的整合方法。H061 啟動卡死（多執行緒 import lock 死結）就是在
這個盲區裡發生的：全套測試綠，實機三次啟動全卡死。

**做法**：`Bot.__new__(Bot)` 繞過 `__init__`（那裡面有音訊裝置、模板載入、四個
worker thread，測試環境跑不起來也不該跑），只掛上受測方法真正會碰到的屬性，其餘
協作物件用 stub。要驗的是「這些方法之間的接線」，不是 I/O 本身。

**用法**：

    bot = make_fake_bot(
        bind=["_consume_web_pending"],          # 綁真實方法（受測目標）
        _web_pending=PendingReplies(),          # 其餘屬性直接指定
    )

`bind` 先套用，屬性後套用——所以要 stub 掉某個真實方法時，直接在 kwargs 給就好。
"""
import logging
import types

from miningbot.main import Bot


class RecordingRegistry:
    """假的 WebSocket client registry：把 broadcast 的 WebMessage 收進 list。"""

    def __init__(self):
        self.calls = []

    def broadcast(self, msg):
        self.calls.append(msg)

    def broadcast_binary(self, data):
        pass

    def begin_intervention_replay(self):
        pass

    def end_intervention_replay(self):
        pass

    def payloads(self, event=None):
        """回收到的 payload dict；給 event 名就只回該事件。"""
        out = [c.payload for c in self.calls if hasattr(c, "payload")]
        if event is not None:
            out = [p for p in out if p.get("event") == event]
        return out


class FakeWebThread:
    """假的 WebIPCThread：只提供 `.app.state.registry`（廣播路徑唯一會碰的東西）。"""

    def __init__(self):
        self.registry = RecordingRegistry()
        state = types.SimpleNamespace(registry=self.registry)
        self.app = types.SimpleNamespace(state=state)


class FakeFallback:
    """假的 FallbackState：直接指定「現在算不算 fallback」。

    is_fallback=False ＝ 網頁有人在線（走 web 路徑）；True ＝ 沒人（走 Discord）。
    """

    def __init__(self, fallback=False):
        self._fallback = fallback

    def is_fallback(self, now, grace_s):
        return self._fallback


class FakeHarvestCtx:
    """harvest flow 的 _aim_context 替身（只帶受測路徑會讀的欄位）。"""

    def __init__(self, harvest_id="007", pose_net_rotations=0, pose_pitch_layer="mid",
                 shots=()):
        self.harvest_id = harvest_id
        self.pose_net_rotations = pose_net_rotations
        self.pose_pitch_layer = pose_pitch_layer
        self.shots = list(shots)     # _push_web_aim_candidates 推整輪方位用（採 158）


class FakeReentryCtx:
    """reentry flow 的 ctx 替身。"""

    def __init__(self, episode_id="3"):
        self.episode_id = episode_id
        self.clicks = []


def make_fake_bot(*, bind=(), **attrs):
    """組一台 fake bot。

    bind：要綁上去的**真實** Bot 方法名（受測目標）。
    attrs：其餘屬性 / stub 方法，覆蓋預設值。
    """
    bot = Bot.__new__(Bot)
    bot.logger = logging.getLogger("tests.fake_bot")
    bot.log_harvest = logging.getLogger("tests.fake_bot.harvest")
    bot.log_discord = logging.getLogger("tests.fake_bot.discord")
    # web 三件組預設「沒有 web」——要測 web 路徑的測試自己傳進來覆蓋
    bot._web_pending = None
    bot._web_fallback = None
    bot._web_thread = None
    bot._ping_messenger = None
    bot._pending_ping_mid = {}
    bot._mine_resetting = False
    bot._rr_ctx = None
    bot._pending_aim = None
    # 防掛機（_antiafk_tick 由 _await_web_action 呼叫；預設 0=未計時，
    # 第一次只設 timer 就 return，interval 900s 遠大於測試 mock 時間）
    bot._antiafk_last = 0.0
    bot._antiafk_pressed_at = 0.0
    bot._antiafk_mute_logged = False
    bot.paused = False
    # 聊天喚醒（H064）＝純 I/O（移游標＋抓幀），不是這裡要驗的接線 → 預設 no-op
    bot._reveal_chat = lambda: True
    # 俯仰前卸裝 D2＝純 I/O（截圖＋按鍵），不是接線測試要驗的 → 預設 no-op
    bot._unequip_scanner = lambda *a, **k: None
    for name in bind:
        setattr(bot, name, types.MethodType(getattr(Bot, name), bot))
    for key, value in attrs.items():
        setattr(bot, key, value)
    return bot
