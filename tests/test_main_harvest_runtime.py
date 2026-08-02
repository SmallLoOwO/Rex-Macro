import types

import cv2
import numpy as np

from miningbot import main, remote_aim
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


def test_shared_d3_cooldown_starts_immediately_before_hold_click(monkeypatch):
    bot = Bot.__new__(Bot)
    bot._last_d3_fire_at = None
    bot.log_harvest = _LogRecorder()
    now = [100.0]
    actions = []

    monkeypatch.setattr(main.cfg, "d3_cooldown_s", 10.0)
    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(main.time, "sleep", lambda seconds: actions.append(("sleep", seconds)))
    monkeypatch.setattr(main.ic, "key_press", lambda key: actions.append(("key", key)))

    def click(x, y, hold):
        assert bot._last_d3_fire_at == now[0]
        actions.append(("click", x, y, hold))

    monkeypatch.setattr(main.ic, "click_at", click)

    assert bot._fire_d3_at(640, 480) is True
    assert actions == [
        ("key", "2"), ("sleep", 0.15),
        ("key", "3"), ("sleep", 0.3),
        ("click", 640, 480, 0.4), ("sleep", 0.5),
    ]

    now[0] = 109.999
    assert bot._fire_d3_at(640, 480) is False
    assert len(actions) == 6

    now[0] = 110.0
    assert bot._fire_d3_at(640, 480) is True
    assert len(actions) == 12


def test_aim_renderer_matches_candidates_by_exact_snapshot_path(tmp_path, monkeypatch):
    first_path = str(tmp_path / "first.png")
    second_path = str(tmp_path / "second.png")
    black = np.zeros((400, 1000, 3), dtype=np.uint8)
    assert cv2.imwrite(first_path, black)
    assert cv2.imwrite(second_path, black)

    shots = [
        remote_aim.SweepShot("mid", 2, first_path, []),
        remote_aim.SweepShot("mid", 2, second_path, []),
    ]
    candidates = [
        remote_aim.AimCandidate(
            1, "mid", 2, (200, 180), 0.9, "first",
            status="accepted", snapshot_path=first_path),
        remote_aim.AimCandidate(
            2, "mid", 2, (750, 180), 0.8, "second",
            status="fired", snapshot_path=second_path),
    ]
    ctx = remote_aim.AimContext(
        candidates=candidates, shots=shots, pose_net_rotations=0,
        pose_pitch_layer="mid", harvest_id="079", created_at=1.0)
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    monkeypatch.setattr(main.cfg, "log_dir", str(tmp_path))
    monkeypatch.setattr(main.cfg, "remote_aim_snapshot_wait_s", 0.1)

    rendered = bot._render_aim_shots(ctx)

    assert len(rendered) == 2
    first_overlay = cv2.imread(first_path.replace(".png", "_aim.png"))
    assert tuple(first_overlay[180, 164]) == (0, 215, 255)
    assert tuple(first_overlay[180, 714]) != (0, 215, 255)


# --- H054（2026-07-20，harvest 094）：基準無聊天歷史 → 計數差確認必須被擋 ---
# 實機：episode 進場凍結的聊天裁圖落在 Roblox 聊天淡出時段 → 基準只讀到常駐面板
# "NORMAL"、0 條 has-found；sweep 期間事件訊息讓聊天整段重新淡入 → 計數差把開火前
# 早就在的舊採集行全當新增 → rare 0→2 + special 判 SUCCESS。鐵證：框未消失
# (gone=False)、開火前後聊天裁圖 MD5 相同＝這一發沒產生任何新行，礦其實沒挖到。
from tests.test_ocr import (H054_BASELINE_HIDDEN, H054_AFTER_094,
                            H054_BASELINE_VISIBLE_082, H054_AFTER_082,
                            H054_COMMON)


class _WarnRecorder(_LogRecorder):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)
        super().warning(message, *args)

    def debug(self, message, *args):
        pass


