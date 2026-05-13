"""Helpers shared by multiple poll steps.

Anything that's reused across steps (numeric coercion, label normalization,
unit conversions) belongs here so each step module can stay tightly focused
on its one responsibility.
"""

from __future__ import annotations

from typing import Protocol


# Tautulli reports session bandwidth in kilobits per second; Prometheus
# convention prefers bytes/s. Centralized here so any step that touches
# bandwidth uses the same conversion.
KBPS_TO_BPS = 1000 // 8


class Step(Protocol):
    """Minimal contract every poll step satisfies.

    ``name`` is used as the ``step`` label on
    ``tautulli_exporter_poll_failures_total`` so an operator can see exactly
    which call failed.
    """

    name: str

    def run(self) -> None: ...


def to_int(value, default: int = 0) -> int:
    """Coerce Tautulli's loosely-typed numeric fields to ``int``.

    Tautulli sometimes returns ints, sometimes numeric strings, sometimes
    empty strings, sometimes ``None``. This collapses all of those into a
    deterministic int (or ``default``).
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def to_float(value, default: float = 0.0) -> float:
    """Coerce loosely-typed numeric fields to ``float``."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_bool(value, default: bool = False) -> bool:
    """Coerce Tautulli's mixed bool/int fields (0/1, ``True``/``False``)."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def label_or(value, default: str = "unknown") -> str:
    """Stringify a label value, replacing missing/empty with ``default``."""
    if value is None or value == "":
        return default
    return str(value)


def session_identity(session: dict) -> dict[str, str]:
    """Common ``(user, title)`` label set used by per-session detail metrics.

    Bundled here so every per-session metric uses identical label values
    and dashboards can join them by ``user``+``title`` reliably.
    """
    return {
        "user": label_or(session.get("friendly_name")),
        "title": label_or(session.get("full_title")),
    }
