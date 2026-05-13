"""Prometheus metric definitions for the Tautulli exporter."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Info


class Metrics:
    """Container for all metrics the exporter exposes.

    Metrics are bound to an explicit registry so tests can use a fresh
    registry per test and avoid the global ``REGISTRY`` singleton.
    """

    def __init__(self, registry: CollectorRegistry):
        self.registry = registry

        # ---- session activity gauges ----
        self.session_count = Gauge(
            "tautulli_session_count",
            "Active Plex sessions",
            registry=registry,
        )
        self.sessions_by_decision = Gauge(
            "tautulli_sessions_by_decision",
            "Active Plex sessions broken down by transcode decision",
            ["decision"],
            registry=registry,
        )
        self.session_bandwidth_bytes = Gauge(
            "tautulli_session_bandwidth_bytes",
            "Current Plex bandwidth in bytes per second",
            ["scope"],
            registry=registry,
        )
        self.session_info = Gauge(
            "tautulli_session_info",
            "Per-session information; value is the session bandwidth in bytes/s",
            ["user", "player", "platform", "quality", "title", "decision", "ip"],
            registry=registry,
        )
        self.session_geo = Gauge(
            "tautulli_session_geo",
            "Active sessions located via GeoIP; value is always 1",
            ["user", "title", "decision", "city", "region", "country",
             "latitude", "longitude"],
            registry=registry,
        )

        # ---- inventory gauges ----
        self.libraries_total = Gauge(
            "tautulli_libraries_total",
            "Total Plex libraries tracked by Tautulli",
            registry=registry,
        )
        self.library_items = Gauge(
            "tautulli_library_items",
            "Items in a Plex library",
            ["name", "type"],
            registry=registry,
        )

        # ---- exporter self-monitoring ----
        self.poll_duration = Gauge(
            "tautulli_exporter_poll_duration_seconds",
            "Wall-clock duration of the most recent poll cycle",
            registry=registry,
        )
        self.poll_failures = Counter(
            "tautulli_exporter_poll_failures_total",
            "Total number of poll cycles that ended in failure",
            ["step"],
            registry=registry,
        )
        self.last_successful_poll = Gauge(
            "tautulli_exporter_last_successful_poll_timestamp_seconds",
            "Unix timestamp of the most recent successful poll cycle",
            registry=registry,
        )
        self.geoip_lookups = Counter(
            "tautulli_exporter_geoip_lookups_total",
            "GeoIP lookups attempted, by result (hit/miss)",
            ["result"],
            registry=registry,
        )

        # ---- meta ----
        self.plex_version_info = Info(
            "tautulli_plex_version",
            "Connected Plex Media Server version information",
            registry=registry,
        )
        self.up = Gauge(
            "tautulli_up",
            "Whether the exporter can reach Tautulli",
            registry=registry,
        )
