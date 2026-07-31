"""交人工前救援 ＋ chill 前快取 ＋ 雙 chill 對帳的 I/O glue（spec 2026-07-30 三份）。

純函式（環形緩衝取用、面板剖析／差分、上升緣狀態機、對帳判定）在
`test_harvester.py` / `test_audio.py` / `test_panel_fixtures.py`。本檔驗的是**接線**：
哪個方法在什麼條件下被呼叫、旗標怎麼流、降級有沒有真的回到今日行為。

harness 用 `tests/fake_bot.py`——`Bot.__new__` 繞過需要音訊裝置與 worker thread 的
`__init__`，只掛受測路徑真正會碰到的屬性。
"""
import collections
import logging

import numpy as np
import pytest

from miningbot import main
from miningbot.config import DEFAULT as cfg
from miningbot.states import State
from tests.fake_bot import make_fake_bot


class _Rec(logging.Logger):
    """收 log 字串，讓測試能斷言走了哪條降級分支。"""

    def __init__(self):
        super().__init__("tests.rescue")
        self.lines = []

    def info(self, msg, *args, **kw):
        self.lines.append(msg % args if args else msg)

    warning = info


class _FakeEventLog:
    def __init__(self):
        self.records = []

    def log(self, type_, **meta):
        self.records.append((type_, meta))


def _frame(value=7):
    return np.full((1080, 1920, 3), value, dtype=np.uint8)


def _harvest(hid="125"):
    from miningbot.harvester import HarvestState
    return HarvestState(0, 0.0, harvest_id=hid)


# ── 01：chill 前裁圖環形緩衝 ────────────────────────────────────────────────

def _cache_bot(**attrs):
    return make_fake_bot(
        bind=["_prechill_sample", "_prechill_ref"],
        _prechill=collections.deque(maxlen=cfg.prechill_cache_depth),
        _prechill_at=0.0, **attrs)


def test_prechill_sample_throttles_to_configured_interval(monkeypatch):
    bot = _cache_bot()
    now = [1000.0]
    monkeypatch.setattr(main.time, "time", lambda: now[0])
    bot._prechill_sample(_frame())
    now[0] += cfg.prechill_cache_interval_s / 2
    bot._prechill_sample(_frame())          # 未滿間隔 → 不存
    assert len(bot._prechill) == 1
    now[0] += cfg.prechill_cache_interval_s
    bot._prechill_sample(_frame())
    assert len(bot._prechill) == 2


def test_prechill_sample_stores_chat_crop_at_configured_region(monkeypatch):
    bot = _cache_bot()
    monkeypatch.setattr(main.time, "time", lambda: 1000.0)
    bot._prechill_sample(_frame())
    ts, chat = bot._prechill[0]
    assert ts == 1000.0
    assert chat.shape[:2] == (cfg.chat_region.h, cfg.chat_region.w)


def test_prechill_crops_are_copies_not_views(monkeypatch):
    """必須 copy：view 會扣住整張 1920×1080 原幀，6 筆就是 37MB 而不是預算的 3.7MB。"""
    bot = _cache_bot()
    monkeypatch.setattr(main.time, "time", lambda: 1000.0)
    frame = _frame(7)
    bot._prechill_sample(frame)
    frame[:] = 99                            # 主迴圈會覆寫 buffer
    assert bot._prechill[0][1].max() == 7    # 快取不得跟著變


def test_prechill_ring_buffer_is_bounded(monkeypatch):
    bot = _cache_bot()
    now = [1000.0]
    monkeypatch.setattr(main.time, "time", lambda: now[0])
    for _ in range(cfg.prechill_cache_depth * 3):
        bot._prechill_sample(_frame())
        now[0] += cfg.prechill_cache_interval_s
    assert len(bot._prechill) == cfg.prechill_cache_depth


def test_prechill_sample_ignores_none_frame(monkeypatch):
    bot = _cache_bot()
    monkeypatch.setattr(main.time, "time", lambda: 1000.0)
    bot._prechill_sample(None)
    assert len(bot._prechill) == 0


def test_prechill_ref_applies_configured_min_age(monkeypatch):
    bot = _cache_bot()
    now = [1000.0]
    monkeypatch.setattr(main.time, "time", lambda: now[0])
    for _ in range(cfg.prechill_cache_depth):
        bot._prechill_sample(_frame())
        now[0] += cfg.prechill_cache_interval_s
    assert bot._prechill_ref(now[0])[0] <= now[0] - cfg.prechill_min_age_s
    assert bot._prechill_ref(0.0) is None     # 全部都太新


