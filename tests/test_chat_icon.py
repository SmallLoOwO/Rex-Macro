"""聊天圖示開關判定（H047）：泡泡實心/空心兩側夾 gray mean＋toggle 安全動作規劃。

設計：docs/superpowers/specs/2026-07-18-chat-open-icon-check-design.md。
背景：舊版靠輸入列 placeholder OCR 判斷聊天框開關，但聊天框開著且久無新訊息會被
遊戲自動隱藏、placeholder 隨之消失 → 假陰性「關閉」→ 對已開啟的聊天框連點 toggle
圖示，反而關掉（2026-07-17／07-18 兩場實機事故）。改用左上聊天圖示外觀（開＝實心
白泡泡、關＝空心白邊，任何狀態都看得到，不像輸入列會被自動隱藏）＋「unknown 絕不
點擊」的安全方向（誤判開頂多維持現狀；誤判關點下去才會把開著的聊天框關掉）。
"""
import os
import re
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import roblox_menu, vision  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "chat_icon")
ROOT = Path(__file__).resolve().parents[1]

MAX_CLICKS = 3   # 比照 main._ensure_chat_open：chat_open_max_retries(2) + 1
MAX_READS = 3


def _load(name):
    # cv2.imread 在 Windows 吃不了非 ASCII 路徑（專案資料夾是中文名）→ fromfile+imdecode
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


# ---- 1. fixture 分類（規格第 3 節表格） ----

@pytest.mark.parametrize("name, expected", [
    ("h047_icon_open_solid.png", "open"),
    ("h047_icon_closed_hollow.png", "closed"),
    ("h047_icon_closed_hollow_badge11.png", "closed"),
])
def test_chat_icon_state_classifies_fixture(name, expected):
    icon = _load(name)
    state = vision.chat_icon_state(
        icon, cfg.chat_icon_probe,
        cfg.chat_icon_open_min_gray, cfg.chat_icon_closed_max_gray)
    assert state == expected


def test_chat_icon_probe_means_bracket_the_gap():
    """fixture 完整性 sanity：實測開 239／關 83（規格第 3 節表格），確認兩側夾方向沒反。"""
    open_mean = vision.chat_icon_probe_mean(
        _load("h047_icon_open_solid.png"), cfg.chat_icon_probe)
    closed_mean = vision.chat_icon_probe_mean(
        _load("h047_icon_closed_hollow.png"), cfg.chat_icon_probe)
    badge_mean = vision.chat_icon_probe_mean(
        _load("h047_icon_closed_hollow_badge11.png"), cfg.chat_icon_probe)
    assert open_mean >= 230
    assert closed_mean <= 95
    assert badge_mean <= 95


# ---- 2. 合成邊界（安全方向：白閃判開、黑屏判關、中間 unknown 不可點擊） ----

@pytest.mark.parametrize("gray_value, expected", [
    (255, "open"),      # 全白畫面（重置白閃）→ 判開＝不點，方向安全
    (150, "unknown"),   # 兩側夾中間 → 呼叫端不得點擊
    (0, "closed"),      # 黑屏 → 判關（點擊無 UI 可點、無害，記錄行為即可）
])
def test_chat_icon_state_synthetic_boundaries(gray_value, expected):
    icon = np.full((40, 40, 3), gray_value, dtype=np.uint8)
    state = vision.chat_icon_state(
        icon, cfg.chat_icon_probe,
        cfg.chat_icon_open_min_gray, cfg.chat_icon_closed_max_gray)
    assert state == expected


# ---- 3. plan_chat_open_action 全分支（規格第 4.3 節六個分支） ----

def test_plan_open_state_is_always_done_regardless_of_counts():
    for clicks in (0, 1, 2, 5):
        for reads in (0, 1, 5):
            assert roblox_menu.plan_chat_open_action(
                "open", clicks, reads, MAX_CLICKS, MAX_READS) == "done"


def test_plan_closed_state_clicks_within_budget():
    for clicks in range(MAX_CLICKS):
        assert roblox_menu.plan_chat_open_action(
            "closed", clicks, 0, MAX_CLICKS, MAX_READS) == "click"


def test_plan_closed_state_budget_exhausted_gives_up():
    assert roblox_menu.plan_chat_open_action(
        "closed", MAX_CLICKS, 0, MAX_CLICKS, MAX_READS) == "give_up"


def test_plan_unknown_state_rereads_within_budget():
    for reads in range(MAX_READS):
        assert roblox_menu.plan_chat_open_action(
            "unknown", 0, reads, MAX_CLICKS, MAX_READS) == "reread"


def test_plan_unknown_state_budget_exhausted_gives_up():
    assert roblox_menu.plan_chat_open_action(
        "unknown", 0, MAX_READS, MAX_CLICKS, MAX_READS) == "give_up"


def test_plan_unrecognized_state_gives_up_defensively():
    assert roblox_menu.plan_chat_open_action(
        "bogus-state", 0, 0, MAX_CLICKS, MAX_READS) == "give_up"


def test_plan_unknown_state_never_returns_click_regardless_of_clicks_done():
    """toggle 安全核心：unknown 絕不能導致點擊，不管 clicks_done 多少——

    誤判開＝不點＝最多維持現狀；誤判關點下去才會把開著的聊天框關掉，
    所以只在明確判「關」時才可以點擊。
    """
    for clicks in (0, 1, 2, MAX_CLICKS, MAX_CLICKS + 5):
        result = roblox_menu.plan_chat_open_action(
            "unknown", clicks, 0, MAX_CLICKS, MAX_READS)
        assert result != "click"
        assert result == "reread"


# ---- 4. 舊信號退役：chat_input_region/chat_input_phrases 全 repo（miningbot/、tests/）無殘留引用 ----

_RETIRED_PATTERN = re.compile(r"chat_input_(?:region|phrases)")


def test_chat_input_region_and_phrases_have_no_remaining_references():
    hits = []
    for base in (ROOT / "miningbot", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            if _RETIRED_PATTERN.search(text):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == [], f"chat_input_region/chat_input_phrases 仍被引用：{hits}"
