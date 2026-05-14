"""Tests for `steps/status.py` (Plex reachability gauge)."""

from unittest.mock import MagicMock

import requests

from tautulli_exporter.client import TautulliError
from tautulli_exporter.steps import StatusStep


def _read(metric):
    return metric._value.get()


def test_reachable_when_payload_says_connected(metrics):
    client = MagicMock()
    client.get_server_status.return_value = {"connected": True}
    StatusStep(client, metrics).run()
    assert _read(metrics.plex_reachable) == 1


def test_unreachable_when_payload_says_not_connected(metrics):
    client = MagicMock()
    client.get_server_status.return_value = {"connected": False}
    StatusStep(client, metrics).run()
    assert _read(metrics.plex_reachable) == 0


def test_assumes_reachable_when_field_absent(metrics):
    """Older Tautullis or schema drift shouldn't false-alarm to 0."""
    client = MagicMock()
    client.get_server_status.return_value = {}
    StatusStep(client, metrics).run()
    assert _read(metrics.plex_reachable) == 1


def test_tautulli_error_marks_unreachable(metrics):
    client = MagicMock()
    client.get_server_status.side_effect = TautulliError("boom")
    StatusStep(client, metrics).run()
    assert _read(metrics.plex_reachable) == 0


def test_http_error_marks_unreachable(metrics):
    client = MagicMock()
    client.get_server_status.side_effect = requests.HTTPError("503")
    StatusStep(client, metrics).run()
    assert _read(metrics.plex_reachable) == 0


def test_connection_error_marks_unreachable(metrics):
    client = MagicMock()
    client.get_server_status.side_effect = requests.ConnectionError("refused")
    StatusStep(client, metrics).run()
    assert _read(metrics.plex_reachable) == 0


def test_does_not_propagate_request_errors(metrics):
    """The whole point of swallowing is so the activity tier still completes."""
    client = MagicMock()
    client.get_server_status.side_effect = TautulliError("boom")
    StatusStep(client, metrics).run()  # must not raise


# -- plex server start timestamp -----------------------------------------


def test_start_timestamp_zero_before_any_observation(metrics):
    """Default Gauge value sentinels 'no observation yet' for dashboards."""
    assert _read(metrics.plex_server_start_timestamp_seconds) == 0


def test_start_timestamp_set_on_first_reachable_observation(metrics):
    client = MagicMock()
    client.get_server_status.return_value = {"connected": True}
    StatusStep(client, metrics, wall_clock=lambda: 1700000000.0).run()
    assert _read(metrics.plex_server_start_timestamp_seconds) == 1700000000.0


def test_start_timestamp_unchanged_while_plex_stays_up(metrics):
    """Steady-state polls must not re-anchor the timestamp."""
    client = MagicMock()
    client.get_server_status.return_value = {"connected": True}
    times = iter([1000.0, 2000.0, 3000.0])
    step = StatusStep(client, metrics, wall_clock=lambda: next(times))

    step.run()
    step.run()
    step.run()

    assert _read(metrics.plex_server_start_timestamp_seconds) == 1000.0


def test_start_timestamp_updated_on_down_to_up_transition(metrics):
    client = MagicMock()
    # wall_clock fires only on transitions to "reachable" — the middle
    # outage poll skips it, so we model one anchor per transition.
    times = iter([1000.0, 3000.0])
    step = StatusStep(client, metrics, wall_clock=lambda: next(times))

    client.get_server_status.return_value = {"connected": True}
    step.run()
    assert _read(metrics.plex_server_start_timestamp_seconds) == 1000.0

    client.get_server_status.return_value = {"connected": False}
    step.run()
    # Outage doesn't reset the previous anchor — dashboards keep the
    # last known-good value to compute "uptime up until the outage".
    assert _read(metrics.plex_server_start_timestamp_seconds) == 1000.0

    client.get_server_status.return_value = {"connected": True}
    step.run()
    assert _read(metrics.plex_server_start_timestamp_seconds) == 3000.0


def test_start_timestamp_not_touched_when_tautulli_unreachable(metrics):
    """Tautulli flap should not be misread as a Plex restart."""
    client = MagicMock()
    times = iter([1000.0, 2000.0])
    step = StatusStep(client, metrics, wall_clock=lambda: next(times))

    client.get_server_status.return_value = {"connected": True}
    step.run()
    assert _read(metrics.plex_server_start_timestamp_seconds) == 1000.0

    # Tautulli outage: connection refused. plex_reachable drops to 0,
    # but the start timestamp stays put and the next successful poll
    # must NOT treat the recovery as a Plex restart.
    client.get_server_status.side_effect = requests.ConnectionError("refused")
    step.run()
    assert _read(metrics.plex_reachable) == 0
    assert _read(metrics.plex_server_start_timestamp_seconds) == 1000.0

    client.get_server_status.side_effect = None
    client.get_server_status.return_value = {"connected": True}
    step.run()
    # Anchor unchanged: we don't actually know Plex restarted.
    assert _read(metrics.plex_server_start_timestamp_seconds) == 1000.0


def test_start_timestamp_recorded_when_first_observation_is_unreachable(metrics):
    """Down → up transition still anchors even without a prior up observation."""
    client = MagicMock()
    # Only the up-poll consumes the wall clock; the unreachable poll
    # never reads it, so we don't need to model two timestamps here.
    step = StatusStep(client, metrics, wall_clock=lambda: 2000.0)

    client.get_server_status.return_value = {"connected": False}
    step.run()
    assert _read(metrics.plex_server_start_timestamp_seconds) == 0

    client.get_server_status.return_value = {"connected": True}
    step.run()
    assert _read(metrics.plex_server_start_timestamp_seconds) == 2000.0
