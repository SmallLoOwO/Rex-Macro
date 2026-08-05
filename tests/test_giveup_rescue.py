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


def _rescue_bot(monkeypatch, *, chat=(), panel=(), cached=True, entries=None,
                observe=False, **attrs):
    monkeypatch.setattr(main.capture, "grab", _frame)
    monkeypatch.setattr(cfg, "giveup_rescue_observe", observe)
    resumed = []
    if entries is None:
        entries = collections.deque(maxlen=cfg.prechill_cache_depth)
        if cached:
            entries.append(_entry(1000.0))
    attrs.setdefault("_episode_chill_at", 1005.0)
    attrs.setdefault("_panel_zeroed_at", 9999.0)   # 01 已歸零 → 路 B 可信任
    attrs.setdefault("_rescue_observed", [])       # 觀察期記帳（spec 03）
    bot = make_fake_bot(
        bind=["_giveup_rescue", "_prechill_ref"],
        harvest=_harvest(), _prechill=entries, log_harvest=_Rec(),
        log=_FakeEventLog(), logger=_Rec(),
        _rescue_chat_ores=lambda *a: list(chat),
        _panel_rare_ores=lambda *a: list(panel),
        _harvest_resume_mining=lambda: resumed.append(True),
        _enqueue_snapshot=lambda crop, label: f"/snap/{label}.png",
        _hlabel=lambda label: f"125_{label}",
        _save_rescue_observed=lambda: None,        # 持久化另外測，這裡旁路
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


# ── 觀察期（spec 03）────────────────────────────────────────────────────────

def test_observe_mode_hits_but_still_hands_to_human(monkeypatch):
    """觀察中命中 → 回 False、不收尾。玩家照樣被叫，但當場對照得出 bot 判得對不對。

    這條路今天抓到兩個 bug（回傳整份面板礦名、模糊配到 Lovessence），方向都是
    「多宣告一次已進帳」＝靜默放生一顆真稀有礦。先觀察再自動。
    """
    bot, resumed = _rescue_bot(monkeypatch, panel=["faedrine"], observe=True)
    assert bot._giveup_rescue("全方位掃描未找到追蹤框") is False
    assert resumed == [], "觀察中不得自己收尾回 MINING"


def test_observe_mode_still_records_evidence(monkeypatch):
    """觀察期的價值在事後對得起帳：HARVEST_RESCUED 照記、截圖照帶。"""
    bot, _ = _rescue_bot(monkeypatch, panel=["faedrine"], observe=True)
    bot._giveup_rescue("x")
    kind, meta = bot.log.records[0]
    assert kind == "HARVEST_RESCUED"
    assert meta["ore_names"] == ["faedrine"]
    assert meta["observed"] is True          # 與自動路徑的紀錄分得開
    assert meta["image_paths"], "證據截圖不可省"


def test_observe_mode_counts_hits(monkeypatch):
    """命中次數累計；滿門檻不自動切換，只記一行 log（由之後的 session 問玩家）。"""
    bot, _ = _rescue_bot(monkeypatch, panel=["faedrine"], observe=True)
    bot._giveup_rescue("x")
    bot._giveup_rescue("y")
    assert len(bot._rescue_observed) == 2
    assert bot._rescue_observed[-1]["ore_names"] == ["faedrine"]
    assert bot._rescue_observed[-1]["source"] == "panel"


def test_observe_mode_notes_progress_in_human_message(monkeypatch):
    """交人工訊息要帶上「本來會判已進帳」＋第幾次，玩家才對照得到。"""
    bot, _ = _rescue_bot(monkeypatch, panel=["faedrine"], observe=True)
    bot._giveup_rescue("x")
    assert bot._rescue_observe_note, "交人工訊息要有觀察期註記"
    assert "faedrine" in bot._rescue_observe_note
    assert "1" in bot._rescue_observe_note      # 第 1 次


def test_observe_off_behaves_like_today(monkeypatch):
    """關掉觀察 → 完全是今天的自動行為（收尾、回 True、不記觀察帳）。"""
    bot, resumed = _rescue_bot(monkeypatch, panel=["faedrine"], observe=False)
    assert bot._giveup_rescue("x") is True
    assert resumed == [True]
    assert bot._rescue_observed == []


def test_observe_mode_records_nothing_when_no_evidence(monkeypatch):
    """兩路都沒命中 → 計數不變（否則門檻會被沒命中的場次灌水）。"""
    bot, _ = _rescue_bot(monkeypatch, observe=True)
    assert bot._giveup_rescue("x") is False
    assert bot._rescue_observed == []


def test_observe_note_reaches_the_player_reason_once(monkeypatch):
    """註記要進 `_human_reason`（玩家看得到），而且只用一次不沾到下一場。"""
    bot, _ = _rescue_bot(monkeypatch, panel=["faedrine"], observe=True)
    bot._giveup_rescue("x")
    note = bot._rescue_observe_note
    # 模擬 _harvest_giveup 那兩行（不整支跑，避免拉進整條 giveup I/O）
    reason = "全方位掃描未找到追蹤框"
    bot._human_reason = f"{reason}\n{note}" if note else reason
    bot._rescue_observe_note = ""
    assert "faedrine" in bot._human_reason
    assert bot._rescue_observe_note == "", "一次性：下一場沒命中不該還掛著"


def test_rescue_observed_load_tolerates_missing_and_broken_file(tmp_path, monkeypatch):
    """計數檔不存在／壞掉 → 從 0 起算，不丟例外（否則啟動就炸）。"""
    monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
    bot = make_fake_bot(bind=["_load_rescue_observed", "_rescue_observed_path"],
                        logger=_Rec())
    assert bot._load_rescue_observed() == []          # 檔案不存在
    (tmp_path / "rescue_observed.json").write_text("{not json", encoding="utf-8")
    assert bot._load_rescue_observed() == []          # 壞檔
    (tmp_path / "rescue_observed.json").write_text('{"a": 1}', encoding="utf-8")
    assert bot._load_rescue_observed() == []          # 型別不對


def test_rescue_observed_round_trips_through_disk(tmp_path, monkeypatch):
    """存了要讀得回來——跨 session 累計靠這個。"""
    monkeypatch.setattr(cfg, "log_dir", str(tmp_path))
    bot = make_fake_bot(
        bind=["_load_rescue_observed", "_save_rescue_observed", "_rescue_observed_path"],
        logger=_Rec(),
        _rescue_observed=[{"harvest_id": "125", "ore_names": ["faedrine"]}])
    bot._save_rescue_observed()
    assert bot._load_rescue_observed() == [
        {"harvest_id": "125", "ore_names": ["faedrine"]}]


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


def _panel_boxes(names):
    """偽 read_text_boxes：標頭 + 一列一個礦名（座標過 col_max_x / row_min_y 兩道閘）。"""
    boxes = [{"text": "NORMAL", "score": 0.99, "center": (118, 14)}]
    for i, n in enumerate(names):
        boxes.append({"text": n, "score": 0.99, "center": (80, 78 + i * 36)})
    return boxes


def test_panel_path_returns_only_whitelist_ores(monkeypatch):
    """只回白名單（Exotic+），不是面板上全部的礦名。

    回全部的話：鎬子挖出來的低階礦永遠在面板上 → 路 B 每次 giveup 都命中 →
    每顆真稀有礦都被判「已進帳」靜默放生（H069 那一型）。先前只因面板歸零驗證
    實機必失敗、`_panel_zeroed_at` 恆 None 才沒爆出來。
    """
    bot = make_fake_bot(bind=["_panel_rare_ores"], log_harvest=_Rec())
    monkeypatch.setattr(main.capture, "grab", _frame)
    monkeypatch.setattr(main.capture, "crop", lambda f, r: f[:r.h, :r.w].copy())
    monkeypatch.setattr(main.ocr, "rapidocr_available", lambda: True)
    monkeypatch.setattr(main.ocr, "read_text_boxes",
                        lambda *a, **kw: _panel_boxes(
                            ["shamrock", "loinnire", "fortunatum"]))
    assert bot._panel_rare_ores("125", "救援路B") == []


def _panel_bot(monkeypatch, names, row_hue):
    bot = make_fake_bot(bind=["_panel_rare_ores"], log_harvest=_Rec())
    rows = [78 + i * 36 for i in range(len(names))]
    crop = _panel_crop_with_hue(row_hue, rows)
    monkeypatch.setattr(main.capture, "grab", _frame)
    monkeypatch.setattr(main.capture, "crop", lambda f, r: crop.copy())
    monkeypatch.setattr(main.ocr, "rapidocr_available", lambda: True)
    monkeypatch.setattr(main.ocr, "read_text_boxes",
                        lambda *a, **kw: _panel_boxes(names))
    return bot


def test_panel_path_still_reports_whitelist_hit(monkeypatch):
    """有白名單礦、底色也是白名單色 → 照樣回它。"""
    bot = _panel_bot(monkeypatch, ["faedrine", "shamrock"], 128.0)
    assert bot._panel_rare_ores("125", "救援路B") == ["faedrine"]


def test_panel_path_vetoed_when_row_colour_says_low_tier(monkeypatch):
    """礦名說白名單（exact）、底色說低階 → 否決（照舊交人工）。

    雙訊號 AND：礦名與底色都是獨立的 tier 證據，任一說「不是高階」就不算命中。
    用 faedrine（exact rare）配上低階底色 H=0 演這條——例如面板重繪期間 OCR 讀到
    上一幀的名字、或裁圖錯位讀到隔壁列的色。假命中的代價是靜默放生一顆真稀有礦。

    （`essence of luck` 那個 fuzzy 假陽性的測試已由 spec 02 的
    `test_rare_panel_ores_rejects_fuzzy_match` 接手——它在更上游就被擋掉了。）
    """
    bot = _panel_bot(monkeypatch, ["faedrine"], 0.0)
    assert bot._panel_rare_ores("125", "救援路B") == []
    assert any("否決" in line for line in bot.log_harvest.lines)


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


def _panel_crop_with_hue(hue_deg, row_ys):
    """合成一張面板裁圖：指定列的底色是 `hue_deg`（度），其餘全黑。"""
    import cv2
    crop = np.zeros((cfg.backpack_review_region.h, cfg.backpack_review_region.w, 3),
                    dtype=np.uint8)
    for cy in row_ys:
        band = np.zeros((17, crop.shape[1], 3), dtype=np.uint8)
        band[:, :] = (int(round(hue_deg / 2.0)), 200, 200)
        crop[cy - 8:cy + 9] = cv2.cvtColor(band, cv2.COLOR_HSV2BGR)
    return crop


def _clear_bot(monkeypatch, *, header="NORMAL", names=None, exc=None, later=None,
               row_hue=None, focused=True, ink_changes=True):
    """組一個 fake bot 只綁 _clear_panel_filter，OCR／click／time／key 全旁路。

    `focused`＝`_focus_roblox()` 的回傳、`ink_changes`＝打字前後篩選框墨量有沒有變
    （H070：失焦時整組輸入被丟掉，兩者都是那條路的守門）。
    """
    import pydirectinput
    clicks = []
    typed = []
    keys = []

    def fake_click(x, y, **kw):
        clicks.append((x, y))

    if exc:
        def boom(*a, **kw):
            raise RuntimeError(exc)
        monkeypatch.setattr(main.ic, "click_at", boom)
    else:
        monkeypatch.setattr(main.ic, "click_at", fake_click)
    monkeypatch.setattr(main.ic, "key_press",
                        lambda k, **kw: keys.append(k))
    monkeypatch.setattr(main.ic, "key_down", lambda k: keys.append("+" + k))
    monkeypatch.setattr(main.ic, "key_up", lambda k: keys.append("-" + k))
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
    # 篩選框墨量：預設演「字有進去」（每次讀不同值）。要演 H070 的「輸入被丟掉」
    # 就把 ink_changes 設 False——兩次讀到同一個值。
    ink = iter(range(100, 999)) if ink_changes else iter(lambda: 42, None)
    monkeypatch.setattr(main.vision, "filter_box_ink", lambda crop: next(ink))
    if row_hue is None:
        monkeypatch.setattr(main.capture, "crop", lambda f, r: f[:r.h, :r.w].copy())
    else:
        rows = [78 + i * 36 for i in range(len(names or []))]
        crop = _panel_crop_with_hue(row_hue, rows)
        monkeypatch.setattr(main.capture, "crop", lambda f, r: crop.copy())

    extra = {"_panel_zeroed_at": None}
    if exc:
        extra["_panel_zeroed_at"] = 1234.0   # 驗證例外會清成 None

    bot = make_fake_bot(
        bind=["_clear_panel_filter"],
        logger=_Rec(),
        _focus_roblox=lambda: focused,
        **extra)
    return bot, clicks, typed, keys, panel_ocr


def test_clear_requires_foreground_before_touching_ui(monkeypatch):
    """H070：Roblox 不在前景時整組輸入被丟掉——不得盲送點擊與 8 個 w。

    實機 2026-07-31 23:40:20：清空「成功」跑完但面板紋風不動，1 秒後的旋轉鍵
    `mean_diff=0.00013` 被判定被吃、重新聚焦才恢復——同一段失焦區間。清空是唯一
    沒有聚焦守門的輸入序列（旋轉有 _rotate_verified、俯仰有 _pitch_drag_verified）。
    """
    bot, clicks, typed, keys, _ocr = _clear_bot(monkeypatch, header="NORMAL",
                                                names=[], focused=False)
    bot._clear_panel_filter()
    assert clicks == [], "沒有前景焦點就不該點 UI"
    assert typed == [], "沒有前景焦點就不該打字（w 會變成 8 次前進）"
    assert keys == ["enter"], "連 backspace 都不該送（Enter 在 finally，照舊）"
    assert bot._panel_zeroed_at is None
    assert any("焦點" in line for line in bot.logger.lines)


def test_clear_failure_log_carries_the_ink_numbers(monkeypatch):
    """失敗時墨量前後值要進 log（H070 的線索保留，但**降級成線索**）。

    H070 當初用它分辨「輸入全滅」與「面板本來就有礦」，兩者在 log 上同形。H071 之後
    顯示飽和也會讓墨量不變，所以它不再是判斷、只是下一場查案的數字。
    """
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["faedrine"],
                         ink_changes=False)
    saved = []
    bot._enqueue_snapshot = lambda crop, label: saved.append(label)
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None
    assert any("墨量" in line and "沒變" in line for line in bot.logger.lines)
    assert saved == ["panel_zero_failed"], "要留裁圖，下一場才查得動"


