"""Tests for `steps/activity.py`.

Owns: every `tautulli_session_*` metric, sessions_secure, plex bandwidth,
session geo, geoip lookup counter.
"""

from unittest.mock import MagicMock

import pytest

from tautulli_exporter.steps import ActivityStep


@pytest.fixture
def fake_client():
    client = MagicMock()
    client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
    }
    return client


@pytest.fixture
def step(fake_client, metrics):
    return ActivityStep(fake_client, metrics)


def _read(metric):
    return metric._value.get()


def _labels(metric) -> dict:
    return {labels: child._value.get() for labels, child in metric._metrics.items()}


# -- aggregates ---------------------------------------------------------


def test_session_count_and_decisions_seed_all_buckets(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 3,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [
            {"transcode_decision": "direct play"},
            {"transcode_decision": "direct stream"},
            {"transcode_decision": "transcode"},
        ],
    }
    step.run()
    assert _read(metrics.session_count) == 3
    decisions = _labels(metrics.sessions_by_decision)
    assert decisions[("direct play",)] == 1
    assert decisions[("direct stream",)] == 1   # the bug-fix the proposal called out
    assert decisions[("copy",)] == 0
    assert decisions[("transcode",)] == 1


def test_state_breakdown_seeds_standard_states(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 2,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"state": "playing"}, {"state": "paused"}],
    }
    step.run()
    states = _labels(metrics.sessions_by_state)
    assert states[("playing",)] == 1
    assert states[("paused",)] == 1
    assert states[("buffering",)] == 0


def test_location_breakdown_includes_relay(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 2,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"location": "wan"}, {"location": "relay"}],
    }
    step.run()
    locations = _labels(metrics.sessions_by_location)
    assert locations[("relay",)] == 1
    assert locations[("wan",)] == 1
    assert locations[("lan",)] == 0


def test_media_type_breakdown(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 3,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [
            {"media_type": "movie"},
            {"media_type": "episode"},
            {"media_type": "track"},
        ],
    }
    step.run()
    mt = _labels(metrics.sessions_by_media_type)
    assert mt[("movie",)] == 1
    assert mt[("episode",)] == 1
    assert mt[("track",)] == 1
    assert mt[("live",)] == 0
    assert mt[("clip",)] == 0


def test_secure_count(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 3,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"secure": 1}, {"secure": "1"}, {"secure": 0}],
    }
    step.run()
    assert _read(metrics.sessions_secure) == 2


def test_bandwidth_kbps_to_bytes(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 8000, "lan_bandwidth": 6000, "wan_bandwidth": 2000,
    }
    step.run()
    bw = _labels(metrics.session_bandwidth_bytes)
    assert bw[("total",)] == 8000 * 1000 // 8
    assert bw[("lan",)] == 6000 * 1000 // 8
    assert bw[("wan",)] == 2000 * 1000 // 8


# -- per-session detail ------------------------------------------------


def test_session_info_labels_and_bandwidth(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "player": "Roku", "platform": "tv",
            "product": "Plex for Roku", "product_version": "8.1.0",
            "quality_profile": "Original", "full_title": "Inception",
            "transcode_decision": "direct play", "ip_address": "192.168.1.10",
            "bandwidth": 16000,
        }],
    }
    step.run()
    info = _labels(metrics.session_info)
    expected_labels = ("alice", "Roku", "tv", "Plex for Roku", "8.1.0",
                       "Original", "Inception", "direct play", "192.168.1.10")
    assert info[expected_labels] == 16000 * 1000 // 8


def test_session_info_clears_between_polls(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"friendly_name": "alice", "full_title": "Inception",
                      "bandwidth": 0}],
    }
    step.run()
    assert _labels(metrics.session_info)

    fake_client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
    }
    step.run()
    assert _labels(metrics.session_info) == {}


def test_session_info_uses_unknown_for_missing_fields(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{}],
    }
    step.run()
    info = _labels(metrics.session_info)
    assert (("unknown",) * 8 + ("",)) in info


def test_session_stream_info_emitted(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "full_title": "Inception",
            "transcode_decision": "transcode",
            "stream_video_decision": "transcode",
            "stream_audio_decision": "direct play",
            "stream_subtitle_decision": "burn",
            "video_codec": "hevc", "stream_video_codec": "h264",
            "audio_codec": "eac3", "stream_audio_codec": "aac",
            "container": "mkv", "stream_container": "mp4",
        }],
    }
    step.run()
    stream_info = _labels(metrics.session_stream_info)
    expected = (
        "alice", "Inception",
        "transcode", "transcode", "direct play", "burn",
        "hevc", "h264", "eac3", "aac", "mkv", "mp4",
    )
    assert stream_info[expected] == 1


def test_session_stream_info_falls_back_to_legacy_decision_keys(
    step, fake_client, metrics,
):
    # Older Tautulli responses only ship `video_decision` / `audio_decision`
    # without the `stream_*_decision` siblings; make sure we still surface them.
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "full_title": "Inception",
            "transcode_decision": "transcode",
            "video_decision": "copy",
            "audio_decision": "transcode",
            "subtitle_decision": "direct play",
        }],
    }
    step.run()
    stream_info = _labels(metrics.session_stream_info)
    # video_decision / audio_decision / subtitle_decision come from the
    # legacy keys; codec/container default to "unknown".
    expected = (
        "alice", "Inception",
        "transcode", "copy", "transcode", "direct play",
        "unknown", "unknown", "unknown", "unknown", "unknown", "unknown",
    )
    assert stream_info[expected] == 1


