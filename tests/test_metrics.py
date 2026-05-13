"""Sanity checks on metric registration and label contracts.

Dashboards depend on label *names* staying stable. These tests are the
canary that fires when someone accidentally renames a label or drops a
metric.
"""

from prometheus_client import CollectorRegistry

from tautulli_exporter.metrics import Metrics


def test_metrics_register_without_collision():
    """All metric names should be unique within the registry."""
    Metrics(CollectorRegistry())


def test_session_count_starts_at_zero(metrics):
    assert metrics.session_count._value.get() == 0


def _expect_labels(metric, expected: tuple[str, ...]):
    assert metric._labelnames == expected, (
        f"label drift on {metric._name}: got {metric._labelnames}, want {expected}"
    )


def test_session_info_labels(metrics):
    _expect_labels(
        metrics.session_info,
        ("user", "player", "platform", "quality", "title", "decision", "ip"),
    )


def test_session_geo_labels(metrics):
    _expect_labels(
        metrics.session_geo,
        ("user", "title", "decision", "city", "region", "country",
         "latitude", "longitude"),
    )


def test_session_detail_labels_are_consistent(metrics):
    """Per-session detail metrics share (user, title) so dashboards can join."""
    for metric in (
        metrics.session_progress_ratio,
        metrics.session_transcode_speed_ratio,
        metrics.session_throttled,
    ):
        _expect_labels(metric, ("user", "title"))


def test_session_transcode_hw_labels(metrics):
    _expect_labels(metrics.session_transcode_hw, ("user", "title", "direction"))


def test_session_breakdown_labels(metrics):
    _expect_labels(metrics.sessions_by_decision, ("decision",))
    _expect_labels(metrics.sessions_by_state, ("state",))
    _expect_labels(metrics.sessions_by_location, ("location",))
    _expect_labels(metrics.sessions_by_media_type, ("media_type",))


def test_library_metrics_share_name_type_labels(metrics):
    """All per-library gauges use the same label set so they line up in panels."""
    for metric in (
        metrics.library_items,
        metrics.library_seasons,
        metrics.library_episodes,
        metrics.library_plays,
        metrics.library_play_duration_seconds,
        metrics.library_last_accessed_timestamp_seconds,
        metrics.library_active,
        metrics.library_size_bytes,
    ):
        _expect_labels(metric, ("name", "type"))


def test_user_metrics_share_user_label(metrics):
    for metric in (
        metrics.user_last_seen_timestamp_seconds,
        metrics.user_plays,
        metrics.user_play_duration_seconds,
    ):
        _expect_labels(metric, ("user",))


def test_unlabeled_meta_metrics_present(metrics):
    """Spot-check that the unlabeled gauges exist and start at 0."""
    for metric in (
        metrics.users_total, metrics.users_active, metrics.users_home,
        metrics.sessions_secure,
        metrics.plex_reachable,
        metrics.plex_update_available,
        metrics.up,
    ):
        assert metric._value.get() == 0
