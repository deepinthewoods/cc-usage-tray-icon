import pytest

from ccstatuspanel.claude_api import (
    UsageFetchError,
    _coerce_pct,
    _parse_iso,
    parse_usage_payload,
)
from ccstatuspanel.models import State


def test_coerce_pct_handles_fraction_and_percent():
    assert _coerce_pct(0.5) == 0.5
    assert _coerce_pct(50) == 0.5
    assert _coerce_pct(150) == 1.0
    assert _coerce_pct(-0.1) == 0.0
    assert _coerce_pct("nope") == 0.0  # type: ignore[arg-type]
    assert _coerce_pct(None) == 0.0  # type: ignore[arg-type]


def test_parse_iso_handles_z_suffix():
    dt = _parse_iso("2026-04-26T15:30:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.hour == 15 and dt.minute == 30


def test_parse_iso_returns_none_on_garbage():
    assert _parse_iso("not-a-date") is None
    assert _parse_iso("") is None
    assert _parse_iso(None) is None  # type: ignore[arg-type]


def test_parse_usage_payload_happy_path():
    payload = {
        "five_hour": {"utilization": 0.47, "resets_at": "2026-04-26T15:30:00Z"},
        "seven_day": {"utilization": 0.62},
        "seven_day_opus": {"utilization": 0.10},
    }
    snap = parse_usage_payload(payload)
    assert snap.state == State.OK
    assert snap.session_pct == 0.47
    assert snap.week_pct == 0.62
    assert snap.week_opus_pct == 0.10
    assert snap.resets_at is not None


def test_parse_usage_payload_accepts_percent_form():
    payload = {
        "five_hour": {"utilization": 47, "resets_at": "2026-04-26T15:30:00Z"},
        "seven_day": {"utilization": 62},
    }
    snap = parse_usage_payload(payload)
    assert snap.session_pct == 0.47
    assert snap.week_pct == 0.62


def test_parse_usage_payload_missing_fields_uses_zero():
    snap = parse_usage_payload({"five_hour": {}, "seven_day": {}})
    assert snap.session_pct == 0.0
    assert snap.week_pct == 0.0
    assert snap.resets_at is None


def test_parse_usage_payload_rejects_non_object_root():
    with pytest.raises(UsageFetchError):
        parse_usage_payload("not an object")  # type: ignore[arg-type]


def test_parse_usage_payload_rejects_bad_subobjects():
    with pytest.raises(UsageFetchError):
        parse_usage_payload({"five_hour": "wrong type", "seven_day": {}})
