"""The adapter interface every historical-award source implements, and the machinery they
share: polite cached downloads, normalisation, and an idempotent bulk upsert that records
provenance in a DatasetImport row.

An adapter only knows its source's format. It yields AwardRow objects; everything derived
(year, ratio, sector, buyer/winner keys, amounts in today's rupees) is computed here, the
same way for every source, so the model never sees two sources disagree on a definition.
"""

import hashlib
import logging
import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from intel.models import RATIO_MAX, RATIO_MIN, DatasetImport, HistoricalAward
from intel.prices import Deflator
from tenders.resolution import normalise
from tenders.sectors import SECTOR_BY_SLUG, classify

log = logging.getLogger(__name__)

RAW_DIR = Path(settings.BASE_DIR) / "data" / "intel" / "raw"
BATCH = 1000
CATEGORIES = {c.value for c in HistoricalAward.Category}
METHODS = {m.value for m in HistoricalAward.Method}


@dataclass
class AwardRow:
    """One awarded contract as an adapter sees it. Amounts in `currency`, as published."""

    source_id: str
    country: str = "IN"
    state: str = ""
    district: str = ""
    buyer: str = ""
    title: str = ""
    category: str = ""  # works | goods | services | consultancy | ""
    sector: str = ""  # tenders.sectors slug; "" = classify from title/category
    method: str = ""  # HistoricalAward.Method value or ""
    currency: str = "INR"
    estimated_value: Decimal | float | None = None
    award_value: Decimal | float | None = None
    num_bidders: int | None = None
    bids: list[float] | None = None  # every bid amount, same currency
    winner: str = ""
    tender_date: date | None = None
    award_date: date | None = None
    # Only when the source has a year but no date (e.g. a sanction year); dates win.
    year: int | None = None
    url: str = ""
    tender_id: int | None = None  # tenders.Tender pk when matched
    organization_id: int | None = None
    shared: bool = True


class ImportContext:
    """What an adapter gets to work with: options, a polite HTTP client with a download
    cache, and a place to record which files it read."""

    def __init__(
        self,
        source: "Source",
        *,
        limit: int | None = None,
        since: int | None = None,
        file: str | None = None,
        refresh: bool = False,
        client: httpx.Client | None = None,
        min_interval: float | None = None,
    ):
        self.source = source
        self.limit = limit
        self.since = since
        self.file = Path(file) if file else None
        self.refresh = refresh
        self.files: list[dict] = []
        self.cache_dir = RAW_DIR / source.key
        self.min_interval = (
            source.min_interval_seconds if min_interval is None else min_interval  # tests pass 0
        )
        self._last_request = 0.0
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(120, connect=20),
            follow_redirects=True,
            headers={"User-Agent": settings.CRAWLER["USER_AGENT"]},
        )

    def _wait(self) -> None:
        delay = self.min_interval - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()

    def get(self, url: str, *, params: dict | None = None, attempts: int = 4) -> httpx.Response:
        """GET with the source's rate limit and retries on 429/5xx/transport errors."""
        for attempt in range(1, attempts + 1):
            self._wait()
            try:
                resp = self.client.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt == attempts:
                    raise
                log.warning("%s: %s (attempt %s)", url, exc, attempt)
            else:
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()
                    return resp
                if attempt == attempts:
                    resp.raise_for_status()
                log.warning("%s: HTTP %s (attempt %s)", url, resp.status_code, attempt)
            time.sleep(min(60, 2**attempt) if self.min_interval else 0)
        raise RuntimeError("unreachable")

    def download(self, url: str, name: str | None = None) -> Path:
        """Streams `url` into the cache (once; --refresh re-downloads) and records its
        sha256. Returns the local path."""
        name = name or re.sub(r"[^\w.-]+", "_", url.rsplit("/", 1)[-1])[:150] or "download"
        path = self.cache_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.refresh or not path.exists():
            tmp = path.with_suffix(path.suffix + ".part")
            self._wait()
            with self.client.stream("GET", url) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes(1 << 20):
                        fh.write(chunk)
            tmp.replace(path)
        self.record_file(url, path)
        return path

    def record_file(self, url: str, path: Path) -> None:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        self.files.append({"url": url, "sha256": h.hexdigest(), "bytes": path.stat().st_size})


