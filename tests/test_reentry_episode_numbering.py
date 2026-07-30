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


# ---------------------------------------------------------------------------
# 2026-07-26：「回礦的功能依舊不能在網頁上使用」的根因與修法。
#
# 實機 log（18:32~18:34）：
#   [RR#26] 回礦 web 介入：reply timeout（attempt 1/3），fall through Discord 八方位
# 網頁**有連上**（不是 fallback），但舊順序是「先問 web、逾時才掃八方位」，
# 而問 web 時只推「當下這一幀」——回礦開場人站在地表，傳送板九成不在視野內。
# 玩家看著一張沒有目標的圖，唯一能做的就是等它逾時。
# ---------------------------------------------------------------------------


class TestSweepHappensBeforeAskingWeb:
    def test_open_episode_sweeps_before_web_intervention(self):
        """順序防迴歸：_rr_open_episode 必須先拿到八方位圖，才問 web。"""
        import inspect
        src = inspect.getsource(main.Bot._rr_open_episode)
        sweep_at = src.index("_rr_sweep_capture")
        ask_at = src.index("_reentry_await_player_click")
        assert sweep_at < ask_at, "必須先掃八方位再問 web，否則玩家沒東西可點"

    def test_web_path_does_not_sweep_twice(self):
        """兩條路徑共用同一次旋轉——絕不能為了 web 再轉一圈（~15s 且會改面向）。"""
        import inspect
        src = inspect.getsource(main.Bot._rr_open_episode)
        assert src.count("self._rr_sweep_capture(") == 1

    def test_discord_send_is_separate_from_capture(self):
        """拍照與發 Discord 拆開，web 接手時才不會順便洗版 8 張圖。"""
        assert hasattr(main.Bot, "_rr_sweep_capture")
        assert hasattr(main.Bot, "_rr_sweep_send_discord")
        capture_src = main.Bot._rr_sweep_capture.__code__.co_names
        assert "_rr_notify" not in capture_src, "拍照函式不該自己發 Discord"

    def test_capture_returns_web_pngs_only_when_asked(self):
        """encode_for_web=False 時不做多餘的 PNG 編碼（Discord 路徑用不到）。"""
        import inspect
        sig = inspect.signature(main.Bot._rr_sweep_capture)
        assert "encode_for_web" in sig.parameters
        assert sig.parameters["encode_for_web"].default is False


class TestWebInterventionBudget:
    def test_no_timeout_config_left(self):
        """所有等待預算欄位都刪光了（2026-07-30 使用者指定「無限時等待」）。

        沿革 120s→300s→900s＋120s join grace，每次拉長只是把同一條 race 往後推：
        RR#34 推圖 2 分鐘後退場清緩衝，使用者 13 分鐘後開網頁看到空白面板。
        """
        from miningbot.config import Config
        c = Config()
        for gone in ("web_intervention_budget_s",
                     "web_intervention_retry_budget_s",
                     "web_join_grace_s"):
            assert not hasattr(c, gone), f"{gone} 應已刪除（無限等不需要預算）"

    def test_reentry_wait_has_no_deadline(self):
        """防迴歸：等待迴圈不得再引入任何逾時預算，也別借 remote_aim_budget_s。

        只掃**程式碼**——docstring 記著 120s→900s 的沿革，那些字串不是迴歸。
        """
        import inspect
        code = ""
        for fn in (main.Bot._reentry_await_player_click,
                   main.Bot._await_web_reentry_action):
            code += inspect.getsource(fn).replace(fn.__doc__ or "", "")
        assert "budget_s" not in code
        assert "timeout_s" not in inspect.signature(
            main.Bot._await_web_reentry_action).parameters

    def test_unbounded_wait_still_aborts_on_shutdown(self):
        """無限等的前提是中止條件齊全：重置／關閉／暫停都要放得掉主迴圈。"""
        import inspect
        src = inspect.getsource(main.Bot._await_web_reentry_action)
        assert "_mine_resetting" in src
        assert "_running" in src and "paused" in src