def test_clear_ink_guard_does_not_block_the_happy_path(monkeypatch):
    """兩側夾：墨量有變（字進去了）時，零點照樣成立。"""
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=[], ink_changes=True)
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0


def test_clear_ink_unchanged_but_panel_empty_still_counts_h071(monkeypatch):
    """H071：墨量沒變不得再當硬閘——**這就是玩家回報的那個 bug**。

    篩選框的字越積越多之後顯示會壓縮到飽和，再多打幾個 w 一個像素都不變（實機字寬
    07-31 23:55 五個 w=57px → 169px → 23:56 之後永遠停在 199px／ink=494）。但框吃得下
    無限長的字，文字其實有變、遊戲的篩選照樣重跑、面板照樣清空——舊版卻把「墨量沒變」
    當成「字沒進 TextBox」直接 return，連面板 OCR 都不跑，08-01 三次歸零全被這道假閘
    擋掉。面板 OCR 才是真正的判準。
    """
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=[], ink_changes=False)
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0


def test_clear_input_sequence_is_click_w_then_enter_h071c(monkeypatch):
    """H071c：輸入序列只有 click(×N) → key_press w × N → Enter，不做任何清空動作。

    H071b 實機確認 typing alone 就能觸發 filter，不需要 Ctrl+A 或 backspace。
    H071c 改用 key_press（90ms 間隔）取代 typewrite（40ms），解決 harvest 153
    的 timing 問題（typewrite 太快、遊戲來不及讀）。這條測試守的是輸入序列。
    2026-08-05：click 次數由 panel_clear_clicks 控制（預設 2），避免單次 click
    被遊戲忙碌吃掉。
    """
    order = []
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=[], ink_changes=False)
    monkeypatch.setattr(main.ic, "click_at", lambda *a, **kw: order.append("click"))
    monkeypatch.setattr(main.ic, "key_down", lambda k: order.append("+" + k))
    monkeypatch.setattr(main.ic, "key_up", lambda k: order.append("-" + k))
    monkeypatch.setattr(main.ic, "key_press", lambda k, **kw: order.append(k))
    bot._clear_panel_filter()
    expected = ["click"] * cfg.panel_clear_clicks + ["w"] * cfg.panel_clear_keystrokes + ["enter"]
    assert order == expected