# ── 02：chill 上升緣記錄 ────────────────────────────────────────────────────

def _edge_bot():
    return make_fake_bot(bind=["_record_chill_edge"], _chill_above=False,
                         _chill_fell_at=None, _chill_edges=[], log_harvest=_Rec())


def test_record_chill_edge_appends_only_on_rise():
    bot = _edge_bot()
    for score in (0.01, 0.40, 0.44, 0.38):    # 一聲、連續三個 tick 在門檻上
        bot._record_chill_edge(score)
    assert len(bot._chill_edges) == 1


def test_record_chill_edge_tracks_fall_and_gap(monkeypatch):
    bot = _edge_bot()
    now = [1000.0]
    monkeypatch.setattr(main.time, "time", lambda: now[0])
    bot._record_chill_edge(0.40)              # 上升緣 #1
    now[0] += 1.0
    bot._record_chill_edge(0.01)              # 回落
    now[0] += 16.0
    bot._record_chill_edge(0.37)              # 上升緣 #2（實錄間隔 16s）
    assert [e[2] for e in bot._chill_edges] == [None, 16.0]
    assert any("回落" in line for line in bot.log_harvest.lines)


def test_record_chill_edge_never_touches_decisions():
    """純記錄：不得回傳任何東西、不得改 chill_audio（observe 已在呼叫前定案）。"""
    bot = _edge_bot()
    assert bot._record_chill_edge(0.40) is None


# ── 04：交人工前救援 ────────────────────────────────────────────────────────

def _entry(ts):
    return (ts,
            np.zeros((cfg.chat_region.h, cfg.chat_region.w, 3), np.uint8))


def _rescue_bot(monkeypatch, *, chat=(), panel=(), cached=True, entries=None, **attrs):
    monkeypatch.setattr(main.capture, "grab", _frame)
    resumed = []
    if entries is None:
        entries = collections.deque(maxlen=cfg.prechill_cache_depth)
        if cached:
            entries.append(_entry(1000.0))
    attrs.setdefault("_episode_chill_at", 1005.0)
    attrs.setdefault("_panel_zeroed_at", 9999.0)   # 01 已歸零 → 路 B 可信任
    bot = make_fake_bot(
        bind=["_giveup_rescue", "_prechill_ref"],
        harvest=_harvest(), _prechill=entries, log_harvest=_Rec(),
        log=_FakeEventLog(), logger=_Rec(),
        _rescue_chat_ores=lambda *a: list(chat),
        _panel_rare_ores=lambda *a: list(panel),
        _harvest_resume_mining=lambda: resumed.append(True),
        _enqueue_snapshot=lambda crop, label: f"/snap/{label}.png",
        _hlabel=lambda label: f"125_{label}",
        **attrs)
    # giveup 發生在 chill 之後好幾分鐘——錨點若誤用「現在」，min_age 閘就完全失效
    monkeypatch.setattr(main.time, "time", lambda: 1200.0)
    return bot, resumed


def test_rescue_anchors_reference_at_chill_not_at_giveup(monkeypatch):
    """`prechill_min_age_s` 是「比 **chill** 早這麼久」。

    誤用 giveup 當下的時間當錨會讓那道閘完全失效：episode 常跑好幾分鐘，任何快取都
    「夠舊」，於是永遠取到最新那筆＝礦已經被挖掉的那一幀＝差分恆為 0，救援形同關閉。
    """
    entries = collections.deque([_entry(1000.0), _entry(1004.5)],
                                maxlen=cfg.prechill_cache_depth)
    bot, _ = _rescue_bot(monkeypatch, entries=entries)
    bot._giveup_rescue("x")
    # chill=1005.0、min_age=3.0 → 上界 1002.0 → 取 1000.0（1004.5 太新，可能已含那次挖掘）
    assert bot._prechill_ref(bot._episode_chill_at)[0] == 1000.0
    # 拿 giveup 當下（1200.0）當錨：min_age 閘失效，只剩 max_age 擋著 → 整個沒得救。
    # 兩道閘任一寫錯都會讓救援靜默失效，所以錨點必須是 chill 時刻。
    assert bot._prechill_ref(main.time.time()) is None


