from unittest.mock import MagicMock

import pytest

from tautulli_exporter.poller import Poller


@pytest.fixture
def fake_client():
    client = MagicMock()
    client.get_server_info.return_value = {
        "pms_version": "1.40.0", "pms_name": "media",
    }
    client.get_libraries.return_value = []
    client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
    }
    return client


@pytest.fixture
def poller(fake_client, metrics, config):
    return Poller(fake_client, metrics, config)


def _read_gauge(metric):
    return metric._value.get()


def _label_values(metric) -> dict:
    return {
        labels: child._value.get()
        for labels, child in metric._metrics.items()
    }


# -- inventory + up -------------------------------------------------------


def test_poll_once_marks_up(poller, metrics):
    poller.poll_once()
    assert _read_gauge(metrics.up) == 1


def test_poll_once_records_plex_version(poller, metrics):
    poller.poll_once()
    assert metrics.plex_version_info._value == {
        "version": "1.40.0", "server_name": "media",
    }


def test_poll_once_marks_down_on_failure(poller, fake_client, metrics):
    fake_client.get_server_info.side_effect = RuntimeError("boom")
    poller.poll_once()
    assert _read_gauge(metrics.up) == 0


def test_poll_failure_records_step_label(poller, fake_client, metrics):
    fake_client.get_libraries.side_effect = RuntimeError("api down")
    poller.poll_once()
    failures = _label_values(metrics.poll_failures)
    assert failures[("libraries",)] == 1


def test_poll_success_sets_self_monitoring_metrics(poller, metrics):
    poller.poll_once()
    assert _read_gauge(metrics.poll_duration) >= 0
    assert _read_gauge(metrics.last_successful_poll) > 0


def test_first_success_log_then_recovery_log(poller, fake_client, caplog):
    import logging
    caplog.set_level(logging.INFO)

    poller.poll_once()
    assert any("First successful poll" in r.message for r in caplog.records)
    caplog.clear()

    fake_client.get_libraries.side_effect = RuntimeError("api down")
    poller.poll_once()
    poller.poll_once()
    fake_client.get_libraries.side_effect = lambda: []
    caplog.clear()
    poller.poll_once()
    assert any("Recovered after" in r.message for r in caplog.records)


# -- libraries ------------------------------------------------------------


def test_libraries_total_and_per_library_items(poller, fake_client, metrics):
    fake_client.get_libraries.return_value = [
        {"section_name": "Movies", "section_type": "movie", "count": 1500},
        {"section_name": "TV", "section_type": "show", "count": 250},
    ]
    poller.poll_once()
    assert _read_gauge(metrics.libraries_total) == 2
    items = _label_values(metrics.library_items)
    assert items[("Movies", "movie")] == 1500
    assert items[("TV", "show")] == 250


def test_libraries_clears_between_polls(poller, fake_client, metrics):
    fake_client.get_libraries.return_value = [
        {"section_name": "Old", "section_type": "movie", "count": 10},
    ]
    poller.poll_once()
    assert ("Old", "movie") in _label_values(metrics.library_items)

    fake_client.get_libraries.return_value = [
        {"section_name": "New", "section_type": "show", "count": 5},
    ]
    poller.poll_once()
    items = _label_values(metrics.library_items)
    assert ("Old", "movie") not in items
    assert items[("New", "show")] == 5


# -- activity -------------------------------------------------------------


def test_session_count_and_decisions(poller, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 3,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [
            {"transcode_decision": "direct play"},
            {"transcode_decision": "transcode"},
            {"transcode_decision": "transcode"},
        ],
    }
    poller.poll_once()
    assert _read_gauge(metrics.session_count) == 3
    decisions = _label_values(metrics.sessions_by_decision)
    assert decisions[("direct play",)] == 1
    assert decisions[("copy",)] == 0
    assert decisions[("transcode",)] == 2


def test_bandwidth_converted_from_kbps_to_bytes(poller, fake_client, metrics):
    """Tautulli reports kbps; we expose bytes/s. 8000 kbps -> 1_000_000 bytes/s."""
    fake_client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 8000, "lan_bandwidth": 6000, "wan_bandwidth": 2000,
    }
    poller.poll_once()
    bw = _label_values(metrics.session_bandwidth_bytes)
    assert bw[("total",)] == 8000 * 1000 // 8
    assert bw[("lan",)] == 6000 * 1000 // 8
    assert bw[("wan",)] == 2000 * 1000 // 8


