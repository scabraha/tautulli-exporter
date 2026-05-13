"""Meta tier — slow-changing facts like Plex update availability.

Polls plex.tv (via Tautulli) so we keep this on a long interval to be
polite. Default cadence is 30 minutes.
"""

from __future__ import annotations

import logging

from ..client import TautulliClient
from ..metrics import Metrics
from ._common import to_bool

log = logging.getLogger(__name__)


class MetaStep:
    """Refresh Plex Media Server update info."""

    name = "meta"

    def __init__(self, client: TautulliClient, metrics: Metrics):
        self._client = client
        self._metrics = metrics

    def run(self) -> None:
        payload = self._client.get_pms_update()
        available = to_bool(payload.get("update_available"))
        self._metrics.plex_update_available.set(1 if available else 0)

        # Pair with an Info metric carrying version/release_date so a
        # dashboard can show *what* the pending version is, not just that
        # one exists.
        self._metrics.plex_update_info.info({
            "version": str(payload.get("version") or ""),
            "release_date": str(payload.get("release_date") or ""),
            "platform": str(payload.get("platform") or ""),
        })

        log.debug(
            "PMS update check: available=%s version=%s",
            available, payload.get("version"),
        )
