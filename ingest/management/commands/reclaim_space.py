"""Give a size-capped hosted Postgres (Neon's free tier: 512 MB) its space back.

`prune` deletes rows, and VACUUM only makes their space reusable: the files keep their
size. A database that has hit its cap cannot grow a single file, so even the migrations
that would reuse that space fail ("could not extend file because project size limit
(512 MB) has been exceeded"). TRUNCATE hands the files back at once.

Stored HTML (raw_page) and per-tender crawl outcomes (crawl_item) are most of the
database and the next crawl re-creates them, so they go. Tenders, buyers, users, alerts
and workspaces stay; rows that pointed at a page get NULL, as on_delete=SET_NULL would
do, which only `backfill` notices. TRUNCATE refuses a table other tables reference, so
those foreign keys are dropped first and re-created afterwards with Django's own SQL.
"""

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from ingest.models import CrawlItem, RawPage

TRUNCATED = (RawPage, CrawlItem)


def _size_mb() -> int:
    with connection.cursor() as cur:
        cur.execute("select pg_database_size(current_database())")
        return cur.fetchone()[0] // (1024 * 1024)


def _foreign_keys_to_raw_page():
    return [
        (model, field)
        for model in apps.get_models()
        for field in model._meta.local_concrete_fields
        if field.many_to_one and field.related_model is RawPage
    ]


class Command(BaseCommand):
    help = "Truncate stored HTML and crawl items to shrink a size-capped hosted database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--if-over-mb",
            type=int,
            default=0,
            help="Do nothing while the database is smaller than this many MB.",
        )

    def handle(self, *args, if_over_mb: int, **opts):
        size = _size_mb()
        self.stdout.write(f"database size: {size} MB")
        if size < if_over_mb:
            self.stdout.write(f"under {if_over_mb} MB; nothing to reclaim")
            return

        fks = _foreign_keys_to_raw_page()
        tables = ", ".join(connection.ops.quote_name(m._meta.db_table) for m in TRUNCATED)
        # 1. Drop the foreign keys and truncate. This writes no new rows, so it works at
        #    the cap, and the space comes back when the transaction commits.
        with transaction.atomic(), connection.schema_editor(atomic=False) as editor:
            for model, field in fks:
                for name in editor._constraint_names(model, [field.column], foreign_key=True):
                    editor.execute(editor._delete_fk_sql(model, name))
            editor.execute(f"TRUNCATE {tables}")
        self.stdout.write(f"truncated {tables}")

        # 2. Now there is room: clear the dangling ids and restore the foreign keys exactly
        #    as the migrations created them. Safe to re-run if an earlier run stopped here.
        with transaction.atomic(), connection.schema_editor(atomic=False) as editor:
            for model, field in fks:
                if model not in TRUNCATED:
                    model._base_manager.filter(**{f"{field.name}__isnull": False}).update(
                        **{field.name: None}
                    )
                if not editor._constraint_names(model, [field.column], foreign_key=True):
                    editor.execute(
                        editor._create_fk_sql(model, field, "_fk_%(to_table)s_%(to_column)s")
                    )

        # The NULLs rewrote every referencing row; VACUUM makes the old versions reusable.
        updated = sorted({m._meta.db_table for m, _ in fks if m not in TRUNCATED})
        if updated:
            with connection.cursor() as cur:
                cur.execute(
                    "VACUUM (ANALYZE) " + ", ".join(map(connection.ops.quote_name, updated))
                )
        self.stdout.write(f"database size: {_size_mb()} MB")
