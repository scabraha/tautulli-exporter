"""Tests for `steps/meta.py` (Plex update info)."""

from unittest.mock import MagicMock

from tautulli_exporter.steps import MetaStep


def _read(metric):
    return metric._value.get()


def test_update_available_sets_gauge_and_info(metrics):
    client = MagicMock()
    client.get_pms_update.return_value = {
        "update_available": True,
        "version": "1.41.0",
        "release_date": "1700000000",
        "platform": "Linux",
    }
    MetaStep(client, metrics).run()
    assert _read(metrics.plex_update_available) == 1
    assert metrics.plex_update_info._value == {
        "version": "1.41.0",
        "release_date": "1700000000",
        "platform": "Linux",
    }


def test_no_update_clears_to_zero(metrics):
    client = MagicMock()
    client.get_pms_update.return_value = {"update_available": False}
    MetaStep(client, metrics).run()
    assert _read(metrics.plex_update_available) == 0


def test_handles_missing_fields(metrics):
    """Tautulli sometimes returns minimal payloads — don't blow up on them."""
    client = MagicMock()
    client.get_pms_update.return_value = {}
    MetaStep(client, metrics).run()
    assert _read(metrics.plex_update_available) == 0
    assert metrics.plex_update_info._value == {
        "version": "", "release_date": "", "platform": "",
    }
