"""P4 即時介入面板整合測試。

web_pending → main.py 整合點（manual_survey / reentry click）需要 fake bot 與
大量 monkeypatch 才能有意義地跑；本檔先放 skip skeleton，留 P5 或實機驗收補回。

會被執行的 web pipeline 整合測試（不靠 main.py）放 Task 7 補上。
"""
import pytest


def test_main_harvest_manual_survey_consumes_web_reply():
    """manual_survey 進入時應檢查 web_pending，若有玩家 reply 直接走 fire+verify。

    fake bot 需模擬：_web_pending 在線、_web_fallback.is_fallback()=False、
    capture.grab() 回固定幀、_send_web_intervention_event / _focus_roblox no-op、
    _await_web_pointer_reply 回 {x, y}、_execute_remote_fire_from_web stub 回 (True, ...)。
    斷言：未進入既有 Discord 八方位流程（notify.send_images_message 不被呼叫）。
    """
    pytest.skip("main.py manual_survey 整合需 fake bot；P5 或實機驗收補")


def test_main_execute_remote_fire_short_circuits_on_web_reply():
    """_execute_remote_fire_from_web 收到 (x, y) 應直接呼叫 _aim_fire_and_verify。

    fake bot 需模擬：_wait_for_d3_cooldown 回 (True, "")、_focus_roblox 回 True、
    _mine_resetting=False、capture.grab / capture.crop 回固定幀、
    _aim_fire_and_verify stub 記錄被呼叫的 pos+deadline+chat_base_crop。
    斷言：pos == (x, y)；未呼叫 _detect_core_in_cell / _refind_tracker_near。
    """
    pytest.skip("main.py _execute_remote_fire 整合需 fake bot；P5 或實機驗收補")


def test_main_reentry_consumes_web_click_reply():
    """回礦 _rr_open_episode 開場鏈全閘通過後應先檢查 web_pending，若有玩家 reply
    直接走 _rr_click_from_web。

    fake bot 需模擬：_web_pending 在線、_web_fallback.is_fallback()=False、
    capture.grab() 回固定幀、_send_web_intervention_event / _focus_roblox no-op、
    _await_web_pointer_reply 回 {x, y, attempt_id}、_rr_click_from_web stub 記錄
    被呼叫的 (x, y)。
    斷言：未進入既有 Discord 八方位流程（_rr_sweep_and_send 不被呼叫、未貼 embed）。
    """
    pytest.skip("main.py reentry click 整合需 fake bot；P5 或實機驗收補")
