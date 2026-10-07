"""robots.txt gate: a crawl run asks the portal's robots.txt before it fetches anything else.

Behaviour follows RFC 9309 section 2.3.1:
  * 2xx: obey the rules for our User-Agent (product token "TenderLens").
  * 4xx: no robots.txt, so no restrictions.
  * 5xx, 429 or a network error: the portal has not answered, which is not permission.
    Use the last good copy if it is at most 30 days old, otherwise skip this run.

A good answer (2xx or 4xx) is cached for 24 hours in the Django cache, so 36 portals crawled
several times a day cost one robots.txt request each per day. The copy is kept for 30 days
as the fallback for the 5xx case.
"""

import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from django.conf import settings
from django.core.cache import cache

from ingest.fetcher import Fetcher, FetchError
from ingest.sources import Source

log = logging.getLogger(__name__)

FRESH_SECONDS = 24 * 3600
KEEP_SECONDS = 30 * 24 * 3600
MAX_BYTES = 500 * 1024  # RFC 9309: parse at least the first 500 KiB


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    message: str  # why; for a refusal this is the run's problem message
    robots_url: str
    status: int | None = None  # HTTP status of the copy that decided
    cached: bool = False  # decided by a cached copy, not a fetch made now


def _key(origin: str) -> str:
    return f"tenderlens:robots:{origin}"


def _cache_get(origin: str) -> dict | None:
    try:
        return cache.get(_key(origin))
    except Exception:  # a cache outage must not crash a crawl; it only costs a fetch
        log.warning("robots cache read failed for %s", origin, exc_info=True)
        return None


def _cache_set(origin: str, copy: dict) -> None:
    try:
        cache.set(_key(origin), copy, KEEP_SECONDS)
    except Exception:
        log.warning("robots cache write failed for %s", origin, exc_info=True)


def check(source: Source, fetcher: Fetcher) -> Verdict:
    """May this source be crawled now? Fetches robots.txt through the crawler's own
    fetcher (same User-Agent, same per-host rate limit) unless a fresh copy is cached."""
    robots_url = f"{source.origin}/robots.txt"
    copy = _cache_get(source.origin)
    if copy and time.time() - copy["fetched_at"] < FRESH_SECONDS:
        return _decide(source, robots_url, copy, cached=True)
    try:
        result = fetcher.get(robots_url)
        status, body, error = result.status, result.body, ""
    except (FetchError, httpx.HTTPError) as exc:
        status, body, error = None, "", str(exc)
    if status is not None and status < 500:
        good = {
            "status": status,
            "body": body[:MAX_BYTES] if 200 <= status < 300 else "",
            "fetched_at": time.time(),
        }
        _cache_set(source.origin, good)
        return _decide(source, robots_url, good)
    error = error or f"HTTP {status}"
    if copy and time.time() - copy["fetched_at"] <= KEEP_SECONDS:
        log.warning(
            "robots.txt %s unreachable (%s); using the copy cached earlier", robots_url, error
        )
        return _decide(source, robots_url, copy, cached=True)
    return Verdict(
        False,
        f"robots.txt at {robots_url} could not be read ({error}) and there is no copy from "
        "the last 30 days, so this run was skipped",
        robots_url,
        status,
    )


def _decide(source: Source, robots_url: str, copy: dict, *, cached: bool = False) -> Verdict:
    status = copy["status"]
    if not 200 <= status < 300:
        return Verdict(
            True, f"robots.txt answered HTTP {status}: no rules", robots_url, status, cached
        )
    parser = RobotFileParser(robots_url)
    parser.parse(copy["body"].splitlines())
    agent = settings.CRAWLER["USER_AGENT"]
    for url in (source.base_url, source.org_index_url):
        if not can_fetch(parser, agent, url):
            return Verdict(
                False,
                f"robots.txt at {robots_url} disallows {url} for {agent.split('/')[0]}; "
                "nothing was crawled",
                robots_url,
                status,
                cached,
            )
    return Verdict(True, "robots.txt allows the crawl", robots_url, status, cached)


def _path(url: str) -> str:
    """The URL's path and query quoted the way robotparser quotes rule paths, so the two
    compare like for like."""
    parsed = urlparse(unquote(url))
    return quote(urlunparse(("", "", parsed.path, parsed.params, parsed.query, ""))) or "/"


def _pattern(rule_path: str) -> re.Pattern:
    """A quoted rule path -> regex: '*' (quoted %2A) matches anything, a final '$' (%24)
    anchors the end."""
    anchored = rule_path.endswith("%24")
    body = rule_path[:-3] if anchored else rule_path
    return re.compile(".*".join(re.escape(part) for part in body.split("%2A")) + "$" * anchored)


def can_fetch(parser: RobotFileParser, agent: str, url: str) -> bool:
    """RFC 9309 matching on robotparser's parsed groups: the longest matching rule wins
    and Allow wins a tie. robotparser's own can_fetch takes the *first* matching rule and
    has no wildcards, so "Allow: /" before "Disallow: /eprocure/" would let us in."""
    entry = next((e for e in parser.entries if e.applies_to(agent)), parser.default_entry)
    if entry is None:
        return True
    target = _path(url)
    best: tuple[int, bool] | None = None
    for line in entry.rulelines:
        if _pattern(line.path).match(target):
            candidate = (len(line.path), line.allowance)
            best = candidate if best is None else max(best, candidate)
    return best is None or best[1]
