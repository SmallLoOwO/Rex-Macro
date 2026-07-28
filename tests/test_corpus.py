"""回礦語料夾（`miningbot/corpus.py`）：語料止血的純函式 + 落檔行為。

背景（2026-07-28 實測）：ledger 記了 200 張八方位快照，磁碟只剩 58 張讀得到，
能配成 (圖, 座標) 的僅 1 正 7 負——`snapshot_max_total_mb` 到頂從最舊刪起，
不分那張圖有沒有 click ground truth。這裡驗的是「在刪之前搬走」這條路的每一環。
"""

import json
import logging
import os
import types

import pytest

from miningbot import corpus


# ---- 命名與方位翻面（內部 0-based ↔ 檔名/meta 1-based）---------------------

def test_group_name_uses_episode_and_attempt():
    assert corpus.group_name(27, 2) == "ep27_attempt2"


def test_shot_filename_is_one_based():
    """`ctx.shots` 內部 0-based；檔名沿用 2026-07-18 起的玩家介面慣例 1-8。"""
    assert corpus.shot_filename(0) == "dir1.png"
    assert corpus.shot_filename(7) == "dir8.png"


def test_normalize_click_translates_dir_and_keeps_measured_layer():
    """`layer_seen`（(世界,Depth) 反推）保留；玩家宣告的 `layer` 不進 meta。"""
    got = corpus.normalize_click({
        "pos": (1604, 450), "dir": 1, "layer": "Mantle Layer",
        "layer_seen": "Shamrock", "depth_m": 7100, "invalid": False})
    assert got == {"dir": 2, "pos": [1604, 450], "layer_seen": "Shamrock",
                   "depth_m": 7100, "invalid": False}
    assert "layer" not in got


def test_normalize_click_wraps_accumulated_cur_dir():
    """`ctx.cur_dir` 是累積的淨右轉數，可能超過 8（`方位` 指令一路加）。"""
    assert corpus.normalize_click({"pos": (1, 2), "dir": 9})["dir"] == 2


def test_normalize_click_keeps_missing_measurements_as_none():
    """量不到就寫 None——補值會讓事後分析把「沒量到」誤當成「量到某層」。"""
    got = corpus.normalize_click({"pos": (1, 2), "dir": 0})
    assert got["layer_seen"] is None and got["depth_m"] is None


# ---- attempt 篩選（不篩就會把 attempt 1 的座標配到 attempt 3 的圖）---------

def test_clicks_for_attempt_keeps_only_matching_round():
    clicks = [{"attempt": 1, "pos": (1, 1)}, {"attempt": 3, "pos": (2, 2)}]
    assert corpus.clicks_for_attempt(clicks, 3) == [{"attempt": 3, "pos": (2, 2)}]


def test_clicks_for_attempt_drops_legacy_rows_without_attempt():
    """舊筆沒有 attempt 欄位：寧可少一筆正樣本，不要一筆錯配。"""
    assert corpus.clicks_for_attempt([{"pos": (1, 1)}], 1) == []


# ---- meta.json 形狀 --------------------------------------------------------

def _meta(**kw):
    base = dict(episode=27, attempt=2, world="Lucernia", sticky_layer="Shamrock",
                outcome="confirmed_by_user", t=1785170168.8, shots=[], clicks=[])
    base.update(kw)
    return corpus.build_meta(**base)


def test_build_meta_lists_only_copied_shots():
    meta = _meta(shots=[(0, "dir1.png"), (1, "dir2.png")])
    assert meta["shots"] == [{"dir": 1, "file": "dir1.png"},
                             {"dir": 2, "file": "dir2.png"}]


def test_build_meta_has_no_absolute_paths():
    """語料夾要能整包搬到別台機器；絕對路徑一搬就死（且會踩 MSIX 重導）。"""
    meta = _meta(shots=[(i, corpus.shot_filename(i)) for i in range(8)])
    dumped = json.dumps(meta, ensure_ascii=False)
    assert ":\\" not in dumped and "/" not in dumped and "\\" not in dumped


def test_build_meta_without_clicks_keeps_empty_list():
    """`skip`／無 click 的那輪也要存：八張天然負樣本本身就是資訊。"""
    assert _meta(outcome="skip")["clicks"] == []


# ---- 容量上限：優先刪無 click 的組 -----------------------------------------

def test_plan_corpus_cleanup_under_cap_deletes_nothing():
    groups = [("ep1_attempt1", True, 100.0, 1024 * 1024)]
    assert corpus.plan_corpus_cleanup(groups, max_total_mb=4096) == []


def test_plan_corpus_cleanup_prefers_groups_without_clicks():
    """有 ground truth 的組不可再生；無 click 的下一輪回礦就能再收一組。"""
    mb = 1024 * 1024
    groups = [
        ("old_with_click", True, 1.0, 3 * mb),      # 最舊，但有 ground truth
        ("new_no_click", False, 9.0, 3 * mb),       # 最新，但只有負樣本
    ]
    assert corpus.plan_corpus_cleanup(groups, max_total_mb=4) == ["new_no_click"]


