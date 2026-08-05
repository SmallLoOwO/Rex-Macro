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


def test_render_annotate_html_has_no_variant_buttons():
    """變體整區已移除（使用者 2026-07-31：「變體其實對外框的資訊不影響」）。

    schema 仍留 `variant` 欄位（舊素材寫過），但 UI 不再問、payload 恆送 null。
    """
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色", "Spectral"]))
    assert 'id="variants"' not in html
    assert "data-variant=" not in html
    assert "<h2>變體</h2>" not in html
    assert "variant: null" in html


def test_render_annotate_html_tier_locked_unless_observation_is_ore():
    """症狀互斥：選 2/3/4 時稀有度按鈕 disabled 並清空選擇（不只送出時丟掉）。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "function applyObsGating()" in html
    gating = html.split("function applyObsGating()")[1].split("\n}")[0]
    assert "activeObs === 'ore'" in gating
    assert "b.disabled = !isOre" in gating
    assert "activeTier = null" in gating


def test_render_annotate_html_queue_exhausted_hides_image_and_submit():
    """佇列走完＝顯示「沒有其他圖片了」並鎖住送出，不留最後一張在畫面上。

    使用者 2026-07-31：「完全清完後會出現最後的圖片，我擔心會造成重複標注」。
    """
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]),
                                queue=[{"path": "/a.png", "label": "x"}])
    assert "沒有其他圖片了" in html
    assert "function setQueueDone(" in html
    done = html.split("function setQueueDone(done)")[1].split("renderQueuePos();")[0]
    assert "submitBtn.disabled = true" in done
    assert "updateSubmitGate()" in done
    assert "img.style.display = done ? 'none' : ''" in done


def test_render_annotate_html_ctrl_z_undoes_last_submit():
    """Ctrl+Z 打 /api/annotate/undo，並把該張插回佇列原位重標。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]),
                                queue=[{"path": "/a.png", "label": "x"}])
    assert "/api/annotate/undo" in html
    assert "e.ctrlKey || e.metaKey" in html
    assert "undoStack.push(" in html
    assert "queue.splice(at, 0, last.item)" in html


def test_render_annotate_html_asks_what_you_see_not_which_symptom():
    """玩家只回答「看到什麼」，四顆按鈕整句白話、不出現 FN/FP 術語。

    使用者原話（2026-07-29）：「症狀內容不夠明確 不知道 fn fp 是甚麼」；
    （2026-07-31）：「給予的圖片大部分只有 1 與 4，所以我也不知道 2 與 3 的
    差別，並且 bot 有沒有接受……腳本在記錄圖片的時候應該就會有了」——症狀改成
    由（看到什麼 × bot 判定）推導，玩家不再挑症狀。
    """
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    block = html.split('<div id="observations">')[1].split("<p id=")[0]
    assert "有礦框" in block
    assert "不是礦框" in block
    assert "什麼都沒有" in block
    assert "不確定" in block
    assert "FN" not in block and "FP" not in block


def test_render_annotate_html_observation_buttons_cover_the_mapping():
    """四顆按鈕的 data-obs 必須就是 SYMPTOM_BY_OBSERVATION 的鍵，一個不漏。

    少一顆＝那一列推導永遠觸不到（例如 decoy 沒了就再也標不出「該拒沒拒」）。
    """
    from miningbot.web_annotation import SYMPTOM_BY_OBSERVATION
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    for obs in SYMPTOM_BY_OBSERVATION:
        assert f'data-obs="{obs}"' in html


