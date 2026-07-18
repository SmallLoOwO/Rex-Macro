from miningbot import main
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


def _bot(monkeypatch, center_back_px):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._pitch_offset_px = 0
    bot._sampler_pitch_prepare = lambda: None
    monkeypatch.setattr(main.cfg, "sweep_pitch_center_back_px", center_back_px)
    monkeypatch.setattr(main.cfg, "sweep_pitch_clamp_px", 1500)
    return bot


def test_pitch_home_mining_skips_when_uncalibrated(monkeypatch):
    bot = _bot(monkeypatch, 0)
    calls = []
    bot._pitch_drag_verified = lambda label, drag: calls.append(label) or True
    assert bot._pitch_home_mining("啟動") is False
    assert calls == []                       # 未校準：一次拖曳都不准送
    assert any("未校準" in r for r in bot.logger.records)


def test_pitch_home_mining_success_sets_offset(monkeypatch):
    bot = _bot(monkeypatch, 300)
    drags = []
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: drags.append((down, back)))

    def verified(label, drag):
        drag()
        return True

    bot._pitch_drag_verified = verified
    assert bot._pitch_home_mining("啟動") is True
    assert drags == [(1500, 300)]
    assert bot._pitch_offset_px == 300       # 記帳與 _rr_pitch 同語意（距夾限偏移）


def test_pitch_home_mining_two_eaten_warns_not_blocks(monkeypatch):
    bot = _bot(monkeypatch, 300)
    attempts = []
    bot._pitch_drag_verified = lambda label, drag: attempts.append(label) or False
    assert bot._pitch_home_mining("啟動") is False
    assert len(attempts) == 2                # 重試一次即止
    assert any("兩輪皆疑似被吃" in r for r in bot.logger.records)


from miningbot import reentry_remote


def _rr_bot(monkeypatch, order):
    bot = Bot.__new__(Bot)
    bot._pitch_home_mining = lambda label: order.append("home") or True
    bot._rr_finalize = lambda outcome: order.append("finalize")
    bot._rr_notify = lambda msg, **kw: None
    return bot


def test_rr_success_order_home_finalize(monkeypatch):
    # `走` 退役（2026-07-18）後成功收尾：歸位 → ledger → 回 MINING
    order = []
    bot = _rr_bot(monkeypatch, order)
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=8, created_at=0.0, sticky_layer="mid")
    bot._rr_success(ctx, "confirmed_by_user")
    assert order == ["home", "finalize"]
    assert bot._reentry_done is True


# ===== H048：開場鏈俯仰歸位 prepare＋被吃重試（2026-07-18）=====
def test_rr_open_pitch_retry_on_eaten(monkeypatch):
    """開場鏈與其他俯仰路徑同規格：prepare → 量測 → 被吃再 prepare 重試一次。"""
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._focus_roblox = lambda: True
    bot._rr_open_first_ts = 0.0
    bot._click_surface_verified = lambda tag: False
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=3, created_at=0.0, sticky_layer="L", trigger="manual")
    bot._rr_ensure_ctx = lambda reroll: None
    prepares, attempts, notes = [], [], []
    bot._sampler_pitch_prepare = lambda: prepares.append(1)

    def measured(label, drag):
        attempts.append(label)
        return (False, 2.0, 0.03)          # 被吃但非凍結（夜間地表家族）
    bot._pitch_drag_measured = measured
    bot._maybe_arm_chime = lambda pct: None
    bot._rr_notify = lambda msg, **kw: notes.append(msg)
    bot._rr_sweep_and_send = lambda **kw: None
    bot._rr_embed_mid = None
    bot._rr_post_embed = lambda: None
    monkeypatch.setattr(main.capture, "grab", lambda: "FRAME")
    monkeypatch.setattr(main.capture, "crop", lambda f, region: f)
    monkeypatch.setattr(main.ocr, "read_depth_is_surface", lambda img, path: True)

    bot._rr_open_episode()

    assert len(attempts) == 2              # 被吃重試一次即止
    assert "attempt 1" in attempts[0] and "attempt 2" in attempts[1]
    assert len(prepares) == 3              # 首次 prepare＋兩次失敗後各一次
    assert any("疑似被吃" in n for n in notes)   # 只警告不擋拍照（H046 語意不變）


def test_rr_open_pitch_no_retry_when_ok(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._focus_roblox = lambda: True
    bot._rr_open_first_ts = 0.0
    bot._click_surface_verified = lambda tag: False
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=4, created_at=0.0, sticky_layer="L", trigger="manual")
    bot._rr_ensure_ctx = lambda reroll: None
    attempts, notes = [], []
    bot._sampler_pitch_prepare = lambda: None
    bot._pitch_drag_measured = lambda label, drag: attempts.append(label) or (True, 19.7, 0.31)
    bot._maybe_arm_chime = lambda pct: None
    bot._rr_notify = lambda msg, **kw: notes.append(msg)
    bot._rr_sweep_and_send = lambda **kw: None
    bot._rr_embed_mid = None
    bot._rr_post_embed = lambda: None
    monkeypatch.setattr(main.capture, "grab", lambda: "FRAME")
    monkeypatch.setattr(main.capture, "crop", lambda f, region: f)
    monkeypatch.setattr(main.ocr, "read_depth_is_surface", lambda img, path: True)

    bot._rr_open_episode()

    assert len(attempts) == 1              # 生效即停，不重複拖
    assert not any("疑似被吃" in n for n in notes)
