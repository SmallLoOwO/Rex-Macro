"""harvest 101 手動瞄準精定位：_detect_core_in_cell 編排邏輯（Phase 2）。

驗證 grid 路徑限縮偵測的座標映射、命中/未命中分流、素材 log label、預算與格無效守門。
純邏輯——capture/vision/_hsnap 全 monkeypatch，不碰真實 I/O。
"""
import numpy as np

from miningbot import main, remote_aim, notify
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, msg, *a):
        self.records.append(msg % a if a else msg)

    def warning(self, msg, *a):
        self.records.append(msg % a if a else msg)


def _bare_bot():
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot.log_harvest = bot.logger
    bot._reveal_chat = lambda: True        # H064：純 I/O（移游標＋抓幀），這裡不驗
    bot._shape_templates = {}              # 形狀 fallback 模板（H076）；這裡測編排邏輯不測形狀比對
    return bot


def _patch_io(monkeypatch, detect_result, frame=None):
    """統一 monkeypatch：grab 回固定幀、detect_tracker_core 回可控結果、放大圖＋快照 no-op。"""
    monkeypatch.setattr(main.cfg, "remote_aim_zoom_margin_frac", 0.0)   # C1→(640,0,320,270)
    monkeypatch.setattr(main.cfg, "remote_aim_fine_grid", 6)
    monkeypatch.setattr(main.cfg, "reentry_remote_zoom_scale", 3)
    frame = np.zeros((1080, 1920, 3), np.uint8) if frame is None else frame
    monkeypatch.setattr(main.capture, "grab", lambda: frame)
    monkeypatch.setattr(main.vision, "detect_tracker_core",
                        lambda crop, profiles, **kw: detect_result)
    monkeypatch.setattr(main.reentry_remote, "render_zoom",
                        lambda f, r, **k: np.zeros((10, 10, 3), np.uint8))
    return frame


def test_detect_core_hit_maps_region_origin_to_absolute(monkeypatch):
    # 101 真值：框在 C1、偵測回相對 (211,189) → +原點 (640,0) = (851,189)、0px 誤差
    bot = _bare_bot()
    _patch_io(monkeypatch, (211, 189, "green", 0.35))
    snapped = []
    monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: snapped.append(("crop", l)))
    monkeypatch.setattr(bot, "_hsnap", lambda f, l: snapped.append(("big", l)))

    pos, score, detail = bot._detect_core_in_cell("C1", 4, deadline=1e12, hid="101")

    assert pos == (851, 189)
    assert score == 0.35
    assert detail == ""
    # 命中：記裁格＋放大圖，但不記 miss label
    assert ("crop", "aim_cell_dir4_C1") in snapped
    assert any("zoom" in l for _, l in snapped)
    assert not any("miss" in l for _, l in snapped)


def test_detect_core_crop_region_matches_grid_cell(monkeypatch):
    # cell_crop 尺寸＝region 大小：C1 margin 0 → (270, 320, 3)
    bot = _bare_bot()
    seen = {}
    monkeypatch.setattr(main.cfg, "remote_aim_zoom_margin_frac", 0.0)
    monkeypatch.setattr(main.capture, "grab",
                        lambda: np.zeros((1080, 1920, 3), np.uint8))

    def spy(crop, profiles, **kw):
        seen["shape"] = crop.shape
        return (100, 100, "green", 0.2)

    monkeypatch.setattr(main.vision, "detect_tracker_core", spy)
    monkeypatch.setattr(main.reentry_remote, "render_zoom",
                        lambda f, r, **k: np.zeros((10, 10, 3), np.uint8))
    monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: None)
    monkeypatch.setattr(bot, "_hsnap", lambda f, l: None)
    bot._detect_core_in_cell("C1", 4, deadline=1e12, hid="101")
    assert seen["shape"] == (270, 320, 3)


def test_detect_core_miss_logs_miss_label_and_no_blind_fire(monkeypatch):
    # 未命中：不盲打、回 detail；另記 aim_core_miss label（補色系 profile fixture 來源）
    bot = _bare_bot()
    _patch_io(monkeypatch, None)
    snapped = []
    monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: snapped.append(l))
    monkeypatch.setattr(bot, "_hsnap", lambda f, l: snapped.append(l))

    pos, score, detail = bot._detect_core_in_cell("C1", 4, deadline=1e12, hid="101")

    assert pos is None and score == -1.0
    assert "未命中" in detail and "C1" in detail
    assert "aim_cell_dir4_C1" in snapped       # 每次裁格都記
    assert "aim_core_miss_dir4_C1" in snapped  # miss 額外記


