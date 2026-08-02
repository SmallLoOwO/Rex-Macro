"""層轉換後重按一次 D2（spec 2026-07-28 `sweep-pitch-enable` D2）。

只驗外部可觀察行為：有沒有觸發新掃描、順序在拖曳之後、排除基準有沒有被動到、
每層計時預算什麼時候歸零——不驗呼叫了哪些私有方法、不驗參數逐字內容。
"""
import itertools
import types

from miningbot import harvester, main
from tests.fake_bot import make_fake_bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    warning = info
    debug = info


def _bot(monkeypatch, *, layers=("up", "down"), drag_ok=True, resetting=False,
         ref="進場時拍的排除基準（框出現前）", last_scan_at=0.0):
    """組一台只掛 `_pitch_layer_transition` 真身的 fake bot。

    回 (bot, events)。`events` 是外部可觀察的動作序列：`("drag", label)` 與
    `("scan", 掃描當下的 _harvest_start)`——後者讓「預算在掃描之後才歸零」不必數
    呼叫次數就驗得出來。時鐘換成單調計數器，秒數才可預期。
    """
    events = []
    monkeypatch.setattr(main.time, "time", lambda c=itertools.count(1000): float(next(c)))

    bot = make_fake_bot(
        bind=["_pitch_layer_transition"],
        logger=_LogRecorder(),
        log_harvest=_LogRecorder(),
        harvest=types.SimpleNamespace(
            harvest_id="777", pitch_layer="mid", pitch_touched=False,
            # 層序列由 production 函式產（步進量取任意已校準值——這裡驗的是層轉換的
            # 接線，不是校準常數；抄 config 預設只會做出一個改變偵測器）
            pitch_layers_left=[layer for layer in harvester.plan_pitch_layers(True, 120, 370)
                               if layer.name in layers]),
        _mine_resetting=resetting,
        _pre_scan_ref=ref,
        _radar_last={"scan": last_scan_at},
        _harvest_start=0.0,
        _pitch_drag_verified=lambda label, drag: events.append(("drag", label)) or drag_ok,
        _focus_roblox=lambda: True,
        _await_scan_ready=lambda where: True,
        _run_scan=lambda: events.append(("scan", bot._harvest_start)),
        _confirm_scan=lambda where: True,
    )
    monkeypatch.setattr(main.harvester, "prepare_scan", lambda: None)
    monkeypatch.setattr(main.ic, "settle", lambda seconds: None)
    return bot, events


def test_layer_transition_rescans_after_the_pitch_drag(monkeypatch):
    """切層成功 → 觸發一次新掃描，且在俯仰拖曳之後（先掃再拖＝掃的是舊角度）。"""
    bot, events = _bot(monkeypatch)

    assert bot._pitch_layer_transition() is True
    assert bot.harvest.pitch_layer == "up"
    assert [kind for kind, _ in events] == ["drag", "drag", "scan"]


def test_layer_transition_keeps_the_exclusion_reference(monkeypatch):
    """H026：重掃時畫面上往往已有活框，重拍 ref 會把活框寫進排除基準自我致盲。"""
    ref = object()
    bot, _ = _bot(monkeypatch, ref=ref)

    assert bot._pitch_layer_transition() is True
    assert bot._pre_scan_ref is ref, "排除基準幀在層轉換前後必須是同一個物件"


def test_layer_budget_starts_after_the_rescan(monkeypatch):
    """每層 sweep_timeout_s 預算從重掃之後才歸零——放前面會被掃描內含的等待吃掉。"""
    bot, events = _bot(monkeypatch)

    assert bot._pitch_layer_transition() is True
    at_scan = [start for kind, start in events if kind == "scan"][0]
    assert bot._harvest_start > at_scan, "掃描當下就歸零＝預算被掃描自己吃掉"


def test_eaten_drag_skips_the_layer_without_pressing_d2(monkeypatch):
    """拖曳兩輪都被吃 → 跳過該層；沒切成功的層白按 D2 只是浪費 30s 共享冷卻。"""
    bot, events = _bot(monkeypatch, drag_ok=False)

    assert bot._pitch_layer_transition() is False
    assert [kind for kind, _ in events] == ["drag"] * 4, "兩層 × 兩輪重試"
    assert bot.harvest.pitch_layer == "mid", "沒切成功就不該記成新層"