def test_filter_box_ink_changes_with_text():
    """`filter_box_ink` 要真的隨字量變（合成裁圖：多畫一筆就多一些亮像素）。"""
    import numpy as np
    from miningbot.vision import filter_box_ink
    blank = np.zeros((36, 226, 3), dtype=np.uint8)
    one = blank.copy(); one[10:26, 100:108] = 255
    two = one.copy(); two[10:26, 112:120] = 255
    assert filter_box_ink(blank) == 0
    assert filter_box_ink(one) > 0
    assert filter_box_ink(two) != filter_box_ink(one)


def test_filter_box_text_width_spans_the_bright_text():
    """`filter_box_text_width`：字往右長，跨距就變大；沒有亮字回 0。

    這是墨量分不出來的那一軸，也是 H071 真正解開案情的量——顯示壓縮飽和後墨量恆定，
    字寬仍看得出「已經到底了」。只給 log 用，不參與判斷。
    """
    import numpy as np
    from miningbot.vision import filter_box_text_width
    blank = np.zeros((36, 226, 3), dtype=np.uint8)
    one = blank.copy(); one[10:26, 100:108] = 255
    two = one.copy(); two[10:26, 112:120] = 255
    assert filter_box_text_width(blank) == 0
    assert filter_box_text_width(one) == 8
    assert filter_box_text_width(two) == 20      # 100..119 的跨距（含中間空白）


