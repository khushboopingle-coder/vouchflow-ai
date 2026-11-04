"""
Rate limit per API key (Phase 4).

A sliding window kept in memory: at most `limit` calls per `window` seconds for each key.
It protects the (slow, AI-using) ingest endpoint from loops and mistakes in an automation.
Note: the counters live in one server process; with several server processes each would
count separately. Restarting the server resets them.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException, status

from backend.config import settings

WINDOW_SECONDS = 60
_calls: Dict[int, Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def check_rate_limit(key_id: int, limit: int = None, window: int = WINDOW_SECONDS) -> None:
    """Counts one call for this key, or raises 429 (with a Retry-After header)."""
    limit = settings.INGEST_RATE_LIMIT_PER_MINUTE if limit is None else limit
    now = time.monotonic()
    with _lock:
        calls = _calls[key_id]
        while calls and now - calls[0] >= window:
            calls.popleft()
        if len(calls) >= limit:
            retry_after = max(1, int(window - (now - calls[0])) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests for this API key (limit {limit} per minute). "
                       f"Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
        calls.append(now)


def reset() -> None:
    """Forget all counters (used by tests)."""
    with _lock:
        _calls.clear()
