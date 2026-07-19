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
    bot._rr_pitch_back_px = None
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
    bot._rr_pitch_back_px = None
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


# ===== 重骰保留 session 仰角＋開場記帳同步（2026-07-19 使用者反映）=====
def _rr_open_bot(monkeypatch, session_back, drags):
    """開場鏈最小 Bot：俯仰量測必成功，drag 實跑以記錄 pitch_reset 參數。"""
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._focus_roblox = lambda: True
    bot._rr_open_first_ts = 0.0
    bot._click_surface_verified = lambda tag: False
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=6, created_at=0.0, sticky_layer="L", trigger="manual")
    bot._rr_ensure_ctx = lambda reroll: None
    bot._rr_pitch_back_px = session_back
    bot._pitch_offset_px = 0
    bot._sampler_pitch_prepare = lambda: None

    def measured(label, drag):
        drag()
        return (True, 19.7, 0.31)
    bot._pitch_drag_measured = measured
    bot._maybe_arm_chime = lambda pct: None
    bot._rr_notify = lambda msg, **kw: None
    bot._rr_sweep_and_send = lambda **kw: None
    bot._rr_embed_mid = None
    bot._rr_post_embed = lambda: None
    monkeypatch.setattr(main.ic, "pitch_reset",
                        lambda down, back: drags.append((down, back)))
    monkeypatch.setattr(main.cfg, "reentry_pitch_clamp_px", 1500)
    monkeypatch.setattr(main.cfg, "reentry_pitch_back_px", 400)
    monkeypatch.setattr(main.capture, "grab", lambda: "FRAME")
    monkeypatch.setattr(main.capture, "crop", lambda f, region: f)
    monkeypatch.setattr(main.ocr, "read_depth_is_surface", lambda img, path: True)
    return bot


def test_rr_open_default_homes_to_config_and_syncs_accounting(monkeypatch):
    """episode 內沒調過：歸位到 config 標準角，且記帳同步（卡面俯仰行讀它）。"""
    drags = []
    bot = _rr_open_bot(monkeypatch, None, drags)
    bot._rr_open_episode()
    assert drags == [(1500, 400)]
    assert bot._pitch_offset_px == 400


def test_rr_open_reroll_applies_session_pitch(monkeypatch):
    """`上|下` 調過後重骰：開場歸位回拉量＝使用者記帳值，不被 config 標準角洗掉。"""
    drags = []
    bot = _rr_open_bot(monkeypatch, 260, drags)
    bot._rr_open_episode(reroll=True)
    assert drags == [(1500, 260)]
    assert bot._pitch_offset_px == 260


