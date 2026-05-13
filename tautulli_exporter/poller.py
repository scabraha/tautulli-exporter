"""Polling loop that drives metric updates."""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterable

import requests

from .client import TautulliClient
from .config import Config
from .geoip import GeoIPLookup
from .metrics import Metrics

log = logging.getLogger(__name__)


class _StepFailure(Exception):
    """Internal: marks which poll step raised, for error context."""

    def __init__(self, step: str, original: BaseException):
        super().__init__(step)
        self.step = step
        self.original = original


# Tautulli reports session bandwidth in kbps; convert to bytes/s for Prometheus.
_KBPS_TO_BPS = 1000 // 8


class Poller:
    """Periodically polls Tautulli and updates Prometheus metrics."""

    def __init__(
        self,
        client: TautulliClient,
        metrics: Metrics,
        config: Config,
        *,
        geoip: GeoIPLookup | None = None,
    ):
        self._client = client
        self._metrics = metrics
        self._config = config
        self._geoip = geoip
        self._has_succeeded_once = False
        self._consecutive_failures = 0

    # -- public API -----------------------------------------------------

    def poll_once(self) -> None:
        """Run a single poll cycle, updating all metrics."""
        started = time.monotonic()
        try:
            self._run_step("version", self._poll_version)
            self._run_step("libraries", self._poll_libraries)
            self._run_step("activity", self._poll_activity)
        except _StepFailure as fail:
            self._record_failure(fail, time.monotonic() - started)
            return
        self._record_success(time.monotonic() - started)

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        """Poll in a loop until ``stop_event`` is set."""
        stop_event = stop_event or threading.Event()
        log.info("Poll loop starting (interval=%ds)", self._config.poll_interval)
        while not stop_event.is_set():
            self.poll_once()
            stop_event.wait(self._config.poll_interval)
        log.info("Poll loop stopped")

    # -- step orchestration --------------------------------------------

    @staticmethod
    def _run_step(name: str, fn) -> None:
        try:
            fn()
        except BaseException as exc:
            raise _StepFailure(name, exc) from exc

    def _record_success(self, duration_s: float) -> None:
        self._metrics.up.set(1)
        self._metrics.poll_duration.set(duration_s)
        self._metrics.last_successful_poll.set(time.time())

        if not self._has_succeeded_once:
            self._has_succeeded_once = True
            log.info(
                "First successful poll cycle in %.2fs; exporter is healthy",
                duration_s,
            )
        elif self._consecutive_failures > 0:
            log.info(
                "Recovered after %d consecutive failures (poll took %.2fs)",
                self._consecutive_failures, duration_s,
            )
        else:
            log.debug("Poll cycle completed in %.2fs", duration_s)
        self._consecutive_failures = 0

    def _record_failure(self, fail: _StepFailure, duration_s: float) -> None:
        self._metrics.up.set(0)
        self._metrics.poll_duration.set(duration_s)
        self._metrics.poll_failures.labels(step=fail.step).inc()
        self._consecutive_failures += 1

        exc = fail.original
        if isinstance(exc, requests.HTTPError):
            log.error(
                "Poll step '%s' failed (consecutive_failures=%d): %s",
                fail.step, self._consecutive_failures, exc,
            )
            log.debug("HTTPError details", exc_info=(type(exc), exc, exc.__traceback__))
        else:
            log.error(
                "Poll step '%s' failed (consecutive_failures=%d)",
                fail.step, self._consecutive_failures,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    # -- steps ----------------------------------------------------------

    def _poll_version(self) -> None:
        info = self._client.get_server_info()
        version = str(info.get("pms_version") or "unknown")
        name = str(info.get("pms_name") or "unknown")
        self._metrics.plex_version_info.info({"version": version, "server_name": name})
        log.debug("Plex version=%s name=%s", version, name)

    def _poll_libraries(self) -> None:
        libraries = self._client.get_libraries()
        self._metrics.libraries_total.set(len(libraries))
        self._metrics.library_items.clear()
        for lib in libraries:
            name = str(lib.get("section_name") or "unknown")
            section_type = str(lib.get("section_type") or "unknown")
            count = _to_int(lib.get("count"))
            self._metrics.library_items.labels(name=name, type=section_type).set(count)
        log.debug("Tracked %d libraries", len(libraries))

    def _poll_activity(self) -> None:
        activity = self._client.get_activity()
        sessions = activity.get("sessions") or []

        self._metrics.session_count.set(_to_int(activity.get("stream_count")))

        decisions = {"direct play": 0, "copy": 0, "transcode": 0}
        for session in sessions:
            decision = str(session.get("transcode_decision") or "unknown")
            decisions[decision] = decisions.get(decision, 0) + 1

        self._metrics.sessions_by_decision.clear()
        for decision, count in decisions.items():
            self._metrics.sessions_by_decision.labels(decision=decision).set(count)

        self._metrics.session_bandwidth_bytes.labels(scope="total").set(
            _to_int(activity.get("total_bandwidth")) * _KBPS_TO_BPS
        )
        self._metrics.session_bandwidth_bytes.labels(scope="lan").set(
            _to_int(activity.get("lan_bandwidth")) * _KBPS_TO_BPS
        )
        self._metrics.session_bandwidth_bytes.labels(scope="wan").set(
            _to_int(activity.get("wan_bandwidth")) * _KBPS_TO_BPS
        )

        self._metrics.session_info.clear()
        for session in sessions:
            self._set_session_info(session)

        self._metrics.session_geo.clear()
        self._update_session_geo(sessions)

        log.debug(
            "Activity poll: streams=%d direct_play=%d copy=%d transcode=%d",
            _to_int(activity.get("stream_count")),
            decisions.get("direct play", 0),
            decisions.get("copy", 0),
            decisions.get("transcode", 0),
        )

    # -- helpers --------------------------------------------------------

    def _set_session_info(self, session: dict) -> None:
        labels = {
            "user": str(session.get("friendly_name") or "unknown"),
            "player": str(session.get("player") or "unknown"),
            "platform": str(session.get("platform") or "unknown"),
            "quality": str(session.get("quality_profile") or "unknown"),
            "title": str(session.get("full_title") or "unknown"),
            "decision": str(session.get("transcode_decision") or "unknown"),
            "ip": str(session.get("ip_address") or ""),
        }
        bandwidth = _to_int(session.get("bandwidth")) * _KBPS_TO_BPS
        self._metrics.session_info.labels(**labels).set(bandwidth)

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
                user=str(session.get("friendly_name") or "unknown"),
                title=str(session.get("full_title") or "unknown"),
                decision=str(session.get("transcode_decision") or "unknown"),
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


def _to_int(value, default: int = 0) -> int:
    """Coerce Tautulli's loosely-typed numeric fields to ``int``."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default
