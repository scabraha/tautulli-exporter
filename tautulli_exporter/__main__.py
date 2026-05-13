"""CLI entry point: ``python -m tautulli_exporter``."""

from __future__ import annotations

import logging
import signal
import sys
import threading

from prometheus_client import REGISTRY, start_http_server

from . import __version__
from .client import TautulliClient
from .config import Config, ConfigError
from .geoip import GeoIPLookup
from .logging_setup import setup_logging
from .metrics import Metrics
from .poller import Poller

log = logging.getLogger("tautulli_exporter")


def main() -> int:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    setup_logging(level=config.log_level, fmt=config.log_format)

    log.info("tautulli-exporter v%s starting", __version__)
    log.info("Effective config: %s", config.sanitized())

    client = TautulliClient(
        base_url=config.tautulli_url,
        api_key=config.api_key,
        timeout=config.request_timeout,
    )
    metrics = Metrics(REGISTRY)

    geoip = None
    if config.geoip_enabled:
        geoip = GeoIPLookup(client, ttl_seconds=config.geoip_cache_ttl)
        log.info("GeoIP lookups enabled (cache TTL=%ds)", config.geoip_cache_ttl)
    else:
        log.info("GEOIP_ENABLED=false; per-session geolocation metric disabled")

    poller = Poller(client, metrics, config, geoip=geoip)

    stop_event = threading.Event()

    def _shutdown(signum, _frame):
        log.info("Received signal %d, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        start_http_server(config.exporter_port)
    except OSError:
        log.exception("Failed to bind metrics server on port %d", config.exporter_port)
        return 1
    log.info("Metrics endpoint listening on :%d/metrics", config.exporter_port)

    poller.run_forever(stop_event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
