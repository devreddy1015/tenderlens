"""HTTP fetching only. Parsing lives in ingest/parsers; nothing here understands HTML."""

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.utils import timezone

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """The request failed after all in-process attempts."""


@dataclass
class FetchResult:
    url: str
    status: int
    body: str
    fetched_at: datetime


class Fetcher:
    """httpx client with timeouts, a rate limiter, and retries with exponential backoff.

    The cookie jar is the portal session: GePNIC links are only valid inside the
    session that produced them, so a crawl uses one Fetcher end to end, and Celery
    tasks hand the cookies along (see export_cookies / load_cookies).
    """

    def __init__(
        self,
        rate_limiter,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
        max_attempts: int | None = None,
        backoff_base: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep=None,
    ):
        conf = settings.CRAWLER
        self.rate_limiter = rate_limiter
        self.max_attempts = max_attempts or conf["MAX_ATTEMPTS"]
        self.backoff_base = backoff_base
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))
        self.client = httpx.Client(
            headers={
                "User-Agent": user_agent or conf["USER_AGENT"],
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-IN,en;q=0.8",
            },
            timeout=httpx.Timeout(timeout or conf["TIMEOUT_SECONDS"], connect=10.0),
            follow_redirects=True,
            transport=transport,
        )

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def export_cookies(self) -> dict[str, str]:
        return {c.name: c.value for c in self.client.cookies.jar}

    def load_cookies(self, cookies: dict[str, str], domain: str) -> None:
        self.client.cookies.clear()
        for name, value in cookies.items():
            self.client.cookies.set(name, value, domain=domain)

    def reset_session(self) -> None:
        self.client.cookies.clear()

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), 120.0)
        return self.backoff_base * (2 ** (attempt - 1)) + random.uniform(0, self.backoff_base)

    def get(self, url: str, *, referer: str | None = None) -> FetchResult:
        host = urlsplit(url).hostname or ""
        headers = {"Referer": referer} if referer else None
        last_error: str = ""
        for attempt in range(1, self.max_attempts + 1):
            self.rate_limiter.wait(host)
            try:
                resp = self.client.get(url, headers=headers)
            except httpx.TransportError as exc:  # timeouts, resets, DNS
                last_error = f"{type(exc).__name__}: {exc}"
                retry_after = None
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    return FetchResult(
                        url=url, status=resp.status_code, body=resp.text, fetched_at=timezone.now()
                    )
                last_error = f"HTTP {resp.status_code}"
                retry_after = resp.headers.get("Retry-After")
            if attempt < self.max_attempts:
                delay = self._backoff(attempt, retry_after)
                log.warning(
                    "fetch %s failed (%s), retry %d in %.1fs", url, last_error, attempt, delay
                )
                self._sleep(delay)
        raise FetchError(f"{url}: {last_error} after {self.max_attempts} attempts")
