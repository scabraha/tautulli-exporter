"""Prometheus metric definitions for the Tautulli exporter.

Metrics are organized by the tier that owns them (activity / inventory /
meta / self). Each tier's poll step is the only writer of its metrics —
that single-writer property is what makes individual steps trivially
testable without coordinating across the rest of the exporter.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Info


class Metrics:
    """Container for every metric the exporter exposes.

    Bound to an explicit registry so each test can use a fresh one and
    avoid the global ``REGISTRY`` singleton.
    """

    def __init__(self, registry: CollectorRegistry):
        self.registry = registry

        # =====================================================================
        # Tier 1 — activity loop (fast, ~10s)
        # =====================================================================

        # Aggregate session breakdowns.
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
        self.sessions_by_state = Gauge(
            "tautulli_sessions_by_state",
            "Active Plex sessions broken down by player state",
            ["state"],
            registry=registry,
        )
        self.sessions_by_location = Gauge(
            "tautulli_sessions_by_location",
            "Active Plex sessions broken down by network location",
            ["location"],
            registry=registry,
        )
        self.sessions_by_media_type = Gauge(
            "tautulli_sessions_by_media_type",
            "Active Plex sessions broken down by media type",
            ["media_type"],
            registry=registry,
        )
        self.sessions_secure = Gauge(
            "tautulli_sessions_secure",
            "Number of active sessions using a TLS-encrypted connection to Plex",
            registry=registry,
        )

        # Bandwidth.
        self.session_bandwidth_bytes = Gauge(
            "tautulli_session_bandwidth_bytes",
            "Current Plex bandwidth in bytes per second",
            ["scope"],
            registry=registry,
        )

        # Per-session detail (cardinality bounded by concurrent stream count).
        self.session_info = Gauge(
            "tautulli_session_info",
            "Per-session information; value is the session bandwidth in bytes/s",
            [
                "user", "player", "platform", "product", "product_version",
                "quality", "title", "decision", "ip",
            ],
            registry=registry,
        )
        # Codec / container / per-stream-decision breakdown. Separate from
        # session_info so dashboards graphing bandwidth don't have to carry
        # 10 extra label dimensions, and so the codec slice can be queried
        # independently. Joined to session_info on (user, title).
        self.session_stream_info = Gauge(
            "tautulli_session_stream_info",
            (
                "Per-session codec, container, and per-stream transcode decisions; "
                "value is always 1"
            ),
            [
                "user", "title",
                "transcode_decision", "video_decision", "audio_decision",
                "subtitle_decision",
                "video_codec", "stream_video_codec",
                "audio_codec", "stream_audio_codec",
                "container", "stream_container",
            ],
            registry=registry,
        )
        self.session_progress_ratio = Gauge(
            "tautulli_session_progress_ratio",
            "Current playback progress as view_offset / duration (0.0 to 1.0)",
            ["user", "title"],
            registry=registry,
        )
        self.session_transcode_speed_ratio = Gauge(
            "tautulli_session_transcode_speed_ratio",
            (
                "Tautulli-reported transcode speed; values < 1.0 mean the "
                "transcoder is falling behind real-time playback"
            ),
            ["user", "title"],
            registry=registry,
        )
        self.session_throttled = Gauge(
            "tautulli_session_throttled",
            "1 if the transcoder is currently throttled (client buffer full), else 0",
            ["user", "title"],
            registry=registry,
        )
        self.session_transcode_hw = Gauge(
            "tautulli_session_transcode_hw",
            "1 if hardware-accelerated transcoding is active for the given direction",
            ["user", "title", "direction"],
            registry=registry,
        )
        self.session_geo = Gauge(
            "tautulli_session_geo",
            "Active sessions located via GeoIP; value is always 1",
            [
                "user", "title", "decision", "city", "region", "country",
                "latitude", "longitude",
            ],
            registry=registry,
        )

        # Plex reachability (separate from `tautulli_up`, which is exporter→Tautulli).
        self.plex_reachable = Gauge(
            "tautulli_plex_reachable",
            "Whether Tautulli currently has a working connection to Plex",
            registry=registry,
        )

        # =====================================================================
        # Tier 2 — inventory loop (~5 min)
        # =====================================================================

        self.libraries_total = Gauge(
            "tautulli_libraries_total",
            "Total Plex libraries tracked by Tautulli",
            registry=registry,
        )
        self.library_items = Gauge(
            "tautulli_library_items",
            "Items in a Plex library (movies/shows/artists, depending on type)",
            ["name", "type"],
            registry=registry,
        )
        self.library_seasons = Gauge(
            "tautulli_library_seasons",
            "Parent count for the library (seasons for shows, albums for music)",
            ["name", "type"],
            registry=registry,
        )
        self.library_episodes = Gauge(
            "tautulli_library_episodes",
            "Child count for the library (episodes for shows, tracks for music)",
            ["name", "type"],
            registry=registry,
        )
        self.library_plays = Gauge(
            "tautulli_library_plays",
            "All-time play count for items in this library",
            ["name", "type"],
            registry=registry,
        )
        self.library_play_duration_seconds = Gauge(
            "tautulli_library_play_duration_seconds",
            "All-time watched seconds for items in this library",
            ["name", "type"],
            registry=registry,
        )
        self.library_last_accessed_timestamp_seconds = Gauge(
            "tautulli_library_last_accessed_timestamp_seconds",
            "Unix timestamp of the most recent play from this library",
            ["name", "type"],
            registry=registry,
        )
        self.library_active = Gauge(
            "tautulli_library_active",
            "1 if the library is currently active in Plex, else 0",
            ["name", "type"],
            registry=registry,
        )
        # Opt-in: only emitted when LIBRARY_SIZE_ENABLED=true. Always
        # registered so dashboards don't have to handle a missing series
        # name when the flag is flipped on.
        self.library_size_bytes = Gauge(
            "tautulli_library_size_bytes",
            (
                "Total on-disk size of the library in bytes "
                "(only populated when LIBRARY_SIZE_ENABLED=true)"
            ),
            ["name", "type"],
            registry=registry,
        )

        self.users_total = Gauge(
            "tautulli_users_total",
            "Total Plex users known to Tautulli",
            registry=registry,
        )
        self.users_active = Gauge(
            "tautulli_users_active",
            "Plex users currently flagged active in Tautulli",
            registry=registry,
        )
        self.users_home = Gauge(
            "tautulli_users_home",
            "Plex Home (family) users",
            registry=registry,
        )
        self.user_last_seen_timestamp_seconds = Gauge(
            "tautulli_user_last_seen_timestamp_seconds",
            "Unix timestamp of the user's most recent session",
            ["user"],
            registry=registry,
        )
        self.user_plays = Gauge(
            "tautulli_user_plays",
            "All-time play count for the user (gauge: Tautulli history can be wiped)",
            ["user"],
            registry=registry,
        )
        self.user_play_duration_seconds = Gauge(
            "tautulli_user_play_duration_seconds",
            "All-time watched seconds for the user",
            ["user"],
            registry=registry,
        )

        # =====================================================================
        # Tier 3 — meta loop (~30 min)
        # =====================================================================

        self.plex_update_available = Gauge(
            "tautulli_plex_update_available",
            "1 if Plex Media Server has an update available, else 0",
            registry=registry,
        )
        self.plex_update_info = Info(
            "tautulli_plex_update",
            "Details of the latest available Plex Media Server update",
            registry=registry,
        )

        # =====================================================================
        # Meta / version (refreshed by the inventory tier).
        # =====================================================================

        self.plex_version_info = Info(
            "tautulli_plex_version",
            "Connected Plex Media Server version information",
            registry=registry,
        )

        # =====================================================================
        # Self-monitoring
        # =====================================================================

        self.poll_duration = Gauge(
            "tautulli_exporter_poll_duration_seconds",
            "Wall-clock duration of the most recent activity poll cycle",
            registry=registry,
        )
        self.poll_failures = Counter(
            "tautulli_exporter_poll_failures_total",
            "Total number of poll steps that ended in failure",
            ["step"],
            registry=registry,
        )
        self.last_successful_poll = Gauge(
            "tautulli_exporter_last_successful_poll_timestamp_seconds",
            "Unix timestamp of the most recent successful activity poll",
            registry=registry,
        )
        self.geoip_lookups = Counter(
            "tautulli_exporter_geoip_lookups_total",
            "GeoIP lookups attempted, by result (hit/miss)",
            ["result"],
            registry=registry,
        )
        self.up = Gauge(
            "tautulli_up",
            "Whether the exporter can reach Tautulli (driven by the activity tier)",
            registry=registry,
        )
