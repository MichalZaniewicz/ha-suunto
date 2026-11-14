"""How each Suunto data stream is doing, for Repairs, diagnostics and system health.

The daily update fetches sleep, recovery and workouts side by side and keeps
going when one of them fails: that stream's sensors hold their last values.
Without this, a stream down for hours (a Suunto server hiccup, a changed
export) went unnoticed. Each fetch records here whether it worked; a stream
that has failed without a single success for STREAM_ISSUE_HOURS raises a
Repairs notice (coordinator._update_stream_issues), which goes away by itself
on the next success.

Pure bookkeeping, no Home Assistant imports: one instance per config entry,
shared by both coordinators (__init__.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# A stream failing nonstop for this long gets a Repairs notice.
STREAM_ISSUE_HOURS = 6

# Every stream we fetch: key -> what it is, as the Repairs notice names it.
STREAMS: dict[str, str] = {
    "activity": "24/7 activity (heart rate, steps, energy)",
    "profile": "account profile (BMR, goals)",
    "sleep": "sleep",
    "recovery": "recovery and stress",
    "workouts": "workouts",
    "stats": "lifetime totals",
    "activity_history": "activity history (long-term statistics)",
    "workout_data": "workout details (heart rate, route, laps)",
}


@dataclass
class _Stream:
    successes: int = 0
    failures: int = 0
    # Failures since the last success, and when that run of failures began.
    failing_since: datetime | None = None
    consecutive_failures: int = 0
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_error: str | None = None


@dataclass
class StreamHealth:
    """Per-stream success/failure record since Home Assistant started."""

    _streams: dict[str, _Stream] = field(default_factory=dict)

    def _get(self, name: str) -> _Stream:
        return self._streams.setdefault(name, _Stream())

    def ok(self, name: str, now: datetime) -> None:
        stream = self._get(name)
        stream.successes += 1
        stream.last_success = now
        stream.failing_since = None
        stream.consecutive_failures = 0

    def failed(self, name: str, error: object, now: datetime) -> None:
        stream = self._get(name)
        stream.failures += 1
        stream.consecutive_failures += 1
        stream.last_failure = now
        stream.last_error = str(error)[:300] or type(error).__name__
        if stream.failing_since is None:
            stream.failing_since = now

    def failing(self, now: datetime, hours: float = STREAM_ISSUE_HOURS) -> dict[str, _Stream]:
        """Streams failing nonstop for at least ``hours`` (and more than once)."""
        limit = timedelta(hours=hours)
        return {
            name: stream
            for name, stream in self._streams.items()
            if stream.failing_since is not None
            and stream.consecutive_failures > 1
            and now - stream.failing_since >= limit
        }

    def degraded(self) -> list[str]:
        """Streams whose latest fetch failed, for the system health page."""
        return sorted(
            name for name, stream in self._streams.items() if stream.failing_since is not None
        )

    def known(self) -> list[str]:
        return list(self._streams)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Everything recorded, JSON-ready, for diagnostics."""

        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            name: {
                "successes": stream.successes,
                "failures": stream.failures,
                "consecutive_failures": stream.consecutive_failures,
                "failing_since": iso(stream.failing_since),
                "last_success": iso(stream.last_success),
                "last_failure": iso(stream.last_failure),
                "last_error": stream.last_error,
            }
            for name, stream in sorted(self._streams.items())
        }