def test_plan_corpus_cleanup_touches_click_groups_only_when_forced():
    """無 click 的全刪光還超標，才輪到有 click 的（同類內從最舊刪起）。"""
    mb = 1024 * 1024
    groups = [
        ("clicked_old", True, 1.0, 3 * mb),
        ("clicked_new", True, 5.0, 3 * mb),
        ("empty", False, 9.0, 3 * mb),
    ]
    assert corpus.plan_corpus_cleanup(groups, max_total_mb=4) == ["empty", "clicked_old"]


# ---- 落檔 ------------------------------------------------------------------

def _fake_shots(tmp_path, n=8, size=16):
    src_dir = tmp_path / "snapshots" / "reentry"
    src_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    for i in range(n):
        p = src_dir / f"reentry_ep27_dir{i + 1}.png"
        p.write_bytes(b"x" * size)
        shots.append((i, str(p)))
    return shots


def test_write_group_copies_all_shots_and_writes_meta(tmp_path):
    root = str(tmp_path / "corpus" / "reentry")
    group_dir, copied, requested = corpus.write_group(
        root, episode=27, attempt=2, world="Lucernia", sticky_layer="Shamrock",
        outcome="confirmed_by_user", t=1785170168.8,
        shots=_fake_shots(tmp_path),
        clicks=[{"attempt": 2, "pos": (1604, 450), "dir": 1,
                 "layer_seen": "Shamrock", "depth_m": 7100}])
    assert (copied, requested) == (8, 8)
    assert os.path.basename(group_dir) == "ep27_attempt2"
    for i in range(1, 9):
        assert os.path.exists(os.path.join(group_dir, f"dir{i}.png"))
    meta = json.loads(
        open(os.path.join(group_dir, corpus.META_NAME), encoding="utf-8").read())
    assert [s["file"] for s in meta["shots"]] == [f"dir{i}.png" for i in range(1, 9)]
    assert meta["clicks"] == [{"dir": 2, "pos": [1604, 450],
                               "layer_seen": "Shamrock", "depth_m": 7100,
                               "invalid": False}]


def test_write_group_skips_unreadable_shot_and_omits_it_from_meta(tmp_path):
    """單張複製失敗不讓整組陪葬，但 meta 不可指向不存在的檔案。"""
    root = str(tmp_path / "corpus" / "reentry")
    shots = _fake_shots(tmp_path, n=3)
    shots[1] = (1, str(tmp_path / "does_not_exist.png"))
    group_dir, copied, requested = corpus.write_group(
        root, episode=5, attempt=1, world=None, sticky_layer="Shamrock",
        outcome="skip", t=1.0, shots=shots, clicks=[])
    assert (copied, requested) == (2, 3)
    meta = json.loads(
        open(os.path.join(group_dir, corpus.META_NAME), encoding="utf-8").read())
    assert [s["file"] for s in meta["shots"]] == ["dir1.png", "dir3.png"]
    assert not os.path.exists(os.path.join(group_dir, "dir2.png"))


def test_write_group_ignores_empty_snapshot_paths(tmp_path):
    """`ctx.shots` 在快照寫檔失敗時會留 ``(i, "")``。"""
    root = str(tmp_path / "corpus" / "reentry")
    _group_dir, copied, requested = corpus.write_group(
        root, episode=5, attempt=1, world=None, sticky_layer="L",
        outcome="skip", t=1.0, shots=[(0, ""), (1, "")], clicks=[])
    assert (copied, requested) == (0, 0)


def test_enforce_cap_removes_no_click_group_first(tmp_path):
    root = str(tmp_path / "corpus" / "reentry")
    corpus.write_group(root, episode=1, attempt=1, world="Lucernia",
                       sticky_layer="Shamrock", outcome="confirmed_by_user",
                       t=1.0, shots=_fake_shots(tmp_path, size=4096),
                       clicks=[{"attempt": 1, "pos": (1, 2), "dir": 0}])
    corpus.write_group(root, episode=2, attempt=1, world="Lucernia",
                       sticky_layer="Shamrock", outcome="skip", t=2.0,
                       shots=_fake_shots(tmp_path, size=4096), clicks=[])
    assert corpus.enforce_cap(root, max_total_mb=0) >= 1
    assert not os.path.isdir(os.path.join(root, "ep2_attempt1"))


def test_scan_groups_treats_unreadable_meta_as_having_click(tmp_path):
    """讀不到 meta 就保守當有 ground truth——寧可誤留也不要誤刪不可再生的配對。"""
    root = tmp_path / "corpus" / "reentry"
    (root / "ep9_attempt1").mkdir(parents=True)
    (root / "ep9_attempt1" / corpus.META_NAME).write_text("{ broken", encoding="utf-8")
    assert corpus.scan_groups(str(root))[0][1] is True