def test_clear_focuses_before_clicking(monkeypatch):
    """有焦點才動：_focus_roblox 必須在第一次點擊之前被呼叫到。"""
    order = []
    bot, _clicks, _typed, _keys, _ocr = _clear_bot(monkeypatch, header="NORMAL",
                                                   names=[])
    bot._focus_roblox = lambda: (order.append("focus"), True)[1]
    monkeypatch.setattr(main.ic, "click_at",
                        lambda *a, **kw: order.append("click"))
    bot._clear_panel_filter()
    assert order[:2] == ["focus", "click"]


def test_clear_logs_the_filter_box_numbers_even_on_success(monkeypatch):
    """排錯用：篩選框的座標／墨量／字寬**不論成敗**都要進 log（使用者 2026-08-01 要求）。

    H071 查了半天才發現「墨量沒變是正常的」，就是因為成功那幾輪什麼都沒記，
    只有失敗輪留下一個會誤導人的 WARNING。
    """
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=[])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0
    line = next((l for l in bot.logger.lines if "字寬" in l), None)
    assert line is not None, "成功路徑也要記篩選框現況"
    assert "%d,%d" % cfg.panel_filter_xy in line, "要記點了哪裡（對照 panel_zero_failed 裁圖）"


def test_clear_sets_timestamp_when_normal_and_empty(monkeypatch):
    bot, clicks, typed, keys, ocr = _clear_bot(monkeypatch, header="NORMAL", names=[])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0
    assert ocr.calls == 1                                   # 只 OCR 一次
    assert clicks == [(119, 441)] * cfg.panel_clear_clicks  # 點篩選框 N 次（不再點畫面中央）
    expected_keys = ["w"] * cfg.panel_clear_keystrokes + ["enter"]
    assert keys == expected_keys                            # key_press w × N + Enter 脫離
    assert typed == []                                      # H071c：不再用 typewrite


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
    """點篩選框丟例外 → 記 WARNING、旗標清成 None，**Enter 仍然送出**。

    Enter 在 `finally`：脫離文字框沒做等於後續 W／D1／D3 全打進文字框，
    比零點失敗嚴重得多。
    """
    bot, _clicks, _typed, keys, _ocr = _clear_bot(monkeypatch, exc="click boom")
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None
    assert any("click boom" in line for line in bot.logger.lines)
    assert keys == ["enter"], "例外路徑也必須脫離文字框"


def test_clear_accepts_low_tier_rows(monkeypatch):
    """低階礦回填不算失敗——驗的是「沒有白名單礦」（2026-07-31 使用者提出）。"""
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["shamrock"])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0


def test_clear_blocked_by_whitelist_row_colour_even_when_names_look_clean(monkeypatch):
    """礦名讀歪成低階、但列底色是 Exotic 46 → 零點不成立（D11 的第二條 tier 訊號）。"""
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["shamrock"],
                         row_hue=46.0)
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None
    assert any("底色" in line for line in bot.logger.lines)


def test_clear_blocked_by_unknown_row_colour_treats_as_high_tier(monkeypatch):
    """未量到的色相（90）→ 反向閘當成高階、擋零點成立（spec 01 核心決定）。

    正向閘（只認 46/128/210）會放過 90 → 零點誤判成立 → 新 tier 礦的證據基礎是錯的。
    反向閘「不落在已知低階帶就擋」把這個洞補起來。
    """
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["shamrock"],
                         row_hue=90.0)
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None


def test_clear_not_blocked_by_low_tier_row_colour(monkeypatch):
    """低階色帶（30）不擋——否則每一次都不成立。"""
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["shamrock"],
                         row_hue=30.0)
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0


def test_clear_verifies_before_restoring_focus(monkeypatch):
    """驗證必須在「按 Enter 脫離文字框」之前（spec 01）。

    舊版那一下是點畫面中央＝真的挖礦點擊：17:37:04 實測面板已清乾淨，卻在 OCR 前挖到
    一顆 shamrock 回填。改成 Enter 之後不再挖到任何東西，但順序仍維持「先驗再脫離」。
    """
    bot, clicks, _typed, keys, panel_ocr = _clear_bot(monkeypatch, header="NORMAL", names=[])
    bot._clear_panel_filter()
    assert panel_ocr.clicks_at_ocr == [cfg.panel_clear_clicks], "OCR 當下只該點過篩選框（N 次 click）"
    assert keys[-1] == "enter", "驗完才按 Enter 脫離"
    assert "enter" not in keys[:-1], "Enter 只在最後送一次"


def test_clear_rereads_when_panel_redraw_lags(monkeypatch):
    """第一讀還是舊清單、第二讀才空 → 算歸零成功（只重讀，不重打字）。"""
    bot, _clicks, _typed, keys, panel_ocr = _clear_bot(
        monkeypatch, header="NORMAL", names=["faedrine", "riches"],
        later=("NORMAL", []))
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at == 9999.0
    assert panel_ocr.calls == 2
    assert keys.count("w") == cfg.panel_clear_keystrokes, "重讀不得重打字（H047/H063）"


def test_clear_failure_saves_snapshot_for_next_session(monkeypatch):
    """失敗要留裁圖：先前只有一行 WARNING，事後查不出點沒中還是字沒進。"""
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["faedrine"])
    saved = []
    bot._enqueue_snapshot = lambda crop, label: saved.append(label)
    bot._clear_panel_filter()
    assert saved == ["panel_zero_failed"]


# ── 重試迴圈（2026-08-04 使用者要求「與稀有挖礦一樣」）─────────────────────────

class _PhasedPanelOCR:
    """OCR mock：依呼叫次數回不同 (header, names)，讓 attempt 之間可以換結果。

    phases[i] = (header, names) ——第 i+1 次呼叫回這組（超過範圍重複最後一組）。
    """

    def __init__(self, phases):
        self._phases = phases
        self.calls = 0

    def __call__(self, crop, region_offset=(0, 0)):
        self.calls += 1
        header, names = self._phases[min(self.calls - 1, len(self._phases) - 1)]
        boxes = []
        if header:
            boxes.append({"text": header, "score": 0.99, "center": (118, 14)})
        for i, n in enumerate(names):
            boxes.append({"text": n, "score": 0.99, "center": (80, 78 + i * 36)})
        return boxes


