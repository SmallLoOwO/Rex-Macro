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
    """每列應有連到詳情的錨點。

    2026-07-26 起連的是 `/episode?id=`（詳細頁：時間軸／快照分組／標註歷程），
    不再直接跳 `/annotate`——先看「這一集發生什麼」才知道要標哪一張。
    """
    episodes = [{"harvest_id": "042", "type": "harvest", "count": 1,
                 "first_ts": None, "last_ts": None, "snapshots": []}]
    html = render_history_html(episodes)
    assert ("/episode?id=042" in html
            or "/annotate?episode=042" in html
            or "/api/episode/042" in html)


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


# ---------------------------------------------------------------------------
# 2026-07-26 實機回報「網頁內容特別簡潔，感覺有部分功能沒放進去」。
# 查下去功能其實都在，但四個頁面**彼此沒有任何連結**，而且標註頁的 <img> 永遠破圖
# （沒有 serve 快照的 route）、`/api/episode/{id}` 前端零使用。以下守住這批補完。
# ---------------------------------------------------------------------------


import pytest  # noqa: E402
from miningbot.web_static import (  # noqa: E402
    render_nav, render_episode_html, render_intervention_html,
    render_annotate_html, render_index_html,
)


class _Cfg:
    reentry_mode = "remote"
    reentry_target_layer = ""
    reentry_yaw_sample_sweep = False
    sweep_pitch_enabled = False


@pytest.mark.parametrize("name,html_fn", [
    ("index", lambda: render_index_html(_Cfg())),
    ("history", lambda: render_history_html([])),
    ("annotate", lambda: render_annotate_html("7", "", (["Rare"], ["原色"]))),
    ("intervention", render_intervention_html),
])
def test_every_page_has_nav(name, html_fn):
    """四個頁面都要有導覽列，否則功能找得到卻進不去。"""
    html = html_fn()
    assert 'class="nav"' in html, f"{name} 缺導覽列"
    for href in ("/intervention", "/history"):
        assert href in html, f"{name} 導覽列缺 {href}"
    assert ".nav a.current" in html, f"{name} 缺導覽列 CSS"


def test_nav_marks_current_page():
    assert 'href="/history" class="current"' in render_nav("/history")
    assert 'href="/" class="current"' in render_nav("/")


def _detail(**over):
    d = {"harvest_id": "42", "type": "harvest", "count": 2,
         "first_ts": 1784270000.0, "last_ts": 1784270900.0,
         "snapshots": [
             {"written_at": 1784270000.0, "label": "sweep_dir1",
              "path": r"C:\logs\snapshots\reentry\a.png"},
             {"written_at": 1784270900.0, "label": "sweep_dir1",
              "path": r"C:\logs\snapshots\reentry\b.png"},
         ]}
    d.update(over)
    return d


def test_episode_page_has_timeline_thumbs_and_annotations():
    html = render_episode_html(_detail(), annotations=[])
    assert "事件時間軸" in html
    assert "sweep_dir1" in html
    # 縮圖必須走 /snapshot（先前根本沒有這條 route，<img> 一律破圖）
    assert "/snapshot?path=" in html
    assert "尚無標註" in html


def test_episode_page_groups_snapshots_by_label():
    """同 label 的多張要收在同一組——before/after 對照才看得出來。"""
    html = render_episode_html(_detail(), annotations=[])
    assert html.count("<section class=\"grp\">") == 1
    assert html.count("/snapshot?path=") == 2


def test_episode_page_renders_annotations():
    html = render_episode_html(_detail(), annotations=[
        {"image": "auto_42_fail.png", "tier": "Rare", "variant": "Spectral",
         "mineral": "Tin", "symptom": "false_negative",
         "related_incident": "H057"},
    ])
    for token in ("auto_42_fail.png", "Rare", "Spectral", "Tin",
                  "false_negative", "H057"):
        assert token in html, token


def test_episode_page_url_encodes_windows_paths():
    """Windows 路徑的反斜線與冒號必須 URL-encode，否則 query 解析錯。"""
    html = render_episode_html(_detail(), annotations=[])
    assert "C%3A%5Clogs" in html
    assert r"path=C:\logs" not in html


def test_episode_page_survives_empty_snapshots():
    html = render_episode_html(_detail(snapshots=[], count=0), annotations=[])
    assert "沒有快照" in html


def test_history_has_date_filter():
    """spec §5 A 明列日期篩選；先前只有類型／結果／關鍵字。"""
    html = render_history_html([
        {"harvest_id": "1", "type": "harvest", "count": 1,
         "first_ts": 1784270000.0, "last_ts": 1784270000.0, "snapshots": []}])
    assert 'id="filter-from"' in html and 'id="filter-to"' in html
    assert 'type="date"' in html
    # 每列要帶 data-date 供比較（YYYY-MM-DD，跟 <input type=date> 同格式）
    assert "data-date=\"2026-" in html


def test_intervention_has_skip_button():
    """spec §4 回礦流程第 6 點：失敗時玩家可按「跳過」，不必切回 Discord 打字。"""
    html = render_intervention_html()
    assert 'id="skip"' in html
    assert "'skip'" in html or '"skip"' in html
    # 只對 reentry 顯示（harvest 沒有等價路徑）
    assert "flow !== 'reentry'" in html
