from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Trigram index so the Postgres fallback's icontains search on titles stays fast."""

    dependencies = [("tenders", "0001_initial")]

    operations = [
        TrigramExtension(),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS tender_title_trgm ON tender USING gin (title gin_trgm_ops);",
            "DROP INDEX IF EXISTS tender_title_trgm;",
        ),
    ]
