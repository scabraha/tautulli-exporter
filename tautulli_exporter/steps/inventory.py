"""Inventory tier — refresh library and user aggregates every ``inventory_poll_interval``.

These metrics change on the order of minutes-to-hours (libraries scan,
users join, lifetime play counts tick up). Hits Tautulli's SQLite via
the ``*_table`` endpoints; one round-trip per metric group.
"""

from __future__ import annotations

import logging

from ..client import TautulliClient
from ..metrics import Metrics
from ._common import label_or, to_bool, to_int

log = logging.getLogger(__name__)


class InventoryStep:
    """Refresh per-library, per-user, and Plex-version metrics."""

    name = "inventory"

    def __init__(
        self,
        client: TautulliClient,
        metrics: Metrics,
        *,
        library_size_enabled: bool = False,
    ):
        self._client = client
        self._metrics = metrics
        self._library_size_enabled = library_size_enabled

    def run(self) -> None:
        self._refresh_libraries()
        self._refresh_users()
        self._refresh_version()

    # -- libraries -----------------------------------------------------

    def _refresh_libraries(self) -> None:
        rows = self._client.get_libraries_table()
        self._metrics.libraries_total.set(len(rows))

        # Per-library labeled gauges all need clearing so deleted
        # libraries don't ghost.
        for metric in (
            self._metrics.library_items,
            self._metrics.library_seasons,
            self._metrics.library_episodes,
            self._metrics.library_plays,
            self._metrics.library_play_duration_seconds,
            self._metrics.library_last_accessed_timestamp_seconds,
            self._metrics.library_active,
            self._metrics.library_size_bytes,
        ):
            metric.clear()

        for row in rows:
            name = label_or(row.get("section_name"))
            section_type = label_or(row.get("section_type"))
            ident = {"name": name, "type": section_type}

            self._metrics.library_items.labels(**ident).set(to_int(row.get("count")))
            self._metrics.library_seasons.labels(**ident).set(
                to_int(row.get("parent_count"))
            )
            self._metrics.library_episodes.labels(**ident).set(
                to_int(row.get("child_count"))
            )
            self._metrics.library_plays.labels(**ident).set(to_int(row.get("plays")))
            self._metrics.library_play_duration_seconds.labels(**ident).set(
                to_int(row.get("duration"))
            )
            self._metrics.library_last_accessed_timestamp_seconds.labels(**ident).set(
                to_int(row.get("last_accessed"))
            )
            self._metrics.library_active.labels(**ident).set(
                1 if to_bool(row.get("is_active"), default=True) else 0
            )

            if self._library_size_enabled:
                self._set_library_size(row.get("section_id"), ident)

        log.debug("Refreshed %d libraries", len(rows))

    def _set_library_size(self, section_id, ident: dict[str, str]) -> None:
        if section_id is None or section_id == "":
            return
        try:
            payload = self._client.get_library_media_info(section_id)
        except Exception as exc:  # noqa: BLE001 - opt-in metric, never fatal
            # Don't take the whole inventory step down because one library's
            # media_info walk hiccupped — log and move on.
            log.warning(
                "library_size lookup failed for section_id=%s: %s",
                section_id, exc,
            )
            return
        size = to_int(payload.get("total_file_size"))
        self._metrics.library_size_bytes.labels(**ident).set(size)

    # -- users ---------------------------------------------------------

    def _refresh_users(self) -> None:
        users = self._client.get_users()
        rows = self._client.get_users_table()

        self._metrics.users_total.set(len(users))
        self._metrics.users_active.set(
            sum(1 for u in users if to_bool(u.get("is_active"), default=True))
        )
        self._metrics.users_home.set(
            sum(1 for u in users if to_bool(u.get("is_home_user")))
        )

        for metric in (
            self._metrics.user_last_seen_timestamp_seconds,
            self._metrics.user_plays,
            self._metrics.user_play_duration_seconds,
        ):
            metric.clear()

        for row in rows:
            user = label_or(row.get("friendly_name"))
            last_seen = to_int(row.get("last_seen"))
            plays = to_int(row.get("plays"))
            duration = to_int(row.get("duration"))

            if last_seen:
                self._metrics.user_last_seen_timestamp_seconds.labels(user=user).set(
                    last_seen
                )
            self._metrics.user_plays.labels(user=user).set(plays)
            self._metrics.user_play_duration_seconds.labels(user=user).set(duration)

        log.debug(
            "Refreshed users: total=%d users_table_rows=%d",
            len(users), len(rows),
        )

    # -- version -------------------------------------------------------

    def _refresh_version(self) -> None:
        info = self._client.get_server_info()
        version = str(info.get("pms_version") or "unknown")
        name = str(info.get("pms_name") or "unknown")
        self._metrics.plex_version_info.info({"version": version, "server_name": name})
