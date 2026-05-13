"""Runtime configuration for the exporter."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""


@dataclass(frozen=True)
class Config:
    """Exporter configuration, normally loaded from environment variables."""

    tautulli_url: str
    api_key: str
    exporter_port: int = 9487
    poll_interval: int = 30
    request_timeout: int = 10
    log_level: str = "INFO"
    log_format: str = "text"
    geoip_enabled: bool = True
    geoip_cache_ttl: int = 3600

    def sanitized(self) -> dict:
        """Return the config as a dict with secrets redacted, for logging."""
        from dataclasses import asdict
        data = asdict(self)
        if data.get("api_key"):
            data["api_key"] = "***"
        return data

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        """Build a Config from environment variables.

        Pass ``env`` to override ``os.environ`` (useful for tests).
        """
        env = env if env is not None else os.environ

        url = env.get("TAUTULLI_URL")
        if not url:
            raise ConfigError("TAUTULLI_URL is required")

        api_key = env.get("TAUTULLI_API_KEY")
        if not api_key:
            raise ConfigError("TAUTULLI_API_KEY is required")

        log_format = env.get("LOG_FORMAT", "text").lower()
        if log_format not in ("text", "json"):
            raise ConfigError(f"LOG_FORMAT must be 'text' or 'json', got {log_format!r}")

        return cls(
            tautulli_url=url.rstrip("/"),
            api_key=api_key,
            exporter_port=_int(env, "EXPORTER_PORT", 9487),
            poll_interval=_int(env, "POLL_INTERVAL", 30),
            request_timeout=_int(env, "REQUEST_TIMEOUT", 10),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            log_format=log_format,
            geoip_enabled=_bool(env, "GEOIP_ENABLED", True),
            geoip_cache_ttl=_int(env, "GEOIP_CACHE_TTL", 3600),
        )


def _int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be a boolean, got {raw!r}")