def test_clear_retries_until_zeroed(monkeypatch):
    """第一次 attempt 驗證不過 → 重新聚焦 → 第二次成功（使用者要求的核心行為）。"""
    monkeypatch.setattr(cfg, "panel_clear_max_retries", 2)
    bot, *_ = _clear_bot(monkeypatch)
    # 前 2 次讀（attempt 1 的 2 reads）回 faedrine；第 3 次起（attempt 2）回空。
    ocr = _PhasedPanelOCR([("NORMAL", ["faedrine"])] * 2 + [("NORMAL", [])] * 4)
    monkeypatch.setattr(main.ocr, "read_text_boxes", ocr)
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is not None, "重試後必須歸零成功"
    assert bot._panel_clear_attempts == 2, "應在第 2 次 attempt 成功"


def test_clear_retry_exhausted_sets_none(monkeypatch):
    """所有重試都失敗 → _panel_zeroed_at 維持 None。"""
    monkeypatch.setattr(cfg, "panel_clear_max_retries", 1)
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["faedrine"])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None


def test_clear_retry_exhausted_saves_snapshot_once(monkeypatch):
    """重試用盡只存一次 panel_zero_failed（不洗快照）。"""
    monkeypatch.setattr(cfg, "panel_clear_max_retries", 2)
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["faedrine"])
    saved = []
    bot._enqueue_snapshot = lambda crop, label: saved.append(label)
    bot._clear_panel_filter()
    assert saved == ["panel_zero_failed"], "只應在最後一次 attempt 存一次裁圖"


def test_clear_focus_failure_does_not_retry(monkeypatch):
    """焦點拿不到 → retryable=False → 不重試（重試無益）。"""
    monkeypatch.setattr(cfg, "panel_clear_max_retries", 3)
    bot, clicks, typed, keys, _ocr = _clear_bot(monkeypatch, focused=False)
    bot._clear_panel_filter()
    assert bot._panel_clear_attempts == 1, "焦點失敗不得重試"
    assert clicks == [], "沒焦點不該點 UI"
    assert keys == ["enter"], "只按一次 Enter（finally）"


def test_clear_exception_does_not_retry(monkeypatch):
    """例外 → retryable=False → 不重試（UI 狀態未知）。"""
    monkeypatch.setattr(cfg, "panel_clear_max_retries", 3)
    bot, _clicks, _typed, keys, _ocr = _clear_bot(monkeypatch, exc="boom")
    bot._clear_panel_filter()
    assert bot._panel_clear_attempts == 1, "例外不得重試"
    assert keys == ["enter"], "只按一次 Enter"


def test_clear_zero_retries_matches_old_behavior(monkeypatch):
    """panel_clear_max_retries=0 時只做一次（舊行為）。"""
    monkeypatch.setattr(cfg, "panel_clear_max_retries", 0)
    bot, *_ = _clear_bot(monkeypatch, header="NORMAL", names=["faedrine"])
    bot._clear_panel_filter()
    assert bot._panel_zeroed_at is None
    assert bot._panel_clear_attempts == 1


def test_clear_runs_before_init_in_on_enter_mining(monkeypatch):
    """插入點 A：_on_enter(MINING) 清空排在 init_mining_sequence 之前。

    清空必須成功（_panel_zeroed_at 非 None），否則 MINING 進場降級 NEEDS_HUMAN
    不會跑到 init。
    """
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
    """插入點 B：_resume_mining_tail 清空排在 init_mining_sequence 之前。

    清空必須成功（_panel_zeroed_at 非 None），否則收尾降級 NEEDS_HUMAN 不會跑到 init。
    """
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


# ── 清空失敗 → 降級 NEEDS_HUMAN（2026-08-05 使用者要求）─────────────────────

def test_on_enter_mining_clear_fail_degrades_to_needs_human(monkeypatch):
    """_on_enter(MINING) 清空失敗（_panel_zeroed_at=None）→ 回傳 NEEDS_HUMAN，不 init。"""
    init_called = []
    monkeypatch.setattr(main.ic, "key_up", lambda *_: None)
    monkeypatch.setattr(main.ic, "key_down", lambda *_: None)
    monkeypatch.setattr(main.ic, "mouse_up", lambda *_: None)
    monkeypatch.setattr(main.ic, "mouse_down", lambda *_: None)
    monkeypatch.setattr(main.miner, "init_mining_sequence",
                        lambda **kw: init_called.append(True))
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)

    nh_entered = []
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
        _focus_roblox=lambda: True,
        _zoom_normalize=lambda *_: None,
        _clear_panel_filter=lambda: None,   # 不設 _panel_zeroed_at → 失敗
        _rotate_verified=None,
        _log_w_state=lambda *_: None,
        _human_reason=None,
        _needs_human_extra_meta={},
        _needs_human_extra_image=None,
        _save_needs_human_screenshot=lambda *a, **kw: "/tmp/fake.png",
        _alert=lambda msg: None,
        log=type("LG", (), {"log": lambda *a, **kw: None})(),
    )
    # 攔截遞迴 _on_enter(NEEDS_HUMAN) — 不跑真實 NEEDS_HUMAN 副作用（避免缺方法炸）
    _orig = bot._on_enter

    def _tracking(s, frame):
        if s is State.NEEDS_HUMAN:
            nh_entered.append(s)
            bot.human_cleared = False
            return State.NEEDS_HUMAN
        return _orig(s, frame)
    bot._on_enter = _tracking

    result = bot._on_enter(State.MINING, _frame())
    assert result is State.NEEDS_HUMAN, "清空失敗必須降級 NEEDS_HUMAN"
    assert nh_entered, "必須跑 NEEDS_HUMAN 進場"
    assert not init_called, "清空失敗不應 init_mining_sequence"
    assert bot.human_cleared is False
    assert "清空" in (bot._human_reason or "")


