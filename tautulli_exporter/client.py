"""HTTP client for the Tautulli API.

Tautulli's API surface lives at ``/api/v2`` and uses a query-string
``cmd=`` for the operation plus ``apikey=`` for auth. Every successful
response wraps the payload in ``{"response": {"result": "success",
"data": ...}}`` so callers don't have to repeat that unwrap themselves.

Convenience wrappers are kept thin (one Tautulli command each) so the
poll-step modules can compose them without re-implementing the unwrap
logic, and so each one can be stubbed independently in tests.
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

    def get_libraries_table(self) -> list[dict[str, Any]]:
        """Return the libraries-table view (richer per-library stats).

        Tautulli's ``get_libraries_table`` returns ``{"data": [...]}``
        wrapped in DataTables pagination metadata; we hand back just the
        ``data`` rows since that's all the inventory step cares about.
        """
        data = self.call("get_libraries_table", length=1000)
        if isinstance(data, dict):
            rows = data.get("data") or []
            return rows if isinstance(rows, list) else []
        return []

    def get_library_media_info(self, section_id: str | int) -> dict[str, Any]:
        """Return ``get_library_media_info`` payload for a single section.

        Used only when ``LIBRARY_SIZE_ENABLED`` is on; this call walks
        Tautulli's media_info table and can be slow for huge libraries.
        """
        data = self.call(
            "get_library_media_info",
            section_id=section_id,
            length=1,  # we only need the aggregate total_file_size, not the rows
        )
        return data if isinstance(data, dict) else {}

    def get_users(self) -> list[dict[str, Any]]:
        """Return the full list of Plex users known to Tautulli."""
        data = self.call("get_users")
        return data if isinstance(data, list) else []

    def get_users_table(self) -> list[dict[str, Any]]:
        """Return the users-table view (per-user lifetime stats)."""
        data = self.call("get_users_table", length=1000)
        if isinstance(data, dict):
            rows = data.get("data") or []
            return rows if isinstance(rows, list) else []
        return []

    def get_server_info(self) -> dict[str, Any]:
        """Return the connected Plex Media Server's info (version, name, …)."""
        data = self.call("get_server_info")
        return data if isinstance(data, dict) else {}

    def get_server_status(self) -> dict[str, Any]:
        """Return Tautulli's view of the Plex connection status.

        Tautulli's ``server_status`` reports whether its WebSocket to Plex
        is currently up. Used to drive the ``tautulli_plex_reachable``
        gauge — distinct from ``tautulli_up`` which only reflects the
        exporter↔Tautulli link.
        """
        data = self.call("server_status")
        return data if isinstance(data, dict) else {}

    def get_pms_update(self) -> dict[str, Any]:
        """Return Plex Media Server update info (calls plex.tv via Tautulli).

        Cheap on Tautulli's side but does roundtrip to plex.tv, which is
        why it lives in the slow meta tier.
        """
        data = self.call("get_pms_update")
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
