"""Logging setup for the exporter.

Supports two output formats:

* ``text`` (default) — human readable, one line per record, suitable for
  ``docker logs`` and ``journalctl``.
* ``json`` — one JSON object per line, suitable for log aggregators
  (Loki, CloudWatch, Splunk, ELK).

Also turns up ``urllib3`` to ``WARNING`` so HTTP retries surface in the
operator's log without bringing in every TLS handshake at DEBUG.
"""

from __future__ import annotations

import datetime as dt
import json
import logging


class JsonFormatter(logging.Formatter):
    """Minimal JSON line formatter — no extra dependencies."""

    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc)
                            .isoformat(timespec="milliseconds")
                            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Surface anything passed via logger.<level>(..., extra={...})
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure the root logger.

    Idempotent: replaces any existing handlers so repeated calls (in tests,
    or after a SIGHUP-style reload) don't stack handlers.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    root.addHandler(handler)
    root.setLevel(level.upper())

    # urllib3 is silent at INFO; bump to WARNING so its retry messages are
    # visible to operators without enabling every TLS handshake at DEBUG.
    logging.getLogger("urllib3").setLevel(
        max(logging.WARNING, logging.getLogger().level)
    )
