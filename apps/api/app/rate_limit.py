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
- No Redis does not mean no limit. If `REDIS_URL` is unset (local/dev
  without Redis) or Redis is unreachable, an in-process sliding-window log
  takes over, so a missing Redis never turns the external gateway into an
  unthrottled surface (it used to fail open). The in-process limit is per
  replica, so with N replicas the effective ceiling is N x limit -- still a
  real bound, and Redis restores the exact shared limit.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
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


_LOCAL_MAX_KEYS = 10_000
_local_windows: dict[str, deque[float]] = {}
_local_lock = threading.Lock()


def reset_local_windows() -> None:
    """Test/ops hook: forget every in-process sliding window."""
    with _local_lock:
        _local_windows.clear()


def _prune_local(now: float, window_seconds: int) -> None:
    for name in [name for name, hits in _local_windows.items() if not hits or hits[-1] <= now - window_seconds]:
        _local_windows.pop(name, None)
    if len(_local_windows) > _LOCAL_MAX_KEYS:  # still too many live keys: drop the least recently used
        for name in sorted(_local_windows, key=lambda item: _local_windows[item][-1])[: len(_local_windows) - _LOCAL_MAX_KEYS]:
            _local_windows.pop(name, None)


def _local_check(key: str, limit: int, window_seconds: int) -> RateLimitResult:
    """In-process sliding-window log, used whenever Redis is unavailable.

    Only allowed requests are recorded, so a client that keeps retrying while
    limited regains capacity as its oldest accepted requests age out.
    """
    now = time.monotonic()
    with _local_lock:
        hits = _local_windows.get(key)
        if hits is None:
            if len(_local_windows) >= _LOCAL_MAX_KEYS:
                _prune_local(now, window_seconds)
            hits = _local_windows[key] = deque()
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, math.ceil(hits[0] + window_seconds - now)) if hits else window_seconds
            return RateLimitResult(allowed=False, limit=limit, remaining=0, retry_after_seconds=retry_after)
        hits.append(now)
        return RateLimitResult(allowed=True, limit=limit, remaining=max(0, limit - len(hits)), retry_after_seconds=0)


def check_rate_limit(key: str, limit: int, window_seconds: int, local_fallback: bool = True) -> RateLimitResult:
    """Fixed-window limit in Redis; in-process sliding window when Redis is unavailable.

    ``local_fallback=False`` restores the old fail-open behaviour for a caller
    that explicitly prefers availability over throttling.
    """
    client = _get_client()
    if client is None:
        if local_fallback:
            return _local_check(key, limit, window_seconds)
        return RateLimitResult(allowed=True, limit=limit, remaining=limit, retry_after_seconds=0)
    window = int(time.time()) // window_seconds
    redis_key = f"datapilot:ratelimit:{key}:{window}"
    try:
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, window_seconds + 1)
        ttl = client.ttl(redis_key)
    except Exception:
        if local_fallback:
            return _local_check(key, limit, window_seconds)
        return RateLimitResult(allowed=True, limit=limit, remaining=limit, retry_after_seconds=0)
    remaining = max(0, limit - count)
    retry_after = ttl if isinstance(ttl, int) and ttl > 0 else window_seconds
    return RateLimitResult(allowed=count <= limit, limit=limit, remaining=remaining, retry_after_seconds=retry_after)
