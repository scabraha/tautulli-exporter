"""HTTP client for the Tautulli API.

Tautulli's API surface lives at ``/api/v2`` and uses a query-string
``cmd=`` for the operation plus ``apikey=`` for auth. Every successful
response wraps the payload in ``{"response": {"result": "success",
"data": ...}}`` so callers don't have to repeat that unwrap themselves.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class TautulliError(Exception):
    """Tautulli returned ``result != "success"`` for an API call."""


class TautulliClient:
    """Thin wrapper over the Tautulli ``/api/v2`` endpoint.

    Uses a single ``requests.Session`` with retry/backoff for transient
    failures so callers don't need to care about flaky networking.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: int = 10,
        session: requests.Session | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._session = session or self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def call(self, cmd: str, **params: Any) -> Any:
        """Invoke a Tautulli API command and return the unwrapped ``data``.

        Raises ``requests.HTTPError`` on non-2xx responses (with a useful
        excerpt of the body) and ``TautulliError`` when Tautulli reports
        ``result != "success"``.
        """
        query = {"apikey": self._api_key, "cmd": cmd, **params}
        url = f"{self._base_url}/api/v2"
        started = time.monotonic()
        resp = self._session.get(url, params=query, timeout=self._timeout)
        duration_ms = (time.monotonic() - started) * 1000

        log.debug("Tautulli cmd=%s -> %d in %.0fms", cmd, resp.status_code, duration_ms)

        if not resp.ok:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            hint = ""
            if resp.status_code in (401, 403):
                hint = " (check TAUTULLI_API_KEY)"
            raise requests.HTTPError(
                f"{resp.status_code} {resp.reason} from cmd={cmd}{hint}: {snippet}",
                response=resp,
            )

        body = resp.json()
        response = body.get("response") or {}
        if response.get("result") != "success":
            raise TautulliError(
                f"cmd={cmd} returned {response.get('result')!r}: "
                f"{response.get('message', 'no message')}"
            )
        return response.get("data")

    # -- convenience wrappers -----------------------------------------

    def get_activity(self) -> dict[str, Any]:
        """Return the current playback activity payload."""
        data = self.call("get_activity")
        return data if isinstance(data, dict) else {}

    def get_libraries(self) -> list[dict[str, Any]]:
        """Return the list of Plex libraries Tautulli is tracking."""
        data = self.call("get_libraries")
        return data if isinstance(data, list) else []

    def get_server_info(self) -> dict[str, Any]:
        """Return the connected Plex Media Server's info (version, name, …)."""
        data = self.call("get_server_info")
        return data if isinstance(data, dict) else {}

    def get_geoip_lookup(self, ip: str) -> dict[str, Any] | None:
        """Resolve ``ip`` to a Tautulli GeoIP record, or ``None`` on failure.

        Tautulli's GeoIP API can return ``result="error"`` for unresolvable
        IPs (LAN, anycast, etc.); we surface that as ``None`` rather than
        an exception so the poller can keep going.
        """
        try:
            data = self.call("get_geoip_lookup", ip_address=ip)
        except TautulliError:
            return None
        return data if isinstance(data, dict) else None
