"""Verify the poller's OK->DEGRADED->STALE transitions and one-shot stale notification."""
from __future__ import annotations

import threading
from typing import List

import pytest

from ccstatuspanel import poller as poller_mod
from ccstatuspanel.config import Config
from ccstatuspanel.claude_api import UsageFetchError
from ccstatuspanel.models import State, UsageSnapshot


@pytest.fixture
def quick_config():
    cfg = Config()
    cfg.poll.interval_seconds = 10  # validated minimum
    cfg.poll.stale_after_failures = 2
    return cfg


def _disable_intra_cycle_backoff(monkeypatch):
    monkeypatch.setattr(poller_mod, "_INTRA_CYCLE_BACKOFF", ())


def test_ok_after_successful_fetch(monkeypatch, quick_config):
    _disable_intra_cycle_backoff(monkeypatch)

    def _fake_fetch(_cfg):
        return UsageSnapshot(session_pct=0.4, week_pct=0.5, state=State.OK)

    monkeypatch.setattr(poller_mod, "fetch_usage", _fake_fetch)

    snapshots: List[UsageSnapshot] = []
    stales: List[str] = []
    p = poller_mod.Poller(
        quick_config,
        on_snapshot=snapshots.append,
        on_stale=stales.append,
    )
    p._wake = threading.Event()
    p._cycle()

    assert snapshots[-1].state == State.OK
    assert stales == []


def test_degraded_then_stale_after_threshold(monkeypatch, quick_config):
    _disable_intra_cycle_backoff(monkeypatch)

    def _fake_fetch(_cfg):
        raise UsageFetchError("nope")

    monkeypatch.setattr(poller_mod, "fetch_usage", _fake_fetch)

    snapshots: List[UsageSnapshot] = []
    stales: List[str] = []
    p = poller_mod.Poller(
        quick_config,
        on_snapshot=snapshots.append,
        on_stale=stales.append,
    )
    p._wake = threading.Event()

    p._cycle()
    assert snapshots[-1].state == State.DEGRADED
    assert stales == []  # not stale yet

    p._cycle()
    assert snapshots[-1].state == State.STALE
    assert len(stales) == 1  # exactly one notification on transition

    p._cycle()  # additional failures must NOT re-notify
    assert snapshots[-1].state == State.STALE
    assert len(stales) == 1


def test_recovery_resets_failure_counter_and_allows_future_notification(monkeypatch, quick_config):
    _disable_intra_cycle_backoff(monkeypatch)

    behaviour = {"fail": True}

    def _fake_fetch(_cfg):
        if behaviour["fail"]:
            raise UsageFetchError("nope")
        return UsageSnapshot(session_pct=0.3, week_pct=0.4, state=State.OK)

    monkeypatch.setattr(poller_mod, "fetch_usage", _fake_fetch)

    snapshots: List[UsageSnapshot] = []
    stales: List[str] = []
    p = poller_mod.Poller(
        quick_config,
        on_snapshot=snapshots.append,
        on_stale=stales.append,
    )
    p._wake = threading.Event()

    p._cycle(); p._cycle()  # drive into STALE
    assert snapshots[-1].state == State.STALE
    assert len(stales) == 1

    behaviour["fail"] = False
    p._cycle()
    assert snapshots[-1].state == State.OK

    behaviour["fail"] = True
    p._cycle(); p._cycle()  # back to STALE — must notify again
    assert snapshots[-1].state == State.STALE
    assert len(stales) == 2
