"""Redis-backed rate limiting for externally-facing surfaces.

Closes a real enterprise-readiness gap: the external query-tool gateway
(`/external/v1/*`, `/mcp`) is designed for arbitrary external AI clients to
call over the network, and had no request throttling at all — one
misbehaving or compromised client credential could hammer a governed query
tool without limit. This module also puts `REDIS_URL` to work: it was
already provisioned in `compose.yaml` and `infra/kubernetes/configmap.yaml`
but no application code ever referenced it (verified via grep before this
change) — dead infrastructure sitting next to an unaddressed gap.

Design choices, deliberately conservative:
- Fixed-window counter (INCR + EXPIRE) — simpler and cheaper than a sliding
  window or token bucket, and the small burst error at window boundaries is
  an acceptable trade for an abuse governor rather than a hard billing gate.
- Fails OPEN, not closed. If `REDIS_URL` is unset (local/dev without Redis)
  or Redis is unreachable, requests are allowed through and nothing breaks.
  A rate limiter should never become a new single point of failure for a
  read-only, already-governed gateway that has its own SQL-level guardrails.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover - redis is an optional runtime dependency
    redis = None  # type: ignore[assignment]


_client: Any = None
_client_configured = False


def configure_client(client: Any) -> None:
    """Test/ops hook to inject a specific Redis-compatible client instance."""
    global _client, _client_configured
    _client = client
    _client_configured = True


def reset_client_cache() -> None:
    """Forget any cached/injected client so the next call re-resolves REDIS_URL."""
    global _client, _client_configured
    _client = None
    _client_configured = False


def _get_client() -> Any:
    global _client, _client_configured
    if _client_configured:
        return _client
    _client_configured = True
    url = os.getenv("REDIS_URL")
    if not url or redis is None:
        _client = None
        return None
    try:
        candidate = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        candidate.ping()
        _client = candidate
    except Exception:
        _client = None
    return _client


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


def check_rate_limit(key: str, limit: int, window_seconds: int) -> RateLimitResult:
    """Fixed-window rate limit. See module docstring for the fail-open rationale."""
    client = _get_client()
    if client is None:
        return RateLimitResult(allowed=True, limit=limit, remaining=limit, retry_after_seconds=0)
    window = int(time.time()) // window_seconds
    redis_key = f"datapilot:ratelimit:{key}:{window}"
    try:
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, window_seconds + 1)
        ttl = client.ttl(redis_key)
    except Exception:
        return RateLimitResult(allowed=True, limit=limit, remaining=limit, retry_after_seconds=0)
    remaining = max(0, limit - count)
    retry_after = ttl if isinstance(ttl, int) and ttl > 0 else window_seconds
    return RateLimitResult(allowed=count <= limit, limit=limit, remaining=remaining, retry_after_seconds=retry_after)