def _rr_pitch_bot(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._sampler_pitch_prepare = lambda: None
    bot._pitch_drag_verified = lambda label, drag: True
    bot.notes = []                               # [(msg, kwargs)]
    bot._rr_notify = lambda msg, **kw: bot.notes.append((msg, kw))
    bot._rr_sync_write = lambda img, label: "shot.png"
    bot._pitch_offset_px = 400
    bot._rr_pitch_back_px = None
    monkeypatch.setattr(main.capture, "grab", lambda: "FRAME")
    monkeypatch.setattr(main.cfg, "reentry_pitch_clamp_px", 1500)
    monkeypatch.setattr(main.cfg, "reentry_pitch_back_px", 400)
    monkeypatch.setattr(main.cfg, "sample_pitch_step_px", 40)
    monkeypatch.setattr(main.ic, "pitch_reset", lambda down, back: None)
    monkeypatch.setattr(main.ic, "pitch_nudge", lambda dy: None)
    return bot


def test_rr_pitch_nudge_records_session_back(monkeypatch):
    """`上 120` 後 session 記帳＝新偏移；之後重骰開場沿用（不回 config）。"""
    bot = _rr_pitch_bot(monkeypatch)
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    bot._rr_pitch(ctx, reentry_remote.RemoteReply("pitch", cell="up", steps=120))
    assert bot._pitch_offset_px == 520
    assert bot._rr_pitch_back_px == 520


def test_rr_pitch_reset_clears_session_back(monkeypatch):
    """`歸位` ＝回 config 標準角：session 記帳清空，重骰開場改用 config 現值。"""
    bot = _rr_pitch_bot(monkeypatch)
    bot._rr_pitch_back_px = 520
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    bot._rr_pitch(ctx, reentry_remote.RemoteReply("pitch_reset"))
    assert bot._pitch_offset_px == 400
    assert bot._rr_pitch_back_px is None


def test_rr_pitch_attaches_confirm_shot(monkeypatch):
    """仰角指令回覆附單張當前面向截圖（2026-07-19：免手動 📷 八方位重掃）。"""
    bot = _rr_pitch_bot(monkeypatch)
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    bot._rr_pitch(ctx, reentry_remote.RemoteReply("pitch", cell="down", steps=40))
    assert bot.notes and bot.notes[-1][1].get("image_paths") == ["shot.png"]
    bot.notes.clear()
    bot._rr_pitch(ctx, reentry_remote.RemoteReply("pitch_reset"))
    assert bot.notes and bot.notes[-1][1].get("image_paths") == ["shot.png"]


def test_rr_pitch_shot_failure_does_not_block_reply(monkeypatch):
    """截圖失敗只記 log 不擋回覆（訊息照發、不附圖）。"""
    bot = _rr_pitch_bot(monkeypatch)

    def boom(img, label):
        raise OSError("disk full")
    bot._rr_sync_write = boom
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    bot._rr_pitch(ctx, reentry_remote.RemoteReply("pitch", cell="up", steps=40))
    assert bot.notes and bot.notes[-1][1].get("image_paths") is None


# ===== `存檔`：回礦中把 session 仰角寫回 config 標準角（2026-07-19）=====
def test_rr_pitch_save_writes_config_and_syncs_memory(monkeypatch, tmp_path):
    bot = _rr_pitch_bot(monkeypatch)
    bot._pitch_offset_px = 520
    bot._rr_pitch_back_px = 520
    fake_cfg = tmp_path / "config.py"
    fake_cfg.write_text(
        "    reentry_pitch_back_px: int = 400            # 回拉量\n",
        encoding="utf-8")
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    assert bot._rr_pitch_save(ctx, path=str(fake_cfg)) is True
    assert "reentry_pitch_back_px: int = 520" in fake_cfg.read_text(encoding="utf-8")
    assert main.cfg.reentry_pitch_back_px == 520   # 記憶體同步（monkeypatch 會還原）
    assert bot._rr_pitch_back_px is None           # session 交還標準角（config 現值＝期望值）
    assert any("💾" in m for m, _kw in bot.notes)


def test_rr_pitch_save_missing_anchor_keeps_memory(monkeypatch, tmp_path):
    """錨點不唯一/不存在＝不寫檔也不動記憶體 cfg（檔案與記憶體不分岔）。"""
    bot = _rr_pitch_bot(monkeypatch)
    bot._pitch_offset_px = 520
    fake_cfg = tmp_path / "config.py"
    fake_cfg.write_text("    unrelated: int = 1\n", encoding="utf-8")
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    assert bot._rr_pitch_save(ctx, path=str(fake_cfg)) is False
    assert main.cfg.reentry_pitch_back_px == 400
    assert any("❌" in m for m, _kw in bot.notes)


def test_rr_pitch_save_clamps_value(monkeypatch, tmp_path):
    """記帳負值（實際已飽和在夾限）存檔＝0，與 effective_pitch_back 同語意。"""
    bot = _rr_pitch_bot(monkeypatch)
    bot._pitch_offset_px = -60
    fake_cfg = tmp_path / "config.py"
    fake_cfg.write_text(
        "    reentry_pitch_back_px: int = 400\n", encoding="utf-8")
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    assert bot._rr_pitch_save(ctx, path=str(fake_cfg)) is True
    assert "reentry_pitch_back_px: int = 0" in fake_cfg.read_text(encoding="utf-8")
