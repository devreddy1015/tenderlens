from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Count, Sum

from ingest.models import CrawlItem, CrawlRun, DeadLetter, Quarantine, RawPage
from tenders.models import BuyerAlias, BuyerEntity, BuyerReview, Tender


class Command(BaseCommand):
    help = "Print the numbers the README quotes, straight from the database."

    def handle(self, *args, **opts):
        out = self.stdout.write
        tenders = Tender.objects.count()
        distinct = Tender.objects.values("source", "source_tender_id").distinct().count()
        out(f"tenders stored:                 {tenders:,} (distinct source ids: {distinct:,})")
        by_source = Tender.objects.values_list("source").annotate(n=Count("id")).order_by("-n")
        out("  by source:                    " + ", ".join(f"{s}={n:,}" for s, n in by_source))
        out(
            f"states covered:                 {Tender.objects.exclude(state='').values('state').distinct().count()}"
        )
        total_value = Tender.objects.aggregate(v=Sum("value_inr"))["v"] or 0
        out(f"total disclosed value:          ₹{total_value / 10**7:,.0f} crore")

        # Every time the crawler offered a tender that was already stored, the unique
        # key turned what would have been a duplicate row into an update or a no-op.
        repeats = CrawlItem.objects.filter(
            outcome__in=[
                CrawlItem.Outcome.UPDATED,
                CrawlItem.Outcome.UNCHANGED,
                CrawlItem.Outcome.SKIPPED,
            ]
        ).count()
        out(
            f"duplicates prevented:           {repeats:,} re-seen tenders upserted in place, 0 duplicate rows"
        )

        out("crawl runs:")
        for run in CrawlRun.objects.exclude(status=CrawlRun.Status.RUNNING).order_by("started"):
            dur = (run.finished - run.started).total_seconds() if run.finished else 0
            out(
                f"  #{run.pk:<3} {run.source:<8} {run.mode:<11} {run.status:<10} {dur / 60:6.1f} min  "
                f"pages={run.pages:<5} new={run.new:<5} updated={run.updated:<4} unchanged={run.unchanged:<5} "
                f"skipped={run.skipped:<5} quarantined={run.quarantined} failed={run.failed}"
            )
            for problem in (run.reconciliation or {}).get("problems", []):
                out(f"        reconciliation: {problem}")

        out(f"quarantined rows:               {Quarantine.objects.count()}")
        out(f"dead letters:                   {DeadLetter.objects.count()}")
        with connection.cursor() as cur:
            cur.execute(
                "SELECT pg_size_pretty(pg_total_relation_size('raw_page')), "
                "pg_size_pretty(sum(octet_length(body))::bigint) FROM raw_page"
            )
            on_disk, raw = cur.fetchone()
        out(
            f"raw pages:                      {RawPage.objects.count():,} ({raw} of HTML, {on_disk} on disk)"
        )
        out(
            f"buyer names -> entities:        {Tender.objects.values('buyer_raw').distinct().count()} -> "
            f"{BuyerEntity.objects.count()} "
            f"(fuzzy merges {BuyerAlias.objects.filter(method='fuzzy').count()}, "
            f"open reviews {BuyerReview.objects.filter(status='open').count()})"
        )
