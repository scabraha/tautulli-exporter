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
