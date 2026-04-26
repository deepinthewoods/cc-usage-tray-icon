from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .claude_api import (
    AuthExpiredError,
    CookieDiscoveryError,
    UsageFetchError,
    fetch_usage,
)
from .config import Config
from .models import State, UsageSnapshot

log = logging.getLogger(__name__)


# Backoff in seconds applied within one poll cycle. Last entry must be < interval - margin.
_INTRA_CYCLE_BACKOFF = (5, 15, 45)


class Poller:
    """Background polling thread with OK/DEGRADED/STALE state machine.

    Notification callback fires exactly once on each OK/DEGRADED -> STALE transition.
    """

    def __init__(
        self,
        config: Config,
        on_snapshot: Callable[[UsageSnapshot], None],
        on_stale: Callable[[str], None],
    ) -> None:
        self._config = config
        self._on_snapshot = on_snapshot
        self._on_stale = on_stale
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0
        self._last_snapshot = UsageSnapshot(state=State.STALE, error_msg="not yet polled")
        self._announced_stale = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ccstatuspanel-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def trigger_now(self) -> None:
        """Wake the poller for an immediate refresh — best effort."""
        # Setting and clearing the stop event would be wrong; instead we use a separate event.
        self._wake.set()  # type: ignore[attr-defined]

    def _run(self) -> None:
        self._wake = threading.Event()
        # Initial poll immediately
        self._cycle()
        while not self._stop.is_set():
            interval = max(10, int(self._config.poll.interval_seconds))
            triggered = self._wake.wait(timeout=interval)
            if self._stop.is_set():
                return
            self._wake.clear()
            self._cycle(force=triggered)

    def _cycle(self, *, force: bool = False) -> None:
        threshold = max(1, int(self._config.poll.stale_after_failures))

        for attempt, extra_wait in enumerate((0,) + _INTRA_CYCLE_BACKOFF):
            if self._stop.is_set():
                return
            if extra_wait:
                if self._stop.wait(extra_wait):
                    return
            try:
                snapshot = fetch_usage(self._config.browser)
                snapshot.consecutive_failures = 0
                snapshot.fetched_at = datetime.now(timezone.utc)
                self._consecutive_failures = 0
                self._announced_stale = False
                self._last_snapshot = snapshot
                self._on_snapshot(snapshot)
                return
            except (AuthExpiredError, CookieDiscoveryError, UsageFetchError) as e:
                log.warning("Poll attempt %d failed: %s", attempt + 1, e)
                last_error = e
            except Exception as e:  # network glitch, DNS, libsecret hiccup
                log.warning("Poll attempt %d failed (transport): %s", attempt + 1, e)
                last_error = e

        # All attempts in this cycle failed.
        self._consecutive_failures += 1
        log.info("Cycle failed; consecutive_failures=%d", self._consecutive_failures)

        if self._consecutive_failures >= threshold:
            new_state = State.STALE
        else:
            new_state = State.DEGRADED

        keep_values = self._last_snapshot.is_usable() and new_state == State.DEGRADED
        snapshot = UsageSnapshot(
            session_pct=self._last_snapshot.session_pct if keep_values else 0.0,
            week_pct=self._last_snapshot.week_pct if keep_values else 0.0,
            week_opus_pct=self._last_snapshot.week_opus_pct if keep_values else 0.0,
            resets_at=self._last_snapshot.resets_at if keep_values else None,
            state=new_state,
            error_msg=str(last_error),
            fetched_at=datetime.now(timezone.utc),
            consecutive_failures=self._consecutive_failures,
        )
        self._last_snapshot = snapshot
        self._on_snapshot(snapshot)

        if new_state == State.STALE and not self._announced_stale:
            self._announced_stale = True
            self._on_stale(str(last_error))
