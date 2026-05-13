import pytest
from prometheus_client import CollectorRegistry

from tautulli_exporter.config import Config
from tautulli_exporter.metrics import Metrics


@pytest.fixture
def config() -> Config:
    return Config(
        tautulli_url="http://tautulli.test",
        api_key="test-key",
        poll_interval=1,
        request_timeout=5,
    )


@pytest.fixture
def metrics() -> Metrics:
    """Fresh metrics bound to a fresh registry per test."""
    return Metrics(CollectorRegistry())
