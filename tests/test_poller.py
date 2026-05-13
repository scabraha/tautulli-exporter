"""Tests for the tiered scheduler in `poller.py`."""

from unittest.mock import MagicMock

import pytest
import requests

from tautulli_exporter.poller import Tier, TieredPoller


# -- helpers / fixtures ------------------------------------------------


class FakeClock:
    """Deterministic monotonic clock for scheduling tests."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeStep:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0
        self.fail_with: BaseException | None = None

    def run(self) -> None:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def wall_clock():
    return MagicMock(return_value=1_700_000_000.0)


def _read(metric):
    return metric._value.get()


def _labels(metric) -> dict:
    return {labels: child._value.get() for labels, child in metric._metrics.items()}


# -- construction --------------------------------------------------------


def test_requires_at_least_one_tier(metrics):
    with pytest.raises(ValueError, match="at least one tier"):
        TieredPoller(metrics, [])


def test_requires_exactly_one_heartbeat(metrics):
    with pytest.raises(ValueError, match="heartbeat"):
        TieredPoller(metrics, [
            Tier("a", 10, [FakeStep("a")], heartbeat=False),
        ])
    with pytest.raises(ValueError, match="heartbeat"):
        TieredPoller(metrics, [
            Tier("a", 10, [FakeStep("a")], heartbeat=True),
            Tier("b", 10, [FakeStep("b")], heartbeat=True),
        ])


# -- scheduling ----------------------------------------------------------


def test_first_poll_runs_every_tier(metrics, clock, wall_clock):
    a, b, c = FakeStep("a"), FakeStep("b"), FakeStep("c")
    poller = TieredPoller(
        metrics,
        [
            Tier("activity", 10, [a], heartbeat=True),
            Tier("inventory", 100, [b]),
            Tier("meta", 1000, [c]),
        ],
        clock=clock, wall_clock=wall_clock,
    )
    ran = poller.poll_due()
    assert sorted(ran) == ["activity", "inventory", "meta"]
    assert (a.calls, b.calls, c.calls) == (1, 1, 1)


def test_only_due_tiers_run_after_first_cycle(metrics, clock, wall_clock):
    a, b, c = FakeStep("a"), FakeStep("b"), FakeStep("c")
    poller = TieredPoller(
        metrics,
        [
            Tier("activity", 10, [a], heartbeat=True),
            Tier("inventory", 100, [b]),
            Tier("meta", 1000, [c]),
        ],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()  # first cycle: all run
    clock.advance(15)
    ran = poller.poll_due()
    assert ran == ["activity"]   # only the fast one is due
    assert (a.calls, b.calls, c.calls) == (2, 1, 1)


def test_inventory_runs_on_its_own_cadence(metrics, clock, wall_clock):
    a, b = FakeStep("a"), FakeStep("b")
    poller = TieredPoller(
        metrics,
        [
            Tier("activity", 10, [a], heartbeat=True),
            Tier("inventory", 100, [b]),
        ],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()  # both run at t=0
    # Advance enough for the activity tier to fire 10 times before
    # inventory comes due again.
    for _ in range(10):
        clock.advance(10)
        poller.poll_due()
    assert a.calls == 11
    assert b.calls == 2  # initial + once when inventory_interval elapsed


def test_seconds_until_next_returns_min(metrics, clock, wall_clock):
    a, b = FakeStep("a"), FakeStep("b")
    poller = TieredPoller(
        metrics,
        [
            Tier("activity", 10, [a], heartbeat=True),
            Tier("inventory", 100, [b]),
        ],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()  # both run; next deadlines are now+10 and now+100
    assert poller.seconds_until_next() == pytest.approx(10.0)
    clock.advance(5)
    assert poller.seconds_until_next() == pytest.approx(5.0)


# -- failure isolation --------------------------------------------------


def test_step_failure_isolated_to_step_label(metrics, clock, wall_clock):
    good = FakeStep("good")
    bad = FakeStep("bad")
    bad.fail_with = RuntimeError("boom")

    poller = TieredPoller(
        metrics,
        [Tier("activity", 10, [good, bad], heartbeat=True)],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()

    failures = _labels(metrics.poll_failures)
    assert failures[("bad",)] == 1
    assert good.calls == 1  # good ran even though bad failed


def test_failure_in_non_heartbeat_tier_does_not_flip_up(metrics, clock, wall_clock):
    good = FakeStep("activity")
    bad = FakeStep("inventory")
    bad.fail_with = RuntimeError("db down")

    poller = TieredPoller(
        metrics,
        [
            Tier("activity", 10, [good], heartbeat=True),
            Tier("inventory", 100, [bad]),
        ],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()

    assert _read(metrics.up) == 1            # heartbeat tier succeeded
    assert _labels(metrics.poll_failures)[("inventory",)] == 1


def test_heartbeat_failure_marks_down(metrics, clock, wall_clock):
    bad = FakeStep("activity")
    bad.fail_with = RuntimeError("api dead")

    poller = TieredPoller(
        metrics,
        [Tier("activity", 10, [bad], heartbeat=True)],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()
    assert _read(metrics.up) == 0


def test_heartbeat_success_updates_self_metrics(metrics, clock, wall_clock):
    wall_clock.return_value = 1_700_000_500.0
    good = FakeStep("activity")
    poller = TieredPoller(
        metrics,
        [Tier("activity", 10, [good], heartbeat=True)],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()
    assert _read(metrics.up) == 1
    assert _read(metrics.last_successful_poll) == 1_700_000_500.0
    assert _read(metrics.poll_duration) >= 0


# -- recovery / first-success logging -----------------------------------


def test_first_success_log(metrics, clock, wall_clock, caplog):
    import logging
    caplog.set_level(logging.INFO)
    poller = TieredPoller(
        metrics,
        [Tier("activity", 10, [FakeStep("activity")], heartbeat=True)],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()
    assert any("First successful poll" in r.message for r in caplog.records)


def test_recovery_log(metrics, clock, wall_clock, caplog):
    import logging
    caplog.set_level(logging.INFO)

    step = FakeStep("activity")
    poller = TieredPoller(
        metrics,
        [Tier("activity", 10, [step], heartbeat=True)],
        clock=clock, wall_clock=wall_clock,
    )

    # Initial success.
    poller.poll_due()
    caplog.clear()

    # Two failures.
    step.fail_with = RuntimeError("api dead")
    clock.advance(10); poller.poll_due()
    clock.advance(10); poller.poll_due()
    caplog.clear()

    # Recovery.
    step.fail_with = None
    clock.advance(10); poller.poll_due()
    assert any("Recovered after 2" in r.message for r in caplog.records)


def test_http_error_is_logged_concisely(metrics, clock, wall_clock, caplog):
    import logging
    caplog.set_level(logging.ERROR)
    step = FakeStep("activity")
    step.fail_with = requests.HTTPError("403 forbidden")
    poller = TieredPoller(
        metrics,
        [Tier("activity", 10, [step], heartbeat=True)],
        clock=clock, wall_clock=wall_clock,
    )
    poller.poll_due()
    msgs = [r.message for r in caplog.records]
    assert any("403 forbidden" in m for m in msgs)


# -- run_forever shutdown ----------------------------------------------


def test_run_forever_stops_on_event(metrics, clock, wall_clock):
    import threading
    stop = threading.Event()
    step = FakeStep("activity")

    def stop_after_first():
        stop.set()
    step.run = MagicMock(side_effect=stop_after_first)
    step.name = "activity"

    poller = TieredPoller(
        metrics,
        [Tier("activity", 10, [step], heartbeat=True)],
        clock=clock, wall_clock=wall_clock,
    )
    poller.run_forever(stop)
    assert stop.is_set()
