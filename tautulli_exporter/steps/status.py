"""Plex reachability check — drives the ``tautulli_plex_reachable`` gauge.

Distinct from ``tautulli_up`` (exporter↔Tautulli). Operators want to be
able to alert on "Tautulli is alive but Plex is down" without writing a
template that subtracts one signal from another.

Also drives ``tautulli_plex_server_start_timestamp_seconds``: Tautulli
doesn't surface a real PMS uptime, so we approximate it by stamping the
wall-clock time on every observed Plex down→up transition (and on the
very first reachable observation after exporter start).
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import requests

from ..client import TautulliClient, TautulliError
from ..metrics import Metrics
from ._common import to_bool

log = logging.getLogger(__name__)


class StatusStep:
    """Probe Tautulli's view of the Plex connection."""

    name = "status"

    def __init__(
        self,
        client: TautulliClient,
        metrics: Metrics,
        *,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._client = client
        self._metrics = metrics
        self._wall_clock = wall_clock
        # ``None`` means "no observation yet"; distinguishing it from
        # ``False`` is what lets the very first reachable poll record a
        # start timestamp instead of being silently ignored.
        self._last_reachable: bool | None = None

    def run(self) -> None:
        try:
            payload = self._client.get_server_status()
        except (TautulliError, requests.HTTPError, requests.ConnectionError) as exc:
            # We deliberately swallow these here rather than let them
            # propagate as a step failure: the *purpose* of this step is
            # to publish a 0/1 gauge of Plex reachability. A connection
            # error from Tautulli implies Plex is unreachable; any
            # genuine Tautulli outage is already captured by `tautulli_up`.
            #
            # We also deliberately do NOT touch ``_last_reachable`` here:
            # a Tautulli flap should not be misread as a Plex restart on
            # the next successful poll.
            log.debug("plex reachability check failed: %s", exc)
            self._metrics.plex_reachable.set(0)
            return

        # Tautulli's `server_status` typically returns ``{"connected":
        # true|false}``; treat anything else with a successful HTTP
        # response as reachable so we don't false-alarm on schema drift.
        if "connected" in payload:
            reachable = to_bool(payload["connected"])
        else:
            reachable = True

        self._metrics.plex_reachable.set(1 if reachable else 0)
        self._update_start_timestamp(reachable)
        log.debug("plex_reachable=%d (payload=%s)", 1 if reachable else 0, payload)

    def _update_start_timestamp(self, reachable: bool) -> None:
        # Stamp the start timestamp on either the first-ever reachable
        # observation or any subsequent down→up transition. Leave the
        # gauge alone during outages so dashboards keep the previous
        # known-good anchor instead of dropping to 0.
        if reachable and self._last_reachable is not True:
            ts = self._wall_clock()
            self._metrics.plex_server_start_timestamp_seconds.set(ts)
            if self._last_reachable is False:
                log.info(
                    "Plex came back up; recording PMS start timestamp=%d",
                    int(ts),
                )
        self._last_reachable = reachable
