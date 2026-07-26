# tests/test_web_static.py
"""P5 Task 7：純 HTML render 函式測試（render_history_html / render_annotate_html）。

直接呼叫 miningbot.web_static 的純函式，斷言關鍵字串在 HTML 裡——不靠 FastAPI
routing（route 層覆蓋在 test_web_server_p5.py；這裡聚焦 UI 字串與 schema 一致性）。
"""
from miningbot.web_static import render_annotate_html, render_history_html


# ── render_history_html ───────────────────────────────────────────────────


def test_render_history_html_includes_episode_id():
    """列表每列應含 episode_id 字串，並可點連到詳情。"""
    episodes = [
        {"harvest_id": "007", "type": "harvest", "first_ts": 1000.0,
         "last_ts": 1001.0, "count": 2, "snapshots": []},
        {"harvest_id": "009", "type": "reentry", "first_ts": 2000.0,
         "last_ts": 2000.0, "count": 1, "snapshots": []},
    ]
    html = render_history_html(episodes)
    assert "007" in html
    assert "009" in html


def test_render_history_html_episode_row_links_to_annotate_or_detail():
    """每列應有連到詳情的錨點（/annotate?episode= 或 /api/episode/）。"""
    episodes = [{"harvest_id": "042", "type": "harvest", "count": 1,
                 "first_ts": None, "last_ts": None, "snapshots": []}]
    html = render_history_html(episodes)
    assert "/annotate?episode=042" in html or "/api/episode/042" in html


def test_render_history_html_has_type_filter():
    """型態篩選 UI 須存在（all/harvest/reentry 至少其一為 option value）。"""
    html = render_history_html([])
    assert "harvest" in html
    assert "reentry" in html


def test_render_history_html_shows_count_per_episode():
    """每列顯示該 episode 的 snapshot 數。"""
    episodes = [{"harvest_id": "007", "type": "harvest", "count": 5,
                 "first_ts": None, "last_ts": None, "snapshots": []}]
    html = render_history_html(episodes)
    assert "5" in html


def test_render_history_html_empty_episodes_renders_without_error():
    """空 list 也要能 render（不 crash）。"""
    html = render_history_html([])
    assert "MiningBot" in html


# ── render_annotate_html ──────────────────────────────────────────────────


def test_render_annotate_html_includes_tier_names_from_rarity_choices():
    """tier 按鈕須列出 rarity_choices[0] 的每個 tier。"""
    tiers = ["Legendary", "Mythic", "Surreal"]
    variants = ["原色", "Spectral", "Ionized"]
    html = render_annotate_html("007", "/snap.png", (tiers, variants))
    for t in tiers:
        assert t in html, f"tier {t!r} 應出現在 HTML"


def test_render_annotate_html_includes_variant_names():
    """變體按鈕須列出 rarity_choices[1]。"""
    tiers = []
    variants = ["原色", "Spectral", "Ionized"]
    html = render_annotate_html("007", "/snap.png", (tiers, variants))
    for v in variants:
        assert v in html, f"variant {v!r} 應出現在 HTML"


def test_render_annotate_html_includes_all_four_symptom_buttons():
    """四個症狀按鈕（中文顯示）都該在 HTML。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "漏判" in html and "FN" in html
    assert "誤判" in html and "FP" in html
    assert "該拒沒拒" in html
    assert "不確定" in html


def test_render_annotate_html_symptom_buttons_map_to_validate_annotation_values():
    """症狀按鈕的 data-symptom 必須是 validate_annotation 接受的標準 enum 值。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert 'data-symptom="false_negative"' in html
    assert 'data-symptom="false_positive"' in html
    assert 'data-symptom="should_reject_failed"' in html
    assert 'data-symptom="unknown"' in html


def test_render_annotate_html_submit_posts_to_api_annotate():
    """Submit 必須呼叫 /api/annotate（POST + JSON body）。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "/api/annotate" in html
    assert "POST" in html or "method" in html.lower()


def test_render_annotate_html_has_mineral_input():
    """mineral 文字欄位必須存在（spec §5：可選）。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "mineral" in html


def test_render_annotate_html_has_related_incident_input():
    """related_incident 文字欄位必須存在（spec §5：可選）。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "related_incident" in html or "related-incident" in html


def test_render_annotate_html_shows_snapshot_image_when_path_provided():
    """snapshot_path 提供 → <img src=...> 出現。"""
    html = render_annotate_html("007", "/snapshots/foo.png",
                                (["Mythic"], ["原色"]))
    assert "<img" in html
    assert "/snapshots/foo.png" in html


def test_render_annotate_html_handles_missing_snapshot():
    """snapshot_path 為空字串時也要能 render（不該 crash、img 可缺席）。"""
    html = render_annotate_html("007", "", ([], []))
    assert "MiningBot" in html


def test_render_annotate_html_source_kind_is_manual():
    """玩家手動標註 → source.kind = 'manual'（validate_annotation 必填）。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "manual" in html


def test_render_annotate_html_has_square_drag_pointer_logic():
    """1:1 方形拖曳需 pointerdown/move/up 事件（spec §5 C 區）。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "pointerdown" in html
    assert "pointermove" in html
    assert "pointerup" in html


def test_render_annotate_html_has_pinch_zoom_or_wheel_zoom():
    """pinch-zoom（手機）+ wheel zoom（桌機）至少一個。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    has_zoom = ("wheel" in html or "touchmove" in html
                or "touchstart" in html)
    assert has_zoom
