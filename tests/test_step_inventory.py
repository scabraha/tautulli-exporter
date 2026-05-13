"""Tests for `steps/inventory.py`."""

from unittest.mock import MagicMock

import pytest

from tautulli_exporter.steps import InventoryStep


@pytest.fixture
def fake_client():
    client = MagicMock()
    client.get_libraries_table.return_value = []
    client.get_users_table.return_value = []
    client.get_users.return_value = []
    client.get_server_info.return_value = {
        "pms_version": "1.40.0", "pms_name": "media",
    }
    return client


@pytest.fixture
def step(fake_client, metrics):
    return InventoryStep(fake_client, metrics)


def _read(metric):
    return metric._value.get()


def _labels(metric) -> dict:
    return {labels: child._value.get() for labels, child in metric._metrics.items()}


# -- libraries -----------------------------------------------------------


def test_libraries_total_and_per_library_metrics(step, fake_client, metrics):
    fake_client.get_libraries_table.return_value = [
        {
            "section_name": "Movies", "section_type": "movie",
            "count": 1500, "parent_count": 0, "child_count": 0,
            "plays": 750, "duration": 360000, "last_accessed": 1700000000,
            "is_active": 1,
        },
        {
            "section_name": "TV", "section_type": "show",
            "count": 200, "parent_count": 700, "child_count": 8000,
            "plays": 4200, "duration": 1800000, "last_accessed": 1700001234,
            "is_active": 1,
        },
    ]
    step.run()

    assert _read(metrics.libraries_total) == 2

    items = _labels(metrics.library_items)
    assert items[("Movies", "movie")] == 1500
    assert items[("TV", "show")] == 200

    assert _labels(metrics.library_seasons)[("TV", "show")] == 700
    assert _labels(metrics.library_episodes)[("TV", "show")] == 8000
    assert _labels(metrics.library_plays)[("TV", "show")] == 4200
    assert _labels(metrics.library_play_duration_seconds)[("TV", "show")] == 1800000
    assert _labels(metrics.library_last_accessed_timestamp_seconds)[("TV", "show")] \
        == 1700001234
    assert _labels(metrics.library_active)[("TV", "show")] == 1


def test_inactive_library_reports_zero(step, fake_client, metrics):
    fake_client.get_libraries_table.return_value = [{
        "section_name": "Old", "section_type": "movie",
        "count": 0, "is_active": 0,
    }]
    step.run()
    assert _labels(metrics.library_active)[("Old", "movie")] == 0


def test_libraries_clear_between_polls(step, fake_client, metrics):
    fake_client.get_libraries_table.return_value = [
        {"section_name": "Old", "section_type": "movie", "count": 10, "is_active": 1},
    ]
    step.run()
    assert ("Old", "movie") in _labels(metrics.library_items)

    fake_client.get_libraries_table.return_value = [
        {"section_name": "New", "section_type": "show", "count": 5, "is_active": 1},
    ]
    step.run()
    items = _labels(metrics.library_items)
    assert ("Old", "movie") not in items
    assert items[("New", "show")] == 5


# -- library size opt-in -------------------------------------------------


def test_library_size_skipped_when_disabled(fake_client, metrics):
    fake_client.get_libraries_table.return_value = [
        {"section_name": "Movies", "section_type": "movie",
         "section_id": 1, "count": 10, "is_active": 1},
    ]
    InventoryStep(fake_client, metrics, library_size_enabled=False).run()
    fake_client.get_library_media_info.assert_not_called()
    assert _labels(metrics.library_size_bytes) == {}


def test_library_size_emitted_when_enabled(fake_client, metrics):
    fake_client.get_libraries_table.return_value = [
        {"section_name": "Movies", "section_type": "movie",
         "section_id": 1, "count": 10, "is_active": 1},
    ]
    fake_client.get_library_media_info.return_value = {"total_file_size": 7_000_000_000}
    InventoryStep(fake_client, metrics, library_size_enabled=True).run()
    assert _labels(metrics.library_size_bytes)[("Movies", "movie")] == 7_000_000_000


def test_library_size_failure_does_not_break_inventory(fake_client, metrics, caplog):
    """One library's media_info hiccup shouldn't take inventory down."""
    import logging
    caplog.set_level(logging.WARNING)
    fake_client.get_libraries_table.return_value = [
        {"section_name": "Bad", "section_type": "movie",
         "section_id": 1, "count": 1, "is_active": 1},
        {"section_name": "Good", "section_type": "movie",
         "section_id": 2, "count": 1, "is_active": 1},
    ]
    fake_client.get_library_media_info.side_effect = [
        RuntimeError("media_info exploded"),
        {"total_file_size": 42},
    ]
    InventoryStep(fake_client, metrics, library_size_enabled=True).run()
    sizes = _labels(metrics.library_size_bytes)
    assert sizes.get(("Bad", "movie")) is None
    assert sizes[("Good", "movie")] == 42
    assert any("library_size lookup failed" in r.message for r in caplog.records)


# -- users ---------------------------------------------------------------


def test_user_aggregates(step, fake_client, metrics):
    fake_client.get_users.return_value = [
        {"user_id": 1, "is_active": 1, "is_home_user": 1},
        {"user_id": 2, "is_active": 1, "is_home_user": 0},
        {"user_id": 3, "is_active": 0, "is_home_user": 0},
    ]
    fake_client.get_users_table.return_value = []
    step.run()
    assert _read(metrics.users_total) == 3
    assert _read(metrics.users_active) == 2
    assert _read(metrics.users_home) == 1


def test_per_user_metrics(step, fake_client, metrics):
    fake_client.get_users_table.return_value = [
        {"friendly_name": "alice", "plays": 50, "duration": 12345,
         "last_seen": 1700000000},
        {"friendly_name": "bob", "plays": 5, "duration": 100, "last_seen": 0},
    ]
    step.run()

    plays = _labels(metrics.user_plays)
    assert plays[("alice",)] == 50
    assert plays[("bob",)] == 5

    durations = _labels(metrics.user_play_duration_seconds)
    assert durations[("alice",)] == 12345

    last_seen = _labels(metrics.user_last_seen_timestamp_seconds)
    assert last_seen[("alice",)] == 1700000000
    # bob has last_seen=0 (never seen) — we deliberately don't emit a
    # bogus epoch-zero timestamp series for those users.
    assert ("bob",) not in last_seen


def test_users_clear_between_polls(step, fake_client, metrics):
    fake_client.get_users_table.return_value = [
        {"friendly_name": "alice", "plays": 50, "duration": 1, "last_seen": 100},
    ]
    step.run()
    assert ("alice",) in _labels(metrics.user_plays)

    fake_client.get_users_table.return_value = [
        {"friendly_name": "bob", "plays": 1, "duration": 1, "last_seen": 200},
    ]
    step.run()
    plays = _labels(metrics.user_plays)
    assert ("alice",) not in plays
    assert plays[("bob",)] == 1


# -- version -------------------------------------------------------------


def test_plex_version_info_set(step, fake_client, metrics):
    step.run()
    assert metrics.plex_version_info._value == {
        "version": "1.40.0", "server_name": "media",
    }