def test_session_stream_info_clears_between_polls(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "full_title": "Inception",
            "video_codec": "h264",
        }],
    }
    step.run()
    assert _labels(metrics.session_stream_info)

    fake_client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
    }
    step.run()
    assert _labels(metrics.session_stream_info) == {}


def test_session_progress_ratio_clamped_and_zero_when_no_duration(
    step, fake_client, metrics,
):
    fake_client.get_activity.return_value = {
        "stream_count": 3,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [
            {"friendly_name": "a", "full_title": "halfway",
             "duration": 1000, "view_offset": 500},
            {"friendly_name": "b", "full_title": "no_duration",
             "duration": 0, "view_offset": 100},
            {"friendly_name": "c", "full_title": "over_run",
             "duration": 100, "view_offset": 9999},
        ],
    }
    step.run()
    progress = _labels(metrics.session_progress_ratio)
    assert progress[("a", "halfway")] == 0.5
    assert progress[("b", "no_duration")] == 0.0
    assert progress[("c", "over_run")] == 1.0


def test_session_transcode_speed_emitted(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "full_title": "Inception",
            "transcode_speed": "1.4",
        }],
    }
    step.run()
    speed = _labels(metrics.session_transcode_speed_ratio)
    assert speed[("alice", "Inception")] == pytest.approx(1.4)


def test_session_throttled_and_hw(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "full_title": "Inception",
            "transcode_throttled": "1",
            "transcode_hw_decoding": 1,
            "transcode_hw_encoding": 0,
        }],
    }
    step.run()
    assert _labels(metrics.session_throttled)[("alice", "Inception")] == 1
    hw = _labels(metrics.session_transcode_hw)
    assert hw[("alice", "Inception", "decode")] == 1
    assert hw[("alice", "Inception", "encode")] == 0


def test_session_detail_clears_between_polls(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "full_title": "Inception",
            "duration": 100, "view_offset": 50, "transcode_speed": 1.0,
        }],
    }
    step.run()
    assert _labels(metrics.session_progress_ratio)
    assert _labels(metrics.session_transcode_speed_ratio)

    fake_client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
    }
    step.run()
    assert _labels(metrics.session_progress_ratio) == {}
    assert _labels(metrics.session_transcode_speed_ratio) == {}
    assert _labels(metrics.session_throttled) == {}
    assert _labels(metrics.session_transcode_hw) == {}


# -- geoip --------------------------------------------------------------


def test_session_geo_emitted_when_geoip_resolves(fake_client, metrics):
    geoip = MagicMock()
    geoip.lookup.return_value = {
        "city": "Seattle", "region": "WA", "country": "US",
        "latitude": 47.6, "longitude": -122.3,
    }
    step = ActivityStep(fake_client, metrics, geoip=geoip)
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{
            "friendly_name": "alice", "full_title": "Inception",
            "transcode_decision": "direct play", "ip_address": "8.8.8.8",
        }],
    }
    step.run()

    geo = _labels(metrics.session_geo)
    assert geo[(
        "alice", "Inception", "direct play",
        "Seattle", "WA", "US", "47.6", "-122.3",
    )] == 1


def test_geoip_lookup_counters(fake_client, metrics):
    geoip = MagicMock()
    geoip.lookup.side_effect = lambda ip: (
        {"city": "S", "region": "", "country": "US",
         "latitude": 1.0, "longitude": 2.0}
        if ip == "8.8.8.8" else None
    )
    step = ActivityStep(fake_client, metrics, geoip=geoip)
    fake_client.get_activity.return_value = {
        "stream_count": 2,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [
            {"ip_address": "8.8.8.8", "friendly_name": "a"},
            {"ip_address": "1.1.1.1", "friendly_name": "b"},
        ],
    }
    step.run()
    lookups = _labels(metrics.geoip_lookups)
    assert lookups[("hit",)] == 1
    assert lookups[("miss",)] == 1


def test_session_geo_skipped_without_geoip(step, fake_client, metrics):
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"ip_address": "8.8.8.8", "friendly_name": "a"}],
    }
    step.run()
    assert _labels(metrics.session_geo) == {}


def test_session_geo_skips_sessions_without_ip(fake_client, metrics):
    geoip = MagicMock()
    step = ActivityStep(fake_client, metrics, geoip=geoip)
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"friendly_name": "a"}],
    }
    step.run()
    geoip.lookup.assert_not_called()


def test_session_geo_clears_between_polls(fake_client, metrics):
    geoip = MagicMock()
    geoip.lookup.return_value = {
        "city": "S", "region": "", "country": "US",
        "latitude": 1.0, "longitude": 2.0,
    }
    step = ActivityStep(fake_client, metrics, geoip=geoip)
    fake_client.get_activity.return_value = {
        "stream_count": 1,
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
        "sessions": [{"ip_address": "8.8.8.8", "friendly_name": "a",
                      "full_title": "x", "transcode_decision": "direct play"}],
    }
    step.run()
    assert _labels(metrics.session_geo)

    fake_client.get_activity.return_value = {
        "stream_count": 0, "sessions": [],
        "total_bandwidth": 0, "lan_bandwidth": 0, "wan_bandwidth": 0,
    }
    step.run()
    assert _labels(metrics.session_geo) == {}
