from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class State(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    STALE = "stale"


@dataclass
class UsageSnapshot:
    session_pct: float = 0.0
    week_pct: float = 0.0
    # Per-model weekly cap. Historically Opus-specific (the old `seven_day_opus`
    # bucket); claude.ai now exposes it as a generic model-scoped weekly limit, so
    # `week_scoped_model` names which model it currently applies to (e.g. "Sonnet").
    week_opus_pct: float = 0.0
    week_scoped_model: str = ""
    resets_at: Optional[datetime] = None
    state: State = State.STALE
    error_msg: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consecutive_failures: int = 0

    def time_to_reset_seconds(self, now: Optional[datetime] = None) -> Optional[int]:
        if self.resets_at is None:
            return None
        now = now or datetime.now(timezone.utc)
        delta = (self.resets_at - now).total_seconds()
        return max(0, int(delta))

    def is_usable(self) -> bool:
        return self.state in (State.OK, State.DEGRADED)
