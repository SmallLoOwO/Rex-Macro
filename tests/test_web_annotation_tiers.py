"""快照標註優先序：關鍵的排最上面（2026-07-26）。

episode 詳細頁先前按 label **字母排序**，於是要標的圖散落整頁。改成按
「這張圖對改善偵測有多少價值」排——依據是使用者的實機判斷：**chill 標語、
背包、聊天框都已經是成熟的 OCR 路徑**，真正沒解決的是**八方位掃描**與
**礦物／追蹤框偵測**。

label 詞彙取自實機 snapshot_index.jsonl（2026-07-26 全庫統計）。
"""
import pytest

from miningbot.web_history import (
    annotation_tier, ANNOTATION_TIER_LABELS,
)
from miningbot.web_static import render_episode_html


# ── tier 分類 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label", [
    "113_sweep_empty_dir0",              # 八方位掃描全空——最需要標的一類
    "114_sweep_seen_once_dir3_2_1",      # 單幀出現、沒穩定下來
    "113_aim_overlay_dir2_mid_rejected",  # 追蹤框被拒
    "101_aim_fail_scene",                # 開火後場景沒變
    "114_needs_human_1_2",
    "108_manual_survey_dir5",
    "109_d3_miss_2",
    "109_d3_gone_unconfirmed",
])
def test_unsolved_detection_is_tier0(label):
    assert annotation_tier(label) == 0, f"{label} 應該排在最前面"


@pytest.mark.parametrize("label", [
    "113_boost_count_unreadable",
    "112_d4_unknown",
    "chat_open_fail",
])
def test_known_failures_are_tier1(label):
    assert annotation_tier(label) == 1


@pytest.mark.parametrize("label", [
    "113_sweep_confirmed_dir4_1_2",
    "113_sweep_accepted_dir4_1_2",
    "113_aim_overlay_dir4_mid_accepted",
    "113_aim_overlay_dir4_mid_fired",
    "101_aim_fire_960x540",
    "109_d3_fire_dir2_3x4",
    "110_harvest_success",
])
def test_hit_control_group_is_tier2(label):
    assert annotation_tier(label) == 2


@pytest.mark.parametrize("label", [
    "113_chill_closeup",                 # chill 標語＝成熟 OCR
    "spawn_chill",
    "113_giveup_before_chat",            # 聊天框＝成熟 OCR
    "113_giveup_after_backpack",         # 背包＝成熟 OCR
    "113_rare_found",
    "109_d3_chat_before",
    "reentry_ep23_dir5",                 # H059 yaw 語料（量最大，要壓到最後）
    "112_pitch_ok_before",
    "112_pitch_eaten_after",
    "111_mine_reset",
])
def test_mature_paths_are_last(label):
    assert annotation_tier(label) == 3, f"{label} 是成熟路徑，不該排在前面"


def test_unknown_label_falls_back_to_last_tier():
    """沒見過的 label 不該插隊到待標註區。"""
    assert annotation_tier("something_totally_new") == 3
    assert annotation_tier("") == 3
    assert annotation_tier(None) == 3


def test_tier_labels_cover_every_tier():
    """每個 tier 都要有對應標題，render 端才不會 IndexError。"""
    tiers = {annotation_tier(x) for x in
             ["sweep_empty_dir0", "d4_unknown", "harvest_success", "chill_closeup"]}
    assert tiers == {0, 1, 2, 3}
    assert len(ANNOTATION_TIER_LABELS) == 4


def test_sweep_beats_chat_ordering():
    """核心訴求的最小斷言：八方位掃描必須排在聊天框前面。

    舊的字母排序下 `giveup_after_chat` < `sweep_empty_dir0`，正好相反。
    """
    assert annotation_tier("113_sweep_empty_dir0") < annotation_tier("113_giveup_after_chat")


# ── 詳細頁渲染順序 ─────────────────────────────────────────────────────────

def _detail(labels):
    return {
        "harvest_id": "113", "type": "harvest", "count": len(labels),
        "first_ts": 1000.0, "last_ts": 1000.0 + len(labels),
        "snapshots": [
            {"label": lb, "path": f"C:\\snaps\\{lb}.png", "written_at": 1000.0 + i}
            for i, lb in enumerate(labels)
        ],
    }


def _thumbs_section(html: str) -> str:
    """只取縮圖區——事件時間軸在它上面且**刻意**保持時間順序，不受 tier 影響。

    （不切的話 html.index 會抓到時間軸裡的那一份，量到的是時間順序。）
    """
    marker = "快照（依標註優先序"
    assert marker in html
    return html[html.index(marker):]


def test_episode_page_puts_unsolved_groups_first():
    """實機 113 的真實 label 組合：掃描/瞄準要在聊天/背包之前。"""
    body = _thumbs_section(render_episode_html(_detail([
        "113_chill_closeup",
        "113_giveup_after_backpack",
        "113_sweep_empty_dir0",
        "113_aim_overlay_dir2_mid_rejected",
    ]), []))
    order = [body.index(x) for x in [
        "113_sweep_empty_dir0", "113_aim_overlay_dir2_mid_rejected",
        "113_chill_closeup", "113_giveup_after_backpack"]]
    assert order[0] < order[2] and order[0] < order[3]
    assert order[1] < order[2] and order[1] < order[3]


def test_timeline_stays_chronological():
    """時間軸不該被 tier 重排——它的用途是「這一集依序發生了什麼」。"""
    html = render_episode_html(_detail(
        ["113_chill_closeup", "113_sweep_empty_dir0"]), [])
    timeline = html[html.index("事件時間軸"):html.index("快照（依標註優先序")]
    assert timeline.index("113_chill_closeup") < timeline.index("113_sweep_empty_dir0")


def test_episode_page_shows_tier_headings():
    html = render_episode_html(_detail(
        ["113_sweep_empty_dir0", "113_chill_closeup"]), [])
    assert ANNOTATION_TIER_LABELS[0] in html
    assert ANNOTATION_TIER_LABELS[3] in html


def test_episode_page_heading_appears_once_per_tier():
    """同 tier 多個 label 只出一次標題。"""
    html = render_episode_html(_detail(
        ["113_sweep_empty_dir0", "113_sweep_empty_dir1", "113_sweep_empty_dir2"]), [])
    assert html.count(ANNOTATION_TIER_LABELS[0]) == 1


def test_episode_page_keeps_direction_order_within_tier():
    """同 tier 內按時間排——八個方位要維持 dir0→dir7，不是字母亂序。"""
    labels = [f"113_sweep_empty_dir{i}" for i in range(8)]
    body = _thumbs_section(render_episode_html(_detail(labels), []))
    positions = [body.index(lb) for lb in labels]
    assert positions == sorted(positions)
