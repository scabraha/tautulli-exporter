"""Activity tier — refresh per-session state every ``activity_poll_interval``.

Owns every metric whose value can change between scrapes when a user
hits play / pause / stop. Tautulli's ``get_activity`` is in-memory on its
side, so polling this every 10s by default is essentially free; the
GeoIP lookups are TTL-cached so repeated polls of the same active stream
don't hammer Tautulli.
"""

from __future__ import annotations

import logging
from typing import Iterable

from ..client import TautulliClient
from ..geoip import GeoIPLookup
from ..metrics import Metrics
from ._common import (
    KBPS_TO_BPS,
    label_or,
    session_identity,
    to_bool,
    to_float,
    to_int,
)

log = logging.getLogger(__name__)


# Seeded so dashboards see all the standard buckets present (with value 0)
# rather than missing series when nothing matches that label this cycle.
_DECISION_SEEDS = ("direct play", "direct stream", "copy", "transcode")
_STATE_SEEDS = ("playing", "paused", "buffering")
_LOCATION_SEEDS = ("lan", "wan", "relay")
_MEDIA_TYPE_SEEDS = ("movie", "episode", "track", "live", "clip")


class ActivityStep:
    """Refresh `tautulli_session_*` and friends from ``get_activity``."""

    name = "activity"

    def __init__(
        self,
        client: TautulliClient,
        metrics: Metrics,
        *,
        geoip: GeoIPLookup | None = None,
    ):
        self._client = client
        self._metrics = metrics
        self._geoip = geoip

    def run(self) -> None:
        activity = self._client.get_activity()
        sessions = activity.get("sessions") or []

        self._update_aggregates(activity, sessions)
        self._update_bandwidth(activity)
        self._refresh_per_session_metrics(sessions)

        log.debug(
            "Activity poll: streams=%d sessions=%d",
            to_int(activity.get("stream_count")),
            len(sessions),
        )

    # -- aggregates ----------------------------------------------------

    def _update_aggregates(self, activity: dict, sessions: list[dict]) -> None:
        self._metrics.session_count.set(to_int(activity.get("stream_count")))

        # Build all four breakdowns in a single pass over the session list.
        decisions = {key: 0 for key in _DECISION_SEEDS}
        states = {key: 0 for key in _STATE_SEEDS}
        locations = {key: 0 for key in _LOCATION_SEEDS}
        media_types = {key: 0 for key in _MEDIA_TYPE_SEEDS}
        secure_count = 0

        for session in sessions:
            decision = label_or(session.get("transcode_decision"))
            decisions[decision] = decisions.get(decision, 0) + 1

            state = label_or(session.get("state"))
            states[state] = states.get(state, 0) + 1

            location = label_or(session.get("location"))
            locations[location] = locations.get(location, 0) + 1

            media_type = label_or(session.get("media_type"))
            media_types[media_type] = media_types.get(media_type, 0) + 1

            if to_bool(session.get("secure")):
                secure_count += 1

        _set_breakdown(self._metrics.sessions_by_decision, "decision", decisions)
        _set_breakdown(self._metrics.sessions_by_state, "state", states)
        _set_breakdown(self._metrics.sessions_by_location, "location", locations)
        _set_breakdown(self._metrics.sessions_by_media_type, "media_type", media_types)
        self._metrics.sessions_secure.set(secure_count)

    def _update_bandwidth(self, activity: dict) -> None:
        for scope, key in (
            ("total", "total_bandwidth"),
            ("lan", "lan_bandwidth"),
            ("wan", "wan_bandwidth"),
        ):
            self._metrics.session_bandwidth_bytes.labels(scope=scope).set(
                to_int(activity.get(key)) * KBPS_TO_BPS
            )

    # -- per-session detail --------------------------------------------

    def _refresh_per_session_metrics(self, sessions: list[dict]) -> None:
        # Clearing each per-session metric is what stops "ghost streams"
        # from sticking around after the user closes their player.
        self._metrics.session_info.clear()
        self._metrics.session_progress_ratio.clear()
        self._metrics.session_transcode_speed_ratio.clear()
        self._metrics.session_throttled.clear()
        self._metrics.session_transcode_hw.clear()
        self._metrics.session_geo.clear()

        for session in sessions:
            self._set_session_info(session)
            self._set_session_detail(session)

        self._update_session_geo(sessions)

    def _set_session_info(self, session: dict) -> None:
        labels = {
            "user": label_or(session.get("friendly_name")),
            "player": label_or(session.get("player")),
            "platform": label_or(session.get("platform")),
            "quality": label_or(session.get("quality_profile")),
            "title": label_or(session.get("full_title")),
            "decision": label_or(session.get("transcode_decision")),
            "ip": str(session.get("ip_address") or ""),
        }
        bandwidth = to_int(session.get("bandwidth")) * KBPS_TO_BPS
        self._metrics.session_info.labels(**labels).set(bandwidth)

    def _set_session_detail(self, session: dict) -> None:
        ident = session_identity(session)

        # Progress: view_offset / duration. Guard against the Plex "no
        # duration yet" case (live TV before the EPG fills, music tracks
        # mid-buffer) — emit 0 rather than NaN.
        duration = to_float(session.get("duration"))
        offset = to_float(session.get("view_offset"))
        progress = (offset / duration) if duration > 0 else 0.0
        # Clamp: Plex occasionally reports view_offset > duration on live.
        progress = max(0.0, min(1.0, progress))
        self._metrics.session_progress_ratio.labels(**ident).set(progress)

        # Transcode speed only exists for transcoding sessions; emit 0
        # for direct play so the panel doesn't show "missing" series.
        speed = to_float(session.get("transcode_speed"))
        self._metrics.session_transcode_speed_ratio.labels(**ident).set(speed)

        throttled = to_bool(session.get("transcode_throttled"))
        self._metrics.session_throttled.labels(**ident).set(1 if throttled else 0)

        for direction, key in (("decode", "transcode_hw_decoding"),
                               ("encode", "transcode_hw_encoding")):
            on = to_bool(session.get(key))
            self._metrics.session_transcode_hw.labels(
                direction=direction, **ident
            ).set(1 if on else 0)

    # -- geoip ----------------------------------------------------------

    def _update_session_geo(self, sessions: Iterable[dict]) -> None:
        if self._geoip is None:
            return

        hits = 0
        misses = 0
        for session in sessions:
            ip = str(session.get("ip_address") or "")
            if not ip:
                continue
            geo = self._geoip.lookup(ip)
            if geo is None:
                misses += 1
                continue
            hits += 1
            self._metrics.session_geo.labels(
                user=label_or(session.get("friendly_name")),
                title=label_or(session.get("full_title")),
                decision=label_or(session.get("transcode_decision")),
                city=str(geo.get("city") or ""),
                region=str(geo.get("region") or ""),
                country=str(geo.get("country") or ""),
                latitude=str(geo.get("latitude") or ""),
                longitude=str(geo.get("longitude") or ""),
            ).set(1)

        if hits or misses:
            self._metrics.geoip_lookups.labels(result="hit").inc(hits)
            self._metrics.geoip_lookups.labels(result="miss").inc(misses)
            log.debug("GeoIP lookups: hits=%d misses=%d", hits, misses)


def _set_breakdown(metric, label_name: str, counts: dict[str, int]) -> None:
    """Replace a labeled gauge's contents with ``counts``.

    Clearing first, then re-setting, keeps stale label values from
    lingering after a user agent / state / location stops appearing.
    """
    metric.clear()
    for value, count in counts.items():
        metric.labels(**{label_name: value}).set(count)
