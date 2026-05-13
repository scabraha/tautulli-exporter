from prometheus_client import CollectorRegistry

from tautulli_exporter.metrics import Metrics


def test_metrics_register_without_collision():
    """All metric names should be unique within the registry."""
    Metrics(CollectorRegistry())


def test_session_count_starts_at_zero(metrics):
    assert metrics.session_count._value.get() == 0


def test_session_info_labels_match_dashboard_contract(metrics):
    """Dashboards rely on this label set; protect it from accidental drift."""
    expected = ("user", "player", "platform", "quality", "title", "decision", "ip")
    assert metrics.session_info._labelnames == expected


def test_session_geo_labels_match_dashboard_contract(metrics):
    expected = (
        "user", "title", "decision", "city", "region", "country",
        "latitude", "longitude",
    )
    assert metrics.session_geo._labelnames == expected