def test_resume_mining_tail_clear_fail_degrades_to_needs_human(monkeypatch):
    """_resume_mining_tail 清空失敗 → state=NEEDS_HUMAN，不 init。"""
    init_called = []
    monkeypatch.setattr(main.ic, "key_up", lambda *_: None)
    monkeypatch.setattr(main.ic, "key_down", lambda *_: None)
    monkeypatch.setattr(main.ic, "mouse_up", lambda *_: None)
    monkeypatch.setattr(main.ic, "mouse_down", lambda *_: None)
    monkeypatch.setattr(main.ic, "center_crosshair", lambda: None)
    monkeypatch.setattr(main.miner, "init_mining_sequence",
                        lambda **kw: init_called.append(True))
    monkeypatch.setattr(main.miner, "ensure_pickaxe", lambda: False)
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(main.harvester, "restore_view", lambda *a, **kw: None)

    nh_entered = []
    bot = make_fake_bot(
        bind=["_resume_mining_tail"],
        logger=_Rec(), _panel_zeroed_at=None,
        harvest=_harvest(), _mine_resetting=False,
        _post_harvest_watch=0,
        _log_w_state=lambda *_: None,
        _rotate_verified=None,
        _clear_panel_filter=lambda: None,   # 不設 _panel_zeroed_at → 失敗
        state=State.MINING,
        _human_reason=None,
        _needs_human_extra_meta={},
        _needs_human_extra_image=None,
        _save_needs_human_screenshot=lambda *a, **kw: "/tmp/fake.png",
        _alert=lambda msg: None,
        log=type("LG", (), {"log": lambda *a, **kw: None})(),
    )
    _orig_on_enter = bot._on_enter

    def _tracking_on_enter(s, frame):
        if s is State.NEEDS_HUMAN:
            nh_entered.append(s)
            bot.human_cleared = False
            return State.NEEDS_HUMAN
        return _orig_on_enter(s, frame)
    bot._on_enter = _tracking_on_enter
    monkeypatch.setattr(main.capture, "grab", lambda: _frame())

    bot._resume_mining_tail(0)
    assert nh_entered, "清空失敗必須降級 NEEDS_HUMAN"
    assert not init_called, "清空失敗不應 init_mining_sequence"
    assert bot.state is State.NEEDS_HUMAN
    assert "清空" in (bot._human_reason or "")


# ── 容量停滯警報（spec 04）：只通知，絕不停機 ──────────────────────────────

def _stall_bot(monkeypatch, state=None, stall=None):
    return make_fake_bot(
        bind=["_check_capacity_stall"], logger=_Rec(), log=_FakeEventLog(),
        state=state or main.State.MINING,
        _capacity_stall=stall or (10.0, 0.0, False),
        _mine_resetting=False, _human_reason="")


def test_capacity_stall_alert_never_stops_the_bot(monkeypatch):
    """觸發時只發通知：不得改 state、不得寫 _mine_resetting／_human_reason。

    唯一停機信號仍然是重置橫幅（2026-07-12 死鎖實錄：Capacity 假陽性卡死 RESET_WAIT）。
    """
    monkeypatch.setattr(main.time, "time", lambda: 10_000.0)   # 距 last_change 遠超門檻
    bot = _stall_bot(monkeypatch)
    bot._check_capacity_stall(10.0)
    assert [k for k, _m in bot.log.records] == ["CAPACITY_STALL"]
    assert bot.state is main.State.MINING
    assert bot._mine_resetting is False
    assert bot._human_reason == ""


def test_capacity_stall_goes_through_the_event_sink_not_blocking_http(monkeypatch):
    """通知走 EventLog（非同步 sink），不得在 banner worker 執行緒直接打 HTTP。

    miningbot/AGENTS.md THREADING：「Discord/network sends belong behind the async
    sink or poller」——這裡阻塞會卡住 0.5s 節奏的重置橫幅偵測。
    """
    monkeypatch.setattr(main.time, "time", lambda: 10_000.0)
    monkeypatch.setattr(main.notify, "send_message",
                        lambda *a, **kw: pytest.fail("worker 執行緒不得直接送 Discord"))
    bot = _stall_bot(monkeypatch)
    bot._check_capacity_stall(10.0)
    _kind, meta = bot.log.records[0]
    assert meta["pct"] == 10 and meta["minutes"] == 15


def test_capacity_stall_resets_outside_mining(monkeypatch):
    """離開 MINING 一律重置計時——交人工等半小時不是卡住。"""
    monkeypatch.setattr(main.time, "time", lambda: 10_000.0)
    bot = _stall_bot(monkeypatch, state=main.State.NEEDS_HUMAN)
    bot._check_capacity_stall(10.0)
    assert bot.log.records == [], "非 MINING 不得警報"
    assert bot._capacity_stall == (None, 10_000.0, False)


# ── H072 進場面板色檢（chill 前鎬子已挖到稀有 礦）─────────────────────────────

def _entry_panel_bot(monkeypatch, *, panel=(), zeroed=True, enabled=True, **attrs):
    monkeypatch.setattr(cfg, "harvest_entry_panel_check", enabled)
    giveup_called = []
    bot = make_fake_bot(
        bind=["_harvest_entry_panel_check", "_episode_panel_gains"],
        harvest=_harvest(), log_harvest=_Rec(),
        _panel_zeroed_at=9999.0 if zeroed else None,
        _panel_rare_ores=lambda *a, **kw: list(panel),
        _harvest_giveup=lambda reason: giveup_called.append(reason),
        _panel_check_observed=[],
        _save_panel_check_observed=lambda: None,
        _panel_check_observed_path=lambda: "/tmp/test_panel_check.json",
        **attrs)
    return bot, giveup_called


def test_entry_panel_check_returns_gains_when_rare_in_panel(monkeypatch):
    """面板已有白名單 礦（chill 前鎬子已挖到）→ 回傳 gains（呼叫端短路 NEEDS_HUMAN）。"""
    bot, giveup = _entry_panel_bot(monkeypatch, panel=["faedrine"])
    assert bot._harvest_entry_panel_check("162") == ["faedrine"]
    assert giveup == [], "_harvest_entry_panel_check 不直接 giveup——短路由 _on_enter 呼叫端做"


