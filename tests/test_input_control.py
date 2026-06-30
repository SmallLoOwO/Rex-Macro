"""Tests for miningbot.input_control safety properties."""
from miningbot import input_control as ic


def test_hold_key_always_releases(monkeypatch):
    """hold_key must pair keyDown with keyUp — a held movement key can never stay down."""
    calls = []
    monkeypatch.setattr(ic.pydirectinput, "keyDown", lambda k: calls.append(("down", k)))
    monkeypatch.setattr(ic.pydirectinput, "keyUp", lambda k: calls.append(("up", k)))
    monkeypatch.setattr(ic.time, "sleep", lambda *_: None)

    ic.hold_key("d", 0.3)

    # (a) keyDown called exactly once with "d"
    down_calls = [c for c in calls if c[0] == "down"]
    assert len(down_calls) == 1, f"Expected 1 keyDown, got {down_calls}"
    assert down_calls[0] == ("down", "d")

    # (b) keyUp called exactly once with "d"
    up_calls = [c for c in calls if c[0] == "up"]
    assert len(up_calls) == 1, f"Expected 1 keyUp, got {up_calls}"
    assert up_calls[0] == ("up", "d")

    # (c) keyDown happens before keyUp in recorded order
    assert calls == [("down", "d"), ("up", "d")], f"Wrong call order: {calls}"