def test_mine_reset_gives_up_without_dragging_or_scanning(monkeypatch):
    """礦坑重置中 → 直接回「沒有可切的層」，不拖曳也不掃描。"""
    bot, events = _bot(monkeypatch, resetting=True)

    assert bot._pitch_layer_transition() is False
    assert events == []


def test_logs_seconds_since_last_d2(monkeypatch):
    """harvest.log 要留下距上次 D2 的秒數，「這次重掃有沒有生效」才是可查的事實。"""
    bot, _ = _bot(monkeypatch, last_scan_at=960.0)

    assert bot._pitch_layer_transition() is True
    assert any("距上次掃描" in r for r in bot.log_harvest.records)
    assert any("重新 8 方位掃描" in r for r in bot.logger.records)


def test_no_layers_left_is_a_noop(monkeypatch):
    bot, events = _bot(monkeypatch, layers=())

    assert bot._pitch_layer_transition() is False
    assert events == []


# ── 俯仰前卸裝 D2（避免抬頭觸發全域掃描）──

def test_layer_transition_unequips_d2_before_pitching(monkeypatch):
    """抬頭前必須先卸裝 D2——拿著掃描器抬頭會觸發全伺服器掃描，汙染偵測。

    pitch_reset 的夾限步驟會讓視角掃過正上方，所以無論目標是上層還是下層都會經過
    抬頭。_pitch_goto_layer 在拖曳前先呼叫 _unequip_scanner，順序不可顛倒。
    """
    bot, events = _bot(monkeypatch)
    bot._unequip_scanner = lambda reason: events.append(("unequip", reason))

    assert bot._pitch_layer_transition() is True
    kinds = [kind for kind, _ in events]
    assert kinds == ["unequip", "drag", "drag", "scan"], \
        "unequip 必須在 drag 之前——先卸 D2 再抬頭"


def test_unequip_scanner_presses_2_when_d2_equipped(monkeypatch):
    """D2 已裝備 → 按 "2" toggle 卸裝，再讀一次確認生效。"""
    monkeypatch.setattr(main.capture, "grab", lambda *a, **k: None)
    results = [True, False]  # 第一次：已裝備；第二次（驗證）：已卸裝
    monkeypatch.setattr(main.vision, "slot_selected",
                        lambda *a, **k: results.pop(0))
    presses = []
    monkeypatch.setattr(main.ic, "key_press", lambda key: presses.append(key))
    monkeypatch.setattr(main.time, "sleep", lambda *a, **k: None)

    bot = make_fake_bot(bind=["_unequip_scanner"])
    bot._unequip_scanner("test")

    assert presses == ["2"], "D2 已裝備時應按一次 '2' toggle 卸下"


def test_unequip_scanner_noop_when_d2_not_equipped(monkeypatch):
    """D2 未裝備 → 不按鍵（防 toggle 反向裝上）。"""
    monkeypatch.setattr(main.capture, "grab", lambda *a, **k: None)
    monkeypatch.setattr(main.vision, "slot_selected", lambda *a, **k: False)
    presses = []
    monkeypatch.setattr(main.ic, "key_press", lambda key: presses.append(key))
    monkeypatch.setattr(main.time, "sleep", lambda *a, **k: None)

    bot = make_fake_bot(bind=["_unequip_scanner"])
    bot._unequip_scanner("test")

    assert presses == [], "D2 未裝備時不應按鍵——否則 toggle 會反而裝上"


def test_unequip_scanner_warns_when_key_eaten(monkeypatch):
    """按了 "2" 但 slot_selected 仍為 True → 按鍵疑似被吃，best-effort 照常俯仰。"""
    monkeypatch.setattr(main.capture, "grab", lambda *a, **k: None)
    monkeypatch.setattr(main.vision, "slot_selected", lambda *a, **k: True)
    presses = []
    monkeypatch.setattr(main.ic, "key_press", lambda key: presses.append(key))
    monkeypatch.setattr(main.time, "sleep", lambda *a, **k: None)

    bot = make_fake_bot(bind=["_unequip_scanner"])
    bot._unequip_scanner("test")

    assert presses == ["2"], "仍嘗試按了一次（best-effort）"
