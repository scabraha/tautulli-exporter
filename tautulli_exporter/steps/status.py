"""Plex reachability check — drives the ``tautulli_plex_reachable`` gauge.

Distinct from ``tautulli_up`` (exporter↔Tautulli). Operators want to be
able to alert on "Tautulli is alive but Plex is down" without writing a
template that subtracts one signal from another.
"""

from __future__ import annotations

import logging

import requests

from ..client import TautulliClient, TautulliError
from ..metrics import Metrics
from ._common import to_bool

log = logging.getLogger(__name__)


class StatusStep:
    """Probe Tautulli's view of the Plex connection."""

    name = "status"

    def __init__(self, client: TautulliClient, metrics: Metrics):
        self._client = client
        self._metrics = metrics

    def run(self) -> None:
        try:
            payload = self._client.get_server_status()
        except (TautulliError, requests.HTTPError, requests.ConnectionError) as exc:
            # We deliberately swallow these here rather than let them
            # propagate as a step failure: the *purpose* of this step is
            # to publish a 0/1 gauge of Plex reachability. A connection
            # error from Tautulli implies Plex is unreachable; any
            # genuine Tautulli outage is already captured by `tautulli_up`.
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
        log.debug("plex_reachable=%d (payload=%s)", 1 if reachable else 0, payload)
