"""Cached GeoIP lookups via Tautulli's ``get_geoip_lookup`` API.

Tautulli already runs MaxMind under the hood, so we don't need a local
``.mmdb`` file: this module just adds a small TTL cache around the
client call so repeated scrapes for the same active session don't hit
Tautulli on every poll. RFC1918 / loopback / link-local IPs short-circuit
without an API call because GeoIP can't resolve them anyway.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from typing import Any, Optional

from .client import TautulliClient

log = logging.getLogger(__name__)


class GeoIPLookup:
    """TTL-cached wrapper around ``TautulliClient.get_geoip_lookup``."""

    def __init__(self, client: TautulliClient, ttl_seconds: int = 3600):
        self._client = client
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Optional[dict[str, Any]]]] = {}

    def lookup(self, ip: str) -> Optional[dict[str, Any]]:
        """Return Tautulli's GeoIP record for ``ip``, or ``None``."""
        if not ip or _is_local(ip):
            return None

        now = time.time()
        cached = self._cache.get(ip)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]

        record = self._client.get_geoip_lookup(ip)
        if record is not None and not _has_coords(record):
            # Tautulli sometimes returns success with empty/zero coords for
            # IPs MaxMind couldn't resolve — treat that as a miss so we don't
            # publish meaningless (0.0, 0.0) points on a Grafana world map.
            record = None

        self._cache[ip] = (now, record)
        if record is None:
            log.debug("GeoIP miss for %s", ip)
        return record


def _is_local(ip: str) -> bool:
    """True for IPs MaxMind can't usefully resolve (private, loopback, …)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def _has_coords(record: dict[str, Any]) -> bool:
    lat = record.get("latitude")
    lon = record.get("longitude")
    if lat in (None, "", 0, 0.0, "0", "0.0"):
        return False
    if lon in (None, "", 0, 0.0, "0", "0.0"):
        return False
    return True
