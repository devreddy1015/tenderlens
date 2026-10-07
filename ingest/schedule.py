"""Celery beat entries for crawling: one hourly incremental and one nightly full crawl per
enabled source, staggered so 30+ portals do not all start in the same minute.

Every source is a different host, so politeness per host holds either way (the Redis rate
limiter enforces 1 req/s per host); the stagger spreads the load on our own workers and
database instead. start_crawl skips a source whose previous run is still going.
"""

from celery.schedules import crontab

from ingest.sources import resolve_keys

HOURLY_FIRST_MINUTE = 5  # :05 ... :49, then alerts at :50 and the word list at :40 catch up
HOURLY_WINDOW_MINUTES = 45
NIGHTLY_FIRST = (1, 0)  # 01:00 IST
NIGHTLY_STEP_MINUTES = 4  # 35 sources -> the last full crawl starts at 03:16


def crawl_beat_schedule(sources: list[str] | tuple[str, ...]) -> dict:
    keys = resolve_keys(sources)
    n = max(len(keys), 1)
    schedule = {}
    for i, key in enumerate(keys):
        minute = HOURLY_FIRST_MINUTE + (i * HOURLY_WINDOW_MINUTES) // n
        schedule[f"crawl-incremental-{key}"] = {
            "task": "ingest.tasks.start_crawl",
            "schedule": crontab(minute=minute),
            "kwargs": {"mode": "incremental", "sources": [key]},
        }
        start = NIGHTLY_FIRST[0] * 60 + NIGHTLY_FIRST[1] + i * NIGHTLY_STEP_MINUTES
        schedule[f"crawl-full-{key}"] = {
            "task": "ingest.tasks.start_crawl",
            "schedule": crontab(minute=start % 60, hour=(start // 60) % 24),
            "kwargs": {"mode": "full", "sources": [key]},
        }
    return schedule
