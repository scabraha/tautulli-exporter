import json
import logging

import pytest

from tautulli_exporter.logging_setup import JsonFormatter, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)


def test_setup_text_format(capsys):
    setup_logging("INFO", "text")
    logging.getLogger("test").info("hello %s", "world")
    captured = capsys.readouterr()
    assert "hello world" in captured.err
    assert "INFO" in captured.err


def test_setup_json_format(capsys):
    setup_logging("INFO", "json")
    logging.getLogger("svc").info("hello %s", "world")
    line = capsys.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "svc"
    assert payload["message"] == "hello world"
    assert payload["ts"].endswith("Z")


def test_setup_is_idempotent():
    setup_logging("INFO", "text")
    setup_logging("DEBUG", "json")
    assert len(logging.getLogger().handlers) == 1
    assert logging.getLogger().level == logging.DEBUG


def test_json_formatter_includes_extras():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        "svc", logging.INFO, __file__, 1, "msg", None, None
    )
    record.user = "alice"
    record.session_id = "xyz"
    payload = json.loads(formatter.format(record))
    assert payload["user"] == "alice"
    assert payload["session_id"] == "xyz"


def test_json_formatter_includes_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord(
            "svc", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    payload = json.loads(formatter.format(record))
    assert "ValueError: boom" in payload["exception"]


def test_urllib3_logger_clamped_to_warning_or_above():
    setup_logging("DEBUG", "text")
    assert logging.getLogger("urllib3").level >= logging.WARNING
