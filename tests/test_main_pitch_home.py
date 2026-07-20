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
    # yaw 回正（2026-07-20）：_rr_success 走 harvester.restore_view——stub 掉避免
    # 需要真的 _rotate_verified，並把淨轉動記入 order 供順序／傳值斷言。
    monkeypatch.setattr(main.harvester, "restore_view",
                        lambda net, rotate=None: order.append(("yaw", net)))
    return bot


def test_rr_success_order_home_yaw_finalize(monkeypatch):
    # 成功收尾順序：俯仰歸位 → yaw 回正 → ledger → 回 MINING
    order = []
    bot = _rr_bot(monkeypatch, order)
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=8, created_at=0.0, sticky_layer="mid")
    bot._rr_success(ctx, "confirmed_by_user")
    assert order == ["home", ("yaw", 0), "finalize"]
    assert bot._reentry_done is True


def test_rr_success_restores_yaw_from_cur_dir(monkeypatch):
    """回礦中 `方位` 指令累積的 ctx.cur_dir 在成功收尾時反向回正（2026-07-20
    使用者反映：選了斜向方位後沒回正，會帶進挖礦、W 往斜向走）。比照採集收尾
    _resume_mining_tail 的 restore_view，把淨旋轉送進去反向送鍵轉回。"""
    yaw_calls = []
    bot = Bot.__new__(Bot)
    bot._pitch_home_mining = lambda label: True
    bot._rr_finalize = lambda outcome: None
    bot._rr_notify = lambda msg, **kw: None
    bot._rotate_verified = lambda d: True
    monkeypatch.setattr(main.harvester, "restore_view",
                        lambda net, rotate=None: yaw_calls.append(net))
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=9, created_at=0.0, sticky_layer="L")
    ctx.cur_dir = 3                      # 使用者下過 `方位` 指令累積淨右轉
    bot._rr_success(ctx, "success")
    assert yaw_calls == [3]


# ===== H048/H052：開場鏈俯仰歸位——重試與成敗只認凍結探針（2026-07-19）=====
def _rr_open_gate_bot(monkeypatch, measured_results):
    """開場鏈最小 Bot：俯仰量測按 measured_results 依序回，記錄 prepare/attempt/notify。"""
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._focus_roblox = lambda: True
    bot._rr_open_first_ts = 0.0
    bot._click_surface_verified = lambda tag: False
    bot._rr_ctx = reentry_remote.RemoteReentryContext(
        episode_id=3, created_at=0.0, sticky_layer="L", trigger="manual")
    bot._rr_ensure_ctx = lambda reroll: None
    bot._rr_pitch_back_px = None
    bot._pitch_offset_px = 0
    bot.prepares, bot.attempts, bot.notes, bot.sweeps = [], [], [], []
    bot._sampler_pitch_prepare = lambda: bot.prepares.append(1)

    def measured(label, drag):
        bot.attempts.append(label)
        return measured_results[len(bot.attempts) - 1]
    bot._pitch_drag_measured = measured
    bot._maybe_arm_chime = lambda pct: None
    bot._rr_notify = lambda msg, **kw: bot.notes.append(msg)
    bot._rr_sweep_and_send = lambda **kw: bot.sweeps.append(1)
    bot._rr_embed_mid = None
    bot._rr_post_embed = lambda: None
    bot.last_action = ""
    monkeypatch.setattr(main.cfg, "reentry_pitch_back_px", 400)
    monkeypatch.setattr(main.capture, "grab", lambda: "FRAME")
    monkeypatch.setattr(main.capture, "crop", lambda f, region: f)
    monkeypatch.setattr(main.ocr, "read_depth_is_surface", lambda img, path: True)
    return bot


def test_rr_open_pitch_dark_low_diff_is_success(monkeypatch):
    """H052（RR#7 實錄 mean=4.64/2.34 誤判被吃）：eaten 門檻是白天礦內兩側夾
    （被吃 ≤3.29 vs 生效 ≥32.5），夜間地表真動只有 0.93~5.13 落在中間——歸位冪等，
    生效後重做畫面必然不變，eaten 判定對歸位無意義。開場鏈成敗只認凍結探針
    （H046 兩側夾：凍結 0.00/0.0000 vs 活著最小 0.09/0.0004）：非凍結＝生效，
    不重試、不發「疑似被吃」、記帳照同步。"""
    bot = _rr_open_gate_bot(monkeypatch, [(False, 2.0, 0.03)])
    bot._rr_open_episode()
    assert len(bot.attempts) == 1          # 非凍結＝生效，不再白拖第二輪（RR#7 每輪 ~20s）
    assert not any("疑似被吃" in n for n in bot.notes)
    assert bot._pitch_offset_px == 400     # 記帳同步（誤判被吃時曾脫鉤——卡面/存檔讀它）
    assert bot.sweeps == [1]


def test_rr_open_pitch_frozen_retries_then_defers(monkeypatch):
    """真凍結（H044/H046：逐位元 0.00）才 prepare 重試；兩次都凍結 → 開場閘擋拍照。"""
    bot = _rr_open_gate_bot(monkeypatch, [(False, 0.0, 0.0), (False, 0.0, 0.0)])
    bot._rr_open_episode()
    assert len(bot.attempts) == 2          # 凍結重試一次即止
    assert "attempt 1" in bot.attempts[0] and "attempt 2" in bot.attempts[1]
    assert len(bot.prepares) == 3          # 首次 prepare＋兩次凍結後各一次
    assert bot.sweeps == []                # gate=frozen：不拍照，回探測迴圈
    assert bot._pitch_offset_px == 0       # 凍結不記帳


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
    bot._pitch_drag_measured = lambda label, drag: (True, 19.7, 0.31)
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


def test_rr_pitch_reset_dark_low_diff_is_success(monkeypatch):
    """H052：`歸位` 指令與開場鏈同語意——非凍結（夜間地表 mean 2.0 級）＝生效，
    一次即止、✅ 回覆、記帳同步；不再回「⚠ 仰角歸位疑似被吃」誤導。"""
    bot = _rr_pitch_bot(monkeypatch)
    calls = []

    def measured(label, drag):
        calls.append(label)
        return (False, 2.0, 0.03)          # eaten 門檻下「被吃」、凍結探針下活著
    bot._pitch_drag_measured = measured
    bot._pitch_offset_px = 111
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    bot._rr_pitch(ctx, reentry_remote.RemoteReply("pitch_reset"))
    assert len(calls) == 1
    assert bot._pitch_offset_px == 400
    assert bot.notes and "✅" in bot.notes[-1][0]


def test_rr_pitch_reset_frozen_warns_after_retry(monkeypatch):
    """真凍結（0.00 逐位元）：重試一次仍凍結 → ⚠ 警告、不動記帳。"""
    bot = _rr_pitch_bot(monkeypatch)
    calls = []

    def measured(label, drag):
        calls.append(label)
        return (False, 0.0, 0.0)
    bot._pitch_drag_measured = measured
    bot._pitch_offset_px = 111
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=7, created_at=0.0, sticky_layer="L")
    bot._rr_pitch(ctx, reentry_remote.RemoteReply("pitch_reset"))
    assert len(calls) == 2
    assert bot._pitch_offset_px == 111
    assert bot.notes and "疑似被吃" in bot.notes[-1][0]


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