def test_rescue_hits_on_panel_only(monkeypatch):
    """125 型：面板有新的非-common 礦名 → 不交人工。"""
    bot, resumed = _rescue_bot(monkeypatch, panel=["faedrine"])
    assert bot._giveup_rescue("全方位掃描未找到追蹤框") is True
    assert resumed == [True]
    kind, meta = bot.log.records[0]
    assert kind == "HARVEST_RESCUED"
    assert meta["source"] == "panel" and meta["ore_names"] == ["faedrine"]


def test_rescue_source_is_both_when_paths_agree(monkeypatch):
    bot, _ = _rescue_bot(monkeypatch, chat=["faedrine"], panel=["faedrine"])
    assert bot._giveup_rescue("x") is True
    _kind, meta = bot.log.records[0]
    assert meta["source"] == "both"
    assert meta["ore_names"] == ["faedrine"]        # 聯集去重


def test_rescue_never_fakes_harvest_success(monkeypatch):
    """實機驗證期要能把救援命中與正常採集成功分開統計。"""
    bot, _ = _rescue_bot(monkeypatch, chat=["faedrine"])
    bot._giveup_rescue("x")
    assert [k for k, _m in bot.log.records] == ["HARVEST_RESCUED"]


def test_rescue_declines_when_no_evidence(monkeypatch):
    bot, resumed = _rescue_bot(monkeypatch)
    assert bot._giveup_rescue("x") is False
    assert resumed == [] and bot.log.records == []


def test_rescue_path_a_skipped_without_prechill_cache_but_path_b_still_works(monkeypatch):
    """路 A（聊天）沒有 chill 前快取 → 跳過；路 B（面板）若已歸零仍可命中。

    新設計（spec 2026-07-31）：两條路獨立運作，路 B 不再依賴 prechill 緩衝。
    """
    bot, resumed = _rescue_bot(monkeypatch, panel=["faedrine"], cached=False)
    assert bot._giveup_rescue("x") is True     # 路 B 命中
    assert resumed == [True]
    assert any("路 A" in line and "跳過" in line for line in bot.log_harvest.lines)


def test_rescue_skipped_when_both_paths_degraded(monkeypatch):
    """路 A 無快取 + 路 B 面板未歸零 → 照舊交人工。"""
    bot, resumed = _rescue_bot(monkeypatch, panel=["faedrine"], cached=False,
                               _panel_zeroed_at=None)
    assert bot._giveup_rescue("x") is False
    assert resumed == []
    assert any("路 B" in line and "跳過" in line for line in bot.log_harvest.lines)


def test_rescue_disabled_by_config(monkeypatch):
    bot, resumed = _rescue_bot(monkeypatch, panel=["faedrine"])
    monkeypatch.setattr(cfg, "giveup_rescue_enabled", False)
    assert bot._giveup_rescue("x") is False
    assert resumed == []


def test_rescue_exception_falls_back_to_giveup(monkeypatch):
    """任何例外 → WARNING 後回 False，救援本身絕不能把 giveup 弄壞。"""
    def _boom(*a):
        raise RuntimeError("OCR 掛了")

    bot, resumed = _rescue_bot(monkeypatch, panel=["faedrine"])
    bot._panel_rare_ores = _boom
    assert bot._giveup_rescue("x") is False
    assert resumed == []
    assert any("例外" in line for line in bot.log_harvest.lines)


def test_harvest_giveup_returns_early_when_rescued(monkeypatch):
    """救援命中 → _harvest_giveup 不得再走到 NEEDS_HUMAN。"""
    bot = make_fake_bot(
        bind=["_harvest_giveup"], harvest=_harvest(), state=State.HARVESTING,
        _giveup_rescue=lambda reason: True,
        _log_chill_reconcile_only=lambda: pytest.fail("救援命中後不該再對帳"),
        _on_enter=lambda s, f: pytest.fail("救援命中後不該進 NEEDS_HUMAN"),
        _needs_human_extra_meta={})
    bot._harvest_giveup("全方位掃描未找到追蹤框")
    assert bot.state is State.HARVESTING


# ── 路 A / 路 B 的降級 ──────────────────────────────────────────────────────

