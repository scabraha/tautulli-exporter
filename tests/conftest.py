import pytest
from prometheus_client import CollectorRegistry

from tautulli_exporter.config import Config
from tautulli_exporter.metrics import Metrics


@pytest.fixture
def config() -> Config:
    return Config(
        tautulli_url="http://tautulli.test",
        api_key="test-key",
        activity_poll_interval=1,
        inventory_poll_interval=10,
        meta_poll_interval=60,
        request_timeout=5,
    )


@pytest.fixture
def metrics() -> Metrics:
    """Fresh metrics bound to a fresh registry per test."""
    return Metrics(CollectorRegistry())


# ---------- shared metric introspection helpers ----------------------
#
# Tests reach into prometheus_client internals (`_value`, `_metrics`)
# rather than scraping `generate_latest()`. Same trick the original
# test_poller.py used; centralized here so a future prom-client API
# change only needs one fix-up.


def read_gauge(metric):
    return metric._value.get()


def label_values(metric) -> dict:
    return {
        labels: child._value.get()
        for labels, child in metric._metrics.items()
    }


def info_value(metric) -> dict:
    return metric._value
