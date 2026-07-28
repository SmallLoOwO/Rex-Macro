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

MAX_CLICKS = cfg.chat_open_max_retries + 1   # 比照 main._ensure_chat_open（H063 後＝1）
MAX_READS = 3


def _load(name):
    # cv2.imread 在 Windows 吃不了非 ASCII 路徑（專案資料夾是中文名）→ fromfile+imdecode
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def _state(icon):
    """一律走 config 的現行三個門檻，測試不重寫數值（改門檻時測試跟著走）。"""
    return vision.chat_icon_state(
        icon, cfg.chat_icon_probe,
        cfg.chat_icon_open_min_gray, cfg.chat_icon_closed_max_gray,
        cfg.chat_icon_closed_min_gray)


# ---- 1. fixture 分類（規格第 3 節表格） ----

@pytest.mark.parametrize("name, expected", [
    ("h047_icon_open_solid.png", "open"),
    ("h047_icon_closed_hollow.png", "closed"),
    ("h047_icon_closed_hollow_badge11.png", "closed"),
])
def test_chat_icon_state_classifies_fixture(name, expected):
    icon = _load(name)
    state = _state(icon)
    assert state == expected


def test_chat_icon_probe_means_bracket_the_gap():
    """fixture 完整性 sanity：實測開 239／關 83（規格第 3 節表格），確認兩側夾方向沒反。

    關值同時要**高於** `chat_icon_closed_min_gray`（H063 下界）——真的關著的圖示不能
    掉進「太暗＝沒讀到」那一格，否則檢查永遠不敢點開。
    """
    open_mean = vision.chat_icon_probe_mean(
        _load("h047_icon_open_solid.png"), cfg.chat_icon_probe)
    closed_mean = vision.chat_icon_probe_mean(
        _load("h047_icon_closed_hollow.png"), cfg.chat_icon_probe)
    badge_mean = vision.chat_icon_probe_mean(
        _load("h047_icon_closed_hollow_badge11.png"), cfg.chat_icon_probe)
    assert open_mean >= 230
    assert cfg.chat_icon_closed_min_gray < closed_mean <= 95
    assert cfg.chat_icon_closed_min_gray < badge_mean <= 95


# ---- 2. 合成邊界（安全方向：白閃判開、太暗＝沒讀到圖示、只有實測關值區間才判關） ----

@pytest.mark.parametrize("gray_value, expected", [
    (255, "open"),      # 全白畫面（重置白閃）→ 判開＝不點，方向安全
    (150, "unknown"),   # 關上界與開下界之間 → 呼叫端不得點擊
    (85, "closed"),     # 實測關值區間（81..94）
    (41, "unknown"),    # H063 實機值：補丁被暗色浮層蓋住，不是「關」
    (0, "unknown"),     # 全黑（圖示整個沒照到）→ 同上，絕不點擊
])
def test_chat_icon_state_synthetic_boundaries(gray_value, expected):
    icon = np.full((40, 40, 3), gray_value, dtype=np.uint8)
    assert _state(icon) == expected


def test_chat_icon_state_dark_patch_is_not_closed_h063():
    """H063 兩側夾：實機 41.0（三幀分毫不差＝靜態暗色浮層）不得判 'closed'。

    舊碼 `mean <= closed_max_gray(130)` 把它當關 → 對看不見的圖示連點 toggle →
    奇數次點擊把**開著的**聊天框關掉（2026-07-28 14:09 實機）。太暗＝沒讀到＝unknown，
    而 unknown 在 plan_chat_open_action 任何情況下都不會回 'click'。
    """
    dark = np.full((40, 40, 3), 41, dtype=np.uint8)
    assert _state(dark) == "unknown"
    for clicks in (0, 1, MAX_CLICKS):
        assert roblox_menu.plan_chat_open_action(
            _state(dark), clicks, 0, MAX_CLICKS, MAX_READS) != "click"


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


def test_configured_budget_allows_exactly_one_click_h063():
    """實機額度（config）下，判關最多點一次就 give_up——奇數次 toggle 才是破壞性的。

    每一次點擊都是一次 toggle：讀值若本身是錯的（H063 的 41.0），連點 3 次剛好把
    開著的聊天框關掉。實機 5 場「點了沒反應」的重試 0 次救回，成功場一律第一次就開。
    """
    budget = cfg.chat_open_max_retries + 1
    assert budget == 1
    assert roblox_menu.plan_chat_open_action(
        "closed", 0, 0, budget, MAX_READS) == "click"
    assert roblox_menu.plan_chat_open_action(
        "closed", 1, 0, budget, MAX_READS) == "give_up"


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