def test_chat_path_blind_when_baseline_saw_no_history(monkeypatch):
    """H054：chill 前聊天淡出（0 條 has-found）→ 差分無效，整條路 A 跳過。

    不擋的話任何新訊息會讓舊行整段重新顯示，差分把舊採集行全當本次新增＝假救援。
    """
    bot = make_fake_bot(bind=["_rescue_chat_ores"], log_harvest=_Rec())
    monkeypatch.setattr(main.ocr, "read_text_multi", lambda *a, **kw: ["NORMAL"])
    monkeypatch.setattr(main.ocr, "extract_new_found_lines_multi",
                        lambda *a: pytest.fail("空基準不得進差分"))
    assert bot._rescue_chat_ores(None, None, "125") == []


def test_chat_path_filters_common_ores(monkeypatch):
    bot = make_fake_bot(bind=["_rescue_chat_ores"], log_harvest=_Rec())
    monkeypatch.setattr(main.ocr, "read_text_multi",
                        lambda *a, **kw: ["small_lo has found Weevil"])
    monkeypatch.setattr(main.ocr, "extract_new_found_lines_multi",
                        lambda *a: ["small_lo has found Weevil",
                                    "small_lo has found Faedrine"])
    assert bot._rescue_chat_ores(None, None, "125") == ["faedrine"]


def test_chat_path_ignores_lines_already_in_prechill(monkeypatch):
    """pre-chill 已含該行 → 不算新（差分由 extract_new_found_lines_multi 負責）。"""
    bot = make_fake_bot(bind=["_rescue_chat_ores"], log_harvest=_Rec())
    before = "small_lo has found Faedrine"
    monkeypatch.setattr(main.ocr, "read_text_multi", lambda *a, **kw: [before])
    assert bot._rescue_chat_ores(None, None, "125") == []


def test_panel_path_skipped_without_rapidocr(monkeypatch):
    """read_text_boxes 只有 rapidocr 路徑、不做 tesseract 後備 → 整條跳過只跑路 A。"""
    bot = make_fake_bot(bind=["_panel_rare_ores"], log_harvest=_Rec())
    monkeypatch.setattr(main.ocr, "rapidocr_available", lambda: False)
    monkeypatch.setattr(main.ocr, "read_text_boxes",
                        lambda *a, **kw: pytest.fail("引擎不可用不得呼叫"))
    assert bot._panel_rare_ores("125", "救援路B") == []


# ── 05：雙 chill 對帳（出廠關閉）────────────────────────────────────────────

def test_reconcile_is_off_by_default():
    """門檻沒有實機分布之前不可上線——猜錯會直接製造新的人工次數。"""
    assert cfg.chill_reconcile_enabled is False
    assert cfg.chill_edge_release_s == 0.0


def _reconcile_bot(monkeypatch, *, edges, gains, enabled=True, release_s=2.0):
    monkeypatch.setattr(cfg, "chill_reconcile_enabled", enabled)
    monkeypatch.setattr(cfg, "chill_edge_release_s", release_s)
    monkeypatch.setattr(main.capture, "grab", _frame)
    monkeypatch.setattr(main.harvester, "restore_view", lambda net, rotate=None: None)
    entered = []
    return make_fake_bot(
        bind=["_chill_reconcile"], harvest=_harvest(), state=State.HARVESTING,
        _chill_edges=edges, _sweep_shots=[],
        _episode_panel_gains=lambda: list(gains), _rotate_verified=lambda d: True,
        _enqueue_snapshot=lambda crop, label: None,
        _snapshot_crop=lambda f, r, label: None, _hlabel=lambda label: label,
        _on_enter=lambda s, f: entered.append(s), _needs_human_extra_meta={},
        _human_reason="", log_harvest=_Rec()), entered


def test_reconcile_disabled_does_nothing(monkeypatch):
    bot, entered = _reconcile_bot(monkeypatch, edges=[(1.0, 0.4, None), (20.0, 0.4, 18.0)],
                                  gains=[], enabled=False)
    assert bot._chill_reconcile("收尾") is False
    assert entered == []


def test_reconcile_disabled_when_release_threshold_unset(monkeypatch):
    """release_s=0（沒有實機分布）＝停用，即使 enabled 被打開也不跑。"""
    bot, entered = _reconcile_bot(monkeypatch, edges=[(1.0, 0.4, None), (20.0, 0.4, 18.0)],
                                  gains=[], release_s=0.0)
    assert bot._chill_reconcile("收尾") is False
    assert entered == []