class Source:
    """Subclass, set the class attributes, implement rows(), and decorate with @register.
    Adapters live in intel/sources/<name>.py and are discovered automatically."""

    key: ClassVar[str]
    name: ClassVar[str]
    url: ClassVar[str]  # landing page, shown on /api/intel/coverage
    license: ClassVar[str]
    # "outcomes": has award values (and ideally estimates/bids); "history": contracts
    # without a bid outcome (market history, competitor radar).
    kind: ClassVar[str] = "outcomes"
    min_interval_seconds: ClassVar[float] = 1.0

    def rows(self, ctx: ImportContext) -> Iterator[AwardRow]:
        raise NotImplementedError


REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    if cls.key in REGISTRY and REGISTRY[cls.key] is not cls:
        raise ValueError(f"duplicate intel source key {cls.key!r}")
    REGISTRY[cls.key] = cls
    return cls


# --- parsing helpers shared by adapters ---------------------------------------------------

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def parse_amount(text, *, unit: str = "") -> Decimal | None:
    """'₹ 4,91,87,000.00' / '1,874,075' / '12.5 Cr' -> Decimal; None for blank, NA or 0.
    `unit` ("lakh" or "crore") scales a bare number published in that unit."""
    if text is None:
        return None
    if isinstance(text, int | float | Decimal):
        value = Decimal(str(text))
    else:
        s = str(text).strip().lower().replace(",", "")
        m = _NUM.search(s)
        if not m:
            return None
        try:
            value = Decimal(m.group())
        except InvalidOperation:
            return None
        if re.search(r"\bcr(ore)?s?\b", s):
            unit = "crore"
        elif re.search(r"\b(lakh|lac|lacs|lakhs)\b", s):
            unit = "lakh"
    value *= {"crore": Decimal(10**7), "lakh": Decimal(10**5)}.get(unit, Decimal(1))
    return value if value > 0 else None


# CPV (EU Common Procurement Vocabulary) division/group -> TenderLens sector, longest
# prefix first. Used by TED and by OCDS publishers that classify items with CPV.
CPV_SECTORS = [
    ("45233", "roads"),
    ("45221", "roads"),
    ("45234", "roads"),  # railways
    ("45231", "water"),
    ("45232", "water"),
    ("45240", "water"),
    ("45247", "water"),
    ("45252", "water"),
    ("4531", "electrical"),
    ("4533", "water"),  # plumbing
    ("45", "buildings"),
    ("904", "water"),  # sewage
    ("909", "facility"),  # cleaning
    ("90", "facility"),
    ("79710", "security"),
    ("79714", "security"),
    ("795", "facility"),
    ("796", "facility"),
    ("555", "facility"),
    ("77", "facility"),
    ("71", "consultancy"),
    ("73", "consultancy"),
    ("79", "consultancy"),
    ("72", "it"),
    ("48", "it"),
    ("30", "it"),
    ("32", "it"),
    ("33", "health"),
    ("85", "health"),
    ("38", "lab"),
    ("35", "security"),
    ("09", "electrical"),
    ("31", "electrical"),
    ("65", "electrical"),  # utilities
    ("34", "transport"),
    ("60", "transport"),
    ("63", "transport"),
    ("50", "facility"),  # repair and maintenance services
]


def cpv_sector(cpv: str | None) -> str:
    code = re.sub(r"\D", "", str(cpv or ""))
    for prefix, sector in CPV_SECTORS:
        if code.startswith(prefix):
            return sector
    return "supplies" if code[:2] in {"03", "14", "15", "18", "19", "22", "24", "39", "44"} else ""


# --- normalisation and upsert -------------------------------------------------------------


def _decimal(v) -> Decimal | None:
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d > 0 else None


