from django.core.management.base import BaseCommand, CommandError

from intel.sources import REGISTRY
from intel.sources.base import run_import


class Command(BaseCommand):
    help = "Import historical award data from one source (idempotent): intel_import <source>"

    def add_arguments(self, parser):
        parser.add_argument("source", nargs="?", help="source key; --list shows them")
        parser.add_argument("--list", action="store_true", help="list the sources and exit")
        parser.add_argument("--limit", type=int, help="stop after this many rows")
        parser.add_argument("--since", type=int, help="only rows from this year on")
        parser.add_argument("--file", help="read this local file instead of downloading")
        parser.add_argument("--refresh", action="store_true", help="re-download cached files")

    def handle(self, *args, **opts):
        if opts["list"] or not opts["source"]:
            for key, cls in sorted(REGISTRY.items()):
                self.stdout.write(f"{key:20} {cls.kind:9} {cls.name} ({cls.license})")
            return
        if opts["source"] not in REGISTRY:
            raise CommandError(f"unknown source {opts['source']!r}; try --list")
        run = run_import(
            opts["source"],
            limit=opts["limit"],
            since=opts["since"],
            file=opts["file"],
            refresh=opts["refresh"],
        )
        self.stdout.write(
            f"{run.source}: {run.status}, seen {run.rows_seen}, inserted {run.rows_inserted}, "
            f"updated {run.rows_updated}, skipped {run.rows_skipped}, "
            f"with ratio {run.params.get('ratios', 0)}"
        )