def _verify_bot(monkeypatch, after_text):
    bot = Bot.__new__(Bot)
    bot.log_harvest = _WarnRecorder()
    bot._chat_ledger = None
    monkeypatch.setattr(main.ocr, "read_text_multi",
                        lambda *args, **kwargs: [after_text])
    monkeypatch.setattr(main.cfg, "found_keywords", ("has found", "found a"))
    monkeypatch.setattr(main.cfg, "special_keywords", ("ionized", "spectral"))
    monkeypatch.setattr(Bot, "_log_rapid_diag", lambda self, hid, why: None)
    return bot


def test_h054_hidden_baseline_suppresses_count_diff_confirmation(monkeypatch):
    bot = _verify_bot(monkeypatch, H054_AFTER_094)
    _, confirmed, special = bot._verify_chat_ocr(
        None, [H054_BASELINE_HIDDEN], H054_COMMON, (), "094", "poll")

    assert confirmed is False and special is False
    assert any("H054 基準閘" in w for w in bot.log_harvest.warnings)


def test_h054_visible_baseline_still_confirms_real_success(monkeypatch):
    # 兩側夾另一側：082 真成功（基準看得到 10 條歷史）不可被閘擋掉
    bot = _verify_bot(monkeypatch, H054_AFTER_082)
    _, confirmed, _ = bot._verify_chat_ocr(
        None, [H054_BASELINE_VISIBLE_082], H054_COMMON, (), "082", "poll")

    assert confirmed is True
    assert bot.log_harvest.warnings == []


def test_h054_gate_does_not_veto_ledger_confirmation(monkeypatch):
    # 帳本自帶錨點、規則等效，基準閘不可連它一起擋（否則 H032 晚到行救不回）
    bot = _verify_bot(monkeypatch, H054_AFTER_094)
    bot._chat_ledger = main.ocr.ChatLedger([H054_BASELINE_HIDDEN])
    monkeypatch.setattr(type(bot._chat_ledger), "confirmed", property(lambda self: True))
    monkeypatch.setattr(Bot, "_maybe_detect_world_from_ore_lines", lambda self, lines: None)

    _, confirmed, _ = bot._verify_chat_ocr(
        None, [H054_BASELINE_HIDDEN], H054_COMMON, (), "094", "poll")

    assert confirmed is True


# --- H064（2026-07-28，harvest 110~119）：淡出基準 + 聊天重顯示 → 底行才是本次新增 ---
# 走完整 _verify_chat_ocr：H054 基準閘照樣把計數差歸零並記 WARNING，但帳本以「重顯示
# 只認底行」規則入帳 → confirmed 仍為 True（舊行為整輪棄權 → RESWEEP → 誤交人工）。
from tests.test_ocr import H064_AFTER_119, H064_COMMON


def test_h064_faded_baseline_confirms_through_ledger_bottom_line(monkeypatch):
    bot = _verify_bot(monkeypatch, H064_AFTER_119)
    bot._chat_ledger = main.ocr.ChatLedger([""])
    monkeypatch.setattr(Bot, "_maybe_detect_world_from_ore_lines", lambda self, lines: None)

    _, confirmed, _ = bot._verify_chat_ocr(
        None, [""], H064_COMMON, (), "119", "poll")

    assert confirmed is True
    assert bot._chat_ledger.rare_lines == ["small_lo has found Coinstorm"]
    assert any("H054 基準閘" in w for w in bot.log_harvest.warnings)


def test_h064_faded_baseline_094_still_rejected_end_to_end(monkeypatch):
    # 兩側夾：同一條路徑餵 094（底行是一般礦 Syrooze）必須仍判不成功
    bot = _verify_bot(monkeypatch, H054_AFTER_094)
    bot._chat_ledger = main.ocr.ChatLedger([H054_BASELINE_HIDDEN])
    monkeypatch.setattr(Bot, "_maybe_detect_world_from_ore_lines", lambda self, lines: None)

    _, confirmed, special = bot._verify_chat_ocr(
        None, [H054_BASELINE_HIDDEN], H054_COMMON, (), "094", "poll")

    assert confirmed is False and special is False


