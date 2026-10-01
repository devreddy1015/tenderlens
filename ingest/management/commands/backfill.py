from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

from ingest.loader import load_detail_page
from ingest.models import RawPage

IST = ZoneInfo("Asia/Kolkata")


def _day(value: str, end: bool) -> datetime:
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"dates are YYYY-MM-DD, got {value!r}") from exc
    return datetime.combine(d, time.max if end else time.min, tzinfo=IST)


class Command(BaseCommand):
    help = (
        "Re-parse stored detail pages fetched between FROM and TO (inclusive, IST) and load "
        "them again. Safe to re-run: upserts are idempotent and an older page never "
        "overwrites newer data."
    )

    def add_arguments(self, parser):
        parser.add_argument("date_from", metavar="FROM")
        parser.add_argument("date_to", metavar="TO")
        parser.add_argument("--source")
        parser.add_argument("--no-index", action="store_true", help="skip Elasticsearch re-index")

    def handle(self, *args, date_from, date_to, source, no_index, **opts):
        start, end = _day(date_from, False), _day(date_to, True)
        if start > end:
            raise CommandError("FROM is after TO")
        pages = RawPage.objects.filter(
            kind=RawPage.Kind.DETAIL, fetched_at__gte=start, fetched_at__lte=end
        ).order_by("fetched_at")
        if source:
            pages = pages.filter(source=source)
        counts: dict[str, int] = {}
        for page in pages.iterator(chunk_size=200):
            outcome = load_detail_page(page, index=not no_index).outcome
            counts[outcome] = counts.get(outcome, 0) + 1
        summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no pages"
        self.stdout.write(f"backfill {date_from}..{date_to}: {summary}")