def test_entry_panel_check_passes_when_panel_empty(monkeypatch):
    """面板沒有白名單 礦 → 正常進入採集。"""
    bot, giveup = _entry_panel_bot(monkeypatch, panel=[])
    assert bot._harvest_entry_panel_check("162") == []
    assert giveup == []


def test_entry_panel_check_skips_when_panel_not_zeroed(monkeypatch):
    """面板未歸零（_panel_zeroed_at is None）→ _episode_panel_gains 回 [] → 跳過。"""
    bot, giveup = _entry_panel_bot(monkeypatch, panel=["faedrine"], zeroed=False)
    assert bot._harvest_entry_panel_check("162") == []
    assert giveup == []


def test_entry_panel_check_disabled_by_config(monkeypatch):
    bot, giveup = _entry_panel_bot(monkeypatch, panel=["faedrine"], enabled=False)
    assert bot._harvest_entry_panel_check("162") == []
    assert giveup == []


def test_entry_panel_check_records_observe_hit(monkeypatch):
    """命中時記進 _panel_check_observed（觀察期）；函式本身不 giveup，短路由呼叫端。"""
    bot, giveup = _entry_panel_bot(monkeypatch, panel=["faedrine", "hallonite"])
    saved = []
    bot._save_panel_check_observed = lambda: saved.append(True)
    assert bot._harvest_entry_panel_check("162") == ["faedrine", "hallonite"]
    assert len(bot._panel_check_observed) == 1
    rec = bot._panel_check_observed[0]
    assert rec["harvest_id"] == "162"
    assert "faedrine" in rec["ore_names"]
    assert saved, "_save_panel_check_observed 必須被呼叫"
    assert giveup == [], "_harvest_entry_panel_check 不直接 giveup"


# ── _sample_banner_color：banner 色相跳變偵測（double chill，2026-08-02）────────

def test_sample_banner_color_detects_large_hue_jump(monkeypatch):
    """Regression for circular distance bug：大角度跳變（0→100°）必須偵測到。

    舊 min(diff, 90-diff) 公式對 diff=100 算出 -10（負數）→ 永遠 < 門檻 → 漏判。
    修後用 hue_circular_diff：min(100, 180-100)=80 → 正確偵測。
    """
    from miningbot import vision, capture
    bot = make_fake_bot(
        bind=["_sample_banner_color"],
        log_harvest=_Rec(),
        _banner_hue=0.0,
        _banner_color_changes=[])
    monkeypatch.setattr(vision, "banner_text_hue", lambda *a, **kw: 100.0)
    monkeypatch.setattr(capture, "crop", lambda frame, region: np.zeros((10, 10, 3)))
    monkeypatch.setattr(cfg, "banner_color_sample_enabled", True)
    bot._sample_banner_color(None)
    assert len(bot._banner_color_changes) == 1, "大角度色相跳變必須被偵測到"


def test_sample_banner_color_ignores_small_hue_diff(monkeypatch):
    """色相變化 < 門檻 → 不記跳變。"""
    from miningbot import vision, capture
    bot = make_fake_bot(
        bind=["_sample_banner_color"],
        log_harvest=_Rec(),
        _banner_hue=50.0,
        _banner_color_changes=[])
    monkeypatch.setattr(vision, "banner_text_hue", lambda *a, **kw: 53.0)  # Δ=3° < 15°
    monkeypatch.setattr(capture, "crop", lambda frame, region: np.zeros((10, 10, 3)))
    monkeypatch.setattr(cfg, "banner_color_sample_enabled", True)
    bot._sample_banner_color(None)
    assert bot._banner_color_changes == [], "小角度變化不應記為跳變"


def test_sample_banner_color_no_text_no_change(monkeypatch):
    """banner_text_hue 回 None（無文字像素）→ 不更新、不記跳變。"""
    from miningbot import vision, capture
    bot = make_fake_bot(
        bind=["_sample_banner_color"],
        log_harvest=_Rec(),
        _banner_hue=50.0,
        _banner_color_changes=[])
    monkeypatch.setattr(vision, "banner_text_hue", lambda *a, **kw: None)
    monkeypatch.setattr(capture, "crop", lambda frame, region: np.zeros((10, 10, 3)))
    monkeypatch.setattr(cfg, "banner_color_sample_enabled", True)
    bot._sample_banner_color(None)
    assert bot._banner_color_changes == []
    assert bot._banner_hue == 50.0, "hue 不應被 None 覆蓋"


# ── double chill len() >= 2（非 any()）：grilling 2026-08-04 ──────────────────

def test_double_chill_threshold_single_change_not_double(monkeypatch):
    """單一 banner 色相跳變不算 double chill——any() 會誤判，len() >= 2 正確。

    單一 chill 必產生 ≥1 跳變（chill 訊息刷新 banner），any() 在單 chill 也 fire，
    使面板命中短路永遠被擋住。log 驗證（harvest 171/184）：兩筆命中都是單 chill。
    """
    now = 1000.0
    window = cfg.double_chill_window_s
    changes = [now - 1.0]  # 窗內 1 次
    recent = [t for t in changes if t >= now - window]
    assert not (len(recent) >= 2), "1 次跳變 ≠ double chill"


def test_double_chill_threshold_two_changes_is_double(monkeypatch):
    """窗內 2 次跳變＝double chill（兩則 chill 訊息不同隨機色）。"""
    now = 1000.0
    window = cfg.double_chill_window_s
    changes = [now - 2.0, now - 0.5]  # 窗內 2 次
    recent = [t for t in changes if t >= now - window]
    assert len(recent) >= 2, "2 次跳變 ＝ double chill"


def test_double_chill_threshold_changes_outside_window_ignored(monkeypatch):
    """窗外跳變不算——只有近 double_chill_window_s 秒的跳變才有效。"""
    now = 1000.0
    window = cfg.double_chill_window_s
    changes = [now - window - 1.0, now - window - 0.5]  # 都在窗外
    recent = [t for t in changes if t >= now - window]
    assert not (len(recent) >= 2), "窗外跳變不算"


# ── 面板命中短路 NEEDS_HUMAN（2026-08-04 grilling）────────────────────────────