# --- H064：_reveal_chat 拍基準前用 hover 把淡出的聊天叫回來 ---------------------
# 實機量測（2026-07-28 全螢幕、Roblox 前景）：hover 聊天圖示只冒出 "Chat" tooltip
# （chat_region 亮像素 304），hover 聊天內容區才會整段顯示（13614），游標移開後
# ≥25s 不再淡出。聊天隱藏時該座標下面是 3D 場景 → **絕不可點擊**。
def _reveal_bot(monkeypatch, bright_px):
    bot = Bot.__new__(Bot)
    bot.log_harvest = _WarnRecorder()
    moves, clicks = [], []
    crop = np.zeros((10, 10, 3), dtype=np.uint8)
    crop.reshape(-1, 3)[:bright_px] = (255, 255, 255)   # 亮像素數＝bright_px

    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(main.ic, "move_to", lambda x, y: moves.append((x, y)))
    monkeypatch.setattr(main.ic, "_screen_center", lambda: (960, 540))
    monkeypatch.setattr(main.ic, "click_at",
                        lambda *a, **k: clicks.append(a))
    monkeypatch.setattr(main.ic, "mouse_click",
                        lambda *a, **k: clicks.append(a))
    monkeypatch.setattr(main.capture, "grab", lambda: None)
    monkeypatch.setattr(main.capture, "crop", lambda frame, region: crop)
    return bot, moves, clicks


def test_h064_reveal_chat_hovers_the_chat_area_and_never_clicks(monkeypatch):
    bot, moves, clicks = _reveal_bot(monkeypatch, bright_px=50)
    monkeypatch.setattr(main.cfg, "chat_reveal_min_bright_px", 20)

    assert bot._reveal_chat() is True
    # 先停在聊天內容區、再移開（不可停在那裡擋畫面/影響後續點擊）
    assert moves == [tuple(main.cfg.chat_reveal_xy), (960, 540)]
    assert clicks == []                      # ★ 安全釘樁：一次都不准點
    assert moves[0] != tuple(main.cfg.chat_icon_xy)   # 圖示是 toggle，不是喚醒點


def test_h064_reveal_chat_warns_when_chat_stays_hidden(monkeypatch):
    # 最可能的失敗型＝Roblox 不在前景，合成 hover 整個被丟掉 → 亮像素仍在淡出側
    bot, moves, clicks = _reveal_bot(monkeypatch, bright_px=3)
    monkeypatch.setattr(main.cfg, "chat_reveal_min_bright_px", 20)

    assert bot._reveal_chat() is False
    assert any("聊天喚醒無效" in w for w in bot.log_harvest.warnings)
    assert clicks == []                      # 失敗也不准改成點擊救援


# --- H118（2026-07-28）：_harvest_boost_guard 中途補 D5 讓 ref 對不上新 FOV -----
#
# 118 實錄：01:07:45 sweep 中途補 D5（FOV 收縮/展開）；01:07:57 轉回去 verify
# 剛才看過的框卻找不到了；緊接的重掃（_reharvest_sweep，H026 對策不重拍 ref）
# 沿用同一份已經跟新 FOV 對不上的 ref，結果 8 方位全空。


def _harvest_state():
    return types.SimpleNamespace(harvest_id="118", net_rotations=0, pitch_layer="mid")


