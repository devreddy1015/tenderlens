from django.db import migrations


class Migration(migrations.Migration):
    """Raw HTML compresses ~5-8x. lz4 is faster than the default pglz for TOAST."""

    dependencies = [("ingest", "0001_initial")]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE raw_page ALTER COLUMN body SET COMPRESSION lz4;",
            "ALTER TABLE raw_page ALTER COLUMN body SET COMPRESSION pglz;",
        )
    ]