def test_detect_core_invalid_cell(monkeypatch):
    bot = _bare_bot()
    _patch_io(monkeypatch, (10, 10, "green", 0.2))
    monkeypatch.setattr(bot, "_hsnap_crop", lambda f, r, l: None)
    monkeypatch.setattr(bot, "_hsnap", lambda f, l: None)
    pos, score, detail = bot._detect_core_in_cell("Z9", 4, deadline=1e12, hid="101")
    assert pos is None and "無效" in detail


def test_detect_core_deadline_exhausted(monkeypatch):
    bot = _bare_bot()
    monkeypatch.setattr(main.time, "time", lambda: 100.0)
    pos, score, detail = bot._detect_core_in_cell("C1", 4, deadline=50.0, hid="101")
    assert pos is None and detail == "預算用盡"


# ===== Phase 3：放大手選退路編排（awaiting_fine ＋ FOV 守門 ＋ 連鎖放大）=====
def _aim_ctx():
    ctx = remote_aim.AimContext(
        candidates=[], shots=[], pose_net_rotations=0, pose_pitch_layer="mid",
        harvest_id="101", created_at=0.0)
    return ctx


def _patch_fine_io(monkeypatch, bot, boost_present=False, zoom_path="/tmp/fine.png"):
    """統一 monkeypatch 退路 I/O：grab 固定幀、boost 偵測可控、focus True、
    發圖/訊息 no-op、放大圖渲染回固定路徑。"""
    monkeypatch.setattr(main.cfg, "remote_aim_zoom_margin_frac", 0.0)
    monkeypatch.setattr(main.cfg, "remote_aim_fine_grid", 6)
    monkeypatch.setattr(main.cfg, "reentry_remote_zoom_scale", 3)
    monkeypatch.setattr(main.cfg, "remote_aim_fov_recheck_max", 2)
    monkeypatch.setattr(main.capture, "grab", lambda: np.zeros((1080, 1920, 3), np.uint8))
    monkeypatch.setattr(bot, "_detect_boost_present", lambda frame: boost_present)
    monkeypatch.setattr(bot, "_focus_roblox", lambda: True)
    monkeypatch.setattr(bot, "_render_aim_zoom_image",
                        lambda frame, region, d, c, layer=0, scale=None: zoom_path)
    sent = []
    monkeypatch.setattr(notify, "send_images_message",
                        lambda token, ch, caption, paths: sent.append(("img", caption, paths)) or None)
    monkeypatch.setattr(notify, "send_message",
                        lambda token, ch, msg: sent.append(("msg", msg)) or None)
    return sent


def test_enter_aim_fine_sets_state_and_sends_zoom(monkeypatch):
    bot = _bare_bot()
    ctx = _aim_ctx()
    sent = _patch_fine_io(monkeypatch, bot, boost_present=True,
                          zoom_path="/tmp/z.png")
    bot._enter_aim_fine(ctx, "C1", 4, "mid", "101")
    assert ctx.awaiting_fine is True
    assert ctx.fine_cell == "C1" and ctx.fine_tgt_dir == 4
    assert ctx.zoom_region == (640, 0, 320, 270)   # C1 margin 0
    assert ctx.zoom_stack == []
    assert ctx.fov_state0 is True                  # boost 在場
    assert ctx.fov_rechecks == 0
    # 發了一張放大圖、caption 提到 DIR5（方位訊息面 1-8）的 C1
    assert any(c[0] == "img" and "DIR5" in c[1] and "C1" in c[1] for c in sent)


def test_fine_fire_fov_inconsistent_reissues_and_holds_fire(monkeypatch):
    # 發圖時 boost 在（fov_state0=True），玩家回細格時 boost 已到期（False）→ FOV 不一致、
    # 重發放大圖、不開火、留在 awaiting_fine
    bot = _bare_bot()
    ctx = _aim_ctx()
    ctx.awaiting_fine = True
    ctx.zoom_region = (640, 0, 320, 270)
    ctx.fine_tgt_dir = 4
    ctx.fine_cell = "C1"
    ctx.fov_state0 = True        # 發圖時 boost 在
    sent = _patch_fine_io(monkeypatch, bot, boost_present=False)  # 現在 boost 到期
    fired = []
    monkeypatch.setattr(bot, "_aim_fire_and_verify", lambda *a, **k: fired.append(a) or (False, ""))
    monkeypatch.setattr(bot, "_wait_for_d3_cooldown", lambda d: (True, ""))
    bot._execute_aim_fine_fire(ctx, "B3", "101")
    assert fired == []                            # 沒開火
    assert ctx.fov_rechecks == 1
    assert ctx.fov_state0 is False                # 重錄為當下狀態
    assert any(c[0] == "img" and "畫面變了" in c[1] for c in sent)


