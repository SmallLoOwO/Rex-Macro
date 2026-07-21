"""H056：ROI 重找全滅時的全畫面兜底（2026-07-20 harvest 097 實錄）。

097 使用者指了 DIR5 的 D4 格，該格是空草地；ROI（半徑 160px）重找兩輪全滅，
腳本朝格心 (1120,405) 盲開一發打空。但**同一張開火幀**上 (540,481) 就有一個
真追蹤框，離線用實機模板重跑 find_tracker 得 edge=0.586（>= confirmed 門檻
0.42）——唯一漏掉它的原因是 ROI 半徑沒罩到（相距 580px）。

兜底＝ROI 全滅後全畫面再找一次，只認 confirmed 門檻（不放寬、不吃 survivor），
找不到才照舊盲開先驗點。
"""
import numpy as np

from miningbot import main, capture, harvester, vision
from miningbot.main import Bot
from miningbot.config import DEFAULT as cfg


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)

    def debug(self, message, *args):
        self.records.append(message % args if args else message)


class _Ctx:
    def __init__(self):
        self.harvest_id = "097"
        self.pose_net_rotations = 0
        self.pose_pitch_layer = "mid"


def _aim_bot(monkeypatch, *, roi_hit=None, fullframe_hit=None):
    """組一個只跑到「開火點決定」為止的 Bot：_fire_d3_at 回 False 讓流程在開火前收尾。"""
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    monkeypatch.setattr(capture, "grab", lambda *a, **k: frame)
    monkeypatch.setattr(capture, "crop", lambda *a, **k: frame)
    monkeypatch.setattr(harvester, "prepare_scan", lambda *a, **k: None)
    monkeypatch.setattr(harvester, "execute_scan", lambda *a, **k: None)
    monkeypatch.setattr(vision, "find_tracker_near", lambda *a, **k: roi_hit)

    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    bot._mine_resetting = False
    bot._shape_templates = {}
    bot._wait_for_d3_cooldown = lambda deadline: (True, "")
    bot._focus_roblox = lambda: True
    bot._rotate_verified = lambda direction: True
    bot._pitch_drag_verified = lambda label, action: True
    bot._harvest_boost_guard = lambda f: False
    bot._confirm_scan = lambda where: True
    bot._hsnap = lambda f, label: None
    bot._d3_cooldown_remaining = lambda: 9.9
    bot._find_tracker = lambda *a, **k: fullframe_hit

    fired = {}
    def _fire(x, y):
        fired["pos"] = (x, y)
        return False           # 停在開火前，本測試只驗「打哪裡」
    bot._fire_d3_at = _fire
    return bot, fired


def test_h056_fullframe_fallback_recovers_confirmed_tracker(monkeypatch):
    # 097 重現：ROI 全滅，但全畫面找得到 edge=0.586 的真框 -> 打真框而非空草地
    bot, fired = _aim_bot(monkeypatch, roi_hit=None, fullframe_hit=(540, 481, 0.586))

    bot._execute_remote_fire(_Ctx(), "mid", 0, (1120, 405))

    assert fired["pos"] == (540, 481)
    assert any("全畫面兜底命中" in r for r in bot.logger.records)
    assert not any("重找全滅" in r for r in bot.logger.records)


def test_h056_blind_prior_fire_remains_when_fullframe_also_empty(monkeypatch):
    # 全畫面也沒有 -> 維持既有行為（盲開先驗點），不得因兜底而改變
    bot, fired = _aim_bot(monkeypatch, roi_hit=None, fullframe_hit=None)

    bot._execute_remote_fire(_Ctx(), "mid", 0, (1120, 405))

    assert fired["pos"] == (1120, 405)
    assert any("重找全滅" in r for r in bot.logger.records)


def test_h056_roi_hit_still_wins_and_skips_fullframe(monkeypatch):
    # ROI 命中時不得再跑全畫面：使用者指的格子優先於畫面上其他框
    bot, fired = _aim_bot(monkeypatch, roi_hit=(1100, 400, 0.45),
                          fullframe_hit=(540, 481, 0.99))

    bot._execute_remote_fire(_Ctx(), "mid", 0, (1120, 405))

    assert fired["pos"] == (1100, 400)
    assert not any("全畫面兜底" in r for r in bot.logger.records)


def test_h056_fallback_can_be_disabled(monkeypatch):
    bot, fired = _aim_bot(monkeypatch, roi_hit=None, fullframe_hit=(540, 481, 0.586))
    monkeypatch.setattr(cfg, "remote_aim_fullframe_fallback", False)

    bot._execute_remote_fire(_Ctx(), "mid", 0, (1120, 405))

    assert fired["pos"] == (1120, 405)
