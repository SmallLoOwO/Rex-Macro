import cv2
import numpy as np

from miningbot import main, remote_aim
from miningbot.main import Bot


class _LogRecorder:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(message % args if args else message)

    def warning(self, message, *args):
        self.records.append(message % args if args else message)


def test_shared_d3_cooldown_starts_immediately_before_hold_click(monkeypatch):
    bot = Bot.__new__(Bot)
    bot._last_d3_fire_at = None
    bot.log_harvest = _LogRecorder()
    now = [100.0]
    actions = []

    monkeypatch.setattr(main.cfg, "d3_cooldown_s", 10.0)
    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(main.time, "sleep", lambda seconds: actions.append(("sleep", seconds)))
    monkeypatch.setattr(main.ic, "key_press", lambda key: actions.append(("key", key)))

    def click(x, y, hold):
        assert bot._last_d3_fire_at == now[0]
        actions.append(("click", x, y, hold))

    monkeypatch.setattr(main.ic, "click_at", click)

    assert bot._fire_d3_at(640, 480) is True
    assert actions == [
        ("key", "2"), ("sleep", 0.15),
        ("key", "3"), ("sleep", 0.3),
        ("click", 640, 480, 0.4), ("sleep", 0.5),
    ]

    now[0] = 109.999
    assert bot._fire_d3_at(640, 480) is False
    assert len(actions) == 6

    now[0] = 110.0
    assert bot._fire_d3_at(640, 480) is True
    assert len(actions) == 12


def test_aim_renderer_matches_candidates_by_exact_snapshot_path(tmp_path, monkeypatch):
    first_path = str(tmp_path / "first.png")
    second_path = str(tmp_path / "second.png")
    black = np.zeros((400, 1000, 3), dtype=np.uint8)
    assert cv2.imwrite(first_path, black)
    assert cv2.imwrite(second_path, black)

    shots = [
        remote_aim.SweepShot("mid", 2, first_path, []),
        remote_aim.SweepShot("mid", 2, second_path, []),
    ]
    candidates = [
        remote_aim.AimCandidate(
            1, "mid", 2, (200, 180), 0.9, "first",
            status="accepted", snapshot_path=first_path),
        remote_aim.AimCandidate(
            2, "mid", 2, (750, 180), 0.8, "second",
            status="fired", snapshot_path=second_path),
    ]
    ctx = remote_aim.AimContext(
        candidates=candidates, shots=shots, pose_net_rotations=0,
        pose_pitch_layer="mid", harvest_id="079", created_at=1.0)
    bot = Bot.__new__(Bot)
    bot.logger = _LogRecorder()
    monkeypatch.setattr(main.cfg, "log_dir", str(tmp_path))
    monkeypatch.setattr(main.cfg, "remote_aim_snapshot_wait_s", 0.1)

    rendered = bot._render_aim_shots(ctx)

    assert len(rendered) == 2
    first_overlay = cv2.imread(first_path.replace(".png", "_aim.png"))
    assert tuple(first_overlay[180, 164]) == (0, 215, 255)
    assert tuple(first_overlay[180, 714]) != (0, 215, 255)
