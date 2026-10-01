"""At most one request per interval per host.

LocalRateLimiter works inside one process. RedisRateLimiter shares the budget
across every Celery worker, so adding workers never makes the crawler less polite.
"""

import random
import threading
import time


class LocalRateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next.get(host, 0.0))
            self._next[host] = slot + self.min_interval
        if slot > now:
            time.sleep(slot - now)


class RedisRateLimiter:
    def __init__(self, redis_client, min_interval: float, max_wait: float = 600.0):
        self.redis = redis_client
        self.interval_ms = max(1, int(min_interval * 1000))
        self.max_wait = max_wait

    def wait(self, host: str) -> None:
        key = f"tenderlens:ratelimit:{host}"
        deadline = time.monotonic() + self.max_wait
        while True:
            # SET NX PX: whoever creates the key owns the next slot; the key expires
            # after one interval, freeing the slot for the next caller.
            if self.redis.set(key, "1", nx=True, px=self.interval_ms):
                return
            if time.monotonic() > deadline:
                raise TimeoutError(f"rate limiter wait exceeded {self.max_wait}s for {host}")
            ttl = self.redis.pttl(key)
            time.sleep(max(ttl, 10) / 1000 + random.uniform(0, 0.05))