def test_fine_fire_fov_consistent_fires_at_cell_center(monkeypatch):
    # FOV 一致（boost 狀態沒變）→ 開火該細格中心。fine_cell_to_screen(C1,B3) 的絕對座標
    bot = _bare_bot()
    ctx = _aim_ctx()
    ctx.awaiting_fine = True
    ctx.zoom_region = (640, 0, 320, 270)           # C1 margin 0：320×270
    ctx.fine_tgt_dir = 4
    ctx.fine_cell = "C1"
    ctx.fov_state0 = False
    _patch_fine_io(monkeypatch, bot, boost_present=False)  # 一致（兩邊都 False）
    fired = []
    monkeypatch.setattr(
        bot, "_aim_fire_and_verify",
        lambda pos, score, layer, d, c, hid, dl, chat: fired.append((pos, layer, d)) or (True, "ok"))
    monkeypatch.setattr(bot, "_wait_for_d3_cooldown", lambda d: (True, ""))
    bot._execute_aim_fine_fire(ctx, "B3", "101")
    # C1 區域 (640,0,320,270)、6×6 細格：B=欄1 sw=53、3=列2 sh=45 → 中心 (640+26+53, 0+22+45)
    # fine_cell_to_screen：x+idx*sw+sw//2, y+idx*sh+sh//2
    import miningbot.reentry_remote as rr
    expected = rr.fine_cell_to_screen((640, 0, 320, 270), "B3", 6, 6)
    assert fired[0][0] == (int(expected[0]), int(expected[1]))


def test_fine_fire_fov_rechecks_at_max_still_fires(monkeypatch):
    # FOV 不一致但已達重發上限 → 不再重發、直接開火（bounded；總比卡死好）
    bot = _bare_bot()
    ctx = _aim_ctx()
    ctx.awaiting_fine = True
    ctx.zoom_region = (640, 0, 320, 270)
    ctx.fine_tgt_dir = 4
    ctx.fine_cell = "C1"
    ctx.fov_state0 = True
    ctx.fov_rechecks = 2                          # 已達 remote_aim_fov_recheck_max
    sent = _patch_fine_io(monkeypatch, bot, boost_present=False)
    fired = []
    monkeypatch.setattr(bot, "_aim_fire_and_verify", lambda *a, **k: fired.append(a) or (True, "ok"))
    monkeypatch.setattr(bot, "_wait_for_d3_cooldown", lambda d: (True, ""))
    bot._execute_aim_fine_fire(ctx, "B3", "101")
    assert fired != []                            # 仍開火
    assert ctx.fov_rechecks == 2                  # 沒再 +1
    assert not any("畫面變了" in c[1] for c in sent if c[0] == "img")


def test_aim_magnify_pushes_layer_and_shrinks_region(monkeypatch):
    bot = _bare_bot()
    ctx = _aim_ctx()
    ctx.awaiting_fine = True
    ctx.zoom_region = (640, 0, 320, 270)
    ctx.zoom_scale = 3
    ctx.fine_tgt_dir = 4
    ctx.fine_cell = "C1"
    sent = _patch_fine_io(monkeypatch, bot, boost_present=True)
    bot._aim_magnify(ctx, "B3", "101")
    # 上一層 push 進 stack；zoom_region 變成 B3 子區域（更小）
    assert len(ctx.zoom_stack) == 1
    assert ctx.zoom_stack[0]["region"] == (640, 0, 320, 270)
    assert ctx.zoom_region[2] < 320 and ctx.zoom_region[3] < 270   # 子格更小
    assert any("再放大" in c[1] for c in sent if c[0] == "img")


def test_aim_back_pops_layer(monkeypatch):
    bot = _bare_bot()
    ctx = _aim_ctx()
    ctx.awaiting_fine = True
    ctx.zoom_region = (700, 50, 50, 50)           # 假設目前在某放大子格
    ctx.zoom_scale = 9
    ctx.zoom_stack = [{"region": (640, 0, 320, 270), "scale": 3}]
    ctx.fine_tgt_dir = 4
    ctx.fine_cell = "C1"
    sent = _patch_fine_io(monkeypatch, bot, boost_present=True)
    bot._aim_back(ctx, "101")
    assert ctx.zoom_region == (640, 0, 320, 270)  # 退回首層
    assert ctx.zoom_stack == []
    assert ctx.zoom_scale == 3
    assert any("退一層" in c[1] for c in sent if c[0] == "img")


def test_aim_back_at_base_returns_to_cmd(monkeypatch):
    # 已在首層（stack 空）→ 退回等格子、awaiting_fine 關閉
    bot = _bare_bot()
    ctx = _aim_ctx()
    ctx.awaiting_fine = True
    ctx.zoom_region = (640, 0, 320, 270)
    ctx.zoom_stack = []
    ctx.fine_tgt_dir = 4
    ctx.fine_cell = "C1"
    sent = _patch_fine_io(monkeypatch, bot, boost_present=True)
    bot._aim_back(ctx, "101")
    assert ctx.awaiting_fine is False
    assert ctx.zoom_region == ()
    assert any("退回等格子" in c[1] for c in sent if c[0] == "msg")
