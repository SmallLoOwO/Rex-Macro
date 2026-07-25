"""D2 雷達連續使用（掃描／削洞）的純決策測試（2026-07-25）。

行為對照 D4/D5：效果列徽章**不在**＝冷卻好＝該再按一次。徽章位置會漂移，
所以就緒判定吃的是「逐格 OCR 後的文字 list」而非固定座標的單一字串。
"""
import pytest

from miningbot import discord_commands, harvester, miner


# --- Cave Skim 徽章辨識（與 scan_succeeded 對稱） ---

def test_cave_skim_present_reads_two_line_badge():
    assert harvester.cave_skim_present(["cave\nskim"]) is True
    assert harvester.cave_skim_present(["Cave Skim"]) is True


def test_cave_skim_tolerates_ocr_noise():
    assert harvester.cave_skim_present(["cave skirn"]) is True   # m→rn
    assert harvester.cave_skim_present(["Skim"]) is True


def test_cave_skim_rejects_other_badges():
    """Local／Used 是同一列的鄰居，不可互相誤判。"""
    assert harvester.cave_skim_present([]) is False
    assert harvester.cave_skim_present([""]) is False
    assert harvester.cave_skim_present(["Local"]) is False
    assert harvester.cave_skim_present(["used\na"]) is False


def test_local_and_cave_skim_do_not_cross_match():
    """兩個都是 D2 的雷達徽章、外觀相近——分類必須互斥。"""
    assert harvester.scan_succeeded(["cave\nskim"]) is False
    assert harvester.cave_skim_present(["Local"]) is False
    # 兩格同時在場時各自認得自己那格
    both = ["cave\nskim", "Local"]
    assert harvester.scan_succeeded(both) is True
    assert harvester.cave_skim_present(both) is True


# --- 就緒判定（沿用 D4 的 cooldown_ready 語意） ---

def test_ready_only_when_badge_absent_and_past_grace():
    assert miner.cooldown_ready(False, 10.0, 4.0) is True       # 徽章不在＋過寬限 → 可按
    assert miner.cooldown_ready(True, 10.0, 4.0) is False       # 徽章還在＝冷卻中
    assert miner.cooldown_ready(False, 1.0, 4.0) is False       # 剛按過，等徽章出現


# --- dispatch 優先序：CAVE 先於 SCAN，兩者都先於 D5/D4 ---

def _flags(**kw):
    base = dict(boost_expired=False, activity_event=False, scan_event=False,
                cave_event=False, window_unfocused=False)
    base.update(kw)
    return miner.EventFlags(**base)


def test_dispatch_routes_new_events():
    assert miner.dispatch_event(_flags(cave_event=True)) == "CAVE"
    assert miner.dispatch_event(_flags(scan_event=True)) == "SCAN"


def test_dispatch_priority_cave_over_scan_and_tools():
    assert miner.dispatch_event(_flags(cave_event=True, scan_event=True)) == "CAVE"
    assert miner.dispatch_event(
        _flags(scan_event=True, boost_expired=True, activity_event=True)) == "SCAN"
    # 視窗跑位仍是最高優先——輸入進不了遊戲時按什麼都沒意義
    assert miner.dispatch_event(
        _flags(cave_event=True, window_unfocused=True)) == "REFOCUS"


# --- Discord 開關解析 ---

@pytest.mark.parametrize("word", ["開", "on", "啟用", "1", "true", "ON"])
def test_parse_radar_toggle_on(word):
    assert discord_commands.parse_radar_toggle([word]) is True


@pytest.mark.parametrize("word", ["關", "off", "停用", "0", "false"])
def test_parse_radar_toggle_off(word):
    assert discord_commands.parse_radar_toggle([word]) is False


def test_parse_radar_toggle_query_and_bad():
    assert discord_commands.parse_radar_toggle([]) is None          # 查詢
    assert discord_commands.parse_radar_toggle(["開", "關"]) == "bad"
    assert discord_commands.parse_radar_toggle(["yes"]) == "bad"    # 看不懂不可當預設切換


def test_radar_commands_are_whitelisted():
    for name in ("掃描", "scan", "削洞", "caveskim"):
        cmd = discord_commands.parse_command(name + " 開")
        assert cmd is not None and cmd.name == name
        assert discord_commands.RADAR_COMMAND_KIND[name] in ("scan", "cave")


# --- 採集掃描前等冷卻（使用者指定：等冷卻結束再開始稀有掃描） ---

def test_scan_cooldown_ready_uses_badge_when_ocr_ok():
    """OCR 可用時看徽章：Local 還在＝冷卻中，按下去不會生效。"""
    assert harvester.scan_cooldown_ready(True, 999.0, 34.0, ocr_ok=True) is False
    assert harvester.scan_cooldown_ready(False, 0.0, 34.0, ocr_ok=True) is True


def test_scan_cooldown_ready_falls_back_to_timer_without_ocr():
    """OCR 不可用時徽章讀不到 → 只能靠定時，且不可因 badge_present=False 就誤判就緒。"""
    assert harvester.scan_cooldown_ready(False, 5.0, 34.0, ocr_ok=False) is False
    assert harvester.scan_cooldown_ready(False, 40.0, 34.0, ocr_ok=False) is True
    # 沒有 OCR 時 badge 參數不該有影響力
    assert harvester.scan_cooldown_ready(True, 40.0, 34.0, ocr_ok=False) is True


def test_status_text_describes_wait_not_failure():
    """行為已從『可能白掃』改成『先等冷卻』——狀態文字不可再嚇人說會掃不出框。"""
    s = harvester.format_radar_status(True, False)
    assert "等冷卻" in s
    assert "掃不出框" not in s


# --- 啟用情形文字（啟動訊息／status 共用） ---

def test_format_radar_status_shows_both_switches():
    s = harvester.format_radar_status(False, False)
    assert "掃描" in s and "削洞" in s and "關" in s
    assert "⚠" not in s                                   # 都關著不必警告


def test_format_radar_status_mentions_shared_cooldown_when_scan_on():
    """掃描與採集共用 D2 冷卻，開著時要說明會先等——使用者當初的顧慮，不可省略。"""
    s = harvester.format_radar_status(True, False)
    assert "採集" in s and "冷卻" in s


def test_format_radar_status_flags_ocr_fallback():
    assert "定時後備" in harvester.format_radar_status(False, True, ocr_ok=False)
    assert "定時後備" not in harvester.format_radar_status(False, True, ocr_ok=True)
    # 兩個都關時不必提 OCR（根本不會跑就緒判定）
    assert "定時後備" not in harvester.format_radar_status(False, False, ocr_ok=False)