def test_reconcile_unbalanced_goes_to_human(monkeypatch):
    bot, entered = _reconcile_bot(
        monkeypatch, edges=[(1.0, 0.40, None), (20.0, 0.37, 18.0)], gains=["faedrine"])
    assert bot._chill_reconcile("收尾") is True
    assert bot.state is State.NEEDS_HUMAN and entered == [State.NEEDS_HUMAN]
    assert "2 聲" in bot._human_reason and "faedrine" in bot._human_reason


def test_reconcile_balanced_resumes_normally(monkeypatch):
    bot, entered = _reconcile_bot(
        monkeypatch, edges=[(1.0, 0.40, None), (20.0, 0.37, 18.0)],
        gains=["faedrine", "leprechaun"])
    assert bot._chill_reconcile("收尾") is False
    assert entered == []


def test_reconcile_single_chill_never_triggers(monkeypatch):
    bot, entered = _reconcile_bot(monkeypatch, edges=[(1.0, 0.40, None)], gains=[])
    assert bot._chill_reconcile("收尾") is False


def test_reconcile_debounce_merges_same_chill(monkeypatch):
    """短回落（0.3s < release 2.0s）＝同一聲的抖動，不得算成兩聲去對帳。"""
    edges = [(1.0, 0.40, None), (1.6, 0.41, 0.3)]
    bot, entered = _reconcile_bot(monkeypatch, edges=edges, gains=[])
    assert bot._chill_reconcile("收尾") is False
    assert entered == []


def test_reconcile_exception_resumes_normally(monkeypatch):
    def _boom():
        raise RuntimeError("OCR 掛了")

    bot, entered = _reconcile_bot(
        monkeypatch, edges=[(1.0, 0.4, None), (20.0, 0.4, 18.0)], gains=[])
    bot._episode_panel_gains = _boom
    assert bot._chill_reconcile("收尾") is False
    assert entered == []


def test_resume_mining_stops_when_unbalanced(monkeypatch):
    """帳不平 → 不得走 _resume_mining_tail（那會把狀態切回 MINING）。"""
    bot = make_fake_bot(
        bind=["_harvest_resume_mining"], harvest=_harvest(),
        _pitch_restore_if_touched=lambda: None,
        _chill_reconcile=lambda where: True,
        _resume_mining_tail=lambda net: pytest.fail("帳不平不得回 MINING"))
    bot._harvest_resume_mining()


def test_rescue_never_intercepts_post_success_focus_failure(monkeypatch):
    """本場已記過 HARVEST_SUCCESS → 救援一律不跑。

    那條 giveup 只有一個來源：「採到了但無法重新聚焦 Roblox」。讓救援接手會
    (a) 為同一顆礦再記一次 HARVEST_RESCUED，把救援命中與正常採集成功的統計混掉；
    (b) 更糟——呼叫 `_harvest_resume_mining` → `init_mining_sequence`，在焦點**不在**
    Roblox 時送 W/D1/Shift/視角鍵，全被別的視窗吃掉（呼叫端註解裡的既有根因）。
    """
    bot, resumed = _rescue_bot(monkeypatch, chat=["faedrine"], panel=["faedrine"],
                               _episode_succeeded=True)
    assert bot._giveup_rescue("採集成功但無法重新聚焦 Roblox，請處理後按 Q") is False
    assert resumed == [] and bot.log.records == []


def test_rescue_runs_when_episode_has_not_succeeded(monkeypatch):
    """兩側夾：沒記過成功的 episode 照樣要救（否則上面那道閘等於關掉整個功能）。"""
    bot, resumed = _rescue_bot(monkeypatch, panel=["faedrine"],
                               _episode_succeeded=False)
    assert bot._giveup_rescue("全方位掃描未找到追蹤框") is True
    assert resumed == [True]


def test_reconcile_giveup_path_logs_but_never_reroutes(monkeypatch):
    """giveup 路徑（notify=False）：帳不平也只記一筆，不重複交人工、不拍額外快照。

    記它是為了 06 的淨值檢查——要分得出「對帳新增的人工次數」與「本來就會交的」。
    """
    bot, entered = _reconcile_bot(
        monkeypatch, edges=[(1.0, 0.40, None), (20.0, 0.37, 18.0)], gains=[])
    bot._enqueue_snapshot = lambda crop, label: pytest.fail("giveup 路徑不拍對帳快照")
    assert bot._chill_reconcile("giveup", notify=False) is False
    assert entered == []
    assert any("帳不平" in line for line in bot.log_harvest.lines)