def test_session_info_labels_and_bandwidth(poller, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "player": "Roku", "platform": "tv",
            "quality_profile": "Original", "full_title": "Inception",
            "transcode_decision": "direct play", "ip_address": "192.168.1.10",
            "bandwidth": 16000,
        }],
    }
    poller.poll_once()
    info = _label_values(metrics.session_info)
    expected_labels = ("alice", "Roku", "tv", "Original", "Inception",
                       "direct play", "192.168.1.10")
    assert info[expected_labels] == 16000 * 1000 // 8


def test_session_info_clears_between_polls(poller, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"friendly_name": "alice", "full_title": "Inception",
                      "bandwidth": 0}],
    }
    poller.poll_once()
    assert _label_values(metrics.session_info)

    fake_client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
    }
    poller.poll_once()
    assert _label_values(metrics.session_info) == {}


def test_session_info_uses_unknown_for_missing_fields(poller, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{}],
    }
    poller.poll_once()
    info = _label_values(metrics.session_info)
    assert (("unknown",) * 6 + ("",)) in info


# -- session geo ----------------------------------------------------------


def test_session_geo_emitted_when_geoip_resolves(fake_client, metrics, config):
    geoip = MagicMock()
    geoip.lookup.return_value = {
        "city": "Seattle", "region": "WA", "country": "US",
        "latitude": 47.6, "longitude": -122.3,
    }
    poller = Poller(fake_client, metrics, config, geoip=geoip)
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "full_title": "Inception",
            "transcode_decision": "direct play", "ip_address": "8.8.8.8",
        }],
    }
    poller.poll_once()

    geo = _label_values(metrics.session_geo)
    assert geo[(
        "alice", "Inception", "direct play",
        "Seattle", "WA", "US", "47.6", "-122.3",
    )] == 1


def test_session_geo_records_geoip_lookup_results(fake_client, metrics, config):
    geoip = MagicMock()
    geoip.lookup.side_effect = lambda ip: (
        {"city": "S", "region": "", "country": "US",
         "latitude": 1.0, "longitude": 2.0}
        if ip == "8.8.8.8" else None
    )
    poller = Poller(fake_client, metrics, config, geoip=geoip)
    fake_client.get_activity.return_value = {
        "stream_count": 2,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [
            {"ip_address": "8.8.8.8", "friendly_name": "a"},
            {"ip_address": "1.1.1.1", "friendly_name": "b"},
        ],
    }
    poller.poll_once()
    lookups = _label_values(metrics.geoip_lookups)
    assert lookups[("hit",)] == 1
    assert lookups[("miss",)] == 1


def test_session_geo_skipped_when_no_geoip(poller, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"ip_address": "8.8.8.8", "friendly_name": "a"}],
    }
    poller.poll_once()
    assert _label_values(metrics.session_geo) == {}


def test_session_geo_skips_sessions_without_ip(fake_client, metrics, config):
    geoip = MagicMock()
    poller = Poller(fake_client, metrics, config, geoip=geoip)
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"friendly_name": "a"}],
    }
    poller.poll_once()
    geoip.lookup.assert_not_called()


def test_session_geo_clears_between_polls(fake_client, metrics, config):
    geoip = MagicMock()
    geoip.lookup.return_value = {
        "city": "S", "region": "", "country": "US",
        "latitude": 1.0, "longitude": 2.0,
    }
    poller = Poller(fake_client, metrics, config, geoip=geoip)
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"ip_address": "8.8.8.8", "friendly_name": "a",
                      "full_title": "x", "transcode_decision": "direct play"}],
    }
    poller.poll_once()
    assert _label_values(metrics.session_geo)

    fake_client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
    }
    poller.poll_once()
    assert _label_values(metrics.session_geo) == {}


# -- shutdown -------------------------------------------------------------


def test_run_forever_stops_on_event(poller, fake_client):
    import threading
    stop = threading.Event()

    def stop_after_first(*args, **kwargs):
        stop.set()
        return {"stream_count": 0, "sessions": [],
                "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0}

    fake_client.get_activity.side_effect = stop_after_first
    poller.run_forever(stop)
    assert stop.is_set()
