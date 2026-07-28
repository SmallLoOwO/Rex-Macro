"""execute_scan 的 D2 toggle 守門回歸（H065）。

D2(slot 2) 是 toggle（AGENTS.md rule 3、fixtures/slot/README 的警告）：掃描器已裝備時
再按 "2" 會**卸裝**而非重掃。俯仰層轉換時連續兩次 execute_scan（mid 全空→up，中間沒開
D3 換 slot），第二次的 "2" 把掃描器卸下、左鍵點空氣 → 整層沒掃描（harvest 121 up 層
全空即此因）。守門：slot 2 已選中就不按 "2"，只 click 重掃（比照 D1 的 slot_selected）。

這裡只驗控制邏輯（按不按 "2"）；slot_selected 在 d2_region 上的偵測準確度由
test_slot_fixtures.py 的 fixture 兩側夾保證。
"""
import pytest

from miningbot import harvester, capture, vision  # noqa: E402
from miningbot import input_control as ic  # noqa: E402


def _patch_scan_io(monkeypatch, slot2_selected: bool):
    """把掃描的 I/O（截圖／偵測／按鍵／點擊／等待）換成記錄樁。回傳 (presses, clicks)。"""
    monkeypatch.setattr(capture, "grab", lambda *a, **k: None)
    monkeypatch.setattr(vision, "slot_selected", lambda *a, **k: slot2_selected)
    presses, clicks = [], []
    monkeypatch.setattr(ic, "key_press", lambda key: presses.append(key))
    monkeypatch.setattr(ic, "click_at", lambda *a, **k: clicks.append(a))
    monkeypatch.setattr(harvester.time, "sleep", lambda *a, **k: None)
    return presses, clicks


def test_execute_scan_skips_d2_when_scanner_already_equipped(monkeypatch):
    """slot 2 已裝備（綠底）→ 不按 "2"（防 toggle 卸裝），只 click 重掃。"""
    presses, clicks = _patch_scan_io(monkeypatch, slot2_selected=True)
    harvester.execute_scan()
    assert "2" not in presses, "掃描器已裝備卻又按 2 → toggle 卸裝（H065 根因）"
    assert len(clicks) == 1, "已裝備時仍須 click 觸發重掃"


def test_execute_scan_equips_d2_when_scanner_not_equipped(monkeypatch):
    """slot 2 未裝備 → 按 "2" 裝上、再 click 掃描。"""
    presses, clicks = _patch_scan_io(monkeypatch, slot2_selected=False)
    harvester.execute_scan()
    assert "2" in presses
    assert len(clicks) == 1
