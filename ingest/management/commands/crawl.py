from django.core.management.base import BaseCommand

from ingest import pipeline
from ingest.sources import SOURCES


class Command(BaseCommand):
    help = "Crawl a tender source. Queues Celery tasks by default; --sync runs in the foreground."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="central", choices=sorted(SOURCES))
        parser.add_argument("--mode", default="incremental", choices=["incremental", "full"])
        parser.add_argument("--sync", action="store_true", help="run in this process, no Celery")
        parser.add_argument("--max-orgs", type=int, help="only the first N organisations (testing)")
        parser.add_argument("--max-details", type=int, help="only N detail pages (testing, --sync)")

    def handle(self, *args, source, mode, sync, max_orgs, max_details, **opts):
        if sync:
            run = pipeline.run_sync(source, mode=mode, max_orgs=max_orgs, max_details=max_details)
            self.stdout.write(
                f"run {run.pk} {run.status}: pages={run.pages} new={run.new} updated={run.updated} "
                f"unchanged={run.unchanged} skipped={run.skipped} quarantined={run.quarantined} "
                f"failed={run.failed}"
            )
            for problem in (run.reconciliation or {}).get("problems", []):
                self.stdout.write(self.style.WARNING(f"  reconciliation: {problem}"))
            return
        from ingest.models import CrawlRun
        from ingest.tasks import crawl_listing

        run = CrawlRun.objects.create(source=source, mode=mode)
        crawl_listing.delay(run.pk, max_orgs=max_orgs)
        self.stdout.write(f"queued crawl run {run.pk} ({source}, {mode})")
