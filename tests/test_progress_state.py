from __future__ import annotations

from gui.ui.progress_state import EtaEstimator, format_eta_seconds


def test_format_eta_seconds_ranges() -> None:
    assert format_eta_seconds(5) == "~5s"
    assert format_eta_seconds(65) == "~1m 05s"
    assert format_eta_seconds(3665) == "~1h 01m"


def test_eta_hidden_before_threshold() -> None:
    now = [0.0]

    def now_fn() -> float:
        return now[0]

    estimator = EtaEstimator(min_visible_seconds=20.0, now_fn=now_fn)
    now[0] = 10.0
    assert estimator.update(current=20, total=100) is None


def test_eta_visible_after_threshold_with_progress() -> None:
    now = [0.0]

    def now_fn() -> float:
        return now[0]

    estimator = EtaEstimator(min_visible_seconds=20.0, now_fn=now_fn)

    now[0] = 21.0
    assert estimator.update(current=21, total=100) is None

    now[0] = 31.0
    eta = estimator.update(current=31, total=100)
    assert eta is not None
    assert 60.0 <= eta <= 80.0


def test_eta_resets_on_total_change() -> None:
    now = [0.0]

    def now_fn() -> float:
        return now[0]

    estimator = EtaEstimator(min_visible_seconds=0.0, now_fn=now_fn)

    now[0] = 1.0
    estimator.update(current=10, total=100)
    now[0] = 2.0
    assert estimator.update(current=20, total=100) is not None

    now[0] = 3.0
    assert estimator.update(current=10, total=200) is None