def test_scan_groups_on_missing_root_returns_empty(tmp_path):
    assert corpus.scan_groups(str(tmp_path / "nope")) == []


# ---- 語料夾不在 snapshot retention 的掃描範圍內 -----------------------------

def test_snapshot_cleanup_never_collects_corpus_files(tmp_path, monkeypatch):
    """`_snapshot_cleanup_once` 只掃 `<log_dir>/snapshots`；語料夾必須毫髮無傷。

    用 max_total_mb=0 逼它刪光掃到的每個檔案，語料檔還在＝真的沒被收集到。
    """
    import miningbot.main as main_mod
    from miningbot.main import Bot

    snap = tmp_path / "snapshots" / "reentry"
    snap.mkdir(parents=True)
    doomed = snap / "old.png"
    doomed.write_bytes(b"x" * 1024)
    kept = tmp_path / "corpus" / "reentry" / "ep1_attempt1" / "dir1.png"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"x" * 1024)

    monkeypatch.setattr(main_mod.cfg, "log_dir", str(tmp_path))
    monkeypatch.setattr(main_mod.cfg, "snapshot_max_total_mb", 0)
    monkeypatch.setattr(main_mod.cfg, "snapshot_trace_max_total_mb", 0)
    bot = types.SimpleNamespace(logger=logging.getLogger("test_corpus"))
    Bot._snapshot_cleanup_once(bot)

    assert not doomed.exists(), "snapshots 底下的檔案應被清掉（前提條件）"
    assert kept.exists(), "語料夾被 snapshot retention 掃到了"


# ---- 主流程整合：best-effort，失敗不炸回礦收尾 ------------------------------

class _StubCtx:
    def __init__(self, shots, clicks=(), attempt=1):
        self.episode_id = 27
        self.attempt = attempt
        self.sticky_layer = "Shamrock"
        self.created_at = 1785170168.8
        self.shots = list(shots)
        self.clicks = list(clicks)


def _corpus_bot():
    from miningbot.main import Bot
    bot = types.SimpleNamespace(logger=logging.getLogger("test_corpus"))
    bot._rr_save_corpus = types.MethodType(Bot._rr_save_corpus, bot)
    return bot


def test_rr_save_corpus_writes_group(tmp_path, monkeypatch):
    import miningbot.main as main_mod
    monkeypatch.setattr(main_mod.cfg, "log_dir", str(tmp_path))
    ctx = _StubCtx(_fake_shots(tmp_path), attempt=2,
                   clicks=[{"attempt": 2, "pos": (1604, 450), "dir": 1}])
    _corpus_bot()._rr_save_corpus(ctx, "confirmed_by_user", "Lucernia")
    meta_path = (tmp_path / "corpus" / "reentry" / "ep27_attempt2"
                 / corpus.META_NAME)
    assert meta_path.exists()
    assert json.loads(meta_path.read_text(encoding="utf-8"))["clicks"][0]["dir"] == 2


def test_rr_save_corpus_skips_when_no_shots(tmp_path, monkeypatch):
    """沒掃過就收尾（例如重置中斷）→ 不留空目錄。"""
    import miningbot.main as main_mod
    monkeypatch.setattr(main_mod.cfg, "log_dir", str(tmp_path))
    _corpus_bot()._rr_save_corpus(_StubCtx([]), "skip", None)
    assert not (tmp_path / "corpus").exists()


def test_rr_save_corpus_swallows_write_failure(tmp_path, monkeypatch, caplog):
    """複製目標寫不進去時，回礦收尾照常——素材收集是加值路徑。"""
    import miningbot.main as main_mod
    monkeypatch.setattr(main_mod.cfg, "log_dir", str(tmp_path))

    def _boom(*_a, **_kw):
        raise OSError("read-only file system")

    monkeypatch.setattr(main_mod.corpus, "write_group", _boom)
    with caplog.at_level(logging.WARNING):
        _corpus_bot()._rr_save_corpus(_StubCtx(_fake_shots(tmp_path)), "skip", None)
    assert any("語料組寫入失敗" in r.getMessage() for r in caplog.records)


def test_record_click_stamps_attempt():
    """語料配對的關鍵欄位（2026-07-28 加）。"""
    from miningbot import reentry_remote
    ctx = reentry_remote.RemoteReentryContext(
        episode_id=1, created_at=0.0, sticky_layer="Shamrock")
    ctx.attempt = 3
    reentry_remote.record_click(ctx, (10, 20), "Shamrock", (), 1.0)
    assert ctx.clicks[-1]["attempt"] == 3


def test_config_exposes_corpus_cap():
    """門檻放 config，不硬寫在流程裡。"""
    from miningbot.config import Config
    assert Config().corpus_max_total_mb > 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
