from datetime import datetime, timedelta, timezone

from ccstatuspanel.models import State, UsageSnapshot


def test_default_snapshot_is_stale():
    s = UsageSnapshot()
    assert s.state == State.STALE
    assert s.is_usable() is False
    assert s.time_to_reset_seconds() is None


def test_time_to_reset_floors_at_zero():
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    s = UsageSnapshot(state=State.OK, resets_at=past)
    assert s.time_to_reset_seconds() == 0


def test_time_to_reset_returns_seconds():
    future = datetime.now(timezone.utc) + timedelta(hours=2, minutes=30)
    s = UsageSnapshot(state=State.OK, resets_at=future)
    assert 9000 - 5 <= s.time_to_reset_seconds() <= 9000 + 5


def test_is_usable_true_for_ok_and_degraded():
    assert UsageSnapshot(state=State.OK).is_usable()
    assert UsageSnapshot(state=State.DEGRADED).is_usable()
    assert not UsageSnapshot(state=State.STALE).is_usable()
