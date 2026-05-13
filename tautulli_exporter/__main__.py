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
from .poller import Tier, TieredPoller
from .steps import ActivityStep, InventoryStep, MetaStep, StatusStep

log = logging.getLogger("tautulli_exporter")


def _build_tiers(client, metrics, config, geoip):
    """Wire each tier with its steps and cadence.

    Kept as a top-level helper so tests can build a poller with stubbed
    steps without re-implementing the wiring.
    """
    return [
        Tier(
            name="activity",
            interval_seconds=config.activity_poll_interval,
            steps=[
                ActivityStep(client, metrics, geoip=geoip),
                StatusStep(client, metrics),
            ],
            heartbeat=True,
        ),
        Tier(
            name="inventory",
            interval_seconds=config.inventory_poll_interval,
            steps=[
                InventoryStep(
                    client, metrics,
                    library_size_enabled=config.library_size_enabled,
                ),
            ],
        ),
        Tier(
            name="meta",
            interval_seconds=config.meta_poll_interval,
            steps=[MetaStep(client, metrics)],
        ),
    ]


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

    if config.library_size_enabled:
        log.info(
            "LIBRARY_SIZE_ENABLED=true; will call get_library_media_info per "
            "library on every inventory poll (slow on huge libraries)"
        )

    poller = TieredPoller(metrics, _build_tiers(client, metrics, config, geoip))

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