def test_render_annotate_html_submit_posts_to_api_annotate():
    """Submit 必須呼叫 /api/annotate（POST + JSON body）。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "/api/annotate" in html
    assert "POST" in html or "method" in html.lower()


def test_render_annotate_html_has_no_fields_the_player_cannot_know():
    """礦物／相關事故／類別路徑三個輸入框必須不在（2026-07-29）。

    使用者原話：「移除礦物 相關事故 類別路徑等行列，因為這些我都不會知道」。
    schema 兩個可選欄位改送 null，category 由檔名推。
    """
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    for element_id in ('id="mineral"', 'id="related-incident"', 'id="category"'):
        assert element_id not in html, f"{element_id} 應已移除"
    assert "mineral: null" in html
    assert "related_incident: null" in html


def test_render_annotate_html_category_derived_from_filename():
    """類別路徑欄位移除後，回礦素材仍須落 reentry/teleport_board 而非 aim。

    先前那個欄位預設永遠 "aim"，玩家不改就把回礦素材寫進錯資料夾。
    """
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert "reentry_ep" in html and "reentry/teleport_board" in html
    assert "categoryFor(imageName)" in html


def test_render_annotate_html_shows_snapshot_image_when_path_provided():
    """snapshot_path 提供 → <img> 走 /snapshot?path= 取圖。"""
    html = render_annotate_html("007", "/snapshots/foo.png",
                                (["Mythic"], ["原色"]))
    assert "<img" in html
    assert "/snapshot?path=" in html
    assert "%2Fsnapshots%2Ffoo.png" in html   # url-quote 後的原路徑當 query 值


def test_render_annotate_html_never_uses_raw_path_as_img_src():
    """回歸（2026-07-26）：Windows 絕對路徑不得直接當 src。

    舊版 `src="C:\\Users\\...\\x.png"` 會被瀏覽器解析成 `file:///C:/...`，
    http 頁面載 file:// 一律被擋 → naturalWidth 恆 0 → clientToNatural() 除以 0
    → selRect 永遠 null → 「送出標註」永遠只回「請先在快照上拖曳出方形」，
    整個標註工具不能用。這條測試盯的就是「src 不可以是裸路徑」。
    """
    raw = r"C:\Users\puppy\AppData\Local\RexMacro\logs\snapshots\review\a.png"
    html = render_annotate_html("113", raw, (["Mythic"], ["原色"]))
    assert 'src="/snapshot?path=' in html
    # 裸路徑（含碟符與反斜線）不得原封不動出現在 src 屬性裡
    assert f'src="{raw}"' not in html
    assert "file://" not in html


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


def test_render_annotate_html_submit_button_starts_disabled():
    """送出鍵初始 disabled——圖片還沒載入不能送出（防快速連按盲送）。

    2026-08-05：佇列模式快速連按 Enter 時，新圖還沒顯示就送出＝連裡面藏著的
    漏判（FN）也一起錯過。送出鍵在圖片 load 事件前一律禁用。
    """
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    assert 'id="submit" disabled' in html


def test_render_annotate_html_has_preload_and_submit_gate():
    """背景預載 5 張 + imgReady/submitting 守門必須存在於前端 JS。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]),
                                queue=[{"path": "/a.png", "label": "x"}])
    assert "preloadAhead" in html, "預載函式必須存在"
    assert "PRELOAD_AHEAD" in html, "預載張數常數必須存在"
    assert "imgReady" in html, "圖片載入狀態旗標必須存在"
    assert "submitting" in html, "POST 防重複旗標必須存在"
    assert "function updateSubmitGate()" in html, "守門更新函式必須存在"


def test_render_annotate_html_submit_blocks_when_image_not_ready():
    """submitAnnotation 在 imgReady=false 時應提早 return 並提示。"""
    html = render_annotate_html("007", "/snap.png", (["Mythic"], ["原色"]))
    fn = html.split("async function submitAnnotation()")[1]
    assert "!imgReady" in fn, "imgReady=false 時必須攔截"
    assert "圖片還在載入中" in fn, "必須提示玩家圖片仍在載入"


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


def test_episode_page_keeps_same_label_shots_adjacent():
    """同 label 的多張要相鄰——before/after 對照才看得出來。

    2026-07-26：版面從「一個 label 一個整寬 <section>」改成「一個 tier 一個
    wrap 網格」（18~32 張一集，整寬堆疊要捲很久）。分組的**用途**不變，改由
    排序保證相鄰，所以這裡驗相鄰而不是驗已移除的 section 標籤。
    """
    html = render_episode_html(_detail(), annotations=[])
    body = html[html.index("快照（依標註優先序"):]
    a, b = body.index("a.png"), body.index("b.png")
    between = body[min(a, b):max(a, b)]
    assert between.count("<figure>") == 1, "同 label 的兩張中間不該插入別的圖"
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
    # 只對 reentry 顯示（harvest 沒有等價路徑）。2026-07-26 起「跳過」與「重掃」
    # 「重骰」同進退，用 isReentry 一起開關，不再各自寫 flow !== 'reentry'。
    assert "isReentry" in html and "flow === 'reentry'" in html


# ---------------------------------------------------------------------------
# 2026-07-26 使用者回報「設定要加上說明，說明是用於做甚麼的——回礦後八方位是做什麼的、
# 語料是甚麼、掃描俯仰又是甚麼」。四個欄位先前只有標題，沒有任何解釋。
# ---------------------------------------------------------------------------


class _CalibratedCfg(_Cfg):
    sweep_pitch_step_px = 120
    sweep_pitch_center_back_px = 370


class _UncalibratedCfg(_Cfg):
    sweep_pitch_step_px = 0          # 預設值＝從未校準
    sweep_pitch_center_back_px = 370


def test_every_setting_field_has_an_explanation():
    """四個白名單欄位都要有說明段落，不能只有標題。"""
    html = render_index_html(_CalibratedCfg())
    # 每個欄位標題後面都應該跟著至少一段 hint
    assert html.count('class="hint"') >= 4, "說明段落數量少於欄位數"


def test_explains_what_yaw_sample_corpus_is_for():
    """「語料」是專案內部用語，必須解釋清楚它不是遊戲功能。"""
    html = render_index_html(_CalibratedCfg())
    assert "語料" in html
    assert "45" in html, "八方位相鄰差 45° 是這批圖能自我驗證的理由"
    for word in ("隨機", "素材"):
        assert word in html, f"缺少解釋語料用途的關鍵字：{word}"


def test_explains_reentry_mode_and_target_layer():
    html = render_index_html(_CalibratedCfg())
    assert "傳送板" in html, "回礦模式要講清楚回礦是在做什麼"
    assert "不會驗證" in html, "目標層只是記帳、bot 不驗證，這點必須講明"


# 掃描俯仰 UI 已移除（2026-08-05 俯仰層掃描停用）——
# test_warns_when_sweep_pitch_checkbox_would_be_a_no_op 與
# test_no_warning_once_calibrated 隨之退役。
