import pytest

from ccstatuspanel.claude_api import (
    UsageFetchError,
    _coerce_pct,
    _parse_iso,
    parse_usage_payload,
)
from ccstatuspanel.models import State


def test_coerce_pct_treats_value_as_percent():
    # The API always returns utilization as 0-100 percent — never a fraction.
    assert _coerce_pct(0) == 0.0
    assert _coerce_pct(1) == 0.01      # 1% — used to be wrongly 100%
    assert _coerce_pct(0.5) == 0.005   # 0.5% — used to be wrongly 50%
    assert _coerce_pct(50) == 0.5
    assert _coerce_pct(100) == 1.0
    assert _coerce_pct(150) == 1.0     # clamped
    assert _coerce_pct(-0.1) == 0.0    # clamped
    assert _coerce_pct("nope") == 0.0  # type: ignore[arg-type]
    assert _coerce_pct(None) == 0.0    # type: ignore[arg-type]


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
    # Real shape observed from claude.ai/api/organizations/{org}/usage —
    # utilization is always 0-100 percent, never a fraction.
    payload = {
        "five_hour": {"utilization": 47.0, "resets_at": "2026-04-26T15:30:00Z"},
        "seven_day": {"utilization": 62.0},
        "seven_day_opus": {"utilization": 10.0},
    }
    snap = parse_usage_payload(payload)
    assert snap.state == State.OK
    assert snap.session_pct == 0.47
    assert snap.week_pct == 0.62
    assert snap.week_opus_pct == 0.10
    assert snap.resets_at is not None


def test_parse_usage_payload_low_utilization_is_low():
    # Regression: at 1% usage the icon used to wrongly display 100%.
    payload = {
        "five_hour": {"utilization": 1.0, "resets_at": "2026-04-27T15:30:00Z"},
        "seven_day": {"utilization": 0.5},
    }
    snap = parse_usage_payload(payload)
    assert snap.session_pct == 0.01
    assert snap.week_pct == 0.005


def test_parse_usage_payload_missing_fields_uses_zero():
    snap = parse_usage_payload({"five_hour": {}, "seven_day": {}})
    assert snap.session_pct == 0.0
    assert snap.week_pct == 0.0
    assert snap.resets_at is None


def test_parse_usage_payload_prefers_limits_array():
    # New schema: top-level seven_day_opus is null; the model-scoped weekly cap
    # now lives in limits[] as a "weekly_scoped" entry.
    payload = {
        "five_hour": {"utilization": 15.0, "resets_at": "2026-06-29T00:10:00Z"},
        "seven_day": {"utilization": 24.0},
        "seven_day_opus": None,
        "limits": [
            {"kind": "session", "percent": 15, "resets_at": "2026-06-29T00:10:00Z"},
            {"kind": "weekly_all", "percent": 24, "is_active": True},
            {"kind": "weekly_scoped", "percent": 7,
             "scope": {"model": {"display_name": "Sonnet"}}},
        ],
    }
    snap = parse_usage_payload(payload)
    assert snap.state == State.OK
    assert snap.session_pct == 0.15
    assert snap.week_pct == 0.24
    assert snap.week_opus_pct == 0.07
    assert snap.week_scoped_model == "Sonnet"
    assert snap.resets_at is not None


def test_parse_usage_payload_limits_without_scoped_entry():
    payload = {
        "limits": [
            {"kind": "session", "percent": 5, "resets_at": "2026-06-29T00:10:00Z"},
            {"kind": "weekly_all", "percent": 8},
        ],
    }
    snap = parse_usage_payload(payload)
    assert snap.session_pct == 0.05
    assert snap.week_pct == 0.08
    assert snap.week_opus_pct == 0.0
    assert snap.week_scoped_model == ""


def test_parse_usage_payload_legacy_opus_sets_model_name():
    payload = {
        "five_hour": {"utilization": 47.0, "resets_at": "2026-04-26T15:30:00Z"},
        "seven_day": {"utilization": 62.0},
        "seven_day_opus": {"utilization": 10.0},
    }
    snap = parse_usage_payload(payload)
    assert snap.week_opus_pct == 0.10
    assert snap.week_scoped_model == "Opus"


def test_parse_usage_payload_rejects_non_object_root():
    with pytest.raises(UsageFetchError):
        parse_usage_payload("not an object")  # type: ignore[arg-type]


def test_parse_usage_payload_rejects_bad_subobjects():
    with pytest.raises(UsageFetchError):
        parse_usage_payload({"five_hour": "wrong type", "seven_day": {}})