def to_model(row: AwardRow, source_key: str, deflator: Deflator) -> HistoricalAward | None:
    """AwardRow -> unsaved HistoricalAward with every derived column filled. None when the
    row is unusable (no id, or no amount at all)."""
    est, award = _decimal(row.estimated_value), _decimal(row.award_value)
    if not row.source_id or (est is None and award is None):
        return None
    day = row.award_date or row.tender_date
    year = day.year if day else row.year
    ratio = None
    if est and award:
        r = float(award / est)
        ratio = round(r, 6) if RATIO_MIN <= r <= RATIO_MAX else None
    category = row.category if row.category in CATEGORIES else ""
    sector = row.sector if row.sector in SECTOR_BY_SLUG else ""
    if not sector and row.title and row.country == "IN":
        # The keyword rules are English; foreign-language titles rely on the adapter's
        # own classification (CPV) instead of guessing.
        sector = classify(row.title, "", category.capitalize())
    country = (row.country or "IN").upper()[:2]
    currency = (row.currency or "INR").upper()[:3]
    bids = sorted(float(b) for b in row.bids if b and float(b) > 0) if row.bids else None
    num_bidders = row.num_bidders
    if num_bidders is None and bids:
        num_bidders = len(bids)
    return HistoricalAward(
        source=source_key,
        source_id=str(row.source_id)[:255],
        country=country,
        state=row.state[:64],
        district=row.district[:128],
        buyer=row.buyer,
        buyer_key=normalise(row.buyer) if row.buyer else "",
        title=row.title,
        category=category,
        sector=sector,
        method=row.method if row.method in METHODS else "",
        currency=currency,
        estimated_value=est,
        award_value=award,
        estimated_inr_real=deflator.to_inr_real(est, currency, country, year),
        award_inr_real=deflator.to_inr_real(award, currency, country, year),
        ratio=ratio,
        num_bidders=num_bidders if num_bidders and num_bidders > 0 else None,
        bids=bids or None,
        winner=row.winner,
        winner_key=normalise(row.winner) if row.winner else "",
        tender_date=row.tender_date,
        award_date=row.award_date,
        year=year,
        url=row.url,
        tender_id=row.tender_id,
        organization_id=row.organization_id,
        shared=row.shared,
    )


UPDATE_FIELDS = [
    f.name
    for f in HistoricalAward._meta.concrete_fields
    if f.name not in {"id", "source", "source_id", "created_at"}
]


def upsert(
    rows: Iterable[AwardRow],
    source_key: str,
    *,
    imported: DatasetImport | None = None,
    deflator: Deflator | None = None,
) -> dict:
    """Idempotent insert-or-update on (source, source_id), in batches. Duplicate ids in
    one batch keep the last row. Returns {seen, inserted, updated, skipped, ratios}."""
    deflator = deflator or Deflator.load()
    stats = {"seen": 0, "inserted": 0, "updated": 0, "skipped": 0, "ratios": 0}
    batch: dict[str, HistoricalAward] = {}

    def flush():
        if not batch:
            return
        existing = set(
            HistoricalAward.objects.filter(
                source=source_key, source_id__in=list(batch)
            ).values_list("source_id", flat=True)
        )
        now = timezone.now()
        for obj in batch.values():
            obj.imported = imported
            obj.updated_at = now
            obj.created_at = now
        with transaction.atomic():
            HistoricalAward.objects.bulk_create(
                list(batch.values()),
                update_conflicts=True,
                unique_fields=["source", "source_id"],
                update_fields=UPDATE_FIELDS,
            )
        stats["inserted"] += len(batch) - len(existing)
        stats["updated"] += len(existing)
        batch.clear()

    for row in rows:
        stats["seen"] += 1
        obj = to_model(row, source_key, deflator)
        if obj is None:
            stats["skipped"] += 1
            continue
        stats["ratios"] += obj.ratio is not None
        batch[obj.source_id] = obj
        if len(batch) >= BATCH:
            flush()
    flush()
    return stats


def run_import(key: str, **options) -> DatasetImport:
    """Runs one source end to end and records the run. Raises after recording a failure."""
    cls = REGISTRY[key]
    source = cls()
    run = DatasetImport.objects.create(
        source=key,
        license=cls.license,
        params={k: v for k, v in options.items() if k != "client" and v is not None},
    )
    ctx = ImportContext(source, **options)
    try:
        rows = source.rows(ctx)
        if ctx.limit:
            rows = (r for i, r in enumerate(rows) if i < ctx.limit)
        stats = upsert(rows, key, imported=run)
    except Exception as exc:
        run.status = DatasetImport.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:4000]
        run.files = ctx.files
        run.finished_at = timezone.now()
        run.save()
        raise
    run.status = DatasetImport.Status.SUCCEEDED
    run.rows_seen, run.rows_inserted = stats["seen"], stats["inserted"]
    run.rows_updated, run.rows_skipped = stats["updated"], stats["skipped"]
    run.params = {**run.params, "ratios": stats["ratios"]}
    run.files = ctx.files
    run.finished_at = timezone.now()
    run.save()
    log.info("intel import %s: %s", key, stats)
    return run