def _harvesting_entry_bot(monkeypatch, *, panel_gains, banner_changes=None,
                          double_chill_window=3.0):
    """組一台能跑 _on_enter(HARVESTING) 到短路判定點的 fake bot。

    短路在 panel check + double chill 之後、prepare_scan 之前——只要短路觸發，
    後面的 I/O（D2 冷卻、reference 旋轉、sweep）全不會碰到。
    """
    monkeypatch.setattr(cfg, "harvest_entry_panel_check", True)
    monkeypatch.setattr(cfg, "double_chill_window_s", double_chill_window)
    monkeypatch.setattr(cfg, "banner_color_sample_enabled", True)

    need_human_calls = []

    bot = make_fake_bot(
        bind=["_on_enter"],
        log_harvest=_Rec(),
        harvest=None,
        _harvest_seq=200,
        _save_harvest_seq=lambda: None,
        _hsnap_crop=lambda *a, **kw: None,
        _hsnap=lambda *a, **kw: None,
        _panel_check_observed=[],
        _save_panel_check_observed=lambda: None,
        _panel_check_observed_path=lambda: "/tmp/test_panel.json",
        _banner_color_changes=list(banner_changes or []),
        _banner_hue=None,
        _human_reason=None,
        _episode_succeeded=False,
        _double_chill_detected=False,
        _harvest_origin_ref=None,
        _episode_chill_at=0.0,
        _entry_panel_gains=[],
        _needs_human_extra_meta={},
        _needs_human_extra_image=None,
        _save_needs_human_screenshot=lambda *a, **kw: "/tmp/fake.png",
        human_cleared=True,
        listener=type("L", (), {"save_buffer_wav": lambda *a, **kw: None})(),
        log=type("LG", (), {"log": lambda *a, **kw: None})(),
    )
    # _harvest_entry_panel_check 直接回傳預設 gains（繞過面板讀取 I/O）
    bot._harvest_entry_panel_check = lambda hid: list(panel_gains)
    # _alert / ic 不做 I/O
    bot._alert = lambda msg: None
    # _on_enter(NEEDS_HUMAN) 遞迴呼叫時追蹤
    _orig_on_enter = bot._on_enter

    def _tracking_on_enter(s, frame):
        if s is State.NEEDS_HUMAN:
            need_human_calls.append(s)
            bot.human_cleared = False
            return State.NEEDS_HUMAN
        return _orig_on_enter(s, frame)

    bot._on_enter = _tracking_on_enter
    return bot, need_human_calls


def test_on_enter_harvesting_short_circuits_on_panel_hit(monkeypatch):
    """面板命中 + 無 double chill → _on_enter(HARVESTING) 回傳 NEEDS_HUMAN。"""
    from miningbot import harvester as harvester_mod
    import miningbot.capture as capture_mod

    now = [1000.0]
    monkeypatch.setattr(main.time, "time", lambda: now[0])
    monkeypatch.setattr(capture_mod, "crop",
                        lambda f, r: np.zeros((4, 4, 3), dtype=np.uint8))
    monkeypatch.setattr(harvester_mod, "format_harvest_id", lambda n: f"{n:03d}")
    monkeypatch.setattr(harvester_mod, "plan_pitch_layers", lambda *a: [])

    bot, nh_calls = _harvesting_entry_bot(
        monkeypatch, panel_gains=["faedrine"], banner_changes=[])
    result = bot._on_enter(State.HARVESTING, None)

    assert result is State.NEEDS_HUMAN, "面板命中必須短路 NEEDS_HUMAN"
    assert nh_calls, "必須跑 NEEDS_HUMAN 副作用"
    assert "faedrine" in (bot._human_reason or ""), "通知必須提到 礦名"


def test_on_enter_harvesting_short_circuits_with_double_chill_message(monkeypatch):
    """面板命中 + double chill → 仍短路 NEEDS_HUMAN，但通知提到第二顆。"""
    from miningbot import harvester as harvester_mod
    import miningbot.capture as capture_mod

    now = [1000.0]
    monkeypatch.setattr(main.time, "time", lambda: now[0])
    monkeypatch.setattr(capture_mod, "crop",
                        lambda f, r: np.zeros((4, 4, 3), dtype=np.uint8))
    monkeypatch.setattr(harvester_mod, "format_harvest_id", lambda n: f"{n:03d}")
    monkeypatch.setattr(harvester_mod, "plan_pitch_layers", lambda *a: [])

    bot, nh_calls = _harvesting_entry_bot(
        monkeypatch, panel_gains=["coinstorm"],
        banner_changes=[now[0] - 2.0, now[0] - 0.5])
    result = bot._on_enter(State.HARVESTING, None)

    assert result is State.NEEDS_HUMAN
    assert "double chill" in (bot._human_reason or "").lower() or \
           "第二顆" in (bot._human_reason or "")


def test_on_enter_harvesting_normal_flow_when_panel_empty(monkeypatch):
    """面板沒命中 → 不短路：_on_enter(HARVESTING) 回傳 None（正常流程）。"""
    from miningbot import harvester as harvester_mod
    import miningbot.capture as capture_mod

    now = [1000.0]
    monkeypatch.setattr(main.time, "time", lambda: now[0])
    monkeypatch.setattr(capture_mod, "crop",
                        lambda f, r: np.zeros((4, 4, 3), dtype=np.uint8))
    monkeypatch.setattr(harvester_mod, "format_harvest_id", lambda n: f"{n:03d}")
    monkeypatch.setattr(harvester_mod, "plan_pitch_layers", lambda *a: [])

    bot, nh_calls = _harvesting_entry_bot(
        monkeypatch, panel_gains=[], banner_changes=[])

    # 面板空 → 不短路 → _on_enter 繼續跑 prepare_scan 等後續 I/O
    # 這裡只驗「沒短路」：不回傳 NEEDS_HUMAN、不跑 NEEDS_HUMAN 副作用
    # （prepare_scan 等後續 I/O 會因為 fake bot 缺方法而 raise，用 pytest.raises 接住）
    with pytest.raises((AttributeError, TypeError)):
        bot._on_enter(State.HARVESTING, None)
    assert not nh_calls, "面板空時不應跑 NEEDS_HUMAN 副作用"
