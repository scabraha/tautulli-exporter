"""Tests for `steps/_common.py` helpers."""

from tautulli_exporter.steps._common import (
    KBPS_TO_BPS,
    label_or,
    session_identity,
    to_bool,
    to_float,
    to_int,
)


def test_kbps_to_bps_is_125():
    """8000 kbps == 1_000_000 bytes/s; the constant must hold that ratio."""
    assert 8000 * KBPS_TO_BPS == 1_000_000


def test_to_int_handles_strings_and_floats():
    assert to_int(42) == 42
    assert to_int("42") == 42
    assert to_int("42.7") == 42
    assert to_int(42.9) == 42
    assert to_int(None) == 0
    assert to_int("") == 0
    assert to_int("nope") == 0
    assert to_int("nope", default=-1) == -1


def test_to_float_coerces_or_defaults():
    assert to_float("3.14") == 3.14
    assert to_float(2) == 2.0
    assert to_float(None) == 0.0
    assert to_float("nope", default=-1.0) == -1.0


def test_to_bool_handles_int_and_string_forms():
    assert to_bool(1) is True
    assert to_bool(0) is False
    assert to_bool(True) is True
    assert to_bool("1") is True
    assert to_bool("true") is True
    assert to_bool("YES") is True
    assert to_bool("0") is False
    assert to_bool("off") is False
    assert to_bool(None) is False
    assert to_bool(None, default=True) is True
    assert to_bool("garbage") is False


def test_label_or_replaces_missing_with_default():
    assert label_or("alice") == "alice"
    assert label_or(None) == "unknown"
    assert label_or("") == "unknown"
    assert label_or(0) == "0"  # 0 is not "missing"
    assert label_or(None, default="anon") == "anon"


def test_session_identity_picks_friendly_name_and_full_title():
    session = {"friendly_name": "alice", "full_title": "Inception"}
    assert session_identity(session) == {"user": "alice", "title": "Inception"}


def test_session_identity_falls_back_when_fields_missing():
    assert session_identity({}) == {"user": "unknown", "title": "unknown"}
