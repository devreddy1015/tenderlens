from django.core.management.base import BaseCommand
from django.db import connection

from ingest import tasks


class Command(BaseCommand):
    help = "Delete raw pages and crawl items past their retention, then VACUUM those tables."

    def handle(self, *args, **opts):
        def size() -> str:
            with connection.cursor() as cur:
                cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
                return cur.fetchone()[0]

        self.stdout.write(f"database size: {size()}")
        # Crawl items first: deleting them writes nothing, and it leaves fewer rows for the
        # raw page delete to update.
        self.stdout.write(f"crawl items deleted: {tasks.prune_crawl_items()}")
        self.stdout.write(f"raw pages deleted: {tasks.prune_raw_pages()}")
        # Deleted rows only free space for reuse once vacuumed, and VACUUM gives the empty
        # tail of a table back, which is what lowers a hosted database's size.
        with connection.cursor() as cur:
            cur.execute("VACUUM (ANALYZE) raw_page, crawl_item")
        self.stdout.write(f"database size: {size()}")
