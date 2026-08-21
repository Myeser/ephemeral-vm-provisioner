"""Data model for an EC2 instance managed by this tool."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ManagedInstance:
    instance_id: str
    state: str
    instance_type: str
    owner: str
    launch_time: datetime | None
    expires_at: datetime | None
    public_ip: str | None

    @property
    def minutes_remaining(self) -> float | None:
        if self.expires_at is None:
            return None
        delta = self.expires_at - datetime.now(self.expires_at.tzinfo)
        return round(delta.total_seconds() / 60, 1)

    @property
    def is_expired(self) -> bool:
        remaining = self.minutes_remaining
        return remaining is not None and remaining <= 0
