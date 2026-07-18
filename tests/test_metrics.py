import pytest

from miningbot.metrics import LatencyTracker


def test_latency_tracker_reports_percentiles_in_milliseconds():
    tracker = LatencyTracker(max_samples=8)
    for milliseconds in (1, 2, 3, 4):
        tracker.observe("capture", milliseconds / 1000)

    summary = tracker.snapshot()["capture"]

    assert summary.count == 4
    assert summary.p50_ms == pytest.approx(2.5)
    assert summary.p95_ms == pytest.approx(3.85)
    assert summary.p99_ms == pytest.approx(3.97)
    assert summary.max_ms == pytest.approx(4.0)


def test_latency_tracker_keeps_only_bounded_recent_samples():
    tracker = LatencyTracker(max_samples=2)
    tracker.observe("loop", 0.001)
    tracker.observe("loop", 0.002)
    tracker.observe("loop", 0.003)

    summary = tracker.snapshot()["loop"]

    assert summary.count == 2
    assert summary.p50_ms == pytest.approx(2.5)


def test_latency_tracker_snapshot_can_reset_window():
    tracker = LatencyTracker(max_samples=2)
    tracker.observe("tick", 0.010)

    assert tracker.snapshot(reset=True)["tick"].count == 1
    assert tracker.snapshot() == {}
