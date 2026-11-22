"""Per-IP token-bucket rate limiting (in memory, per instance)."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from fastapi import HTTPException, Request


class TokenBucketLimiter:
    """Each client gets `burst` tokens that refill at `per_minute` tokens a minute."""

    def __init__(
        self,
        per_minute: int,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = 10_000,
    ) -> None:
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._clock = clock
        self._max = max_clients
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, client: str) -> float:
        """Spend one token. Returns 0 if allowed, else seconds until a token is available."""
        now = self._clock()
        tokens, last = self._buckets.get(client, (self._burst, now))
        tokens = min(self._burst, tokens + (now - last) * self._rate)
        if tokens >= 1.0:
            self._store(client, tokens - 1.0, now)
            return 0.0
        self._store(client, tokens, now)
        return (1.0 - tokens) / self._rate if self._rate > 0 else 60.0

    def _store(self, client: str, tokens: float, now: float) -> None:
        if client not in self._buckets and len(self._buckets) >= self._max:
            self._buckets.pop(next(iter(self._buckets)))
        self._buckets[client] = (tokens, now)


def client_ip(request: Request, trust_proxy_headers: bool, hop: str = "last") -> str:
    """The caller's address. Cloud Run appends the real client as the last X-Forwarded-For hop;
    Vercel overwrites the header, so the client is the first (with X-Real-IP as a fallback)."""
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[0] if hop == "first" else hops[-1]
        real = request.headers.get("x-real-ip", "").strip()
        if hop == "first" and real:
            return real
    return request.client.host if request.client else "unknown"


def enforce(
    limiter: TokenBucketLimiter, request: Request, trust_proxy_headers: bool, hop: str = "last"
) -> None:
    """Raise 429 with Retry-After when the caller is over the limit."""
    wait = limiter.check(client_ip(request, trust_proxy_headers, hop))
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail="rate_limited",
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )
