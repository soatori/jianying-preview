"""Per-session lifecycle state for launchers and embedded preview windows."""

from __future__ import annotations

import asyncio
import secrets
import time


class SessionLease:
    def __init__(self, token: str | None = None, ttl_s: float = 15.0) -> None:
        self.token = token or secrets.token_urlsafe(24)
        self.ttl_s = max(float(ttl_s), 3.0)
        self.created_at = time.monotonic()
        self.last_seen = self.created_at
        self.closed = asyncio.Event()

    def accepts(self, token: str | None) -> bool:
        return bool(token) and secrets.compare_digest(str(token), self.token)

    def touch(self, token: str | None) -> bool:
        if not self.accepts(token) or self.closed.is_set():
            return False
        self.last_seen = time.monotonic()
        return True

    def close(self, token: str | None = None) -> bool:
        if token is not None and not self.accepts(token):
            return False
        self.closed.set()
        return True

    async def watch(self) -> None:
        while not self.closed.is_set():
            await asyncio.sleep(min(1.0, self.ttl_s / 3))
            if time.monotonic() - self.last_seen > self.ttl_s:
                self.closed.set()
                return

    def describe(self) -> dict:
        return {"enabled": True, "ttl_s": self.ttl_s,
                "age_s": round(time.monotonic() - self.created_at, 3),
                "idle_s": round(time.monotonic() - self.last_seen, 3),
                "closed": self.closed.is_set()}
