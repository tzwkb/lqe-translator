"""One persisted wall-clock allowance for the whole workflow, including resumes."""
from __future__ import annotations

from datetime import datetime, timezone


def remaining_seconds(state: dict, *, now: datetime | None = None) -> float | None:
    maximum = state["policy"].get("max_seconds")
    if maximum is None:  # Existing frozen jobs retain their original policy.
        return None
    started = datetime.fromisoformat(state["started_at"])
    current = now or datetime.now(timezone.utc)
    return max(0.0, maximum - max(0.0, (current - started).total_seconds()))
