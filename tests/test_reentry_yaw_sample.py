"""回礦落地 yaw 取樣（2026-07-21，H059 語料收集）。

根因（2026-07-20 spec，07-21 覆核成立）：回礦每輪 attempt 都按「回到地表」換
重生點＝遊戲隨機化 yaw，sweep 的 cur_dir=0 基底是隨機值，restore_view 轉回的
是那個隨機基底 → 直角/對角各約一半（使用者實測）。根治需視覺校正，但目前
**缺「斜挖」負樣本**，無法依 H040/H054 慣例做門檻兩側夾。

本取樣鉤子解決語料問題：落地後原地拍八方位。相鄰幀固定差 45° ⇒ 偶數組與奇數組
必分屬直角/對角兩類，分類器可用「指標是否以週期 2 交替」自洽驗證，不需絕對標籤；
絕對歸屬只要人工標一輪即可定錨。
"""

from miningbot import diagnostics, harvester, main
from miningbot.main import Bot
from miningbot import reentry_remote


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


# ===== 純函式：快照 label =====
def test_yaw_sample_label_is_one_based():
    """檔名一律 1 起算（2026-07-18 使用者要求，同 reentry_ep{N}_dir{i+1} 慣例）；
    傳入的 dir_idx 是 0-based，與 range(8) 迴圈對齊。"""
    assert harvester.yaw_sample_label(7, 0) == "reentry_ep7_yaw1"
    assert harvester.yaw_sample_label(7, 7) == "reentry_ep7_yaw8"


def test_yaw_sample_label_routes_to_reentry_subdir():
    """label 以 reentry 開頭 → 分流到 snapshots/reentry，不汙染 review 的排錯視野。"""
    assert diagnostics.snapshot_subdir(harvester.yaw_sample_label(3, 0)) == "reentry"


# ===== 整合：_rr_yaw_sample =====
def _sample_bot(monkeypatch, enabled, rotate_results=None):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._mine_resetting = False
    bot._running = True
    bot.paused = False
    bot.shots = []
    bot.rotations = []
    bot._snapshot = lambda frame, label: bot.shots.append(label)
    results = list(rotate_results or [])

    def _rotate(direction):
        bot.rotations.append(direction)
        return results.pop(0) if results else True

    bot._rotate_verified = _rotate
    monkeypatch.setattr(main.capture, "grab", lambda: object())
    monkeypatch.setattr(main.cfg, "reentry_yaw_sample_sweep", enabled)
    return bot


def _ctx(episode_id=5):
    return reentry_remote.RemoteReentryContext(
        episode_id=episode_id, created_at=0.0, sticky_layer="L")


def test_yaw_sample_off_by_default(monkeypatch):
    """預設關：收語料是臨時性需求，不能讓每次回礦都多花 10-15 秒。"""
    assert main.cfg.reentry_yaw_sample_sweep is False
    bot = _sample_bot(monkeypatch, enabled=False)
    bot._rr_yaw_sample(_ctx())
    assert bot.shots == []
    assert bot.rotations == []


def test_yaw_sample_captures_eight_and_completes_full_circle(monkeypatch):
    """8 次同向旋轉＝轉滿一圈回原向（同 _rr_sweep 的 H050 慣例）——取樣結束面向
    不變，不影響後續挖礦；每個方位各拍一張。"""
    bot = _sample_bot(monkeypatch, enabled=True)
    bot._rr_yaw_sample(_ctx(episode_id=11))
    assert bot.shots == ["reentry_ep11_yaw%d" % i for i in range(1, 9)]
    assert bot.rotations == [1] * 8          # 同向 8 次＝淨 0


def test_yaw_sample_warns_when_rotation_eaten(monkeypatch):
    """旋轉被吃 → dir 標籤錯位、該輪語料不可信，必須記數警告（H050 教訓）。
    但照拍不中止：至少留下圖，由人工判斷可用性。"""
    bot = _sample_bot(monkeypatch, enabled=True,
                      rotate_results=[True, False, True, False, True, True, True, True])
    bot._rr_yaw_sample(_ctx())
    assert len(bot.shots) == 8
    assert any("2 次旋轉" in r for r in bot.logger.records)


def test_yaw_sample_aborts_on_reset(monkeypatch):
    """取樣中途遇 reset：立刻停手（reset 會重生、yaw 本就作廢），並警告面向已偏，
    免得事後把殘留旋轉誤判成別的 bug。"""
    bot = _sample_bot(monkeypatch, enabled=True)
    original = bot._snapshot

    def _snap(frame, label):
        original(frame, label)
        if len(bot.shots) == 3:
            bot._mine_resetting = True

    bot._snapshot = _snap
    bot._rr_yaw_sample(_ctx())
    assert len(bot.shots) == 3
    assert any("中止" in r for r in bot.logger.records)


# ===== 整合：_rr_success 串接順序 =====
def test_rr_success_samples_after_yaw_restore(monkeypatch):
    """取樣必須排在 restore_view 之後——語料要反映 bot 實際開挖的那個面向，
    在回正前拍會多帶使用者的方位偏移。"""
    order = []
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._pitch_home_mining = lambda label: order.append("home") or True
    bot._rr_finalize = lambda outcome: order.append("finalize")
    bot._rr_notify = lambda msg, **kw: None
    bot._rr_yaw_sample = lambda ctx: order.append("sample")
    monkeypatch.setattr(main.harvester, "restore_view",
                        lambda net, rotate=None: order.append("yaw"))
    bot._rr_success(_ctx(), "success")
    assert order == ["home", "yaw", "sample", "finalize"]