def test_sweep_for_tracker_flags_fov_shift_when_boost_guard_fires(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.harvest = _harvest_state()
    bot.log_harvest = _LogRecorder()
    bot._tracker_log = None
    bot._find_tracker = lambda *a, **kw: None       # 118 第二輪重掃實錄：全 8 方位都沒找到
    bot._rotate_verified = lambda step: True
    monkeypatch.setattr(main.cfg, "remote_aim_enabled", False)
    monkeypatch.setattr(main.cfg, "sweep_empty_snapshot", False)
    monkeypatch.setattr(main.capture, "grab", lambda: np.zeros((4, 4, 3), np.uint8))

    guard_calls = []

    def guard(frame):
        guard_calls.append(1)
        return len(guard_calls) == 3            # 第 3 個方位補 D5，其餘不用補

    bot._harvest_boost_guard = guard
    bot._harvest_scan_guard = lambda: False

    pos, had = bot._sweep_for_tracker([], None)

    assert pos is None and had is False
    assert bot._sweep_fov_shifted is True, "本輪掃描中補過 D5，旗標該立起來"


def test_sweep_for_tracker_no_flag_when_boost_guard_never_fires(monkeypatch):
    bot = Bot.__new__(Bot)
    bot.harvest = _harvest_state()
    bot.log_harvest = _LogRecorder()
    bot._tracker_log = None
    bot._find_tracker = lambda *a, **kw: None
    bot._rotate_verified = lambda step: True
    bot._harvest_boost_guard = lambda frame: False
    bot._harvest_scan_guard = lambda: False
    monkeypatch.setattr(main.cfg, "remote_aim_enabled", False)
    monkeypatch.setattr(main.cfg, "sweep_empty_snapshot", False)
    monkeypatch.setattr(main.capture, "grab", lambda: np.zeros((4, 4, 3), np.uint8))

    bot._sweep_for_tracker([], None)

    assert bot._sweep_fov_shifted is False, "沒補過 D5，不該誤報 FOV 換過"


def test_reharvest_sweep_refresh_ref_recaptures_after_boost_settle(monkeypatch):
    """refresh_ref=True：捨棄舊 ref，比照進場邏輯——先確認 FOV 展開，按 D2 之前重拍。

    D06 的方位 reference 同樣是舊 FOV 下拍的 → 這條路要一起重拍（旋轉在這個 fake 下
    直接成功，只驗「有去重拍」，八張的細節由 `_capture_dir_references` 自己的測試守）。
    """
    bot = Bot.__new__(Bot)
    bot.harvest = types.SimpleNamespace(d3_attempts=3, net_rotations=0,
                                        pitch_layer="mid", harvest_id="118")
    bot.log_harvest = _LogRecorder()
    bot.logger = _LogRecorder()
    bot._rotate_verified = lambda step: True
    bot._pre_scan_ref = "舊的、FOV 已經對不上的 ref"
    bot._sweep_fov_shifted = True
    bot._await_scan_ready = lambda where: True
    bot._confirm_scan = lambda where: True
    scan_calls = []
    bot._run_scan = lambda: scan_calls.append("run_scan")
    monkeypatch.setattr(main.harvester, "prepare_scan", lambda: None)

    fresh_frame = "新 FOV 底下的乾淨畫面"
    monkeypatch.setattr(main.capture, "grab", lambda: fresh_frame)
    bot._harvest_boost_guard = lambda frame: False   # 已經展開，guard 這次不用再補

    bot._reharvest_sweep(refresh_ref=True)

    assert bot._pre_scan_ref == fresh_frame
    assert bot._sweep_fov_shifted is False
    assert scan_calls == ["run_scan"]
    assert sorted(bot._pre_scan_refs) == list(range(8)), "方位 ref 也要一起重拍"


def test_reharvest_sweep_default_keeps_existing_ref(monkeypatch):
    """refresh_ref=False（預設）——H026 對策不變，既有 ref 原封不動、完全不碰畫面。"""
    bot = Bot.__new__(Bot)
    bot.harvest = types.SimpleNamespace(d3_attempts=3)
    bot._pre_scan_ref = "既有 ref（框可能已在畫面上，不能重拍）"
    bot._sweep_fov_shifted = True   # 防禦性驗證：即使漏傳也不該殘留舊旗標到下一輪
    bot._await_scan_ready = lambda where: True
    bot._confirm_scan = lambda where: True
    bot._run_scan = lambda: None
    monkeypatch.setattr(main.harvester, "prepare_scan", lambda: None)

    def _boom():
        raise AssertionError("refresh_ref=False 不該碰畫面/guard")
    monkeypatch.setattr(main.capture, "grab", lambda: _boom())
    bot._harvest_boost_guard = lambda frame: _boom()

    bot._reharvest_sweep()

    assert bot._pre_scan_ref == "既有 ref（框可能已在畫面上，不能重拍）"
    assert bot._sweep_fov_shifted is False


# --- D06（2026-08-01）：每個方位各拍一張 preexist reference ---------------------
#
# 舊版八方位共用「起始方位」那一張，而 preexist 差分是逐像素同座標比對 → 轉 45° 之後
# 比的是世界上完全不同的地方。玩家標註的 11 張漏抓裡，9 張可測的有 6 張死在
# `ref_fill`（1.00/0.78/0.70/0.22/0.16），量測與被否決的三條便宜路見
# docs/open-detection-issues.md D06。


def _ref_bot(monkeypatch, *, rotate_ok=True, frames=None):
    bot = Bot.__new__(Bot)
    bot.harvest = _harvest_state()
    bot.log_harvest = _LogRecorder()
    bot.logger = _LogRecorder()
    seq = iter(frames) if frames is not None else None
    monkeypatch.setattr(main.capture, "grab",
                        (lambda: next(seq)) if seq else
                        (lambda: np.zeros((4, 4, 3), np.uint8)))
    monkeypatch.setattr(main.cfg, "sweep_per_dir_reference", True)
    rotations = []

    def rotate(step):
        rotations.append(step)
        return rotate_ok or len(rotations) < 3       # 第 3 次被吃
    bot._rotate_verified = rotate
    return bot, rotations


def test_capture_dir_references_shoots_one_per_direction_and_returns_to_start(monkeypatch):
    """八張、鍵是絕對方位、轉滿一圈（8×45°＝360°）回到原方位。"""
    frames = [np.full((4, 4, 3), i, np.uint8) for i in range(8)]
    bot, rotations = _ref_bot(monkeypatch, frames=frames)
    assert bot._capture_dir_references("test") is True
    assert sorted(bot._pre_scan_refs) == list(range(8))
    assert [int(bot._pre_scan_refs[d][0, 0, 0]) for d in range(8)] == list(range(8))
    assert rotations == [1] * 8, "轉滿一圈才回得到原方位"
    assert bot._pre_scan_refs_layer == "mid"


def test_capture_dir_references_aborts_and_restores_when_rotation_eaten(monkeypatch):
    """旋轉被吃 → 整組作廢、轉回原方位、回 False（呼叫端沿用單張 ref＝今日行為）。

    半套的方位 reference 比沒有更糟：鍵值與實際朝向錯開一格，等於把 D06 換個方位重演。
    """
    bot, rotations = _ref_bot(monkeypatch, rotate_ok=False)
    assert bot._capture_dir_references("test") is False
    assert bot._pre_scan_refs == {}
    assert bot._pre_scan_refs_layer is None
    # 前 2 次成功、第 3 次被吃 → 要往回轉 2 步（restore_view 會送 2 個反向鍵）
    assert rotations[:3] == [1, 1, 1]
    assert rotations[3:] == [-1, -1], "轉回去的步數要等於已成功轉出去的步數"


def test_capture_dir_references_is_off_when_flag_is_off(monkeypatch):
    bot, rotations = _ref_bot(monkeypatch)
    monkeypatch.setattr(main.cfg, "sweep_per_dir_reference", False)
    assert bot._capture_dir_references("test") is False
    assert rotations == [], "關掉就一步都不轉"


def test_sweep_uses_the_reference_shot_at_that_direction(monkeypatch):
    """sweep 每個方位要拿**自己**那張 reference 去比，不是起始方位那張。"""
    bot, _ = _ref_bot(monkeypatch)
    bot._pre_scan_refs = {d: np.full((4, 4, 3), d, np.uint8) for d in range(8)}
    bot._pre_scan_refs_layer = "mid"
    bot._tracker_log = None
    bot._harvest_boost_guard = lambda frame: False
    bot._harvest_scan_guard = lambda: False
    monkeypatch.setattr(main.cfg, "remote_aim_enabled", False)
    monkeypatch.setattr(main.cfg, "sweep_empty_snapshot", False)
    seen = []

    def find(frame, excl, ref, **kw):
        seen.append(int(ref[0, 0, 0]))
        return None
    bot._find_tracker = find
    bot._sweep_for_tracker([], np.full((4, 4, 3), 99, np.uint8))
    assert seen == list(range(8)), "每個方位都要用該方位的 ref，不得是 fallback 99"


def test_sweep_falls_back_to_single_reference_on_a_different_pitch_layer(monkeypatch):
    """reference 是在拍攝當下那一層拍的；拿 mid 的去比 up 層等於重演 D06 本身。"""
    bot, _ = _ref_bot(monkeypatch)
    bot._pre_scan_refs = {d: np.full((4, 4, 3), d, np.uint8) for d in range(8)}
    bot._pre_scan_refs_layer = "mid"
    bot.harvest.pitch_layer = "up"
    bot._tracker_log = None
    bot._harvest_boost_guard = lambda frame: False
    bot._harvest_scan_guard = lambda: False
    monkeypatch.setattr(main.cfg, "remote_aim_enabled", False)
    monkeypatch.setattr(main.cfg, "sweep_empty_snapshot", False)
    seen = []

    def find(frame, excl, ref, **kw):
        seen.append(int(ref[0, 0, 0]))
        return None
    bot._find_tracker = find
    bot._sweep_for_tracker([], np.full((4, 4, 3), 99, np.uint8))
    assert seen == [99] * 8, "層對不上就要退回單張 ref"


def test_prefire_relocate_uses_per_direction_reference(monkeypatch):
    """開火前重定位也要用當下方位的 reference（D06 同步到 pre-fire）。

    159（2026-08-01）：sweep 已修（D06 每方位 ref），但 pre-fire 仍用全域
    _pre_scan_ref → dir=3 的框在初始方位 ref 下 rej(preexist) → 無效 RESWEEP 迴圈、
    TRACKER_FOUND 連洗 5 次。
    """
    bot, _ = _ref_bot(monkeypatch)
    bot._pre_scan_refs = {d: np.full((4, 4, 3), d, np.uint8) for d in range(8)}
    bot._pre_scan_refs_layer = "mid"
    bot._pre_scan_ref = np.full((4, 4, 3), 99, np.uint8)   # 全域（初始方位拍）
    bot.harvest.net_rotations = 3                           # 面朝 dir=3
    bot.harvest.pitch_layer = "mid"
    bot.harvest.harvest_id = "159"
    bot.harvest.d3_attempts = 0
    bot._harvest_start = 0.0
    bot._target_marker = (100, 100)                         # sweep 已完成 → 進 D3 階段
    bot._chat_baseline_crop = np.zeros((4, 4, 3), np.uint8)
    bot._chat_baseline = None
    bot.last_action = ""
    bot._harvest_boost_guard = lambda frame: False
    bot._d3_cooldown_remaining = lambda: 0.0
    bot._tracker_exclusions = lambda: []
    bot._reharvest_sweep = lambda **kw: None                # 重定位失敗後不炸
    monkeypatch.setattr(main.game_data, "common_ore_names", lambda: [])
    monkeypatch.setattr(main.time, "time", lambda: 0.0)

    seen = []

    def find(frame, excl, reference_bgr=None, **kw):
        seen.append(int(reference_bgr[0, 0, 0]) if reference_bgr is not None else None)
        return None

    bot._find_tracker = find
    bot._tick_harvest(np.zeros((4, 4, 3), np.uint8))
    assert seen == [3], (
        "pre-fire 重定位必須用當下方位(dir=3)的 ref，不是全域 ref(99)；拿到 %r" % seen)


# ── H072 classify 交叉驗證（harvest 162：Weevil→Weevi 假成功）──────────────

def test_classify_confirms_new_rare_rejects_truncated_common():
    """count_rare_found 說有新稀有（截斷假計數差）、classify_found_ore 說沒有 → 否決。"""
    KW = ["has found", "found a"]
    before = ["small_lo has found Weevil\nsmall_lo has found Siogyne"]
    after  = ["small_lo has found Weevi\nsmall_lo has found Siogyne"]
    assert main.classify_confirms_new_rare(before, after, KW) is False


def test_classify_confirms_new_rare_accepts_real_rare():
    """真稀有 礦入帳：classify 也確認有新稀有 → 不否決。"""
    KW = ["has found", "found a"]
    before = ["small_lo has found Weevil"]
    after  = ["small_lo has found Weevil\nsmall_lo has found Clovara"]
    assert main.classify_confirms_new_rare(before, after, KW) is True