# ── 面板歸零：01 清空原語＋插入點（spec 2026-07-31）─────────────────────────

class _PanelOCR:
    """偽 read_text_boxes：回指定標頭框＋ 礦名列框，讓 _clear_panel_filter 不碰真 OCR。

    `later`＝第二次以後要回的 (header, names)——用來演「第一讀面板還沒重繪、第二讀
    才空」。`watch` 每次呼叫時被叫一下，測「OCR 時點擊做到哪一步了」。
    """

    def __init__(self, header, names, later=None, watch=None):
        self._header = header
        self._names = names
        self._later = later
        self._watch = watch
        self.calls = 0

    def __call__(self, crop, region_offset=(0, 0)):
        self.calls += 1
        if self._watch:
            self._watch()
        header, names = self._header, self._names
        if self.calls > 1 and self._later is not None:
            header, names = self._later
        boxes = []
        if header:
            boxes.append({"text": header, "score": 0.99, "center": (118, 14)})
        for i, n in enumerate(names):
            boxes.append({"text": n, "score": 0.99, "center": (80, 78 + i * 36)})
        return boxes


def _clear_bot(monkeypatch, *, header="NORMAL", names=None, exc=None, later=None):
    """組一個 fake bot 只綁 _clear_panel_filter，OCR／click／time 全旁路。"""
    import pydirectinput
    clicks = []
    typed = []

    def fake_click(x, y, **kw):
        clicks.append((x, y))

    if exc:
        def boom(*a, **kw):
            raise RuntimeError(exc)
        monkeypatch.setattr(main.ic, "click_at", boom)
    else:
        monkeypatch.setattr(main.ic, "click_at", fake_click)
    monkeypatch.setattr(pydirectinput, "typewrite",
                        lambda s, **kw: typed.append(s))
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(main.time, "time", lambda: 9999.0)

    clicks_at_ocr = []
    panel_ocr = _PanelOCR(header, names or [], later=later,
                          watch=lambda: clicks_at_ocr.append(len(clicks)))
    panel_ocr.clicks_at_ocr = clicks_at_ocr
    monkeypatch.setattr(main.ocr, "rapidocr_available", lambda: True)
    monkeypatch.setattr(main.ocr, "read_text_boxes", panel_ocr)
    monkeypatch.setattr(main.capture, "grab", lambda: _frame())
    monkeypatch.setattr(main.capture, "crop", lambda f, r: f[:r.h, :r.w].copy())

    extra = {"_panel_zeroed_at": None}
    if exc:
        extra["_panel_zeroed_at"] = 1234.0   # 驗證例外會清成 None

    bot = make_fake_bot(
        bind=["_clear_panel_filter"],
        logger=_Rec(),
        **extra)
    return bot, clicks, typed, panel_ocr


def test_clear_sets_timestamp_when_normal_and_empty(monkeypatch):
    bot, clicks, typed, ocr = _clear_bot(monkeypatch, header="NORMAL", names=[])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0
    assert ocr.calls == 1                                   # 只 OCR 一次
    assert clicks[0] == (119, 441)                          # 先點篩選框
    assert clicks[1] == (960, 540)                          # 再點畫面中央
    assert typed == ["w" * cfg.panel_clear_keystrokes]


def test_clear_sets_none_when_wrong_page(monkeypatch):
    bot, *_ = _clear_bot(monkeypatch, header="SPECTRAL", names=[])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None
    assert any("SPECTRAL" in line for line in bot.logger.lines)


def test_clear_sets_none_when_has_rows(monkeypatch):
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["faedrine"])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None
    assert any("faedrine" in line for line in bot.logger.lines)


def test_clear_sets_none_on_exception(monkeypatch):
    bot, *_ = _clear_bot(monkeypatch, exc="click boom")
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None
    assert any("click boom" in line for line in bot.logger.lines)


def test_clear_accepts_low_tier_rows(monkeypatch):
    """低階礦回填不算失敗——驗的是「沒有白名單礦」（2026-07-31 使用者提出）。"""
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["shamrock"])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0


