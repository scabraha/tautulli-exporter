"""Tiered polling scheduler.

Three independent monotonic deadlines, one thread, one shutdown event.
The activity tier doubles as the exporter's heartbeat: it owns the
`tautulli_up`, `tautulli_exporter_poll_duration_seconds`, and
`tautulli_exporter_last_successful_poll_timestamp_seconds` gauges.
Slower tiers report their failures via `tautulli_exporter_poll_failures_total`
but don't affect heartbeat semantics — a 5-minute inventory blip
shouldn't flap the up/down indicator.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import requests

from .metrics import Metrics
from .steps._common import Step

log = logging.getLogger(__name__)


# Hard floor / ceiling for the scheduler's idle sleep. The floor keeps a
# misbehaving step from spinning the loop; the ceiling caps shutdown
# latency at 1 second even if every deadline is far in the future.
_MIN_SLEEP_SECONDS = 0.05
_MAX_SLEEP_SECONDS = 1.0


@dataclass(frozen=True)
class Tier:
    """A group of steps that share a polling cadence.

    ``heartbeat=True`` marks the tier whose successes/failures drive the
    exporter's overall up/down indicator. Exactly one tier should set
    this; the rest just emit per-step failure metrics.
    """

    name: str
    interval_seconds: int
    steps: Sequence[Step]
    heartbeat: bool = False


@dataclass
class _TierState:
    """Mutable per-tier scheduling bookkeeping."""

    next_run_monotonic: float = 0.0
    consecutive_failures: int = 0
    has_succeeded_once: bool = False


class TieredPoller:
    """Run multiple groups of poll steps on independent cadences."""

    def __init__(
        self,
        metrics: Metrics,
        tiers: Sequence[Tier],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        if not tiers:
            raise ValueError("TieredPoller requires at least one tier")
        if sum(1 for t in tiers if t.heartbeat) != 1:
            raise ValueError("Exactly one tier must be marked heartbeat=True")

        self._metrics = metrics
        self._tiers = list(tiers)
        self._clock = clock
        self._wall_clock = wall_clock
        # Initial deadlines all expire immediately so the first iteration
        # of `run_forever` runs every tier — same first-poll behavior as
        # the legacy single-loop poller.
        now = clock()
        self._state: dict[str, _TierState] = {
            tier.name: _TierState(next_run_monotonic=now) for tier in self._tiers
        }

    # -- public scheduler API ------------------------------------------

    def poll_due(self) -> list[str]:
        """Run every tier whose deadline has passed.

        Returns the names of tiers that ran this call (useful for tests).
        """
        ran: list[str] = []
        for tier in self._tiers:
            state = self._state[tier.name]
            if self._clock() >= state.next_run_monotonic:
                self._run_tier(tier)
                # Reschedule from `now`, not from the previous deadline,
                # so a slow run can't pile up backlog.
                state.next_run_monotonic = self._clock() + tier.interval_seconds
                ran.append(tier.name)
        return ran

    def seconds_until_next(self) -> float:
        """Wall-clock seconds until the next tier becomes due."""
        return max(0.0, min(s.next_run_monotonic for s in self._state.values()) - self._clock())

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        """Schedule and run tiers in a loop until ``stop_event`` is set."""
        stop_event = stop_event or threading.Event()
        log.info(
            "TieredPoller starting (%s)",
            ", ".join(f"{t.name}={t.interval_seconds}s" for t in self._tiers),
        )
        while not stop_event.is_set():
            self.poll_due()
            wait = min(_MAX_SLEEP_SECONDS, max(_MIN_SLEEP_SECONDS, self.seconds_until_next()))
            stop_event.wait(wait)
        log.info("TieredPoller stopped")

    # -- internals -----------------------------------------------------

    def _run_tier(self, tier: Tier) -> None:
        started = self._clock()
        failures: list[tuple[str, BaseException]] = []
        for step in tier.steps:
            try:
                step.run()
            except BaseException as exc:  # noqa: BLE001 - want to keep going
                failures.append((step.name, exc))
                self._metrics.poll_failures.labels(step=step.name).inc()
                self._log_step_failure(tier, step, exc)
        duration = self._clock() - started

        if tier.heartbeat:
            self._update_heartbeat(tier, failures, duration)

    def _log_step_failure(self, tier: Tier, step: Step, exc: BaseException) -> None:
        if isinstance(exc, requests.HTTPError):
            log.error("[%s] step '%s' failed: %s", tier.name, step.name, exc)
            log.debug("HTTPError details", exc_info=(type(exc), exc, exc.__traceback__))
        else:
            log.error(
                "[%s] step '%s' failed",
                tier.name, step.name,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    def _update_heartbeat(
        self,
        tier: Tier,
        failures: list[tuple[str, BaseException]],
        duration: float,
    ) -> None:
        state = self._state[tier.name]
        self._metrics.poll_duration.set(duration)

        if failures:
            self._metrics.up.set(0)
            state.consecutive_failures += 1
            return

        # Success path.
        self._metrics.up.set(1)
        self._metrics.last_successful_poll.set(self._wall_clock())

        if not state.has_succeeded_once:
            state.has_succeeded_once = True
            log.info(
                "First successful poll cycle in %.2fs; exporter is healthy",
                duration,
            )
        elif state.consecutive_failures > 0:
            log.info(
                "Recovered after %d consecutive failures (poll took %.2fs)",
                state.consecutive_failures, duration,
            )
        else:
            log.debug("Poll cycle completed in %.2fs", duration)
        state.consecutive_failures = 0
