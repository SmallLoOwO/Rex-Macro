"""tier0 批次標註佇列（spec D3b）：一張接一張走完，不再永遠停在 2 張。

tier 排序邏輯（`web_history.annotation_tier`）早就寫好，缺的只是連續動線與去重。
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from miningbot import web_history, web_server
from miningbot.web_static import render_annotate_html


def _rec(label, path, ts):
    return {"written_at": ts, "label": label, "path": path, "harvest_id": None}


# ---- 佇列排序與去重（純函式）-----------------------------------------------

def test_queue_keeps_only_requested_tier():
    """tier0＝掃描全空／框被拒／瞄準失敗；聊天／背包那些成熟流程不進佇列。"""
    got = web_history.build_queue([
        _rec("113_sweep_empty", "a/sweep.png", 3.0),
        _rec("chat_open_fail_x", "a/chat.png", 2.0),
        _rec("120_rare_found", "a/rare.png", 1.0),
    ])
    assert [r["stem"] for r in got] == ["sweep"]


def test_queue_sorts_newest_first():
    """最近的失敗最可能還沒被修掉，先標它資訊量最高。"""
    got = web_history.build_queue([
        _rec("a_sweep_empty", "a/old.png", 1.0),
        _rec("b_sweep_empty", "a/new.png", 9.0),
    ])
    assert [r["stem"] for r in got] == ["new", "old"]


def test_queue_puts_records_without_timestamp_last():
    got = web_history.build_queue([
        _rec("a_sweep_empty", "a/none.png", None),
        _rec("b_sweep_empty", "a/dated.png", 1.0),
    ])
    assert [r["stem"] for r in got] == ["dated", "none"]


def test_queue_drops_already_annotated():
    """不去重的話每次進佇列都從第一張重來。"""
    got = web_history.build_queue(
        [_rec("a_sweep_empty", "a/done.png", 1.0),
         _rec("b_sweep_empty", "a/todo.png", 2.0)],
        annotated={"done"})
    assert [r["stem"] for r in got] == ["todo"]


def test_queue_dedupes_repeated_index_rows():
    got = web_history.build_queue([
        _rec("a_sweep_empty", "a/x.png", 1.0),
        _rec("a_sweep_empty", "a/x.png", 2.0),
    ])
    assert len(got) == 1


def test_queue_skips_records_without_path():
    assert web_history.build_queue([{"label": "sweep_empty", "written_at": 1.0}]) == []


def test_annotated_stems_scans_nested_fixture_dirs(tmp_path):
    (tmp_path / "aim").mkdir()
    (tmp_path / "aim" / "shot.json").write_text("{}", encoding="utf-8")
    (tmp_path / "aim" / "shot.png").write_bytes(b"x")
    assert web_history.annotated_stems(str(tmp_path)) == {"shot"}


def test_annotated_stems_on_missing_dir_is_empty():
    assert web_history.annotated_stems(None) == set()


def test_annotation_queue_reads_index_and_fixtures(tmp_path):
    index = tmp_path / "snapshot_index.jsonl"
    # annotation_queue 過濾掉檔案不存在的列（retention 刪掉的死連結），
    # 測試必須造真的 PNG——即使是 1 byte 也行，只驗 isfile。
    (tmp_path / "todo.png").write_bytes(b"x")
    (tmp_path / "done.png").write_bytes(b"x")
    index.write_text("\n".join(json.dumps(r) for r in [
        _rec("113_sweep_empty", str(tmp_path / "todo.png"), 2.0),
        _rec("114_aim_fail", str(tmp_path / "done.png"), 1.0),
    ]) + "\n", encoding="utf-8")
    fixtures = tmp_path / "fx"
    fixtures.mkdir()
    (fixtures / "done.json").write_text("{}", encoding="utf-8")
    got = web_history.annotation_queue(str(index), str(fixtures))
    assert [r["stem"] for r in got] == ["todo"]


def test_annotation_queue_tolerates_broken_index_lines(tmp_path):
    index = tmp_path / "snapshot_index.jsonl"
    (tmp_path / "x.png").write_bytes(b"x")
    index.write_text(json.dumps(_rec("a_sweep_empty", str(tmp_path / "x.png"), 1.0))
                     + '\n{"label": "part', encoding="utf-8")
    assert len(web_history.annotation_queue(str(index), None)) == 1


# ---- 前端動線 --------------------------------------------------------------

def _queue_html(rows):
    return render_annotate_html(episode_id="", snapshot_path="",
                                rarity_choices=([], []), queue=rows)


def test_queue_page_shows_position_and_keys():
    html = _queue_html([{"path": "a/x.png", "label": "113_sweep_empty"},
                        {"path": "a/y.png", "label": "114_aim_fail"}])
    assert "佇列模式" in html and "queue-pos" in html
    assert "第 ${qIndex + 1} / ${queue.length} 張" in html
    assert "e.key === 'j'" in html and "e.key === 'k'" in html
    assert "e.key === 'Enter'" in html


def test_queue_page_advances_after_submit():
    """送出後把該張從佇列拿掉再跳下一張——不會重複給已標過的。"""
    html = _queue_html([{"path": "a/x.png", "label": "113_sweep_empty"}])
    assert "queue.splice(qIndex, 1)" in html
    assert "showQueueItem(qIndex)" in html


def test_queue_keyboard_ignores_form_fields():
    """游標在礦物／事故欄裡時 j/k/數字要照常打字。"""
    html = _queue_html([{"path": "a/x.png", "label": "113_sweep_empty"}])
    assert "function typingInField" in html
    assert "if (typingInField(e)) return;" in html


def test_empty_queue_says_so():
    html = _queue_html([])
    assert "佇列是空的" in html


def test_non_queue_mode_has_no_queue_bar():
    html = render_annotate_html(episode_id="1", snapshot_path="a.png",
                                rarity_choices=([], []))
    assert 'id="queue-bar"' not in html


def test_queue_first_item_becomes_the_displayed_snapshot():
    html = _queue_html([{"path": "a/first.png", "label": "113_sweep_empty"}])
    assert "first.png" in html


# ---- route -----------------------------------------------------------------

def _client(tmp_path, records):
    from miningbot.web_ipc import FallbackState, PendingReplies
    index = tmp_path / "snapshot_index.jsonl"
    index.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                     encoding="utf-8")
    # 造真實 PNG 讓 annotation_queue 的 isfile 過濾不把它們全刪
    for r in records:
        p = r.get("path")
        if p:
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(p, "wb") as f:
                f.write(b"x")
    fixtures = tmp_path / "fx"
    fixtures.mkdir()
    app = web_server.create_app(
        PendingReplies(), FallbackState(), broadcast_callback=None,
        fixtures_dir=str(fixtures), snapshots_root=str(tmp_path),
        snapshot_index_path=str(index))
    return TestClient(app)


def test_annotate_queue_route_renders_queue(tmp_path):
    client = _client(tmp_path, [
        _rec("113_sweep_empty", str(tmp_path / "a.png"), 2.0),
        _rec("120_rare_found", str(tmp_path / "b.png"), 1.0),
    ])
    body = client.get("/annotate?queue=tier0").text
    assert "佇列模式" in body and "a.png" in body
    assert "b.png" not in body        # tier3 不進 tier0 佇列


def test_annotate_without_queue_param_is_unchanged(tmp_path):
    client = _client(tmp_path, [_rec("113_sweep_empty", str(tmp_path / "a.png"), 1.0)])
    body = client.get("/annotate").text
    assert 'id="queue-bar"' not in body


def test_annotate_queue_uses_existing_tier_logic():
    """沒有另寫一套排序——tier 判定只有 annotation_tier 一份。"""
    import inspect
    src = inspect.getsource(web_history.build_queue)
    assert "annotation_tier(" in src


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ---- 死連結過濾 + 疊圖去重（2026-07-29）------------------------------------

def test_build_queue_filters_dead_links():
    """retention 刪掉的快照不該排在佇列裡（實測 500 列 339 張是死連結）。"""
    got = web_history.build_queue(
        [_rec("a_sweep_empty", "exists.png", 1.0),
         _rec("b_sweep_empty", "gone.png", 2.0)],
        exists=lambda p: p == "exists.png")
    assert [r["stem"] for r in got] == ["exists"]


def test_build_queue_overlay_deduped_when_clean_exists():
    """`_aim.png` 疊圖在乾淨原幀也在佇列時丟掉（同一幀的第二次複本）。"""
    got = web_history.build_queue(
        [_rec("a_sweep_empty", "shot.png", 1.0),
         _rec("a_sweep_empty", "shot_aim.png", 2.0)],
        exists=lambda p: True)
    assert [r["stem"] for r in got] == ["shot"]


def test_build_queue_overlay_kept_when_clean_gone():
    """乾淨原幀被 retention 刪掉時，疊圖留下（比沒有好）。"""
    got = web_history.build_queue(
        [_rec("a_sweep_empty", "shot_aim.png", 1.0)],
        exists=lambda p: True)
    assert [r["stem"] for r in got] == ["shot_aim"]


def test_annotation_queue_negatives_dir_dedup(tmp_path):
    """no_target 標註寫 corpus/negatives/，佇列要去重那邊（不只掃 fixtures）。"""
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "done.json").write_text("{}", encoding="utf-8")
    neg = tmp_path / "neg"
    neg.mkdir()
    (neg / "neg_done.json").write_text("{}", encoding="utf-8")
    stems = web_history.annotated_stems(str(fx), str(neg))
    assert "done" in stems and "neg_done" in stems
