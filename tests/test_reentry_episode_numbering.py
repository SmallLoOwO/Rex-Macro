"""回礦 episode 編號不得重複（2026-07-26 實機事故）。

事故：同一天 13:15 與 18:34 兩場回礦都拿到 `#26`，快照都叫 `reentry_ep26_dir1..8`，
網頁歷史把兩場併成一個 episode ⇒「事件時間軸」出現整組重複的 dir1~dir8。

根因：`ledger_entry` 只在 episode **收尾時**才寫；兩場都在收尾前結束（重啟／逾時），
ledger 末行永遠停在 25，`next_episode_id` 每次都算出 26。

這裡驗的是**接線**（`_rr_ensure_ctx` 真的會佔號），純函式行為在
`test_reentry_remote.py::TestContextLedger` 驗。
"""
import json

import pytest

from miningbot import main, reentry_remote
from miningbot.main import cfg
from tests.fake_bot import make_fake_bot


def _bot(ledger_path, trigger="reset"):
    return make_fake_bot(
        bind=["_rr_ensure_ctx", "_rr_ledger_append"],
        _rr_ctx=None,
        _rr_sticky_layer="Shamrock",
        _rr_trigger=trigger,
        _rr_pitch_back_px=123,
    )


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "reentry_remote" / "ledger.jsonl"
    monkeypatch.setattr(cfg, "reentry_remote_ledger", str(path))
    return path


def _episodes(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestEpisodeReservation:
    def test_first_episode_reserves_id_1(self, ledger):
        bot = _bot(ledger)
        bot._rr_ensure_ctx(reroll=False)
        assert bot._rr_ctx.episode_id == 1
        rows = _episodes(ledger)
        assert [r["outcome"] for r in rows] == ["started"]
        assert rows[0]["episode"] == 1 and rows[0]["trigger"] == "reset"

    def test_unfinished_episode_still_advances_numbering(self, ledger):
        """事故本體：episode 沒收尾（無結果行）時，下一場仍必須拿到新號。"""
        bot = _bot(ledger)
        bot._rr_ensure_ctx(reroll=False)
        first = bot._rr_ctx.episode_id
        # 模擬 bot 重啟：ctx 丟失、ledger 只留佔號行（沒有 finalize 寫的結果行）
        bot._rr_ctx = None
        bot._rr_ensure_ctx(reroll=False)
        assert bot._rr_ctx.episode_id == first + 1, "沒收尾的 episode 也必須佔號"

    def test_reservation_survives_finalize_write(self, ledger):
        """佔號行 + 結果行同號並存時，取號仍走 max（末行不是最大號也不受影響）。"""
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"episode": 25, "outcome": "started"}) + "\n"
            + json.dumps({"episode": 25, "outcome": "skip"}) + "\n",
            encoding="utf-8")
        bot = _bot(ledger)
        bot._rr_ensure_ctx(reroll=False)
        assert bot._rr_ctx.episode_id == 26

    def test_reroll_keeps_same_episode_and_does_not_reserve_again(self, ledger):
        """reroll 是同一集的下一次 attempt——不換號，也不該再寫一行佔號。"""
        bot = _bot(ledger)
        bot._rr_ensure_ctx(reroll=False)
        eid = bot._rr_ctx.episode_id
        bot._rr_ensure_ctx(reroll=True)
        assert bot._rr_ctx.episode_id == eid
        assert bot._rr_ctx.attempt == 2
        assert len(_episodes(ledger)) == 1, "reroll 不得重複佔號"

    def test_ledger_write_failure_does_not_block_reentry(self, ledger, monkeypatch):
        """ledger 是記帳不是流程：寫不進去只記 log，回礦照跑（ctx 仍建起來）。"""
        bot = _bot(ledger)

        def _boom(_d):
            raise OSError("disk full")

        bot._rr_ledger_append = _boom
        bot._rr_ensure_ctx(reroll=False)
        assert bot._rr_ctx is not None and bot._rr_ctx.episode_id == 1


class TestSnapshotLabelsAreUnique:
    def test_two_unfinished_episodes_produce_distinct_labels(self, ledger):
        """事故的可見症狀：快照 label 撞名。編號修好後兩場 label 必須不同。"""
        labels = []
        bot = _bot(ledger)
        for _ in range(2):
            bot._rr_ctx = None
            bot._rr_ensure_ctx(reroll=False)
            eid = bot._rr_ctx.episode_id
            labels.append([f"reentry_ep{eid}_dir{i + 1}" for i in range(8)])
        assert not set(labels[0]) & set(labels[1])


def test_next_episode_id_from_ledger_is_what_main_uses():
    """防迴歸：main 必須用掃全檔的版本，不能退回只看末行的 next_episode_id。"""
    src = main.Bot._rr_ensure_ctx.__code__.co_names
    assert "next_episode_id_from_ledger" in src
    assert reentry_remote.next_episode_id_from_ledger(
        [b'{"episode": 25, "outcome": "started"}']) == 26