def test_clear_verifies_before_restoring_focus(monkeypatch):
    """驗證必須在「點畫面中央還焦點」之前（2026-07-31 實機）。

    那一下點擊是真的挖礦點擊：17:37:04 實測面板已清乾淨，卻在 OCR 前挖到一顆
    shamrock，讀到 1 列判成歸零失敗。零點成不成立只跟篩選框有關，不該被自己的
    還焦點點擊污染。
    """
    bot, clicks, _typed, panel_ocr = _clear_bot(monkeypatch, header="NORMAL", names=[])
    bot._clear_panel_filter()
    assert panel_ocr.clicks_at_ocr == [1], "OCR 當下只該點過篩選框那一下"
    assert clicks[-1] == (960, 540), "驗完仍要把焦點還給 3D 世界"


def test_clear_rereads_when_panel_redraw_lags(monkeypatch):
    """第一讀還是舊清單、第二讀才空 → 算歸零成功（只重讀，不重打字）。"""
    bot, _clicks, typed, panel_ocr = _clear_bot(
        monkeypatch, header="NORMAL", names=["faedrine", "riches"],
        later=("NORMAL", []))
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0
    assert panel_ocr.calls == 2
    assert typed == ["w" * cfg.panel_clear_keystrokes], "重讀不得重打字（H047/H063）"


def test_clear_failure_saves_snapshot_for_next_session(monkeypatch):
    """失敗要留裁圖：先前只有一行 WARNING，事後查不出點沒中還是字沒進。"""
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["faedrine"])
    saved = []
    bot._enqueue_snapshot = lambda crop, label: saved.append(label)
    bot._clear_panel_filter()
    assert saved == ["panel_zero_failed"]


def test_clear_runs_before_init_in_on_enter_mining(monkeypatch):
    """插入點 A：_on_enter(MINING) 清空排在 init_mining_sequence 之前。"""
    order = []
    bot = make_fake_bot(
        bind=["_on_enter"],
        logger=_Rec(), _panel_zeroed_at=None,
        human_cleared=True, _movement_check_due=False,
        _movement_mode_checked=True,
        _chill_edges=[], _aim_context=None,
        _release_web_held_aim=lambda send=False: None,
        _rr_ctx=None, _pending_reentry=None,
        _mine_resetting=False,
        _capacity_pct=None, _capacity_streak=0, _capacity_full_logged=False,
        _post_harvest_watch=0,
        _focus_roblox=lambda: (order.append("focus") or True),
        _zoom_normalize=lambda *_: None,
        _clear_panel_filter=lambda: order.append("clear"),
        _rotate_verified=None,
        _log_w_state=lambda *_: None)
    monkeypatch.setattr(main.miner, "init_mining_sequence",
                        lambda **kw: order.append("init"))
    monkeypatch.setattr(main.ic, "key_up", lambda *_: None)
    monkeypatch.setattr(main.ic, "key_down", lambda *_: None)
    monkeypatch.setattr(main.ic, "mouse_up", lambda *_: None)
    monkeypatch.setattr(main.ic, "mouse_down", lambda *_: None)
    monkeypatch.setattr(main.ic, "center_crosshair", lambda: None)
    monkeypatch.setattr(main.miner, "ensure_pickaxe", lambda: False)
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)

    bot._on_enter(State.MINING, _frame())
    assert order.index("clear") < order.index("init")


def test_clear_runs_before_init_in_resume_mining_tail(monkeypatch):
    """插入點 B：_resume_mining_tail 清空排在 init_mining_sequence 之前。"""
    order = []
    net_rots = 0
    bot = make_fake_bot(
        bind=["_resume_mining_tail"],
        logger=_Rec(), _panel_zeroed_at=None,
        harvest=_harvest(), _mine_resetting=False,
        _post_harvest_watch=0,
        _log_w_state=lambda *_: None,
        _rotate_verified=None,
        _clear_panel_filter=lambda: order.append("clear"))
    monkeypatch.setattr(main.harvester, "restore_view", lambda *a, **kw: None)
    monkeypatch.setattr(main.miner, "init_mining_sequence",
                        lambda **kw: order.append("init"))
    monkeypatch.setattr(main.ic, "key_up", lambda *_: None)
    monkeypatch.setattr(main.ic, "key_down", lambda *_: None)
    monkeypatch.setattr(main.ic, "mouse_up", lambda *_: None)
    monkeypatch.setattr(main.ic, "mouse_down", lambda *_: None)
    monkeypatch.setattr(main.ic, "center_crosshair", lambda: None)
    monkeypatch.setattr(main.miner, "ensure_pickaxe", lambda: False)
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)

    bot._resume_mining_tail(net_rots)
    assert order.index("clear") < order.index("init")
